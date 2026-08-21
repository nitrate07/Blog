"""Tests for the RAG API endpoints."""

import pytest
import httpx

from evidence.api import create_app
from evidence.config import Settings
from evidence.rag.parser import ArticleChunk
from evidence.rag.store import ArticleVectorStore
from evidence.rag.retriever import ArticleRetriever


def _make_test_chunks():
    return [
        ArticleChunk(
            article_id="en:test-exercise", chunk_index=0,
            title="Exercise and Heart Health", heading="Findings",
            text="Regular exercise significantly improves cardiovascular health markers.",
            language="en", category="Exercise", verdict="Mostly Supported",
            rating_value=4, claim_reviewed="Exercise improves heart health",
            file_number=3, source_url="https://example.com/test",
            chunk_type="body",
        ),
        ArticleChunk(
            article_id="en:test-exercise", chunk_index=1,
            title="Exercise and Heart Health", heading="The Verdict",
            text="The evidence supports the claim that exercise improves cardiovascular health.",
            language="en", category="Exercise", verdict="Mostly Supported",
            rating_value=4, claim_reviewed="Exercise improves heart health",
            file_number=3, source_url="https://example.com/test",
            chunk_type="verdict",
        ),
    ]


@pytest.fixture
def rag_client(tmp_path):
    store = ArticleVectorStore(persist_directory=str(tmp_path / "chroma"))
    store.upsert_chunks(_make_test_chunks())
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
async def test_rag_query_returns_results(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.post("/v1/rag/query", headers=HEADERS, json={"query": "exercise heart health"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_results"] > 0
    assert body["context"]
    assert body["results"][0]["article_id"] == "en:test-exercise"


@pytest.mark.asyncio
async def test_rag_search_returns_results(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.get("/v1/rag/search", headers=HEADERS, params={"q": "exercise cardiovascular"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0


@pytest.mark.asyncio
async def test_rag_query_requires_auth(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.post("/v1/rag/query", json={"query": "test"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rag_query_validates_input(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.post("/v1/rag/query", headers=HEADERS, json={"query": "ab"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rag_stats_returns_info(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.get("/v1/rag/stats", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_chunks"] > 0
    assert len(body["article_ids"]) > 0


@pytest.mark.asyncio
async def test_rag_index_rebuilds(rag_client, tmp_path, monkeypatch):
    en_dir = tmp_path / "articles"
    en_dir.mkdir()
    (en_dir / "test.html").write_text("""<!doctype html>
<html lang="en">
<head>
<meta property="og:url" content="https://example.com/new.html">
<title>New Article</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Article","headline":"New","inLanguage":"en"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ClaimReview","claimReviewed":"new claim","reviewRating":{"@type":"Rating","ratingValue":3,"alternateName":"Partly Supported"}}
</script>
</head>
<body>
<main class="wrap" id="main">
<div class="article-header"><span class="num">FILE No. 0050</span></div>
<div class="article-body">
<h2>Introduction</h2>
<p>A new study on nutrition and health outcomes.</p>
</div>
</main>
</body>
</html>""")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        monkeypatch.chdir(tmp_path)
        response = await client.post("/v1/rag/index", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["articles"] >= 1


@pytest.mark.asyncio
async def test_rag_search_with_language_filter(rag_client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rag_client), base_url="http://test") as client:
        response = await client.get("/v1/rag/search", headers=HEADERS, params={"q": "exercise", "language": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
