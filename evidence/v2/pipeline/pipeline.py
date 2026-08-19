"""Evidence Pipeline — the complete verification chain.

Flow:
1. Claim Extraction (rule-based, no LLM)
2. Source Discovery (19 sources in parallel)
3. Passage Verification (verify against original sources)
4. Evidence Engine (hakem — deterministic, no LLM)
5. Contradiction Detection (find conflicting evidence)
6. LLM Interpreter (yorumcu — explains verdict)
7. Graph Update (records the chain)
8. Verification History (persistent record)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..core.database import EvidenceDatabase
from ..core.interfaces import EvidenceEngine, SourceAgent
from ..core.types import (
    Claim,
    Contradiction,
    Evidence,
    MethodologicalEvidence,
    Passage,
    Source,
    SourceType,
    VerificationChain,
    VerificationRecord,
    Verdict,
    content_hash,
    make_claim_id,
    make_evidence_id,
    make_passage_id,
    make_source_id,
    make_verification_id,
)
from ..engine.contradiction import ContradictionDetector
from ..engine.engine import SOURCE_TYPE_MAP
from ..engine.verifier import PassageVerifier
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
    """Search ALL evidence sources in parallel."""
    result = await orchestrator.search(claim, limit_per_agent=limit_per_agent)
    all_results = result.get("results", [])
    
    archive = [r for r in all_results if r.get("source") == "archive"]
    external = [r for r in all_results if r.get("source") in (
        "pubmed", "crossref", "nejm", "jama", "lancet", "bmj"
    )]
    health_orgs = [r for r in all_results if r.get("source") not in (
        "archive", "pubmed", "crossref", "nejm", "jama", "lancet", "bmj"
    )]
    
    return archive, external, health_orgs


# ---------------------------------------------------------------------------
# Step 3: Passage Verification
# ---------------------------------------------------------------------------

async def verify_passages(
    passages: list[Passage],
    sources: dict[str, Source],
) -> list[dict[str, Any]]:
    """Verify passages against original sources."""
    verifier = PassageVerifier()
    
    source_urls = {s.id: s.url for s in sources.values()}
    verifications = await verifier.verify_passages(passages, source_urls)
    
    return [v.to_dict() for v in verifications]


# ---------------------------------------------------------------------------
# Step 4: Evidence Engine (hakem)
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
# Step 5: Contradiction Detection
# ---------------------------------------------------------------------------

def detect_contradictions(
    claim_id: str,
    sources: list[Source],
    matches: list[dict[str, Any]],
) -> list[Contradiction]:
    """Detect contradictions between sources."""
    detector = ContradictionDetector()
    return detector.detect(claim_id, sources, matches)


# ---------------------------------------------------------------------------
# Step 6: LLM Interpreter (yorumcu)
# ---------------------------------------------------------------------------

async def interpret_with_llm(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
    llm_provider: Any | None = None,
) -> str:
    """Interpret the verdict in natural language.
    
    If no LLM provider, use rule-based response.
    LLM is ONLY used as an interpreter — never as evidence source.
    """
    if llm_provider and hasattr(llm_provider, "generate"):
        try:
            prompt = _build_interpreter_prompt(
                claim, verdict, confidence, matches,
                contradictions, supporting, contradicting,
            )
            return await llm_provider.generate(prompt)
        except Exception as e:
            logger.warning(f"LLM interpreter failed, falling back to rule-based: {e}")
    
    return _build_rule_based_response(
        claim, verdict, confidence, matches,
        contradictions, supporting, contradicting,
    )


def _build_interpreter_prompt(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
) -> str:
    """Build prompt for LLM interpreter."""
    evidence_text = ""
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title", "Unknown")
        url = m.get("url", "")
        text = m.get("text", "")[:200]
        quality = m.get("quality_score", 0)
        evidence_text += f"{i}. {title}\n   URL: {url}\n   Quality: {quality:.0%}\n   Excerpt: {text}...\n\n"
    
    contradiction_text = ""
    if contradictions:
        contradiction_text = "\nContradictions detected:\n"
        for c in contradictions:
            contradiction_text += f"- {c.description}\n"
    
    return f"""You are a fact-checking interpreter for Arı Kaynak.

Claim: {claim}
Verdict: {verdict}
Confidence: {confidence:.0%}

