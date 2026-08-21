"""Auto-index entegrasyon testleri — botun kendi arsivini gormesi."""

import pytest

from evidence.v2.api.app import create_app


@pytest.mark.asyncio
async def test_auto_index_enables_archive_agent():
    """auto_index=True ile ArchiveAgent devreye girer (19 ajan)."""
    app = create_app(auto_index=True)
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["agents"] == 19  # 18 harici + ArchiveAgent


@pytest.mark.asyncio
async def test_auto_index_retriever_finds_turkish_article():
    """Endeks kurulunca Turkce makale arsiv aramasinda donmeli."""
    app = create_app(auto_index=True)
    retriever = getattr(app.state, "retriever", None)
    if retriever is None:
        pytest.skip("retriever app.state'e bagli degil")
    results = retriever.retrieve("kahve kolesterol", n_results=3)
    assert len(results) > 0
    titles = " ".join(r.title.lower() for r in results)
    assert "kahve" in titles or "kolesterol" in titles


@pytest.mark.asyncio
async def test_auto_index_disabled_by_default_flag():
    """auto_index=False ile ArchiveAgent yok (18 ajan) — test hizliligii."""
    app = create_app(auto_index=False)
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.json()["agents"] == 18
