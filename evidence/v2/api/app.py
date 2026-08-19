"""FastAPI application — all endpoints for Evidence Verification Infrastructure v2."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..core.database import EvidenceDatabase
from ..engine import DeterministicEngine, ContradictionDetector, PassageVerifier
from ..pipeline import EvidencePipeline, PipelineResult
from ..sources import (
    PubMedAgent,
    CrossrefAgent,
    ArchiveAgent,
    WHOAgent,
    CDCAgent,
    ECDCAgent,
    CochraneAgent,
    ClinicalTrialsAgent,
    FDAAgent,
    EMAAgent,
    GoogleScholarAgent,
    NEJMAgent,
    JAMAAgent,
    LancetAgent,
    BMJAgent,
    NICEAgent,
    AHAAgent,
    ESCAgent,
    TUSEBAgent,
    SourceOrchestrator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)


class VerifyResponse(BaseModel):
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


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    sources: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    query: str
    results: list[dict]
    total_results: int
    agents_succeeded: int
    agents_failed: int
    agent_stats: list[dict]


class StatsResponse(BaseModel):
    claims: int
    sources: int
    passages: int
    evidence: int
    contradictions: int
    verifications: int
    agents: list[dict]
    total_agents: int


class HistoryResponse(BaseModel):
    records: list[dict]
    total: int


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    retriever: Any | None = None,
    llm_provider: Any | None = None,
    db_path: str | None = None,
) -> FastAPI:
    """Create the FastAPI application.
    
    Args:
        retriever: ArticleRetriever instance for Archive agent
        llm_provider: Optional LLM provider for interpreter
        db_path: Optional SQLite database path for persistent storage
    """
    app = FastAPI(title="Arı Kaynak Evidence API v2", version="2.0.0")
    
    # Initialize all agents (19 sources)
    agents = [
        PubMedAgent(),
        CrossrefAgent(),
        WHOAgent(),
        CDCAgent(),
        ECDCAgent(),
        CochraneAgent(),
        ClinicalTrialsAgent(),
        FDAAgent(),
        EMAAgent(),
        GoogleScholarAgent(),
        NEJMAgent(),
        JAMAAgent(),
        LancetAgent(),
        BMJAgent(),
        NICEAgent(),
        AHAAgent(),
        ESCAgent(),
        TUSEBAgent(),
    ]
    if retriever:
        agents.insert(2, ArchiveAgent(retriever))
    
    # Initialize database (if path provided)
    db = EvidenceDatabase(db_path) if db_path else None
    
    # Initialize components
    orchestrator = SourceOrchestrator(agents)
    engine = DeterministicEngine()
    pipeline = EvidencePipeline(orchestrator, engine, llm_provider, db)
    
    app.state.orchestrator = orchestrator
    app.state.engine = engine
    app.state.pipeline = pipeline
    app.state.db = db
    
    # -----------------------------------------------------------------------
    # Endpoints
    # -----------------------------------------------------------------------
    
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0", "agents": len(agents)}
    
    @app.post("/v1/verify", response_model=VerifyResponse)
    async def verify(request: VerifyRequest):
        """Full verification pipeline: 19 sources → Engine → Contradictions → Verdict."""
        result = await pipeline.run(request.query)
        return VerifyResponse(**result.to_dict())
    
    @app.post("/v1/search", response_model=SearchResponse)
    async def search(request: SearchRequest):
        """Search specific sources without running the full pipeline."""
        result = await orchestrator.search(
            request.query,
            limit_per_agent=request.limit,
            sources=request.sources,
        )
        return SearchResponse(**result)
    
    @app.get("/v1/stats", response_model=StatsResponse)
    async def stats():
        """Get statistics about the evidence graph."""
        return StatsResponse(
            claims=len(pipeline.claims),
            sources=len(pipeline.sources),
            passages=len(pipeline.passages),
            evidence=len(pipeline.evidence),
            contradictions=len(pipeline.contradictions),
            verifications=len(pipeline.history),
            agents=orchestrator.list_agents(),
            total_agents=len(agents),
        )
    
    @app.get("/v1/history", response_model=HistoryResponse)
    async def history(limit: int = 100):
        """Get verification history."""
        records = [r.to_dict() for r in pipeline.history[-limit:]]
        return HistoryResponse(records=records, total=len(pipeline.history))
    
    @app.get("/v1/agents")
    async def list_agents():
        """List all available source agents."""
        return {
            "agents": orchestrator.list_agents(),
            "total_agents": len(agents),
        }
    
    @app.get("/v1/claims/{claim_id}")
    async def get_claim(claim_id: str):
        """Get a specific claim from the graph."""
        claim = pipeline.claims.get(claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        return claim.to_dict()
    
    @app.get("/v1/evidence/{claim_id}")
    async def get_evidence(claim_id: str):
        """Get evidence for a specific claim."""
        evidence_list = [
            ev.to_dict() for ev in pipeline.evidence.values()
            if ev.claim_id == claim_id
        ]
        return {"claim_id": claim_id, "evidence": evidence_list}
    
    @app.get("/v1/contradictions")
    async def get_contradictions():
        """Get all detected contradictions."""
        return {
            "contradictions": [c.to_dict() for c in pipeline.contradictions.values()],
            "total": len(pipeline.contradictions),
        }
    
    @app.get("/v1/verification/{verification_id}")
    async def get_verification(verification_id: str):
        """Get a specific verification record."""
        for record in pipeline.history:
            if record.id == verification_id:
                return record.to_dict()
        raise HTTPException(status_code=404, detail="Verification not found")
    
    @app.get("/v1/db/stats")
    async def db_stats():
        """Get database statistics (requires database to be configured)."""
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")
        return db.get_stats()
    
    @app.get("/v1/db/history")
    async def db_history(limit: int = 100):
        """Get verification history from database (requires database)."""
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")
        records = db.get_verification_history(limit)
        return {"records": [r.to_dict() for r in records], "total": len(records)}
    
    return app
