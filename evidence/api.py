"""FastAPI entry point for the public, provider-independent verification contract."""

from fastapi import FastAPI

from .engine import EvidenceVerifier
from .models import VerificationRequest, VerificationResponse


def create_app(verifier: EvidenceVerifier | None = None) -> FastAPI:
    app = FastAPI(title="Arı Kaynak Evidence API", version="0.1.0")
    app.state.verifier = verifier or EvidenceVerifier()

    @app.post("/v1/verify", response_model=VerificationResponse, tags=["verification"])
    async def verify_claim(request: VerificationRequest) -> VerificationResponse:
        return await app.state.verifier.verify(request)

    return app


app = create_app()