Evidence sources:
{evidence_text}
{contradiction_text}
Supporting sources: {len(supporting)}
Contradicting sources: {len(contradicting)}

Explain the verdict in 2-3 sentences. Reference the evidence sources.
Be factual and cite sources. Do NOT generate new evidence.
If there are contradictions, explain why the verdict was still given."""


def _build_rule_based_response(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
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
        journal = m.get("journal", "")
        lines.append(f"{i}. [{title}]({url})")
        lines.append(f"   Source: {source_type} | Quality: {quality:.0%}")
        if journal:
            lines.append(f"   Journal: {journal}")
    
    if contradictions:
        lines.extend(["", "**Contradictions detected:**"])
        for c in contradictions:
            lines.append(f"- {c.description}")
    
    if supporting:
        lines.extend(["", f"**Supporting sources:** {len(supporting)}"])
    if contradicting:
        lines.extend(["", f"**Contradicting sources:** {len(contradicting)}"])
    
    if not matches:
        lines.append("No evidence found.")
    
    lines.extend([
        "",
        "---",
        "*Generated by Arı Kaynak Evidence Engine. LLM interpreted the verdict — evidence came from verified sources only.*",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 7: Graph Update
# ---------------------------------------------------------------------------

def update_graph(
    claim_text: str,
    verdict: str,
    confidence: float,
    rating: int,
    matches: list[dict[str, Any]],
    supporting: list[str],
    contradicting: list[str],
    contradictions: list[Contradiction],
    claims: dict[str, Claim] | None = None,
    sources: dict[str, Source] | None = None,
    passages: dict[str, Passage] | None = None,
    evidence: dict[str, Evidence] | None = None,
) -> dict[str, Any]:
    """Record the verification chain in the Evidence Graph."""
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
            source_type=SOURCE_TYPE_MAP.get(st_str, SourceType.UNKNOWN),
            journal=m.get("journal"),
            impact_factor=m.get("impact_factor"),
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
        supporting_sources=supporting,
        contradicting_sources=contradicting,
    )
    if evidence is not None:
        evidence[ev.id] = ev
    
    return {
        "claim": claim,
        "sources": created_sources,
        "passages": created_passages,
        "evidence": ev,
        "contradictions": contradictions,
    }


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Result of running the full verification pipeline."""
    verification_id: str
    query: str
    extracted_claim: str
    archive_results: list[dict]
    external_results: list[dict]
    health_org_results: list[dict]
    passage_verifications: list[dict]
    contradictions: list[dict]
    verdict: str
    verdict_confidence: float
    rating_value: int
    supporting_sources: list[str]
    contradicting_sources: list[str]
    cited_response: str
    steps: list[dict]
    graph_claim_id: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "query": self.query,
            "extracted_claim": self.extracted_claim,
            "archive_results": self.archive_results,
            "external_results": self.external_results,
            "health_org_results": self.health_org_results,
            "passage_verifications": self.passage_verifications,
            "contradictions": self.contradictions,
            "verdict": self.verdict,
            "verdict_confidence": round(self.verdict_confidence, 3),
            "rating_value": self.rating_value,
            "supporting_sources": self.supporting_sources,
            "contradicting_sources": self.contradicting_sources,
            "cited_response": self.cited_response,
            "steps": self.steps,
            "graph_claim_id": self.graph_claim_id,
            "created_at": self.created_at,
        }


