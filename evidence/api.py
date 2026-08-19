"""FastAPI entry point for the public, provider-independent verification contract."""

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .config import Settings, settings
from .connectors import EvidenceCatalog
from .cross_verification import CrossVerifier
from .engine import EvidenceVerifier
from .graph import EvidenceGraph, GraphBuilder
from .graph.agents import EvidenceSearchAgent
from .graph.health_agents import HealthOrgSearchAgent
from .graph.pipeline import run_pipeline
from .models import EvidenceSearchResponse, VerificationRequest, VerificationResponse
from .provider_registry import create_provider_from_config, get_provider_statuses, list_providers, test_provider
from .rag import ArticleRetriever, ArticleVectorStore
from .security import APIKeyAuthenticator, APIPrincipal, SlidingWindowRateLimiter
from .storage import VerificationStore


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    n_results: int = Field(default=5, ge=1, le=20)
    language: str | None = Field(default=None, pattern="^(en|tr)$")
    category: str | None = None


class RAGQueryResponse(BaseModel):
    query: str
    context: str
    results: list[dict]
    total_results: int


class RAGIndexResponse(BaseModel):
    indexed: int
    chunks: int
    articles: int


class CrossVerifyRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=4000)
    academic_limit: int = Field(default=5, ge=1, le=20)
    article_limit: int = Field(default=5, ge=1, le=20)


class CrossVerifyResponse(BaseModel):
    claim: str
    existing_articles: list[dict]
    academic_sources: list[dict]
    source_count: int
    pubmed_count: int
    crossref_count: int
    existing_count: int
    coverage_score: float
    summary: str


class PipelineRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)


class PipelineResponse(BaseModel):
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


