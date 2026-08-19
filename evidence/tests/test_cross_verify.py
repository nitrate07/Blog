"""Tests for cross-verification module and API endpoint."""

import pytest
import httpx

from evidence.api import create_app
from evidence.config import Settings
from evidence.connectors import EvidenceCatalog
from evidence.cross_verification import CrossVerifier
from evidence.models import EvidenceSearchResult, SourceQuality
from evidence.rag.parser import ArticleChunk
from evidence.rag.parser import ArticleChunk
from evidence.rag.retriever import ArticleRetriever, RetrievalResult
from evidence.rag.store import ArticleVectorStore


class FakeCatalog:
    def __init__(self, results: list[EvidenceSearchResult] | None = None):
        self._results = results or []

    async def search(self, query: str, limit: int) -> list[EvidenceSearchResult]:
        return self._results[:limit]


class FakeRetriever:
    def __init__(self, results: list | None = None):
        self._results = results or []

    def retrieve(self, query: str, n_results: int = 5, **kwargs) -> list:
        return self._results[:n_results]


def _make_search_result(title: str = "Test Study", provider: str = "pubmed") -> EvidenceSearchResult:
    return EvidenceSearchResult(
        title=title,
        url=f"https://example.com/{provider}/{title.lower().replace(' ', '-')}",
        provider=provider,
        doi="10.1234/test" if provider == "crossref" else None,
        pmid="12345" if provider == "pubmed" else None,
        published_year=2026,
        source_type=SourceQuality.PRIMARY,
    )


def _make_rag_result(article_id: str = "en:test-article") -> RetrievalResult:
    return RetrievalResult(
        article_id=article_id,
        title="Test Article",
        heading="Findings",
        text="Exercise improves cardiovascular health.",
        verdict="Mostly Supported",
        rating_value=4,
        category="Exercise",
        chunk_type="body",
        distance=0.3,
        source_url="https://example.com/test",
    )


class TestCrossVerifier:
    @pytest.mark.asyncio
    async def test_verify_returns_results_from_all_sources(self):
        catalog = FakeCatalog([
            _make_search_result("PubMed Study 1", "pubmed"),
            _make_search_result("Crossref Study 1", "crossref"),
        ])
        retriever = FakeRetriever([_make_rag_result()])
        verifier = CrossVerifier(catalog=catalog, retriever=retriever)
        result = await verifier.verify("exercise heart health")
        assert result.source_count == 3
        assert result.pubmed_count == 1
        assert result.crossref_count == 1
        assert result.existing_count == 1

    @pytest.mark.asyncio
    async def test_verify_handles_no_sources(self):
        catalog = FakeCatalog([])
        retriever = FakeRetriever([])
        verifier = CrossVerifier(catalog=catalog, retriever=retriever)
        result = await verifier.verify("obscure topic")
        assert result.source_count == 0
        assert result.coverage_score == 0.0
        assert "No sources found" in result.summary

    @pytest.mark.asyncio
    async def test_verify_handles_academic_failure(self):
        class FailingCatalog:
            async def search(self, query: str, limit: int) -> list:
                raise httpx.HTTPError("Connection failed")
        retriever = FakeRetriever([_make_rag_result()])
        verifier = CrossVerifier(catalog=FailingCatalog(), retriever=retriever)
        result = await verifier.verify("exercise heart health")
        assert result.pubmed_count == 0
        assert result.crossref_count == 0
        assert result.existing_count == 1

    @pytest.mark.asyncio
    async def test_verify_handles_article_failure(self):
        catalog = FakeCatalog([_make_search_result("Study 1", "pubmed")])
        class FailingRetriever:
            def retrieve(self, query: str, n_results: int = 5, **kwargs) -> list:
                raise Exception("RAG failed")
        verifier = CrossVerifier(catalog=catalog, retriever=FailingRetriever())
        result = await verifier.verify("exercise heart health")
        assert result.pubmed_count == 1
        assert result.existing_count == 0

    @pytest.mark.asyncio
    async def test_verify_no_retriever(self):
        catalog = FakeCatalog([_make_search_result("Study 1", "pubmed")])
        verifier = CrossVerifier(catalog=catalog, retriever=None)
        result = await verifier.verify("exercise heart health")
        assert result.existing_count == 0

    @pytest.mark.asyncio
    async def test_coverage_score_high(self):
        catalog = FakeCatalog([
            _make_search_result("S1", "pubmed"),
            _make_search_result("S2", "pubmed"),
            _make_search_result("S3", "crossref"),
        ])
        retriever = FakeRetriever([_make_rag_result(), _make_rag_result("en:test2")])
        verifier = CrossVerifier(catalog=catalog, retriever=retriever)
        result = await verifier.verify("exercise heart health")
        assert result.coverage_score >= 0.7

    @pytest.mark.asyncio
    async def test_coverage_score_low(self):
        catalog = FakeCatalog([])
        retriever = FakeRetriever([_make_rag_result()])
        verifier = CrossVerifier(catalog=catalog, retriever=retriever)
        result = await verifier.verify("exercise heart health")
        assert result.coverage_score <= 0.5

    @pytest.mark.asyncio
    async def test_to_dict(self):
        catalog = FakeCatalog([_make_search_result("Study", "pubmed")])
        retriever = FakeRetriever([])
        verifier = CrossVerifier(catalog=catalog, retriever=retriever)
        result = await verifier.verify("test claim")
        d = result.to_dict()
        assert "claim" in d
        assert "source_count" in d
        assert "coverage_score" in d
        assert "summary" in d