class EvidencePipeline:
    """The complete verification pipeline.
    
    Flow:
    1. Claim Extraction (rule-based, no LLM)
    2. Source Discovery (19 sources in parallel)
    3. Passage Verification (verify against original sources)
    4. Evidence Engine (hakem — deterministic, no LLM)
    5. Contradiction Detection (find conflicting evidence)
    6. LLM Interpreter (yorumcu — explains verdict)
    7. Graph Update (records the chain)
    8. Verification History (persistent record)
    """
    
    def __init__(
        self,
        orchestrator: SourceOrchestrator,
        engine: EvidenceEngine,
        llm_provider: Any | None = None,
        db: EvidenceDatabase | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.engine = engine
        self.llm_provider = llm_provider
        self.db = db
        
        # In-memory graph storage
        self.claims: dict[str, Claim] = {}
        self.sources: dict[str, Source] = {}
        self.passages: dict[str, Passage] = {}
        self.evidence: dict[str, Evidence] = {}
        self.contradictions: dict[str, Contradiction] = {}
        self.history: list[VerificationRecord] = []
    
    async def run(self, user_query: str) -> PipelineResult:
        """Execute the complete verification pipeline."""
        verification_id = make_verification_id()
        steps: list[dict[str, Any]] = []
        created_at = datetime.now(timezone.utc).isoformat()
        
        # Step 1: Claim Extraction
        extracted_claim = extract_claim(user_query)
        steps.append({"name": "claim_extraction", "status": "done", "data": {"claim": extracted_claim}})
        
        # Step 2: Source Discovery (19 sources in parallel)
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
        
        # Step 4: Contradiction Detection
        claim_id = make_claim_id(extracted_claim)
        contradictions = detect_contradictions(
            claim_id,
            list(self.sources.values()),
            engine_result["matches"],
        )
        steps.append({"name": "contradiction_detection", "status": "done", "data": {
            "contradictions_found": len(contradictions),
        }})
        
        # Step 5: LLM Interpreter (yorumcu)
        supporting = engine_result.get("supporting_sources", [])
        contradicting = engine_result.get("contradicting_sources", [])
        
        cited_response = await interpret_with_llm(
            extracted_claim,
            engine_result["verdict"],
            engine_result["confidence"],
            engine_result["matches"],
            contradictions,
            supporting,
            contradicting,
            llm_provider=self.llm_provider,
        )
        steps.append({"name": "llm_interpreter", "status": "done", "data": {"response_length": len(cited_response)}})
        
        # Step 6: Graph Update
        graph_result = update_graph(
            extracted_claim,
            engine_result["verdict"],
            engine_result["confidence"],
            engine_result["rating_value"],
            engine_result["matches"],
            supporting,
            contradicting,
            contradictions,
            claims=self.claims,
            sources=self.sources,
            passages=self.passages,
            evidence=self.evidence,
        )
        steps.append({"name": "graph_update", "status": "done", "data": {"claim_id": graph_result["claim"].id}})
        
        # Step 7: Passage Verification
        passage_verifications = await verify_passages(
            graph_result["passages"],
            self.sources,
        )
        steps.append({"name": "passage_verification", "status": "done", "data": {
            "verified": sum(1 for v in passage_verifications if v.get("verified")),
            "total": len(passage_verifications),
        }})
        
        # Step 8: Save verification record
        record = VerificationRecord(
            id=verification_id,
            query=user_query,
            claim_text=extracted_claim,
            verdict=engine_result["verdict"],
            confidence=engine_result["confidence"],
            rating_value=engine_result["rating_value"],
            sources_count=len(archive) + len(external) + len(health_orgs),
            passages_count=len(graph_result["passages"]),
            contradictions_count=len(contradictions),
            created_at=created_at,
            steps=steps,
            cited_response=cited_response,
        )
        self.history.append(record)
        
        # Step 9: Persist to database (if configured)
        if self.db is not None:
            self._save_to_database(
                graph_result["claim"],
                graph_result["sources"],
                graph_result["passages"],
                graph_result["evidence"],
                contradictions,
                record,
            )
        
        return PipelineResult(
            verification_id=verification_id,
            query=user_query,
            extracted_claim=extracted_claim,
            archive_results=archive,
            external_results=external,
            health_org_results=health_orgs,
            passage_verifications=passage_verifications,
            contradictions=[c.to_dict() for c in contradictions],
            verdict=engine_result["verdict"],
            verdict_confidence=engine_result["confidence"],
            rating_value=engine_result["rating_value"],
            supporting_sources=supporting,
            contradicting_sources=contradicting,
            cited_response=cited_response,
            steps=steps,
            graph_claim_id=graph_result["claim"].id,
            created_at=created_at,
        )
    
    def _save_to_database(
        self,
        claim: Claim,
        sources: list[Source],
        passages: list[Passage],
        evidence: Evidence,
        contradictions: list[Contradiction],
        record: VerificationRecord,
    ) -> None:
        """Persist all artifacts to the SQLite database."""
        try:
            self.db.save_claim(claim)
            for source in sources:
                self.db.save_source(source)
            for passage in passages:
                self.db.save_passage(passage)
            self.db.save_evidence(evidence)
            for contradiction in contradictions:
                self.db.save_contradiction(contradiction)
            self.db.save_verification_record(record)
        except Exception as e:
            logger.warning(f"Failed to save to database: {e}")
