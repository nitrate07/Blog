"""Real integration tests for Evidence Verification Infrastructure v2.

These tests make actual HTTP requests to external APIs.
They are marked with @pytest.mark.integration and can be skipped in CI.
"""

import os
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Skip if INTEGRATION_TESTS env var is not set
INTEGRATION_ENABLED = os.environ.get("INTEGRATION_TESTS", "").lower() == "true"
pytestmark = pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="Integration tests disabled. Set INTEGRATION_TESTS=true to enable."
)

from evidence.v2.sources.pubmed import PubMedAgent
from evidence.v2.sources.crossref import CrossrefAgent
from evidence.v2.sources.who import WHOAgent
from evidence.v2.sources.cdc import CDCAgent
from evidence.v2.sources.cochrane import CochraneAgent
from evidence.v2.sources.clinicaltrials import ClinicalTrialsAgent
from evidence.v2.sources.fda import FDAAgent
from evidence.v2.sources.ema import EMAAgent
from evidence.v2.sources.orchestrator import SourceOrchestrator
from evidence.v2.engine.engine import DeterministicEngine
from evidence.v2.pipeline.pipeline import EvidencePipeline


# ---------------------------------------------------------------------------
# Individual Agent Integration Tests
# ---------------------------------------------------------------------------

class TestPubMedIntegration:
    @pytest.mark.asyncio
    async def test_search_vitamin_d(self):
        agent = PubMedAgent()
        results = await agent.search("vitamin D deficiency", limit=3)
        assert isinstance(results, list)
        if results:
            r = results[0]
            assert "url" in r
            assert "pubmed" in r.get("source", "")
            assert r.get("passage")  # Should have abstract

    @pytest.mark.asyncio
    async def test_search_exercise_heart(self):
        agent = PubMedAgent()
        results = await agent.search("exercise heart health", limit=3)
        assert isinstance(results, list)


class TestCrossrefIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = CrossrefAgent()
        results = await agent.search("COVID-19 vaccine", limit=3)
        assert isinstance(results, list)
        if results:
            assert "doi" in results[0] or "url" in results[0]


class TestWHOIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = WHOAgent()
        results = await agent.search("malaria prevention", limit=3)
        assert isinstance(results, list)


class TestCDCIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = CDCAgent()
        results = await agent.search("influenza vaccine", limit=3)
        assert isinstance(results, list)


class TestCochraneIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = CochraneAgent()
        results = await agent.search("aspirin prevention", limit=3)
        assert isinstance(results, list)


class TestClinicalTrialsIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = ClinicalTrialsAgent()
        results = await agent.search("diabetes treatment", limit=3)
        assert isinstance(results, list)


class TestFDAIntegration:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = FDAAgent()
        results = await agent.search("ibuprofen", limit=3)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Orchestrator Integration Test
# ---------------------------------------------------------------------------

class TestOrchestratorIntegration:
    @pytest.mark.asyncio
    async def test_search_all_sources(self):
        agents = [PubMedAgent(), CrossrefAgent()]
        orchestrator = SourceOrchestrator(agents)
        result = await orchestrator.search("vitamin D health", limit_per_agent=2)
        assert "results" in result
        assert "agents_succeeded" in result
        assert result["agents_succeeded"] >= 1


# ---------------------------------------------------------------------------
# Full Pipeline Integration Test
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_vitamin_d(self):
        agents = [PubMedAgent()]
        orchestrator = SourceOrchestrator(agents)
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine)

        result = await pipeline.run("Is vitamin D deficiency common?")

        assert result.verdict
        assert result.cited_response
        assert result.archive_results or result.external_results or result.health_org_results
        assert len(result.steps) >= 5
