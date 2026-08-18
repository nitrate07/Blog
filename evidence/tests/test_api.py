import pytest
from fastapi.testclient import TestClient

from evidence.api import create_app
from evidence.engine import EvidenceVerifier
from evidence.models import SourceQuality
from evidence.sources import RetrievedSource


class FakeFetcher:
    async def fetch(self, url: str) -> RetrievedSource:
        return RetrievedSource(url=url, title="Official record", text="The official record states exercise improves cardiovascular health.", quality=SourceQuality.PRIMARY)


@pytest.fixture
def client():
    return TestClient(create_app(EvidenceVerifier(fetcher=FakeFetcher())))


def test_verify_endpoint_returns_contract(client):
    response = client.post("/v1/verify", json={"claim": "Exercise improves cardiovascular health", "sources": [{"url": "https://example.com/record"}]})
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "supported"
    assert body["method"] == "evidence_verification"
    assert body["evidence"][0]["passage"]


def test_api_validation_rejects_missing_sources(client):
    response = client.post("/v1/verify", json={"claim": "Exercise improves cardiovascular health", "sources": []})
    assert response.status_code == 422
