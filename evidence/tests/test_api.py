import pytest
import httpx

from evidence.api import create_app
from evidence.config import Settings
from evidence.connectors import EvidenceCatalog
from evidence.engine import EvidenceVerifier
from evidence.models import EvidenceSearchResult, SourceQuality
from evidence.sources import RetrievedSource


class FakeFetcher:
    async def fetch(self, url: str) -> RetrievedSource:
        return RetrievedSource(url=url, title="Official record", text="The official record states exercise improves cardiovascular health.", quality=SourceQuality.PRIMARY)


class FakeCatalog:
    async def search(self, query: str, limit: int):
        return [EvidenceSearchResult(title="Known study", url="https://pubmed.ncbi.nlm.nih.gov/123/", provider="pubmed", pmid="123")]


@pytest.fixture
def client(tmp_path):
    config = Settings(
        database_path=str(tmp_path / "evidence.db"),
        require_api_key=True,
        bootstrap_api_key="test-api-key-that-is-long-enough",
        api_rate_limit_per_minute=10,
    )
    return create_app(EvidenceVerifier(fetcher=FakeFetcher()), config=config, catalog=FakeCatalog())


HEADERS = {"X-API-Key": "test-api-key-that-is-long-enough"}


@pytest.mark.asyncio
async def test_verify_endpoint_returns_contract(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as http_client:
        response = await http_client.post("/v1/verify", headers=HEADERS, json={"claim": "Exercise improves cardiovascular health", "sources": [{"url": "https://example.com/record"}]})
        assert response.status_code == 200
        body = response.json()
        persisted = await http_client.get(f"/v1/verifications/{body['verification_id']}", headers=HEADERS)
    assert response.status_code == 200
    assert body["verdict"] == "supported"
    assert body["method"] == "evidence_verification"
    assert body["evidence"][0]["passage"]
    assert body["verification_id"]
    assert persisted.status_code == 200
    assert persisted.json()["verification_id"] == body["verification_id"]


@pytest.mark.asyncio
async def test_api_validation_rejects_missing_sources(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as http_client:
        response = await http_client.post("/v1/verify", headers=HEADERS, json={"claim": "Exercise improves cardiovascular health", "sources": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_key_is_required(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as http_client:
        response = await http_client.post("/v1/verify", json={"claim": "Exercise improves cardiovascular health", "sources": [{"url": "https://example.com/record"}]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_endpoint_is_authenticated_and_returns_metadata(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as http_client:
        denied = await http_client.get("/v1/search", params={"query": "cardiovascular health"})
        allowed = await http_client.get("/v1/search", headers=HEADERS, params={"query": "cardiovascular health"})
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["results"][0]["pmid"] == "123"
