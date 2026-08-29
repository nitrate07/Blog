"""evidence/v2/sources/{pubmed,crossref,europepmc,openalex}.py testleri.

Bu 4 ajan (PubMed, Crossref, Europe PMC, OpenAlex) en onemli akademik
kaynaklardir ama daha once HIC test kapsami yoktu — yalnizca farkli, eski
bir modul (evidence.graph.agents) test ediliyordu. Bu dosya hem gercek
yanit ayristirmasini hem de yeni eklenen retry/backoff davranisini
(bkz. evidence/v2/sources/http_retry.py) gercek aga hicbir istek
atmadan (httpx.MockTransport) dogrular.
"""

from __future__ import annotations

import httpx
import pytest

from evidence.v2.sources.crossref import CrossrefAgent
from evidence.v2.sources.europepmc import EuropePMCAgent
from evidence.v2.sources.openalex import OpenAlexAgent
from evidence.v2.sources.pubmed import PubMedAgent


def _install_transport(monkeypatch, handler) -> list:
    """httpx.AsyncClient'a MockTransport enjekte eder, tum cagrilari kaydeder."""
    calls: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def recording_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return calls


class TestCrossrefAgent:
    @pytest.mark.asyncio
    async def test_parses_real_shaped_response_async(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1001/x.1",
                            "title": ["Coffee and cholesterol: a review"],
                            "URL": "https://doi.org/10.1001/x.1",
                            "published": {"date-parts": [[2023, 4]]},
                            "author": [{"given": "A.", "family": "Smith"}],
                            "container-title": ["Journal of Nutrition"],
                            "abstract": "<p>Coffee consumption <b>reduces</b> LDL.</p>",
                        }
                    ]
                }
            })

        _install_transport(monkeypatch, handler)
        results = await CrossrefAgent().search("coffee cholesterol")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Coffee and cholesterol: a review"
        assert r["doi"] == "10.1001/x.1"
        assert r["year"] == 2023
        assert r["first_author"] == "A. Smith"
        assert r["journal"] == "Journal of Nutrition"
        assert "<b>" not in r["passage"]  # HTML etiketleri temizlenmis
        assert "reduces" in r["passage"]

    @pytest.mark.asyncio
    async def test_retries_transient_503_then_succeeds(self, monkeypatch):
        calls_ref = []

        def handler(request: httpx.Request) -> httpx.Response:
            if len(calls_ref) < 2:
                calls_ref.append(1)
                return httpx.Response(503)
            return httpx.Response(200, json={"message": {"items": []}})

        calls = _install_transport(monkeypatch, handler)
        results = await CrossrefAgent().search("test")

        assert results == []  # bos ama BASARILI (exception degil)
        assert len(calls) == 3  # 2 basarisiz + 1 basarili deneme

    @pytest.mark.asyncio
    async def test_permanent_error_fails_closed_without_raising(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        calls = _install_transport(monkeypatch, handler)
        results = await CrossrefAgent().search("test")

        assert results == []
        assert len(calls) == 1  # kalici hata — tekrar denenmez


class TestPubMedAgent:
    """3 ardisik cagrisi olan tek ajan (search_ids -> summaries -> abstracts)."""

    ABSTRACT_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
<MedlineCitation>
<PMID>111</PMID>
<Article><Abstract>
<AbstractText Label="BACKGROUND">Coffee affects lipid metabolism.</AbstractText>
<AbstractText>No significant LDL change was found.</AbstractText>
</Abstract></Article>
</MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""

    def _handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "esearch" in url:
            return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
        if "esummary" in url:
            return httpx.Response(200, json={"result": {
                "111": {
                    "title": "Coffee and Lipid Metabolism",
                    "authors": [{"name": "Jane Doe"}],
                    "source": "J Nutr",
                    "pubdate": "2022 Jan",
                    "articleids": [{"idtype": "doi", "value": "10.9/y.1"}],
                }
            }})
        if "efetch" in url:
            return httpx.Response(200, text=self.ABSTRACT_XML)
        return httpx.Response(404)

    @pytest.mark.asyncio
    async def test_full_three_step_flow_parses_correctly(self, monkeypatch):
        _install_transport(monkeypatch, self._handler)
        results = await PubMedAgent().search("coffee cholesterol")

        assert len(results) == 1
        r = results[0]
        assert r["pmid"] == "111"
        assert r["title"] == "Coffee and Lipid Metabolism"
        assert r["first_author"] == "Jane Doe"
        assert r["doi"] == "10.9/y.1"
        assert r["year"] == 2022
        assert "lipid metabolism" in r["passage"].lower()
        assert r["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"

    @pytest.mark.asyncio
    async def test_empty_search_short_circuits_remaining_steps(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"esearchresult": {"idlist": []}})

        calls = _install_transport(monkeypatch, handler)
        results = await PubMedAgent().search("no matches at all")

        assert results == []
        assert len(calls) == 1  # summaries/abstracts hic cagrilmamali

    @pytest.mark.asyncio
    async def test_summary_step_retries_transient_failure(self, monkeypatch):
        state = {"summary_attempts": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "esearch" in url:
                return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
            if "esummary" in url:
                state["summary_attempts"] += 1
                if state["summary_attempts"] < 2:
                    return httpx.Response(503)
                return httpx.Response(200, json={"result": {"111": {"title": "X"}}})
            if "efetch" in url:
                return httpx.Response(200, text=self.ABSTRACT_XML)
            return httpx.Response(404)

        _install_transport(monkeypatch, handler)
        results = await PubMedAgent().search("test")

        assert len(results) == 1
        assert results[0]["title"] == "X"
        assert state["summary_attempts"] == 2  # 1 basarisiz + 1 basarili

    @pytest.mark.asyncio
    async def test_abstract_fetch_failure_still_returns_metadata(self, monkeypatch):
        """Ozet cekimi kalici olarak basarisiz olsa bile, en azindan
        metadata (baslik, DOI vb.) kaybolmamali — bos pasajla doner."""
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "esearch" in url:
                return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
            if "esummary" in url:
                return httpx.Response(200, json={"result": {"111": {"title": "Metadata Only"}}})
            if "efetch" in url:
                return httpx.Response(403)  # kalici hata
            return httpx.Response(404)

        _install_transport(monkeypatch, handler)
        results = await PubMedAgent().search("test")

        assert len(results) == 1
        assert results[0]["title"] == "Metadata Only"
        assert results[0]["passage"] == ""


class TestEuropePMCAgent:
    @pytest.mark.asyncio
    async def test_parses_real_shaped_response(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "resultList": {"result": [
                    {
                        "title": "Coffee Consumption and Cardiovascular Risk",
                        "pmid": "222",
                        "doi": "10.5/z.1",
                        "journalTitle": "Eur J Prev Cardiol",
                        "firstPublicationDate": "2021-06-01",
                        "abstractText": "A cohort study on coffee and CV risk.",
                    }
                ]}
            })

        _install_transport(monkeypatch, handler)
        results = await EuropePMCAgent().search("coffee cardiovascular")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Coffee Consumption and Cardiovascular Risk"
        assert r["url"] == "https://pubmed.ncbi.nlm.nih.gov/222/"
        assert r["published_year"] == 2021

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_without_request(self, monkeypatch):
        calls = _install_transport(monkeypatch, lambda r: httpx.Response(200, json={}))
        results = await EuropePMCAgent().search("")
        assert results == []
        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_retries_timeout_then_succeeds(self, monkeypatch):
        state = {"attempts": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["attempts"] += 1
            if state["attempts"] < 2:
                raise httpx.ConnectTimeout("simulated", request=request)
            return httpx.Response(200, json={"resultList": {"result": []}})

        _install_transport(monkeypatch, handler)
        results = await EuropePMCAgent().search("test")

        assert results == []
        assert state["attempts"] == 2


class TestOpenAlexAgent:
    @pytest.mark.asyncio
    async def test_parses_real_shaped_response_with_inverted_abstract(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "results": [
                    {
                        "doi": "https://doi.org/10.7/a.1",
                        "title": "Statins and Muscle Pain",
                        "publication_year": 2020,
                        "primary_location": {"source": {"display_name": "Circulation"}},
                        "abstract_inverted_index": {
                            "Statins": [0], "cause": [1], "little": [2], "muscle": [3], "pain": [4],
                        },
                    }
                ]
            })

        _install_transport(monkeypatch, handler)
        results = await OpenAlexAgent().search("statin muscle pain")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Statins and Muscle Pain"
        assert r["doi"] == "10.7/a.1"
        assert r["journal"] == "Circulation"
        assert r["passage"] == "Statins cause little muscle pain"

    @pytest.mark.asyncio
    async def test_missing_doi_and_title_dropped(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "results": [
                    {"doi": None, "title": None, "publication_year": 2020},
                ]
            })

        _install_transport(monkeypatch, handler)
        results = await OpenAlexAgent().search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_permanent_failure_fails_closed(self, monkeypatch):
        calls = _install_transport(monkeypatch, lambda r: httpx.Response(404))
        results = await OpenAlexAgent().search("test")
        assert results == []
        assert len(calls) == 1
