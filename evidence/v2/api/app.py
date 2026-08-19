"""FastAPI application — all endpoints for Evidence Verification Infrastructure."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..engine import DeterministicEngine
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
    SourceOrchestrator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)


class VerifyResponse(BaseModel):
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
    agents: list[dict]
    total_agents: int


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    retriever: Any | None = None,
    llm_provider: Any | None = None,
) -> FastAPI:
    """Create the FastAPI application.
    
    Args:
        retriever: ArticleRetriever instance for Archive agent
        llm_provider: Optional LLM provider for interpreter
    """
    app = FastAPI(title="Arı Kaynak Evidence API v2", version="2.0.0")
    
    # Initialize agents
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
    ]
    if retriever:
        agents.insert(2, ArchiveAgent(retriever))
    
    # Initialize components
    orchestrator = SourceOrchestrator(agents)
    engine = DeterministicEngine()
    pipeline = EvidencePipeline(orchestrator, engine, llm_provider)
    
    app.state.orchestrator = orchestrator
    app.state.engine = engine
    app.state.pipeline = pipeline
    
    # -----------------------------------------------------------------------
    # Endpoints
    # -----------------------------------------------------------------------
    
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0"}
    
    @app.post("/v1/verify", response_model=VerifyResponse)
    async def verify(request: VerifyRequest):
        """Full verification pipeline: 11 sources → Engine → Verdict."""
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
            agents=orchestrator.list_agents(),
            total_agents=len(agents),
        )
    
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
    
    return app
