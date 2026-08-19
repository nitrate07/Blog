"""FastAPI entry point for the public, provider-independent verification contract."""

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from .config import Settings, settings
from .connectors import EvidenceCatalog
from .engine import EvidenceVerifier
from .models import EvidenceSearchResponse, VerificationRequest, VerificationResponse
from .provider_registry import create_provider_from_config, get_provider_statuses, list_providers, test_provider
from .security import APIKeyAuthenticator, APIPrincipal, SlidingWindowRateLimiter
from .storage import VerificationStore


def create_app(verifier: EvidenceVerifier | None = None, *, config: Settings = settings, store: VerificationStore | None = None, catalog: EvidenceCatalog | None = None) -> FastAPI:
    app = FastAPI(title="Arı Kaynak Evidence API", version="0.2.0")

    if verifier is None:
        verifier = EvidenceVerifier(provider=create_provider_from_config(config))

    app.state.verifier = verifier
    app.state.store = store or VerificationStore(config.database_path)
    app.state.config = config
    app.state.authenticator = APIKeyAuthenticator(app.state.store, config)
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.catalog = catalog or EvidenceCatalog()

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

    return app


app = create_app()
