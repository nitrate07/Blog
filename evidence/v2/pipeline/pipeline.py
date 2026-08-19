"""Evidence Pipeline — the complete verification chain.

PRINCIPLE: LLM is an interpreter (yorumcu), NEVER an evidence source.
Evidence comes ONLY from: verified sources (11 kaynak).
Evidence Engine is the hakem (referee) — it processes, scores, and judges.
LLM only explains the verdict in natural language.

Flow:
1. Claim Extraction (rule-based, no LLM)
2. Source Discovery (11 sources in parallel)
3. Evidence Engine (hakem — deterministic, no LLM)
4. LLM Interpreter (yorumcu — explains verdict, never generates evidence)
5. Graph Update (records the chain)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from ..core.interfaces import EvidenceEngine, SourceAgent
from ..core.types import (
    Claim,
    Evidence,
    Passage,
    Source,
    SourceType,
    VerificationChain,
    Verdict,
    content_hash,
    make_claim_id,
    make_evidence_id,
    make_passage_id,
    make_source_id,
)
from ..sources.orchestrator import SourceOrchestrator

logger = logging.getLogger(__name__)

# Verdict string → Verdict enum
VERDICT_MAP: dict[str, Verdict] = {
    "supported": Verdict.SUPPORTED,
    "mostly supported": Verdict.MOSTLY_SUPPORTED,
    "mostly_supported": Verdict.MOSTLY_SUPPORTED,
    "partly supported": Verdict.PARTLY_SUPPORTED,
    "partly_supported": Verdict.PARTLY_SUPPORTED,
    "misleading": Verdict.MISLEADING,
    "unsupported": Verdict.UNSUPPORTED,
    "unverified": Verdict.UNVERIFIED,
}


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
# Step 2: Source Discovery
# ---------------------------------------------------------------------------

async def discover_sources(
    claim: str,
    orchestrator: SourceOrchestrator,
    limit_per_agent: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Search ALL evidence sources in parallel.
    
    Returns:
        (archive, external, health_orgs)
    """
    result = await orchestrator.search(claim, limit_per_agent=limit_per_agent)
    all_results = result.get("results", [])
    
    archive = [r for r in all_results if r.get("source") == "archive"]
    external = [r for r in all_results if r.get("source") in ("pubmed", "crossref")]
    health_orgs = [r for r in all_results if r.get("source") not in ("archive", "pubmed", "crossref")]
    
    return archive, external, health_orgs


# ---------------------------------------------------------------------------
# Step 3: Evidence Engine (hakem)
# ---------------------------------------------------------------------------

