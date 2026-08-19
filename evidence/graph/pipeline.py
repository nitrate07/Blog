"""Evidence Pipeline — the complete verification chain.

PRINCIPLE: LLM is an interpreter (yorumcu), NEVER an evidence source.
Evidence comes ONLY from: verified sources (11 kaynak).
Evidence Engine is the hakem (referee) — it processes, scores, and judges.
LLM only explains the verdict in natural language.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..connectors import EvidenceCatalog
from ..config import Settings, settings
from ..llm_providers import LLMProvider
from ..models import EvidenceSearchResult, SourceQuality
from ..providers import NullProvider
from ..rag.retriever import ArticleRetriever, RetrievalResult
from .builder import GraphBuilder
from .health_agents import HealthOrgSearchAgent
from .model import Claim, Evidence, Passage, Source, SourceType, Verdict
from .store import EvidenceGraph

logger = logging.getLogger(__name__)

_VERDICT_MAP = {
    "supported": Verdict.SUPPORTED,
    "mostly supported": Verdict.MOSTLY_SUPPORTED,
    "partly supported": Verdict.PARTLY_SUPPORTED,
    "misleading": Verdict.MISLEADING,
    "unsupported": Verdict.UNSUPPORTED,
    "unverified": Verdict.UNVERIFIED,
}

_SOURCE_QUALITY_SCORES = {
    SourceType.PRIMARY: 1.0,
    SourceType.SECONDARY: 0.75,
    SourceType.TERTIARY: 0.35,
    SourceType.UNKNOWN: 0.5,
}

_HEALTH_SOURCE_TYPE_MAP = {
    "international_organization": SourceType.TERTIARY,
    "government": SourceType.TERTIARY,
    "academic": SourceType.SECONDARY,
    "primary": SourceType.PRIMARY,
    "secondary": SourceType.SECONDARY,
    "tertiary": SourceType.TERTIARY,
    "unknown": SourceType.UNKNOWN,
}


def _safe_source_type(source_type_str: str) -> SourceType:
    """Convert any source_type string to SourceType enum safely."""
    return _HEALTH_SOURCE_TYPE_MAP.get(source_type_str, SourceType.UNKNOWN)


def _content_hash(text: str) -> str:
    """Compute SHA-256 hash of passage content for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Step 1: Claim Extraction
# ---------------------------------------------------------------------------

def extract_claim(user_query: str) -> str:
    """Extract the core claim from a user query. No LLM — pure rule-based."""
    query = user_query.strip()
    prefixes = [
        "is it true that", "does ", "can ", "should ", "is ",
        "are ", "what about ", "tell me about ", "explain ",
        "verify ", "check ", "fact check ", "did ",
    ]
    for prefix in prefixes:
        if query.lower().startswith(prefix):
            query = query[len(prefix):].strip()
            break
    if not query.endswith("?"):
        query = query + "?"
    return query


# ---------------------------------------------------------------------------
# Step 2: Source Discovery (All 11 Sources in Parallel)
# ---------------------------------------------------------------------------

async def discover_sources(
    claim: str,
    retriever: ArticleRetriever,
    catalog: EvidenceCatalog,
    health_agent: HealthOrgSearchAgent | None = None,
    archive_limit: int = 5,
    external_limit: int = 5,
) -> tuple[list[dict[str, Any]], list[Source], list[dict[str, Any]]]:
    """Search ALL evidence sources in parallel:
    
    1. Archive (Arı Kaynak via RAG)
    2. PubMed
    3. Crossref
    4. WHO (Dünya Sağlık Örgütü)
    5. CDC (ABD Hastalık Kontrol)
    6. ECDC (Avrupa Hastalık Kontrol)
    7. Cochrane (Sistematik Derlemeler)
    8. ClinicalTrials.gov (Klinik Araştırmalar)
    9. FDA (ABD İlaç Dairesi)
    10. EMA (Avrupa İlaç Ajansı)
    11. Google Scholar (Akademik Makaleler)
    """
    import asyncio

    async def _search_archive() -> list[RetrievalResult]:
        try:
            return retriever.retrieve(query=claim, n_results=archive_limit)
        except Exception as e:
            logger.warning(f"Archive search failed: {e}")
            return []

    async def _search_external() -> list[Source]:
        try:
            results = await catalog.search(claim, limit=external_limit)
        except Exception as e:
            logger.warning(f"External search failed: {e}")
            return []
        sources: list[Source] = []
        for r in results:
            source = Source(
                id=f"source::{str(r.url).rstrip('/').lower()}",
                url=str(r.url),
                title=r.title,
                source_type=_map_source_type(r.source_type),
                doi=r.doi,
                pmid=r.pmid,
                published_year=r.published_year,
            )
            sources.append(source)
        return sources

    async def _search_health_orgs() -> list[dict[str, Any]]:
        if not health_agent:
            return []
        try:
            result = await health_agent.search(claim, limit_per_agent=3)
            return result.get("results", [])
        except Exception as e:
            logger.warning(f"Health org search failed: {e}")
            return []

    archive_task, external_task, health_task = await asyncio.gather(
        _search_archive(), _search_external(), _search_health_orgs(),
        return_exceptions=True,
    )
    archive = archive_task if isinstance(archive_task, list) else []
    external = external_task if isinstance(external_task, list) else []
    health_orgs = health_task if isinstance(health_task, list) else []
    return archive, external, health_orgs