class TestCrossVerifyAPI:
    @pytest.fixture
    def client(self, tmp_path):
        catalog = FakeCatalog([
            _make_search_result("PubMed Study", "pubmed"),
            _make_search_result("Crossref Study", "crossref"),
        ])
        store = ArticleVectorStore()
        store.upsert_chunks([ArticleChunk(
            article_id="en:test-article", chunk_index=0, title="Test Article",
            heading="Findings", text="Exercise improves cardiovascular health.",
            language="en", category="Exercise", verdict="Mostly Supported",
            rating_value=4, claim_reviewed="Exercise improves health",
            file_number=1, source_url="https://example.com/test", chunk_type="body",
        )])
        retriever = ArticleRetriever(store)
        config = Settings(
            database_path=str(tmp_path / "evidence.db"),
            require_api_key=True,
            bootstrap_api_key="test-api-key-that-is-long-enough",
            api_rate_limit_per_minute=30,
        )
        app = create_app(config=config, catalog=catalog)
        app.state.rag_retriever = retriever
        app.state.cross_verifier = CrossVerifier(
            catalog=catalog, retriever=retriever, config=config,
        )
        return app

    HEADERS = {"X-API-Key": "test-api-key-that-is-long-enough"}

    @pytest.mark.asyncio
    async def test_cross_verify_returns_results(self, client):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as c:
            response = await c.post("/v1/cross-verify", headers=self.HEADERS, json={"claim": "exercise improves heart health"})
        assert response.status_code == 200
        body = response.json()
        assert body["source_count"] > 0
        assert body["coverage_score"] > 0
        assert body["summary"]

    @pytest.mark.asyncio
    async def test_cross_verify_requires_auth(self, client):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as c:
            response = await c.post("/v1/cross-verify", json={"claim": "test"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_cross_verify_validates_input(self, client):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as c:
            response = await c.post("/v1/cross-verify", headers=self.HEADERS, json={"claim": "ab"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_cross_verify_with_limits(self, client):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client), base_url="http://test") as c:
            response = await c.post("/v1/cross-verify", headers=self.HEADERS, json={
                "claim": "exercise heart health",
                "academic_limit": 2,
                "article_limit": 1,
            })
        assert response.status_code == 200
        body = response.json()
        assert len(body["academic_sources"]) <= 2
