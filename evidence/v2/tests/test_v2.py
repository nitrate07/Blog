"""Tests for Evidence Verification Infrastructure v2."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from evidence.v2.core.types import (
    Claim, Source, Passage, Evidence, Verdict, SourceType, StudyDesign,
    Contradiction, ContradictionType, VerificationRecord,
    content_hash, make_source_id, make_passage_id, make_evidence_id,
    make_claim_id, make_verification_id, make_contradiction_id,
    get_journal_impact_factor, get_study_design_level, calculate_source_quality_score,
)
from evidence.v2.core.interfaces import SourceAgent, EvidenceEngine
from evidence.v2.core.infrastructure import RateLimiter, Cache
from evidence.v2.engine.engine import DeterministicEngine
from evidence.v2.engine.contradiction import ContradictionDetector
from evidence.v2.engine.verifier import PassageVerifier
from evidence.v2.pipeline.pipeline import (
    extract_claim,
    discover_sources,
    run_engine,
    detect_contradictions,
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
    
    def test_study_design_enum(self):
        assert StudyDesign.SYSTEMATIC_REVIEW_META == "systematic_review_meta_analysis"
        assert StudyDesign.RCT == "randomized_controlled_trial"
        assert StudyDesign.COHORT == "cohort_study"
    
    def test_content_hash(self):
        h = content_hash("hello world")
        assert len(h) == 16
        assert h == content_hash("hello world")  # deterministic
    
    def test_make_verification_id(self):
        vid = make_verification_id()
        assert vid.startswith("verif::")
        assert len(vid) == 19  # verif:: + 12 hex chars
    
    def test_make_contradiction_id(self):
        cid = make_contradiction_id("s1", "s2")
        assert cid == "contradiction::s1::s2"
    
    def test_journal_impact_factor(self):
        assert get_journal_impact_factor("New England Journal of Medicine") == 158.5
        assert get_journal_impact_factor("The Lancet") == 168.9
        assert get_journal_impact_factor("JAMA") == 120.7
        assert get_journal_impact_factor("BMJ") == 105.0
        assert get_journal_impact_factor("Unknown Journal") == 0.0
    
    def test_study_design_level(self):
        assert get_study_design_level(StudyDesign.SYSTEMATIC_REVIEW_META) == 1
        assert get_study_design_level(StudyDesign.RCT) == 2
        assert get_study_design_level(StudyDesign.CASE_REPORT) == 5
    
    def test_calculate_source_quality_score(self):
        # High quality: primary + RCT + high IF + recent
        score = calculate_source_quality_score(
            SourceType.PRIMARY, StudyDesign.RCT, 158.5, 2024
        )
        assert score >= 0.8
        
        # Low quality: unknown + expert opinion + no IF + old
        score = calculate_source_quality_score(
            SourceType.UNKNOWN, StudyDesign.EXPERT_OPINION, 0.0, 2010
        )
        assert score <= 0.6
    
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
    
    def test_contradiction_to_dict(self):
        c = Contradiction(
            id="c1", source1_id="s1", source2_id="s2", claim_id="cl1",
            contradiction_type=ContradictionType.DIRECT,
            description="test", source1_verdict="supported", source2_verdict="unsupported",
        )
        d = c.to_dict()
        assert d["contradiction_type"] == "direct"
    
    def test_verification_record_to_dict(self):
        r = VerificationRecord(
            id="v1", query="test", claim_text="test claim", verdict="supported",
            confidence=0.8, rating_value=4, sources_count=5, passages_count=3,
            contradictions_count=0, created_at="2024-01-01", steps=[], cited_response="response",
        )
        d = r.to_dict()
        assert d["id"] == "v1"


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
    
    def test_supporting_and_contradicting_sources(self):
        engine = DeterministicEngine()
        external = [
            {"title": "Study 1", "url": "https://example.com/1", "passage": "supports claim", "source_type": "academic"},
            {"title": "Study 2", "url": "https://example.com/2", "passage": "opposes claim", "source_type": "academic"},
        ]
        result = engine.judge("test claim?", [], external, [])
        assert "supporting_sources" in result
        assert "contradicting_sources" in result


# ---------------------------------------------------------------------------
# Contradiction Detection
# ---------------------------------------------------------------------------

class TestContradictionDetector:
    def test_no_contradictions(self):
        detector = ContradictionDetector()
        sources = [
            Source(id="s1", url="https://example.com/1", title="Study 1", source_type=SourceType.PRIMARY),
            Source(id="s2", url="https://example.com/2", title="Study 2", source_type=SourceType.PRIMARY),
        ]
        matches = [
            {"source_id": "s1", "url": "https://example.com/1", "verdict": "supported"},
            {"source_id": "s2", "url": "https://example.com/2", "verdict": "supported"},
        ]
        contradictions = detector.detect("c1", sources, matches)
        assert len(contradictions) == 0
    
    def test_direct_contradiction(self):
        detector = ContradictionDetector()
        sources = [
            Source(id="s1", url="https://example.com/1", title="Study 1", source_type=SourceType.PRIMARY),
            Source(id="s2", url="https://example.com/2", title="Study 2", source_type=SourceType.PRIMARY),
        ]
        matches = [
            {"source_id": "s1", "url": "https://example.com/1", "verdict": "supported"},
            {"source_id": "s2", "url": "https://example.com/2", "verdict": "unsupported"},
        ]
        contradictions = detector.detect("c1", sources, matches)
        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == ContradictionType.DIRECT


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

class TestInfrastructure:
    @pytest.mark.asyncio
    async def test_rate_limiter(self):
        limiter = RateLimiter(max_requests=2, window_seconds=1.0)
        assert await limiter.acquire("test")
        assert await limiter.acquire("test")
        assert not await limiter.acquire("test")
    
    def test_cache(self):
        cache = Cache(max_size=2, ttl_seconds=1.0)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine)
        
        result = await pipeline.run("Is exercise good for heart health?")
        
        assert result.verification_id
        assert result.extracted_claim
        assert result.verdict in ["unverified", "partly_supported", "mostly_supported", "supported"]
        assert result.cited_response
        assert result.graph_claim_id
        assert result.created_at
        assert len(result.steps) >= 7
    
    @pytest.mark.asyncio
    async def test_pipeline_principle(self):
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine, llm_provider=None)
        
        result = await pipeline.run("test query")
        
        assert isinstance(result.archive_results, list)
        assert isinstance(result.external_results, list)
        assert isinstance(result.health_org_results, list)
        assert isinstance(result.passage_verifications, list)
        assert isinstance(result.contradictions, list)
        assert isinstance(result.supporting_sources, list)
        assert isinstance(result.contradicting_sources, list)
        
        assert len(pipeline.claims) >= 1
        assert len(pipeline.evidence) >= 1
        assert len(pipeline.history) >= 1
    
    @pytest.mark.asyncio
    async def test_verification_history(self):
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine)
        
        await pipeline.run("first query")
        await pipeline.run("second query")
        
        assert len(pipeline.history) == 2
        assert pipeline.history[0].query == "first query"
        assert pipeline.history[1].query == "second query"


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
            data = resp.json()
            assert data["status"] == "ok"
            assert data["agents"] == 18  # Without ArchiveAgent
    
    @pytest.mark.asyncio
    async def test_verify_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/verify", json={"query": "Is exercise good?"})
            assert resp.status_code == 200
            data = resp.json()
            assert "verification_id" in data
            assert "verdict" in data
            assert "cited_response" in data
            assert "passage_verifications" in data
            assert "contradictions" in data
    
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
            assert "contradictions" in data
            assert "verifications" in data
    
    @pytest.mark.asyncio
    async def test_history_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/history")
            assert resp.status_code == 200
            assert "records" in resp.json()


# ---------------------------------------------------------------------------
# Database Integration
# ---------------------------------------------------------------------------

class TestDatabaseIntegration:
    def test_database_save_and_retrieve(self, tmp_path):
        from evidence.v2.core.database import EvidenceDatabase
        
        db_path = str(tmp_path / "test.db")
        db = EvidenceDatabase(db_path)
        
        claim = Claim(id="c1", text="test claim", author="pipeline", category="Health", date_filed="", file_number=0)
        db.save_claim(claim)
        retrieved = db.get_claim("c1")
        assert retrieved is not None
        assert retrieved.text == "test claim"
    
    def test_database_stats(self, tmp_path):
        from evidence.v2.core.database import EvidenceDatabase
        
        db_path = str(tmp_path / "test.db")
        db = EvidenceDatabase(db_path)
        
        stats = db.get_stats()
        assert "claims" in stats
        assert "sources" in stats
        assert "passages" in stats
        assert "evidence" in stats
        assert "contradictions" in stats
        assert "verifications" in stats
    
    def test_database_verification_history(self, tmp_path):
        from evidence.v2.core.database import EvidenceDatabase
        
        db_path = str(tmp_path / "test.db")
        db = EvidenceDatabase(db_path)
        
        record = VerificationRecord(
            id="v1", query="test", claim_text="test claim", verdict="supported",
            confidence=0.8, rating_value=4, sources_count=5, passages_count=3,
            contradictions_count=0, created_at="2024-01-01", steps=[], cited_response="response",
        )
        db.save_verification_record(record)
        
        history = db.get_verification_history()
        assert len(history) == 1
        assert history[0].query == "test"
    
    @pytest.mark.asyncio
    async def test_pipeline_persists_to_database(self, tmp_path):
        from evidence.v2.core.database import EvidenceDatabase
        
        db_path = str(tmp_path / "test.db")
        db = EvidenceDatabase(db_path)
        
        mock_agent = MagicMock(spec=SourceAgent)
        mock_agent.name = "test"
        mock_agent.source_type = "test"
        mock_agent.search = AsyncMock(return_value=[])
        
        orchestrator = SourceOrchestrator([mock_agent])
        engine = DeterministicEngine()
        pipeline = EvidencePipeline(orchestrator, engine, db=db)
        
        await pipeline.run("Is exercise good for heart health?")
        
        # Verify database was populated
        stats = db.get_stats()
        assert stats["claims"] >= 1
        assert stats["evidence"] >= 1
        assert stats["verifications"] >= 1
    
    @pytest.mark.asyncio
    async def test_api_with_database(self, tmp_path):
        from httpx import AsyncClient, ASGITransport
        from evidence.v2.core.database import EvidenceDatabase
        
        db_path = str(tmp_path / "test.db")
        app = create_app(db_path=db_path)
        transport = ASGITransport(app=app)
        
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Run a verification
            resp = await client.post("/v1/verify", json={"query": "Is exercise good?"})
            assert resp.status_code == 200
            
            # Check database stats
            resp = await client.get("/v1/db/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["claims"] >= 1
            assert data["verifications"] >= 1
            
            # Check database history
            resp = await client.get("/v1/db/history")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] >= 1