def run_engine(
    engine: EvidenceEngine,
    claim: str,
    archive: list[dict[str, Any]],
    external: list[dict[str, Any]],
    health_orgs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the evidence engine to judge the claim."""
    return engine.judge(claim, archive, external, health_orgs)


# ---------------------------------------------------------------------------
# Step 4: LLM Interpreter (yorumcu)
# ---------------------------------------------------------------------------

async def interpret_with_llm(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    llm_provider: Any | None = None,
) -> str:
    """Interpret the verdict in natural language.
    
    If no LLM provider, use rule-based response.
    LLM is ONLY used as an interpreter — never as evidence source.
    """
    if llm_provider and hasattr(llm_provider, "generate"):
        try:
            prompt = _build_interpreter_prompt(claim, verdict, confidence, matches)
            return await llm_provider.generate(prompt)
        except Exception as e:
            logger.warning(f"LLM interpreter failed, falling back to rule-based: {e}")
    
    return _build_rule_based_response(claim, verdict, confidence, matches)


def _build_interpreter_prompt(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
) -> str:
    """Build prompt for LLM interpreter."""
    evidence_text = ""
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title", "Unknown")
        url = m.get("url", "")
        text = m.get("text", "")[:200]
        evidence_text += f"{i}. {title}\n   URL: {url}\n   Excerpt: {text}...\n\n"
    
    return f"""You are a fact-checking interpreter for Arı Kaynak.

Claim: {claim}
Verdict: {verdict}
Confidence: {confidence:.0%}

Evidence sources:
{evidence_text}

Explain the verdict in 2-3 sentences. Reference the evidence sources.
Be factual and cite sources. Do NOT generate new evidence."""


def _build_rule_based_response(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
) -> str:
    """Build rule-based response without LLM."""
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
    claim_text: str,
    verdict: str,
    confidence: float,
    rating: int,
    matches: list[dict[str, Any]],
    claims: dict[str, Claim] | None = None,
    sources: dict[str, Source] | None = None,
    passages: dict[str, Passage] | None = None,
    evidence: dict[str, Evidence] | None = None,
) -> dict[str, Any]:
    """Record the verification chain in the Evidence Graph.
    
    Returns the created claim, sources, passages, and evidence.
    """
    claim_id = make_claim_id(claim_text)
    verdict_enum = VERDICT_MAP.get(verdict, Verdict.UNVERIFIED)
    
    # Create claim
    claim = Claim(
        id=claim_id,
        text=claim_text,
        author="pipeline",
        category="Health",
        date_filed="",
        file_number=0,
    )
    if claims is not None:
        claims[claim_id] = claim
    
    # Create sources and passages from top matches
    created_sources: list[Source] = []
    created_passages: list[Passage] = []
    
    # Map agent source_type strings to SourceType enum
    source_type_map = {
        "primary": SourceType.PRIMARY,
        "secondary": SourceType.SECONDARY,
        "tertiary": SourceType.TERTIARY,
        "academic": SourceType.SECONDARY,
        "international_organization": SourceType.TERTIARY,
        "government": SourceType.TERTIARY,
        "systematic_review": SourceType.SECONDARY,
        "clinical_trial": SourceType.SECONDARY,
        "regulatory": SourceType.TERTIARY,
    }
    
    for m in matches[:5]:
        source_url = m.get("url", "")
        if not source_url:
            continue
        
        source_id = make_source_id(source_url)
        st_str = m.get("source_type", "unknown")
        source = Source(
            id=source_id,
            url=source_url,
            title=m.get("title", ""),
            source_type=source_type_map.get(st_str, SourceType.UNKNOWN),
        )
        if sources is not None:
            sources[source_id] = source
        created_sources.append(source)
        
        passage_text = m.get("text", "")[:1000]
        passage = Passage(
            id=make_passage_id(claim_id, len(created_passages)),
            text=passage_text,
            source_id=source_id,
            relevance=m.get("relevance", 0.5),
            content_hash=content_hash(passage_text) if passage_text else None,
        )
        if passages is not None:
            passages[passage.id] = passage
        created_passages.append(passage)
    
    # Create evidence
    ev = Evidence(
        id=make_evidence_id(claim_id),
        claim_id=claim_id,
        passages=created_passages,
        verdict=verdict_enum,
        confidence=confidence,
        rating_value=rating,
    )
    if evidence is not None:
        evidence[ev.id] = ev
    
    return {
        "claim": claim,
        "sources": created_sources,
        "passages": created_passages,
        "evidence": ev,
    }


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Result of running the full verification pipeline."""
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


class EvidencePipeline:
    """The complete verification pipeline.
    
    Flow:
    1. Claim Extraction (rule-based, no LLM)
    2. Source Discovery (11 sources in parallel)
    3. Evidence Engine (hakem — deterministic, no LLM)
    4. LLM Interpreter (yorumcu — explains verdict)
    5. Graph Update (records the chain)
    """
    
    def __init__(
        self,
        orchestrator: SourceOrchestrator,
        engine: EvidenceEngine,
        llm_provider: Any | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.engine = engine
        self.llm_provider = llm_provider
        
        # In-memory graph storage
        self.claims: dict[str, Claim] = {}
        self.sources: dict[str, Source] = {}
        self.passages: dict[str, Passage] = {}
        self.evidence: dict[str, Evidence] = {}
    
    async def run(self, user_query: str) -> PipelineResult:
        """Execute the complete verification pipeline."""
        steps: list[dict[str, Any]] = []
        
        # Step 1: Claim Extraction
        extracted_claim = extract_claim(user_query)
        steps.append({"name": "claim_extraction", "status": "done", "data": {"claim": extracted_claim}})
        
        # Step 2: Source Discovery (11 sources in parallel)
        archive, external, health_orgs = await discover_sources(
            extracted_claim, self.orchestrator,
        )
        steps.append({"name": "source_discovery", "status": "done", "data": {
            "archive": len(archive),
            "external": len(external),
            "health_orgs": len(health_orgs),
            "total": len(archive) + len(external) + len(health_orgs),
        }})
        
        # Step 3: Evidence Engine (hakem)
        engine_result = run_engine(self.engine, extracted_claim, archive, external, health_orgs)
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
            llm_provider=self.llm_provider,
        )
        steps.append({"name": "llm_interpreter", "status": "done", "data": {"response_length": len(cited_response)}})
        
        # Step 5: Graph Update
        graph_result = update_graph(
            extracted_claim,
            engine_result["verdict"],
            engine_result["confidence"],
            engine_result["rating_value"],
            engine_result["matches"],
            claims=self.claims,
            sources=self.sources,
            passages=self.passages,
            evidence=self.evidence,
        )
        steps.append({"name": "graph_update", "status": "done", "data": {"claim_id": graph_result["claim"].id}})
        
        return PipelineResult(
            query=user_query,
            extracted_claim=extracted_claim,
            archive_results=archive,
            external_results=external,
            health_org_results=health_orgs,
            verdict=engine_result["verdict"],
            verdict_confidence=engine_result["confidence"],
            rating_value=engine_result["rating_value"],
            cited_response=cited_response,
            steps=steps,
            graph_claim_id=graph_result["claim"].id,
        )
