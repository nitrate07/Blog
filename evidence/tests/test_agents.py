"""Tests for evidence search agents."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from evidence.graph.agents import (
    PubMedAgent,
    CrossrefAgent,
    ArchiveAgent,
    EvidenceSearchAgent,
    CombinedSearchResult,
)
from evidence.rag.retriever import ArticleRetriever, RetrievalResult
from evidence.rag.store import ArticleVectorStore
from evidence.rag.parser import ArticleChunk
from evidence.config import Settings


# ---------------------------------------------------------------------------
# PubMed Agent
# ---------------------------------------------------------------------------

class TestPubMedAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = PubMedAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "esearchresult": {"idlist": ["12345", "67890"]}
        }
        mock_response.raise_for_status = MagicMock()

        mock_summary = MagicMock()
        mock_summary.json.return_value = {
            "result": {
                "12345": {
                    "title": "Test PubMed Article",
                    "authors": [{"name": "John Doe"}],
                    "source": "J Test",
                    "pubdate": "2024 Jan",
                    "articleids": [{"idtype": "doi", "value": "10.1234/test"}],
                },
                "67890": {
                    "title": "Another Article",
                    "authors": [],
                    "source": "J Other",
                    "pubdate": "2023",
                    "articleids": [],
                },
            }
        }
        mock_summary.raise_for_status = MagicMock()

        with patch("evidence.graph.agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=[mock_response, mock_summary])
            results = await agent.search("test query", limit=2)

        assert len(results) == 2
        assert results[0]["source"] == "pubmed"
        assert results[0]["pmid"] == "12345"
        assert results[0]["title"] == "Test PubMed Article"
        assert results[0]["doi"] == "10.1234/test"
        assert results[0]["year"] == 2024

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        agent = PubMedAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {"esearchresult": {"idlist": []}}
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("nonexistent query")

        assert results == []


# ---------------------------------------------------------------------------
# Crossref Agent
# ---------------------------------------------------------------------------

class TestCrossrefAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = CrossrefAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/crossref",
                        "title": ["Crossref Article"],
                        "URL": "https://doi.org/10.1234/crossref",
                        "published": {"date-parts": [[2024]]},
                        "author": [{"given": "Jane", "family": "Smith"}],
                        "container-title": ["Journal of Testing"],
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("test query")

        assert len(results) == 1
        assert results[0]["source"] == "crossref"
        assert results[0]["doi"] == "10.1234/crossref"
        assert results[0]["title"] == "Crossref Article"
        assert results[0]["year"] == 2024
        assert results[0]["first_author"] == "Jane Smith"


# ---------------------------------------------------------------------------
# Archive Agent
# ---------------------------------------------------------------------------

class TestArchiveAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        store = ArticleVectorStore()
        chunks = [
            ArticleChunk(
                article_id="en:test-archive", chunk_index=0,
                title="Test Article", heading="Findings",
                text="Exercise improves health.",
                language="en", category="Health", verdict="Supported",
                rating_value=5, claim_reviewed="Exercise improves health",
                file_number=1, source_url="https://example.com/test",
                chunk_type="body",
            ),
        ]
        store.upsert_chunks(chunks)
        retriever = ArticleRetriever(store)
        agent = ArchiveAgent(retriever)

        results = await agent.search("exercise health")

        assert len(results) >= 1
        assert results[0]["source"] == "archive"
        assert results[0]["verdict"] == "Supported"
        assert results[0]["rating_value"] == 5

    @pytest.mark.asyncio
    async def test_search_handles_empty_store(self):
        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)
        agent = ArchiveAgent(retriever)

        results = await agent.search("anything")

        assert results == []


# ---------------------------------------------------------------------------
# Evidence Search Agent (combined)
# ---------------------------------------------------------------------------

class TestEvidenceSearchAgent:
    @pytest.mark.asyncio
    async def test_search_all_agents(self):
        store = ArticleVectorStore()
        chunks = [
            ArticleChunk(
                article_id="en:test-combined", chunk_index=0,
                title="Test", heading="Body",
                text="Test content about exercise.",
                language="en", category="Health", verdict="Supported",
                rating_value=5, claim_reviewed="Exercise",
                file_number=1, source_url="https://example.com",
                chunk_type="body",
            ),
        ]
        store.upsert_chunks(chunks)
        retriever = ArticleRetriever(store)
        agent = EvidenceSearchAgent(retriever=retriever)

        # Mock external agents to avoid real HTTP calls
        for a in agent.agents:
            if a.name in ("pubmed", "crossref"):
                a.search = AsyncMock(return_value=[])

        result = await agent.search("exercise health")

        assert isinstance(result, CombinedSearchResult)
        assert result.query == "exercise health"
        assert result.agents_succeeded >= 1

    @pytest.mark.asyncio
    async def test_search_single_agent(self):
        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)
        agent = EvidenceSearchAgent(retriever=retriever)

        # Mock external agents
        for a in agent.agents:
            if a.name in ("pubmed", "crossref"):
                a.search = AsyncMock(return_value=[])

        result = await agent.search("test", limit_per_agent=3)

        assert isinstance(result, CombinedSearchResult)
        assert result.total_results >= 0

    @pytest.mark.asyncio
    async def test_deduplication(self):
        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)
        agent = EvidenceSearchAgent(retriever=retriever)

        # Mock agents to return duplicate URLs
        duplicate_results = [
            {"source": "pubmed", "url": "https://example.com/1", "title": "Article 1"},
            {"source": "crossref", "url": "https://example.com/1", "title": "Article 1 Duplicate"},
            {"source": "archive", "url": "https://example.com/2", "title": "Article 2"},
        ]
        for a in agent.agents:
            if a.name == "pubmed":
                a.search = AsyncMock(return_value=[duplicate_results[0]])
            elif a.name == "crossref":
                a.search = AsyncMock(return_value=[duplicate_results[1]])
            elif a.name == "archive":
                a.search = AsyncMock(return_value=[duplicate_results[2]])

        result = await agent.search("test")

        # Should be deduplicated
        assert result.total_results == 2


# ---------------------------------------------------------------------------
# Agent API Endpoints
# ---------------------------------------------------------------------------

class TestAgentAPI:
    @pytest.fixture
    def agent_client(self, tmp_path):
        from evidence.api import create_app
        store = ArticleVectorStore()
        chunks = [
            ArticleChunk(
                article_id="en:test-agent-api", chunk_index=0,
                title="Test Article", heading="Body",
                text="Test content about vitamin D.",
                language="en", category="Health", verdict="Supported",
                rating_value=5, claim_reviewed="Vitamin D",
                file_number=1, source_url="https://example.com/test",
                chunk_type="body",
            ),
        ]
        store.upsert_chunks(chunks)
        retriever = ArticleRetriever(store)
        config = Settings(
            database_path=str(tmp_path / "evidence.db"),
            require_api_key=True,
            bootstrap_api_key="test-api-key-that-is-long-enough",
            api_rate_limit_per_minute=30,
        )
        app = create_app(config=config)
        app.state.rag_retriever = retriever
        return app

    HEADERS = {"X-API-Key": "test-api-key-that-is-long-enough"}

    @pytest.mark.asyncio
    async def test_agent_search_all(self, agent_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_client), base_url="http://test") as client:
            response = await client.get("/v1/agents/search", headers=self.HEADERS, params={"q": "vitamin D"})
        assert response.status_code == 200
        body = response.json()
        assert "total_results" in body
        assert "agents_succeeded" in body

    @pytest.mark.asyncio
    async def test_agent_search_single_source(self, agent_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_client), base_url="http://test") as client:
            response = await client.get("/v1/agents/search", headers=self.HEADERS, params={"q": "vitamin D", "source": "archive"})
        assert response.status_code == 200
        body = response.json()
        assert body["agent"] == "archive"

    @pytest.mark.asyncio
    async def test_agent_search_invalid_source(self, agent_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_client), base_url="http://test") as client:
            response = await client.get("/v1/agents/search", headers=self.HEADERS, params={"q": "test", "source": "invalid"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_agent_stats(self, agent_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_client), base_url="http://test") as client:
            response = await client.get("/v1/agents/stats", headers=self.HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["total_agents"] == 3

    @pytest.mark.asyncio
    async def test_agent_search_requires_auth(self, agent_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_client), base_url="http://test") as client:
            response = await client.get("/v1/agents/search", params={"q": "test"})
        assert response.status_code == 401