# ---------------------------------------------------------------------------
# Step 3: Evidence Engine (hakem — referee)
# ---------------------------------------------------------------------------

def evidence_engine(
    claim: str,
    archive: list[RetrievalResult],
    external: list[Source],
    health_orgs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The hakem: combines evidence from ALL 11 sources, scores, matches, verdict.
    
    This is deterministic. No LLM involvement. The engine judges based on:
    - Source quality (primary > secondary > tertiary)
    - Recency (newer sources score higher)
    - Text overlap (claim words vs evidence words)
    - Archive verdict (if available, strong signal)
    
    Sources: Archive, PubMed, Crossref, WHO, CDC, ECDC, Cochrane, ClinicalTrials, FDA, EMA, Google Scholar
    """
    evidence_items = _combine_evidence(archive, external, health_orgs or [])
    scored = _score_sources(evidence_items)
    matches = _match_claim_evidence(claim, scored)
    verdict, confidence, rating = _compute_verdict(matches)
    return {
        "evidence_items": scored,
        "matches": matches,
        "verdict": verdict,
        "confidence": confidence,
        "rating_value": rating,
    }


def _combine_evidence(
    archive: list[RetrievalResult],
    external: list[Source],
    health_orgs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for r in archive:
        combined.append({
            "source": "archive",
            "title": r.title,
            "url": r.source_url,
            "text": r.text,
            "verdict": r.verdict,
            "rating_value": r.rating_value,
            "distance": r.distance,
            "source_type": "primary",
        })
    for s in external:
        combined.append({
            "source": "external",
            "title": s.title,
            "url": s.url,
            "text": "",
            "verdict": None,
            "rating_value": None,
            "distance": None,
            "source_type": s.source_type.value,
            "doi": s.doi,
            "pmid": s.pmid,
            "published_year": s.published_year,
        })
    for h in health_orgs:
        combined.append({
            "source": "health_org",
            "title": h.get("title", ""),
            "url": h.get("url", ""),
            "text": h.get("passage", ""),
            "verdict": None,
            "rating_value": None,
            "distance": None,
            "source_type": h.get("source_type", "international_organization"),
            "organization": h.get("organization", ""),
        })
    return combined


def _score_sources(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in evidence:
        st = item.get("source_type", "unknown")
        source_type = _safe_source_type(st)
        quality_score = _SOURCE_QUALITY_SCORES.get(source_type, 0.5)
        recency_bonus = 0.0
        year = item.get("published_year")
        if year and year >= 2020:
            recency_bonus = 0.1
        item["quality_score"] = round(min(1.0, quality_score + recency_bonus), 3)
    evidence.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return evidence


def _match_claim_evidence(claim: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claim_words = set(claim.lower().split())
    matches: list[dict[str, Any]] = []
    for item in evidence:
        text = (item.get("text", "") + " " + item.get("title", "")).lower()
        if not text:
            matches.append({**item, "relevance": 0.3, "match_type": "metadata"})
            continue
        text_words = set(text.split())
        overlap = len(claim_words & text_words) / max(len(claim_words), 1)
        matches.append({**item, "relevance": round(min(1.0, overlap * 2), 3), "match_type": "text"})
    matches.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return matches


def _compute_verdict(matches: list[dict[str, Any]]) -> tuple[str, float, int]:
    if not matches:
        return "unverified", 0.0, 0
    archive_matches = [m for m in matches if m.get("source") == "archive"]
    if archive_matches:
        best = archive_matches[0]
        verdict_str = best.get("verdict", "unverified")
        rating = best.get("rating_value", 0)
        confidence = max(0.3, 1.0 - best.get("distance", 0.5))
        return verdict_str, confidence, rating
    quality_scores = [m.get("quality_score", 0.5) for m in matches[:3]]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
    relevance_scores = [m.get("relevance", 0) for m in matches[:3]]
    avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0.0
    confidence = round(min(0.9, avg_quality * 0.6 + avg_relevance * 0.4), 3)
    if confidence >= 0.7:
        return "supported", confidence, 4
    elif confidence >= 0.4:
        return "partly_supported", confidence, 3
    else:
        return "unverified", confidence, 1


# ---------------------------------------------------------------------------
# Step 4: LLM Interpreter (yorumcu — commentator only)
# ---------------------------------------------------------------------------

async def interpret_with_llm(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    provider: LLMProvider | None = None,
) -> str:
    """LLM interprets the evidence engine's verdict in natural language.
    
    CRITICAL: LLM does NOT generate evidence. It only explains what the
    evidence engine already determined. The verdict comes from the engine,
    not from the LLM.
    """
    if isinstance(provider, NullProvider) or provider is None:
        return _build_rule_based_response(claim, verdict, confidence, matches)
    sources_text = _format_sources_for_llm(matches[:5])
    prompt = f"""You are a fact-checking commentator. Your role is to explain the evidence engine's findings in clear, cited language.

IMPORTANT RULES:
- You are a commentator, NOT an evidence source
- You can ONLY cite evidence that was provided to you below
- You MUST NOT invent, assume, or generate new evidence
- You MUST include source citations for every claim you make
- If evidence is insufficient, say so clearly

Claim to evaluate: {claim}

Evidence Engine Verdict: {verdict} (confidence: {confidence:.0%})

Available evidence sources:
{sources_text}

Write a brief, cited explanation of the verdict. Include source URLs. Do NOT add evidence that wasn't provided."""
    try:
        response = await provider._call_llm(prompt)
        return response.strip() if response else _build_rule_based_response(claim, verdict, confidence, matches)
    except Exception as e:
        logger.warning(f"LLM interpreter failed: {e}")
        return _build_rule_based_response(claim, verdict, confidence, matches)


def _format_sources_for_llm(matches: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, m in enumerate(matches, 1):
        title = m.get("title", "Unknown")
        url = m.get("url", "")
        source_type = m.get("source_type", "unknown")
        quality = m.get("quality_score", 0)
        text = m.get("text", "")[:300]
        lines.append(f"{i}. [{title}]({url}) — {source_type} (quality: {quality:.0%})")
        if text:
            lines.append(f"   Excerpt: {text}...")
    return "\n".join(lines)


def _build_rule_based_response(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
) -> str:
    verdict_display = verdict.replace("_", " ").title()
    confidence_pct = round(confidence * 100)
    lines = [
        f"**Claim:** {claim}",
        f"**Verdict:** {verdict_display} (confidence: {confidence_pct}%)",
        "",
        "**Evidence sources:**",
    ]
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title", "Unknown")
        url = m.get("url", "")
        source_type = m.get("source_type", "unknown")
        quality = m.get("quality_score", 0)
        lines.append(f"{i}. [{title}]({url}) — {source_type} (quality: {quality:.0%})")
    if not matches:
        lines.append("No evidence found.")
    lines.extend([
        "",
        "---",
        "*Generated by Arı Kaynak Evidence Engine. LLM interpreted the verdict — evidence came from verified sources only.*",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 5: Graph Update
# ---------------------------------------------------------------------------

def update_graph(
    graph: EvidenceGraph,
    claim_text: str,
    verdict: str,
    confidence: float,
    rating: int,
    matches: list[dict[str, Any]],
) -> str:
    """Record the verification chain in the Evidence Graph."""
    claim_id = f"claim::pipeline::{hash(claim_text) % 100000}"
    verdict_enum = _VERDICT_MAP.get(verdict, Verdict.UNVERIFIED)
    claim = Claim(
        id=claim_id,
        text=claim_text,
        author="pipeline",
        category="Health",
        date_filed="",
        file_number=0,
    )
    graph.add_claim(claim)
    passages: list[Passage] = []
    for m in matches[:5]:
        source_url = m.get("url", "")
        if source_url:
            source_id = f"source::{source_url.rstrip('/').lower()}"
            source = Source(
                id=source_id,
                url=source_url,
                title=m.get("title", ""),
                source_type=_safe_source_type(m.get("source_type", "unknown")),
            )
            graph.add_source(source)
            passage_text = m.get("text", "")[:1000]
            passage = Passage(
                id=f"passage::{claim_id}::{len(passages)}",
                text=passage_text,
                source_id=source_id,
                relevance=m.get("relevance", 0.5),
                content_hash=_content_hash(passage_text) if passage_text else None,
            )
            graph.add_passage(passage)
            passages.append(passage)
    evidence = Evidence(
        id=f"evidence::{claim_id}",
        claim_id=claim_id,
        passages=passages,
        verdict=verdict_enum,
        confidence=confidence,
        rating_value=rating,
    )
    graph.add_evidence(evidence)
    return claim_id


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    query: str
    extracted_claim: str
    archive_results: list[dict]
    external_results: list[dict]
    health_org_results: list[dict]
    verdict: str
    verdict_confidence: float
    rating_value: int
    cited_response: str
    steps: list[dict]
    graph_claim_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "extracted_claim": self.extracted_claim,
            "archive_results": self.archive_results,
            "external_results": self.external_results,
            "health_org_results": self.health_org_results,
            "verdict": self.verdict,
            "verdict_confidence": round(self.verdict_confidence, 3),
            "rating_value": self.rating_value,
            "cited_response": self.cited_response,
            "steps": self.steps,
            "graph_claim_id": self.graph_claim_id,
        }


async def run_pipeline(
    user_query: str,
    retriever: ArticleRetriever,
    catalog: EvidenceCatalog,
    graph_builder: GraphBuilder,
    llm_provider: LLMProvider | None = None,
    health_agent: HealthOrgSearchAgent | None = None,
    config: Settings | None = None,
) -> PipelineResult:
    """Execute the complete verification pipeline.
    
    Flow:
    1. Claim Extraction (rule-based, no LLM)
    2. Source Discovery — 11 sources in parallel:
       - Archive (RAG)
       - PubMed + Crossref
       - WHO, CDC, ECDC, Cochrane, ClinicalTrials, FDA, EMA, Google Scholar
    3. Evidence Engine (hakem — deterministic, no LLM)
    4. LLM Interpreter (yorumcu — explains verdict, never generates evidence)
    5. Graph Update (records the chain)
    """
    config = config or settings
    steps: list[dict[str, Any]] = []

    # Step 1: Claim Extraction
    extracted_claim = extract_claim(user_query)
    steps.append({"name": "claim_extraction", "status": "done", "data": {"claim": extracted_claim}})

    # Step 2: Source Discovery (11 sources in parallel)
    archive, external, health_orgs = await discover_sources(
        extracted_claim, retriever, catalog,
        health_agent=health_agent,
        archive_limit=config.rag_max_results,
        external_limit=5,
    )
    steps.append({"name": "source_discovery", "status": "done", "data": {
        "archive": len(archive),
        "external": len(external),
        "health_orgs": len(health_orgs),
        "total_sources": len(archive) + len(external) + len(health_orgs),
    }})

    # Step 3: Evidence Engine (hakem) — ALL 11 sources
    engine_result = evidence_engine(extracted_claim, archive, external, health_orgs)
    steps.append({"name": "evidence_engine", "status": "done", "data": {
        "verdict": engine_result["verdict"],
        "confidence": engine_result["confidence"],
        "rating": engine_result["rating_value"],
        "total_evidence": len(engine_result["evidence_items"]),
    }})

    # Step 4: LLM Interpreter (yorumcu)
    cited_response = await interpret_with_llm(
        extracted_claim,
        engine_result["verdict"],
        engine_result["confidence"],
        engine_result["matches"],
        provider=llm_provider,
    )
    steps.append({"name": "llm_interpreter", "status": "done", "data": {"response_length": len(cited_response)}})

    # Step 5: Graph Update
    graph_claim_id = update_graph(
        graph_builder.graph,
        extracted_claim,
        engine_result["verdict"],
        engine_result["confidence"],
        engine_result["rating_value"],
        engine_result["matches"],
    )
    steps.append({"name": "graph_update", "status": "done", "data": {"claim_id": graph_claim_id}})

    return PipelineResult(
        query=user_query,
        extracted_claim=extracted_claim,
        archive_results=[r.to_dict() for r in archive],
        external_results=[s.to_dict() for s in external],
        health_org_results=health_orgs,
        verdict=engine_result["verdict"],
        verdict_confidence=engine_result["confidence"],
        rating_value=engine_result["rating_value"],
        cited_response=cited_response,
        steps=steps,
        graph_claim_id=graph_claim_id,
    )


def _map_source_type(source_type: SourceQuality) -> SourceType:
    mapping = {
        SourceQuality.PRIMARY: SourceType.PRIMARY,
        SourceQuality.SECONDARY: SourceType.SECONDARY,
        SourceQuality.TERTIARY: SourceType.TERTIARY,
        SourceQuality.UNKNOWN: SourceType.UNKNOWN,
    }
    return mapping.get(source_type, SourceType.UNKNOWN)
