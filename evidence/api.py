"""FastAPI entry point for the public, provider-independent verification contract."""

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .config import Settings, settings
from .connectors import EvidenceCatalog
from .engine import EvidenceVerifier
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

    return app


app = create_app()
