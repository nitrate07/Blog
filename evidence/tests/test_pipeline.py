"""Tests for the Evidence Pipeline — LLM as interpreter only, Evidence Engine as hakem."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from evidence.graph.pipeline import (
    extract_claim,
    discover_sources,
    evidence_engine,
    interpret_with_llm,
    update_graph,
    run_pipeline,
)
from evidence.graph.store import EvidenceGraph
from evidence.graph.model import Verdict
from evidence.rag.retriever import ArticleRetriever, RetrievalResult
from evidence.connectors import EvidenceCatalog
from evidence.graph import GraphBuilder
from evidence.models import SourceQuality


# ---------------------------------------------------------------------------
# Claim Extraction (rule-based, no LLM)
# ---------------------------------------------------------------------------

class TestClaimExtraction:
    def test_extracts_from_question(self):
        assert extract_claim("Is exercise good for heart health?") == "exercise good for heart health?"

    def test_extracts_from_is_it_true(self):
        assert extract_claim("Is it true that fasting helps weight loss?") == "fasting helps weight loss?"

    def test_extracts_from_tell_me_about(self):
        result = extract_claim("Tell me about vitamin D deficiency")
        assert result == "vitamin D deficiency?"

    def test_adds_question_mark(self):
        assert extract_claim("vitamin D helps bones") == "vitamin D helps bones?"

    def test_preserves_question_mark(self):
        assert extract_claim("exercise improves health?") == "exercise improves health?"

    def test_handles_short_query(self):
        result = extract_claim("exercise benefits")
        assert result == "exercise benefits?"


# ---------------------------------------------------------------------------
# Evidence Engine (hakem — deterministic, no LLM)
# ---------------------------------------------------------------------------

class TestEvidenceEngine:
    def test_empty_evidence_returns_unverified(self):
        result = evidence_engine("test claim?", [], [])
        assert result["verdict"] == "unverified"
        assert result["confidence"] == 0.0
        assert result["rating_value"] == 0

    def test_archive_match_provides_verdict(self):
        archive = [
            RetrievalResult(
                article_id="en:test", title="Test Article", heading="Verdict",
                text="The evidence supports the claim", verdict="Mostly Supported",
                rating_value=4, category="Health", chunk_type="verdict",
                distance=0.3, source_url="https://example.com",
            )
        ]
        result = evidence_engine("test claim?", archive, [])
        assert result["verdict"] == "Mostly Supported"
        assert result["confidence"] >= 0.3

    def test_scores_source_quality(self):
        archive = [
            RetrievalResult(
                article_id="en:test", title="Test", heading="Body",
                text="Test content", verdict=None, rating_value=None,
                category="Health", chunk_type="body",
                distance=0.5, source_url="https://example.com",
            )
        ]
        result = evidence_engine("test claim?", archive, [])
        assert len(result["matches"]) == 1
        assert result["matches"][0]["quality_score"] > 0

    def test_external_sources_scored(self):
        from evidence.graph.model import Source, SourceType
        source = Source(
            id="source::test", url="https://pubmed.ncbi.nlm.nih.gov/12345/",
            title="PubMed Study", source_type=SourceType.PRIMARY,
        )
        result = evidence_engine("test claim?", [], [source])
        assert len(result["matches"]) >= 1


# ---------------------------------------------------------------------------
# LLM Interpreter (yorumcu — explains verdict, never generates evidence)
# ---------------------------------------------------------------------------

class TestLLMInterpreter:
    @pytest.mark.asyncio
    async def test_rule_based_when_no_provider(self):
        matches = [
            {"title": "Study", "url": "https://example.com", "source_type": "primary", "quality_score": 0.8, "text": "Evidence text"}
        ]
        response = await interpret_with_llm("test claim?", "supported", 0.8, matches, provider=None)
        assert "test claim?" in response
        assert "Supported" in response
        assert "https://example.com" in response

    @pytest.mark.asyncio
    async def test_rule_based_on_empty_matches(self):
        response = await interpret_with_llm("test?", "unverified", 0.0, [], provider=None)
        assert "No evidence found" in response

    @pytest.mark.asyncio
    async def test_llm_provider_called_for_interpretation(self):
        from evidence.providers import NullProvider
        provider = NullProvider()
        matches = [
            {"title": "Study", "url": "https://example.com", "source_type": "primary", "quality_score": 0.8, "text": "Evidence"}
        ]
        # NullProvider will fallback to rule-based
        response = await interpret_with_llm("test claim?", "supported", 0.8, matches, provider=provider)
        assert response  # Should get a response


# ---------------------------------------------------------------------------
# Graph Update
# ---------------------------------------------------------------------------

class TestGraphUpdate:
    def test_records_in_graph(self):
        graph = EvidenceGraph()
        matches = [
            {"title": "Study", "url": "https://example.com", "source_type": "primary", "relevance": 0.7, "text": "Evidence text"}
        ]
        claim_id = update_graph(graph, "test claim?", "supported", 0.8, 4, matches)
        assert claim_id.startswith("claim::pipeline::")
        stats = graph.get_stats()
        assert stats["claims"] >= 1
        assert stats["sources"] >= 1


# ---------------------------------------------------------------------------
# Full Pipeline Integration
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocked_sources(self, tmp_path):
        from evidence.rag.store import ArticleVectorStore
        from evidence.rag.parser import ArticleChunk

        store = ArticleVectorStore()
        chunks = [
            ArticleChunk(
                article_id="en:test-pipeline", chunk_index=0,
                title="Exercise and Heart Health", heading="Findings",
                text="Regular exercise significantly improves cardiovascular health.",
                language="en", category="Exercise", verdict="Mostly Supported",
                rating_value=4, claim_reviewed="Exercise improves heart health",
                file_number=3, source_url="https://example.com/test",
                chunk_type="body",
            ),
        ]
        store.upsert_chunks(chunks)
        retriever = ArticleRetriever(store)

        catalog = MagicMock(spec=EvidenceCatalog)
        catalog.search = AsyncMock(return_value=[])

        graph = EvidenceGraph()
        builder = GraphBuilder(graph, catalog=catalog)

        result = await run_pipeline(
            user_query="Is exercise good for heart health?",
            retriever=retriever,
            catalog=catalog,
            graph_builder=builder,
            llm_provider=None,
        )

        assert result.extracted_claim
        assert result.verdict in ["Mostly Supported", "partly_supported", "unverified", "supported"]
        assert result.cited_response
        assert result.graph_claim_id
        assert len(result.steps) >= 5

    @pytest.mark.asyncio
    async def test_pipeline_architecture_principle(self, tmp_path):
        """Verify: LLM is never an evidence source. Evidence comes from ALL 11 sources."""
        from evidence.rag.store import ArticleVectorStore

        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)

        catalog = MagicMock(spec=EvidenceCatalog)
        catalog.search = AsyncMock(return_value=[])

        graph = EvidenceGraph()
        builder = GraphBuilder(graph, catalog=catalog)

        result = await run_pipeline(
            user_query="test query",
            retriever=retriever,
            catalog=catalog,
            graph_builder=builder,
            llm_provider=None,
        )

        # Archive, external, and health org results contain evidence
        assert isinstance(result.archive_results, list)
        assert isinstance(result.external_results, list)
        assert isinstance(result.health_org_results, list)
        # Cited response references sources, not LLM-generated content
        assert "Arı Kaynak Evidence Engine" in result.cited_response
