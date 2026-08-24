"""ChromaArticleVectorStore testleri — ArticleVectorStore ile ayni arayuzu
uygulayan, gercek embedding tabanli alternatif backend.

Bu testler evidence/requirements-rag-chroma.txt'deki agir bagimliliklari
(chromadb, sentence-transformers/torch) gerektirir. Kurulu degilse otomatik
atlanir — varsayilan (tfidf) test kurulumu bundan etkilenmez.
"""

import uuid

import pytest

pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")

from evidence.rag.parser import ArticleChunk  # noqa: E402
from evidence.rag.chroma_store import ChromaArticleVectorStore  # noqa: E402
from evidence.rag.retriever import ArticleRetriever  # noqa: E402


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


@pytest.fixture()
def store():
    # persist_directory=None -> EphemeralClient (bellek-ici, disk yazmaz).
    # EphemeralClient sürecin tamamında paylaşılabildiği için testler
    # arası gerçek izolasyon için benzersiz bir collection_name şart.
    return ChromaArticleVectorStore(persist_directory=None, collection_name=f"test-{uuid.uuid4()}")


class TestChromaArticleVectorStore:
    def test_upsert_and_count(self, store):
        upserted = store.upsert_chunks(_make_chunks())
        assert upserted == 3
        assert store.count == 3

    def test_query_returns_semantically_relevant_results(self, store):
        store.upsert_chunks(_make_chunks())
        # Paraphrase edilmis sorgu — TF-IDF'in yakalayamayacagi, embedding'in
        # yakalamasi gereken bir durum.
        results = store.query("does working out help your heart?", n_results=2)
        assert len(results["ids"][0]) == 2
        assert all(i.startswith("en:test-article") for i in results["ids"][0])

    def test_upsert_is_idempotent(self, store):
        chunks = _make_chunks()
        store.upsert_chunks(chunks)
        store.upsert_chunks(chunks)
        assert store.count == 3

    def test_delete_article(self, store):
        store.upsert_chunks(_make_chunks())
        store.delete_article("en:test-article")
        assert store.count == 0

    def test_list_article_ids(self, store):
        store.upsert_chunks(_make_chunks("en:article-1"))
        store.upsert_chunks(_make_chunks("en:article-2"))
        ids = store.list_article_ids()
        assert "en:article-1" in ids
        assert "en:article-2" in ids

    def test_get_article_chunks(self, store):
        store.upsert_chunks(_make_chunks("en:article-x", count=2))
        result = store.get_article_chunks("en:article-x")
        assert len(result["ids"]) == 2

    def test_clear(self, store):
        store.upsert_chunks(_make_chunks())
        store.clear()
        assert store.count == 0

    def test_upsert_empty_list(self, store):
        assert store.upsert_chunks([]) == 0

    def test_query_on_empty_store_returns_empty(self, store):
        results = store.query("anything", n_results=5)
        assert results["ids"] == [[]]

    def test_where_filter_language(self, store):
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
        results = store.query("exercise", n_results=5, where={"language": "en"})
        assert all(m["language"] == "en" for m in results["metadatas"][0])


class TestChromaWithArticleRetriever:
    """ArticleRetriever'in ArticleVectorStore ile ayni arayuzle calistigini
    dogrular — backend'ler degistirilebilir olmali."""

    def test_retrieve_returns_results(self, store):
        store.upsert_chunks(_make_chunks())
        retriever = ArticleRetriever(store)
        results = retriever.retrieve("exercise heart health")
        assert len(results) > 0
        assert results[0].article_id == "en:test-article"

    def test_build_context(self, store):
        store.upsert_chunks(_make_chunks())
        retriever = ArticleRetriever(store)
        context = retriever.build_context("exercise heart health")
        assert len(context) > 0
        assert "FILE No." in context
