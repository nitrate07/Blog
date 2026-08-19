"""Tests for Evidence Verification Infrastructure v2."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from evidence.v2.core.types import (
    Claim, Source, Passage, Evidence, Verdict, SourceType,
    content_hash, make_source_id, make_passage_id, make_evidence_id, make_claim_id,
)
from evidence.v2.core.interfaces import SourceAgent, EvidenceEngine
from evidence.v2.engine.engine import DeterministicEngine
from evidence.v2.pipeline.pipeline import (
    extract_claim,
    discover_sources,
    run_engine,
    interpret_with_llm,
    update_graph,
    EvidencePipeline,
)
from evidence.v2.sources.orchestrator import SourceOrchestrator
from evidence.v2.api.app import create_app


# ---------------------------------------------------------------------------
# Core Types
# ---------------------------------------------------------------------------

class TestCoreTypes:
    def test_verdict_enum(self):
        assert Verdict.SUPPORTED == "supported"
        assert Verdict.MOSTLY_SUPPORTED == "mostly_supported"
        assert Verdict.PARTLY_SUPPORTED == "partly_supported"
        assert Verdict.MISLEADING == "misleading"
        assert Verdict.UNSUPPORTED == "unsupported"
        assert Verdict.UNVERIFIED == "unverified"
    
    def test_source_type_enum(self):
        assert SourceType.PRIMARY == "primary"
        assert SourceType.SECONDARY == "secondary"
        assert SourceType.TERTIARY == "tertiary"
        assert SourceType.UNKNOWN == "unknown"
    
    def test_content_hash(self):
        h = content_hash("hello world")
        assert len(h) == 16
        assert h == content_hash("hello world")  # deterministic
    
    def test_make_source_id(self):
        assert make_source_id("https://example.com/") == "source::https://example.com"
    
    def test_make_passage_id(self):
        assert make_passage_id("claim::1", 0) == "passage::claim::1::0"
    
    def test_make_evidence_id(self):
        assert make_evidence_id("claim::1") == "evidence::claim::1"
    
    def test_make_claim_id(self):
        id1 = make_claim_id("test claim")
        id2 = make_claim_id("test claim")
        assert id1 == id2  # deterministic
    
    def test_claim_to_dict(self):
        claim = Claim(id="c1", text="test", author="a", category="cat", date_filed="", file_number=0)
        d = claim.to_dict()
        assert d["id"] == "c1"
        assert d["text"] == "test"
    
    def test_source_to_dict(self):
        source = Source(id="s1", url="https://example.com", title="Test", source_type=SourceType.PRIMARY)
        d = source.to_dict()
        assert d["source_type"] == "primary"
    
    def test_passage_to_dict(self):
        passage = Passage(id="p1", text="hello", source_id="s1", relevance=0.8, content_hash="abc123")
        d = passage.to_dict()
        assert d["content_hash"] == "abc123"
    
    def test_evidence_to_dict(self):
        evidence = Evidence(
            id="e1", claim_id="c1", passages=[],
            verdict=Verdict.SUPPORTED, confidence=0.8, rating_value=4,
        )
        d = evidence.to_dict()
        assert d["verdict"] == "supported"
        assert d["confidence"] == 0.8


# ---------------------------------------------------------------------------
# Claim Extraction
# ---------------------------------------------------------------------------

class TestClaimExtraction:
    def test_extracts_from_question(self):
        assert extract_claim("Is exercise good for heart health?") == "exercise good for heart health?"
    
    def test_extracts_from_is_it_true(self):
        assert extract_claim("Is it true that fasting helps weight loss?") == "fasting helps weight loss?"
    
    def test_extracts_from_tell_me_about(self):
        assert extract_claim("Tell me about vitamin D deficiency") == "vitamin D deficiency?"
    
    def test_adds_question_mark(self):
        assert extract_claim("vitamin D helps bones") == "vitamin D helps bones?"
    
    def test_preserves_question_mark(self):
        assert extract_claim("exercise improves health?") == "exercise improves health?"


# ---------------------------------------------------------------------------
# Evidence Engine
# ---------------------------------------------------------------------------

class TestDeterministicEngine:
    def test_empty_evidence_returns_unverified(self):
        engine = DeterministicEngine()
        result = engine.judge("test claim?", [], [], [])
        assert result["verdict"] == "unverified"
        assert result["confidence"] == 0.0
        assert result["rating_value"] == 0
    
    def test_archive_match_provides_verdict(self):
        engine = DeterministicEngine()
        archive = [{
            "title": "Test Article",
            "source_url": "https://example.com",
            "text": "The evidence supports the claim",
            "verdict": "Mostly Supported",
            "rating_value": 4,
            "distance": 0.3,
        }]
        result = engine.judge("test claim?", archive, [], [])
        assert result["verdict"] == "Mostly Supported"
        assert result["confidence"] >= 0.3
    
    def test_health_org_results_scored(self):
        engine = DeterministicEngine()
        health_orgs = [{
            "title": "WHO Report",
            "url": "https://who.int/report",
            "passage": "Vitamin D is important for health",
            "source_type": "international_organization",
        }]
        result = engine.judge("vitamin D health?", [], [], health_orgs)
        assert len(result["matches"]) >= 1
        assert result["matches"][0]["quality_score"] > 0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        # Create mock agents
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine)
        
        result = await pipeline.run("Is exercise good for heart health?")
        
        assert result.extracted_claim
        assert result.verdict in ["unverified", "partly_supported", "mostly_supported", "supported"]
        assert result.cited_response
        assert result.graph_claim_id
        assert len(result.steps) >= 5
    
    @pytest.mark.asyncio
    async def test_pipeline_principle(self):
        """Verify: LLM is never an evidence source."""
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine, llm_provider=None)
        
        result = await pipeline.run("test query")
        
        # All results are lists
        assert isinstance(result.archive_results, list)
        assert isinstance(result.external_results, list)
        assert isinstance(result.health_org_results, list)
        
        # Graph was updated
        assert len(pipeline.claims) >= 1
        assert len(pipeline.evidence) >= 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class TestAPI:
    def test_create_app(self):
        app = create_app()
        assert app.title == "Arı Kaynak Evidence API v2"
        assert app.version == "2.0.0"
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
    
    @pytest.mark.asyncio
    async def test_verify_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/verify", json={"query": "Is exercise good?"})
            assert resp.status_code == 200
            data = resp.json()
            assert "verdict" in data
            assert "cited_response" in data
    
    @pytest.mark.asyncio
    async def test_search_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/search", json={"query": "vitamin D"})
            assert resp.status_code == 200
            assert "results" in resp.json()
    
    @pytest.mark.asyncio
    async def test_stats_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert "claims" in data
            assert "total_agents" in data
