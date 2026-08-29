"""CrossrefJournalAgent birim testleri — ag cagrisi olmadan MockTransport ile."""

import asyncio

import httpx
import pytest

from evidence.v2.sources.journal_base import CrossrefJournalAgent


class _FakeJournalAgent(CrossrefJournalAgent):
    name = "nejm"
    source_type = "academic"
    organization = "NEJM"
    CONTAINER_TITLES = ("New England Journal of Medicine",)


def _item(doi="10.1056/x1", title="Study A", container=("New England Journal of Medicine",),
          year=(2023, 5, 12), url=None, abstract="<p>Finding</p>"):
    item = {"DOI": doi, "title": [title], "container-title": list(container),
            "URL": url, "abstract": abstract}
    if year is not None:
        item["published"] = {"date-parts": [list(year)]}
    return item


def _crossref_response(items):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"items": items}})
    return handler


def _install_transport(monkeypatch, handler):
    """journal_base icindeki httpx.AsyncClient cagrisina MockTransport enjekte eder."""
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def _fast_sleep(seconds):
    pass


class TestGuardClauses:
    """Bos sorgu veya tanimsiz dergi adi hic istek atmadan bos donmeli."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        agent = _FakeJournalAgent()
        assert await agent.search("") == []
        assert await agent.search(None) == []

    @pytest.mark.asyncio
    async def test_no_container_titles_returns_empty(self):
        agent = CrossrefJournalAgent()
        assert await agent.search("coffee") == []


class TestContainerTitleFilter:
    """Istenmeyen dergiden gelen sonuclar elenmeli."""

    @pytest.mark.asyncio
    async def test_foreign_journal_results_dropped(self, monkeypatch):
        items = [
            _item(title="Wrong Journal Study",
                  container=("Journal of Irrelevant Results",)),
            _item(title="Right Study"),
            _item(title="Also Wrong", container=("Other Venue", None)),
        ]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("coffee")
        assert len(results) == 1
        assert results[0]["title"] == "Right Study"
        assert results[0]["journal"] == "New England Journal of Medicine"

    @pytest.mark.asyncio
    async def test_missing_container_title_dropped(self, monkeypatch):
        items = [_item(container=[])]
        _install_transport(monkeypatch, _crossref_response(items))
        assert await _FakeJournalAgent().search("tea") == []


class TestResultTransformation:

    @pytest.mark.asyncio
    async def test_url_fallback_from_doi(self, monkeypatch):
        items = [_item(url=None)]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kolesterol")
        assert results[0]["url"] == "https://doi.org/10.1056/x1"
        assert results[0]["doi"] == "10.1056/x1"

    @pytest.mark.asyncio
    async def test_existing_url_preferred(self, monkeypatch):
        items = [_item(url="https://www.nejm.org/doi/full/10.1056/x1")]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kolesterol")
        assert results[0]["url"] == "https://www.nejm.org/doi/full/10.1056/x1"

    @pytest.mark.asyncio
    async def test_year_parsed_from_date_parts(self, monkeypatch):
        items = [_item(year=(2023, 5, 12))]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kahve")
        assert results[0]["published_year"] == 2023

    @pytest.mark.asyncio
    async def test_missing_date_yields_none(self, monkeypatch):
        items = [_item(year=None)]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kahve")
        assert results[0]["published_year"] is None

    @pytest.mark.asyncio
    async def test_abstract_tags_stripped(self, monkeypatch):
        items = [_item(abstract="<p>Coffee <b>raises</b> LDL.</p>")]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kahve")
        assert results[0]["passage"] == "Coffee raises LDL."

    @pytest.mark.asyncio
    async def test_limit_respected(self, monkeypatch):
        items = [_item(doi=f"10.1056/x{i}", title=f"Study {i}") for i in range(6)]
        _install_transport(monkeypatch, _crossref_response(items))
        results = await _FakeJournalAgent().search("kahve", limit=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_result_shape(self, monkeypatch):
        _install_transport(monkeypatch, _crossref_response([_item()]))
        results = await _FakeJournalAgent().search("kahve")
        r = results[0]
        for key in ["source", "organization", "title", "url", "doi",
                    "journal", "published_year", "passage", "source_type"]:
            assert key in r
        assert r["source"] == "nejm"
        assert r["source_type"] == "academic"


class TestEmptyAndErrorResponses:

    @pytest.mark.asyncio
    async def test_empty_items_list_returns_empty(self, monkeypatch):
        _install_transport(monkeypatch, _crossref_response([]))
        assert await _FakeJournalAgent().search("kahve") == []

    @pytest.mark.asyncio
    async def test_rate_limited_returns_empty(self, monkeypatch):
        """Surekli 429: 3 deneme sonrasi bos liste (bekleme yamali)."""
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(429)

        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
        _install_transport(monkeypatch, handler)
        assert await _FakeJournalAgent().search("kahve") == []
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty(self, monkeypatch):
        """NOT (2026-08-29): Bu test eskiden 'ilk denemede exception -> aninda
        return []' hatali davranisini SESSIZCE dogruluyordu — yalnizca son
        sonucu (`== []`) kontrol ediyordu, kac deneme yapildigini degil. Artik
        gercekten 3 kez denendigi acikca kilitleniyor (get_with_retry duzeltmesi)."""
        calls = []

        def handler(request):
            calls.append(request.url)
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
        _install_transport(monkeypatch, handler)
        assert await _FakeJournalAgent().search("kahve") == []
        assert len(calls) == 3  # eskiden 1 olurdu (retry hic calismiyordu)

    @pytest.mark.asyncio
    async def test_http_error_status_returns_empty(self, monkeypatch):
        """500 gecici sayilan bir durum kodu — artik gercekten tekrar denenir
        (eskiden 429 disindaki her hata aninda vazgeciyordu)."""
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(500)

        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
        _install_transport(monkeypatch, handler)
        assert await _FakeJournalAgent().search("kahve") == []
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_permanent_403_not_retried(self, monkeypatch):
        """403 (bot-engelleme) kalici bir hata — tekrar denenmemeli."""
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(403)

        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
        _install_transport(monkeypatch, handler)
        assert await _FakeJournalAgent().search("kahve") == []
        assert len(calls) == 1  # kalici hata — tekrar denenmez
