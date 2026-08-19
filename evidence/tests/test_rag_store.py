"""Tests for the RAG vector store and retriever."""

import pytest

from evidence.rag.parser import ArticleChunk
from evidence.rag.store import ArticleVectorStore
from evidence.rag.retriever import ArticleRetriever


def _make_chunks(article_id: str = "en:test-article", count: int = 3) -> list[ArticleChunk]:
    texts = [
        "Exercise improves cardiovascular health significantly.",
        "Regular physical activity reduces heart disease risk.",
        "A study found sprint intervals trigger bigger molecular responses.",
    ]
    return [
        ArticleChunk(
            article_id=article_id,
            chunk_index=i,
            title="Test Article",
            heading=f"Section {i}",
            text=texts[i % len(texts)],
            language="en",
            category="Exercise",
            verdict="Mostly Supported",
            rating_value=4,
            claim_reviewed="Exercise improves health",
            file_number=1,
            source_url="https://example.com/test",
            chunk_type="body",
        )
        for i in range(count)
    ]


class TestArticleVectorStore:
    def test_upsert_and_count(self):
        store = ArticleVectorStore()
        chunks = _make_chunks()
        upserted = store.upsert_chunks(chunks)
        assert upserted == 3
        assert store.count == 3

    def test_query_returns_results(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        results = store.query("exercise heart health", n_results=2)
        assert len(results["ids"][0]) == 2

    def test_upsert_is_idempotent(self):
        store = ArticleVectorStore()
        chunks = _make_chunks()
        store.upsert_chunks(chunks)
        store.upsert_chunks(chunks)
        assert store.count == 3

    def test_delete_article(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        store.delete_article("en:test-article")
        assert store.count == 0

    def test_list_article_ids(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks("en:article-1"))
        store.upsert_chunks(_make_chunks("en:article-2"))
        ids = store.list_article_ids()
        assert "en:article-1" in ids
        assert "en:article-2" in ids

    def test_get_article_chunks(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks("en:article-x", count=2))
        result = store.get_article_chunks("en:article-x")
        assert len(result["ids"]) == 2

    def test_clear(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        store.clear()
        assert store.count == 0

    def test_upsert_empty_list(self):
        store = ArticleVectorStore()
        result = store.upsert_chunks([])
        assert result == 0


class TestArticleRetriever:
    def test_retrieve_returns_results(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        retriever = ArticleRetriever(store)
        results = retriever.retrieve("exercise heart health")
        assert len(results) > 0
        assert results[0].article_id == "en:test-article"

    def test_retrieve_with_language_filter(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks("en:test1"))
        store.upsert_chunks([
            ArticleChunk(
                article_id="tr:test2", chunk_index=0, title="Test TR",
                heading=None, text="Egzersiz kalp sagligini iyilestirir.",
                language="tr", category="Exercise", verdict="Supported",
                rating_value=5, claim_reviewed="Egzersiz saglik", file_number=2,
                source_url="https://example.com/tr", chunk_type="metadata",
            )
        ])
        retriever = ArticleRetriever(store)
        tr_results = retriever.retrieve("egzersiz", language="tr")
        assert len(tr_results) > 0
        assert all(r.article_id.startswith("tr:") for r in tr_results)

    def test_build_context(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        retriever = ArticleRetriever(store)
        context = retriever.build_context("exercise heart health")
        assert len(context) > 0
        assert "FILE No." in context

    def test_build_context_empty_query(self):
        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)
        context = retriever.build_context("anything")
        assert context == "No relevant articles found."

    def test_get_stats(self):
        store = ArticleVectorStore()
        store.upsert_chunks(_make_chunks())
        retriever = ArticleRetriever(store)
        stats = retriever.get_stats()
        assert stats["total_chunks"] == 3
        assert len(stats["article_ids"]) == 1

    def test_index_articles(self, tmp_path):
        en_dir = tmp_path / "articles"
        en_dir.mkdir()
        html = """<!doctype html>
<html lang="en">
<head>
<meta property="og:url" content="https://example.com/test.html">
<title>Test — Arı Kaynak</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Article","headline":"Test","inLanguage":"en"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ClaimReview","claimReviewed":"test claim","reviewRating":{"@type":"Rating","ratingValue":4,"alternateName":"Mostly Supported"}}
</script>
</head>
<body>
<main class="wrap" id="main">
<div class="article-header"><span class="num">FILE No. 0001</span></div>
<div class="article-body">
<h2>Findings</h2>
<p>Exercise improves cardiovascular health significantly.</p>
</div>
</main>
</body>
</html>"""
        (en_dir / "test.html").write_text(html)
        store = ArticleVectorStore()
        retriever = ArticleRetriever(store)
        result = retriever.index_articles(en_dir)
        assert result["articles"] >= 1
        assert result["indexed"] >= 1
