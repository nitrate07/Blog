"""Tests for health organization search agents."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from evidence.graph.health_agents import (
    WHOAgent,
    CDCAgent,
    ECDCAgent,
    CochraneAgent,
    ClinicalTrialsAgent,
    FDAAgent,
    EMAAgent,
    GoogleScholarAgent,
    HealthOrgSearchAgent,
)


# ---------------------------------------------------------------------------
# WHO Agent
# ---------------------------------------------------------------------------

class TestWHOAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = WHOAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "resultSet": [
                {
                    "handle": "12345",
                    "metadata": [
                        {"key": "dc.title", "value": "WHO Report on Vaccines"},
                        {"key": "dc.identifier.doi", "value": "10.1234/who"},
                    ],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.health_agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("vaccines", limit=5)

        assert len(results) == 1
        assert results[0]["source"] == "who"
        assert results[0]["organization"] == "World Health Organization"
        assert "vaccines" in results[0]["title"].lower()

    @pytest.mark.asyncio
    async def test_search_handles_failure(self):
        agent = WHOAgent()
        with patch("evidence.graph.health_agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=Exception("Connection failed"))
            results = await agent.search("test")
        assert results == []


# ---------------------------------------------------------------------------
# CDC Agent
# ---------------------------------------------------------------------------

class TestCDCAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = CDCAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "CDC Guidelines on COVID-19",
                    "url": "https://www.cdc.gov/covid/guidelines",
                    "content": "Guidelines for prevention...",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.health_agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("covid guidelines")

        assert len(results) == 1
        assert results[0]["source"] == "cdc"
        assert results[0]["organization"] == "US Centers for Disease Control and Prevention"


# ---------------------------------------------------------------------------
# ClinicalTrials Agent
# ---------------------------------------------------------------------------

class TestClinicalTrialsAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = ClinicalTrialsAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "officialTitle": "Study of Drug X for Diabetes",
                            "nctId": "NCT12345678",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                        },
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.health_agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("diabetes drug")

        assert len(results) == 1
        assert results[0]["source"] == "clinicaltrials"
        assert results[0]["nct_id"] == "NCT12345678"
        assert results[0]["status"] == "RECRUITING"


# ---------------------------------------------------------------------------
# FDA Agent
# ---------------------------------------------------------------------------

class TestFDAAgent:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        agent = FDAAgent()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "openfda": {
                        "brand_name": ["Aspirin"],
                        "generic_name": ["aspirin"],
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.graph.health_agents.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_response)
            results = await agent.search("aspirin")

        assert len(results) == 1
        assert results[0]["source"] == "fda"
        assert results[0]["brand_name"] == "Aspirin"


# ---------------------------------------------------------------------------
# Health Org Search Agent (combined)
# ---------------------------------------------------------------------------

class TestHealthOrgSearchAgent:
    @pytest.mark.asyncio
    async def test_search_all_agents(self):
        agent = HealthOrgSearchAgent()
        # Mock all agents to avoid real HTTP calls
        for a in agent.agents:
            a.search = AsyncMock(return_value=[
                {"source": a.name, "title": f"Test from {a.name}", "url": f"https://{a.name}.org/test"}
            ])

        result = await agent.search("test query")

        assert result["total_results"] >= 1
        assert result["agents_succeeded"] >= 1

    @pytest.mark.asyncio
    async def test_search_specific_sources(self):
        agent = HealthOrgSearchAgent()
        for a in agent.agents:
            a.search = AsyncMock(return_value=[
                {"source": a.name, "title": f"Test from {a.name}", "url": f"https://{a.name}.org/test"}
            ])

        result = await agent.search("test", sources=["who", "cdc"])

        assert result["agents_succeeded"] >= 2

    @pytest.mark.asyncio
    async def test_list_agents(self):
        agent = HealthOrgSearchAgent()
        agents = agent.list_agents()
        assert len(agents) == 8
        names = [a["name"] for a in agents]
        assert "who" in names
        assert "cdc" in names
        assert "fda" in names


# ---------------------------------------------------------------------------
# Health Org API Endpoints
# ---------------------------------------------------------------------------

class TestHealthOrgAPI:
    @pytest.fixture
    def health_client(self, tmp_path):
        from evidence.api import create_app
        from evidence.config import Settings
        config = Settings(
            database_path=str(tmp_path / "evidence.db"),
            require_api_key=True,
            bootstrap_api_key="test-api-key-that-is-long-enough",
            api_rate_limit_per_minute=30,
        )
        app = create_app(config=config)
        return app

    HEADERS = {"X-API-Key": "test-api-key-that-is-long-enough"}

    @pytest.mark.asyncio
    async def test_health_stats(self, health_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=health_client), base_url="http://test") as client:
            response = await client.get("/v1/health/stats", headers=self.HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["total_agents"] == 8

    @pytest.mark.asyncio
    async def test_health_search_requires_auth(self, health_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=health_client), base_url="http://test") as client:
            response = await client.get("/v1/health/search", params={"q": "test"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_health_search_validates_input(self, health_client):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=health_client), base_url="http://test") as client:
            response = await client.get("/v1/health/search", headers=self.HEADERS, params={"q": "ab"})
        assert response.status_code == 422