def create_app(verifier: EvidenceVerifier | None = None, *, config: Settings = settings, store: VerificationStore | None = None, catalog: EvidenceCatalog | None = None) -> FastAPI:
    app = FastAPI(title="Arı Kaynak Evidence API", version="0.3.0")

    if verifier is None:
        verifier = EvidenceVerifier(provider=create_provider_from_config(config))

    app.state.verifier = verifier
    app.state.store = store or VerificationStore(config.database_path)
    app.state.config = config
    app.state.authenticator = APIKeyAuthenticator(app.state.store, config)
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.catalog = catalog or EvidenceCatalog()

    rag_store = ArticleVectorStore(
        persist_directory=config.rag_persist_directory,
    )
    app.state.rag_retriever = ArticleRetriever(rag_store)
    app.state.cross_verifier = CrossVerifier(
        catalog=app.state.catalog,
        retriever=app.state.rag_retriever,
        config=config,
    )

    evidence_graph = EvidenceGraph(persist_path=str(Path(config.rag_persist_directory).parent / "evidence_graph.json"))
    app.state.graph_builder = GraphBuilder(evidence_graph, catalog=app.state.catalog)
    app.state.evidence_agent = EvidenceSearchAgent(retriever=app.state.rag_retriever, config=config)
    app.state.health_agent = HealthOrgSearchAgent(config=config)

    async def principal_for_request(request: Request, x_api_key: str | None = Header(default=None)) -> APIPrincipal | None:
        if not request.app.state.config.require_api_key:
            return None
        principal = request.app.state.authenticator.authenticate(x_api_key)
        request.app.state.rate_limiter.check(principal)
        return principal

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ari-kaynak-evidence"}

    @app.get("/v1/provider/status", tags=["provider"])
    async def provider_status() -> dict[str, object]:
        """Return configuration status of all known LLM providers."""
        statuses = get_provider_statuses(app.state.config)
        return {
            "providers": [
                {"name": s.name, "configured": s.configured, "model": s.model, "is_active": s.is_active}
                for s in statuses
            ],
            "available": list_providers(),
        }

    @app.post("/v1/provider/test/{provider_name}", tags=["provider"])
    async def provider_test(provider_name: str) -> dict[str, object]:
        """Send a minimal request to verify a provider is reachable."""
        result = await test_provider(provider_name, app.state.config)
        if result.get("status") == "error":
            raise HTTPException(status_code=502, detail=result)
        return result

    @app.post("/v1/verify", response_model=VerificationResponse, tags=["verification"])
    async def verify_claim(request: VerificationRequest, principal: APIPrincipal | None = Depends(principal_for_request)) -> VerificationResponse:
        response = await app.state.verifier.verify(request)
        app.state.store.record_verification(response, principal.id if principal else None)
        return response

    @app.get("/v1/search", response_model=EvidenceSearchResponse, tags=["discovery"])
    async def search_evidence(query: str = Query(min_length=3, max_length=500), limit: int = Query(default=5, ge=1, le=10), _: APIPrincipal | None = Depends(principal_for_request)) -> EvidenceSearchResponse:
        return EvidenceSearchResponse(query=query, results=await app.state.catalog.search(query, limit))

    @app.get("/v1/verifications/{verification_id}", response_model=VerificationResponse, tags=["verification"])
    async def get_verification(verification_id: str, _: APIPrincipal | None = Depends(principal_for_request)) -> VerificationResponse:
        response = app.state.store.get_verification(verification_id)
        if not response:
            raise HTTPException(status_code=404, detail="verification not found")
        return response

    @app.post("/v1/rag/query", response_model=RAGQueryResponse, tags=["rag"])
    async def rag_query(request: RAGQueryRequest, _: APIPrincipal | None = Depends(principal_for_request)) -> RAGQueryResponse:
        """Semantic search over Arı Kaynak articles using RAG."""
        retriever = app.state.rag_retriever
        results = retriever.retrieve(
            query=request.query,
            n_results=request.n_results,
            language=request.language,
            category=request.category,
        )
        context = retriever.build_context(
            query=request.query,
            n_results=request.n_results,
            max_context_length=config.rag_max_context_length,
            language=request.language,
        )
        return RAGQueryResponse(
            query=request.query,
            context=context,
            results=[r.to_dict() for r in results],
            total_results=len(results),
        )

    @app.get("/v1/rag/search", tags=["rag"])
    async def rag_search(
        q: str = Query(min_length=3, max_length=500),
        n: int = Query(default=5, ge=1, le=20),
        language: str | None = Query(default=None, pattern="^(en|tr)$"),
        category: str | None = None,
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Quick semantic search over articles."""
        retriever = app.state.rag_retriever
        results = retriever.retrieve(query=q, n_results=n, language=language, category=category)
        return {
            "query": q,
            "results": [r.to_dict() for r in results],
            "total": len(results),
        }

    @app.post("/v1/rag/index", response_model=RAGIndexResponse, tags=["rag"])
    async def rag_index(_: APIPrincipal | None = Depends(principal_for_request)) -> RAGIndexResponse:
        """Re-index all articles into the vector store."""
        retriever = app.state.rag_retriever
        articles_dir = Path(config.rag_articles_dir)
        tr_dir = Path(config.rag_tr_dir) if config.rag_tr_dir else None
        result = retriever.index_articles(articles_dir=articles_dir, tr_dir=tr_dir)
        return RAGIndexResponse(**result)

    @app.get("/v1/rag/stats", tags=["rag"])
    async def rag_stats(_: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Return RAG index statistics."""
        return app.state.rag_retriever.get_stats()

    @app.post("/v1/cross-verify", response_model=CrossVerifyResponse, tags=["verification"])
    async def cross_verify(request: CrossVerifyRequest, principal: APIPrincipal | None = Depends(principal_for_request)) -> CrossVerifyResponse:
        """Multi-source cross-verification: searches PubMed, Crossref, and existing articles simultaneously."""
        result = await app.state.cross_verifier.verify(
            claim=request.claim,
            academic_limit=request.academic_limit,
            article_limit=request.article_limit,
        )
        return CrossVerifyResponse(**result.to_dict())

    @app.post("/v1/graph/build", tags=["graph"])
    async def graph_build(
        source: str = Query(default="claims_json", pattern="^(claims_json|articles)$"),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Build the evidence graph from claims.json or articles."""
        builder = app.state.graph_builder
        if source == "claims_json":
            result = builder.build_from_claims_json("claims.json")
        else:
            articles_dir = Path(config.rag_articles_dir)
            tr_dir = Path(config.rag_tr_dir) if config.rag_tr_dir else None
            result = builder.build_from_articles(articles_dir, tr_dir)
        return {"source": source, **result}

    @app.get("/v1/graph/stats", tags=["graph"])
    async def graph_stats(_: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Return evidence graph statistics."""
        return app.state.graph_builder.graph.get_stats()

    @app.get("/v1/graph/chain/{claim_id}", tags=["graph"])
    async def graph_chain(claim_id: str, _: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Get the full verification chain for a claim: claim → evidence → source → passage → verdict."""
        chain = app.state.graph_builder.get_full_chain(claim_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
        return chain.to_dict()

    @app.get("/v1/graph/related/{claim_id}", tags=["graph"])
    async def graph_related(claim_id: str, _: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Find claims related to a given claim via shared sources or category."""
        related = app.state.graph_builder.graph.get_related_claims(claim_id)
        return {
            "claim_id": claim_id,
            "related": [c.to_dict() for c in related],
            "count": len(related),
        }

    @app.get("/v1/graph/contradictions", tags=["graph"])
    async def graph_contradictions(_: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Find claims that contradict each other."""
        contradictions = app.state.graph_builder.graph.get_contradictions()
        return {
            "contradictions": [
                {"claim_a": a.to_dict(), "claim_b": b.to_dict(), "reason": reason}
                for a, b, reason in contradictions
            ],
            "count": len(contradictions),
        }

    @app.get("/v1/graph/search", tags=["graph"])
    async def graph_search(
        q: str = Query(min_length=2, max_length=500),
        category: str | None = None,
        verdict: str | None = None,
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search claims in the evidence graph."""
        results = app.state.graph_builder.graph.search_claims(q, category=category, verdict=verdict)
        return {
            "query": q,
            "results": [c.to_dict() for c in results],
            "count": len(results),
        }

    @app.post("/v1/pipeline", response_model=PipelineResponse, tags=["pipeline"])
    async def run_full_pipeline(request: PipelineRequest, principal: APIPrincipal | None = Depends(principal_for_request)) -> PipelineResponse:
        """Full verification pipeline: 11 sources in parallel → Evidence Engine → LLM Interpreter → Cited Response.
        
        Sources: Archive, PubMed, Crossref, WHO, CDC, ECDC, Cochrane, ClinicalTrials, FDA, EMA, Google Scholar.
        LLM is used ONLY as an interpreter (yorumcu) to explain the verdict.
        """
        result = await run_pipeline(
            user_query=request.query,
            retriever=app.state.rag_retriever,
            catalog=app.state.catalog,
            graph_builder=app.state.graph_builder,
            llm_provider=app.state.verifier.provider if hasattr(app.state.verifier, "provider") else None,
            health_agent=app.state.health_agent,
            config=config,
        )
        return PipelineResponse(**result.to_dict())

    @app.get("/v1/agents/search", tags=["agents"])
    async def agent_search(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        source: str | None = Query(default=None, pattern="^(pubmed|crossref|archive)$"),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search for evidence using specialized agents (PubMed, Crossref, Archive)."""
        agent = app.state.evidence_agent
        if source:
            # Run single agent
            for a in agent.agents:
                if a.name == source:
                    results = await a.search(q, limit)
                    return {
                        "query": q,
                        "agent": source,
                        "results": results,
                        "total": len(results),
                    }
            raise HTTPException(status_code=400, detail=f"Unknown agent: {source}")
        # Run all agents
        result = await agent.search(q, limit_per_agent=limit)
        return result.to_dict()

    @app.get("/v1/agents/pubmed", tags=["agents"])
    async def agent_pubmed(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search PubMed for medical/scientific evidence."""
        from .graph.agents import PubMedAgent
        pubmed = PubMedAgent(app.state.config)
        results = await pubmed.search(q, limit)
        return {"query": q, "agent": "pubmed", "results": results, "total": len(results)}

    @app.get("/v1/agents/crossref", tags=["agents"])
    async def agent_crossref(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search Crossref for academic papers."""
        from .graph.agents import CrossrefAgent
        crossref = CrossrefAgent(app.state.config)
        results = await crossref.search(q, limit)
        return {"query": q, "agent": "crossref", "results": results, "total": len(results)}

    @app.get("/v1/agents/archive", tags=["agents"])
    async def agent_archive(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search Arı Kaynak archive via RAG."""
        from .graph.agents import ArchiveAgent
        archive = ArchiveAgent(app.state.rag_retriever)
        results = await archive.search(q, limit)
        return {"query": q, "agent": "archive", "results": results, "total": len(results)}

    @app.get("/v1/agents/stats", tags=["agents"])
    async def agent_stats(_: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Return available agents and their status."""
        agent = app.state.evidence_agent
        return {
            "agents": [
                {"name": a.name, "source_type": a.source_type}
                for a in agent.agents
            ],
            "total_agents": len(agent.agents),
        }

    @app.get("/v1/health/search", tags=["health_orgs"])
    async def health_search(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        sources: str | None = Query(default=None, description="Comma-separated agent names: who,cdc,ecdc,cochrane,clinicaltrials,fda,ema,google_scholar"),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search global health organizations for evidence.
        
        Available sources: WHO, CDC, ECDC, Cochrane, ClinicalTrials.gov, FDA, EMA, Google Scholar.
        """
        source_list = [s.strip() for s in sources.split(",")] if sources else None
        result = await app.state.health_agent.search(q, limit_per_agent=limit, sources=source_list)
        return result

    @app.get("/v1/health/who", tags=["health_orgs"])
    async def health_who(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search WHO (World Health Organization)."""
        from .graph.health_agents import WHOAgent
        agent = WHOAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "who", "results": results, "total": len(results)}

    @app.get("/v1/health/cdc", tags=["health_orgs"])
    async def health_cdc(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search CDC (US Centers for Disease Control)."""
        from .graph.health_agents import CDCAgent
        agent = CDCAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "cdc", "results": results, "total": len(results)}

    @app.get("/v1/health/ecdc", tags=["health_orgs"])
    async def health_ecdc(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search ECDC (European Centre for Disease Prevention and Control)."""
        from .graph.health_agents import ECDCAgent
        agent = ECDCAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "ecdc", "results": results, "total": len(results)}

    @app.get("/v1/health/cochrane", tags=["health_orgs"])
    async def health_cochrane(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search Cochrane Library (systematic reviews)."""
        from .graph.health_agents import CochraneAgent
        agent = CochraneAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "cochrane", "results": results, "total": len(results)}

    @app.get("/v1/health/clinicaltrials", tags=["health_orgs"])
    async def health_clinicaltrials(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search ClinicalTrials.gov."""
        from .graph.health_agents import ClinicalTrialsAgent
        agent = ClinicalTrialsAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "clinicaltrials", "results": results, "total": len(results)}

    @app.get("/v1/health/fda", tags=["health_orgs"])
    async def health_fda(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search FDA (US Food and Drug Administration)."""
        from .graph.health_agents import FDAAgent
        agent = FDAAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "fda", "results": results, "total": len(results)}

    @app.get("/v1/health/ema", tags=["health_orgs"])
    async def health_ema(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search EMA (European Medicines Agency)."""
        from .graph.health_agents import EMAAgent
        agent = EMAAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "ema", "results": results, "total": len(results)}

    @app.get("/v1/health/google_scholar", tags=["health_orgs"])
    async def health_google_scholar(
        q: str = Query(min_length=3, max_length=500),
        limit: int = Query(default=5, ge=1, le=20),
        _: APIPrincipal | None = Depends(principal_for_request),
    ) -> dict:
        """Search Google Scholar."""
        from .graph.health_agents import GoogleScholarAgent
        agent = GoogleScholarAgent(app.state.config)
        results = await agent.search(q, limit)
        return {"query": q, "agent": "google_scholar", "results": results, "total": len(results)}

    @app.get("/v1/health/stats", tags=["health_orgs"])
    async def health_stats(_: APIPrincipal | None = Depends(principal_for_request)) -> dict:
        """Return available health organization agents."""
        return {
            "agents": app.state.health_agent.list_agents(),
            "total_agents": len(app.state.health_agent.agents),
        }

    return app


app = create_app()
