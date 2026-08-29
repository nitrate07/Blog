"""HealthOrgAgent._get_with_retry ve altindaki 6 HTML-scraping ajani icin testler.

Bu ajanlarin (nice, ecdc, ema, esc, tuseb, google_scholar) daha once HIC
birim test kapsami yoktu — sadece agac gorunumunde "evidence.graph.health_agents"
altindaki AYRI, eski bir modul test ediliyordu (bkz. test_health_agents.py),
"evidence.v2.sources.*" implementasyonlari degil. Bu dosya once o bosluğu,
sonra da retry/backoff eklentisini (docs/ai-infrastructure-inventory.md,
"Scraping kirilganligi") test eder.

Gercek aga hicbir istek gitmez — httpx.MockTransport ile hepsi sahte.
"""

from __future__ import annotations

import httpx
import pytest

from evidence.v2.sources.ecdc import ECDCAgent
from evidence.v2.sources.google_scholar import GoogleScholarAgent
from evidence.v2.sources.health_base import HealthOrgAgent
from evidence.v2.sources.nice import NICEAgent


def _client_with_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _Counter:
    """Cagri sayacini ve gecmisini tutan basit yardimci (closure yerine)."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> None:
        self.calls.append(request)

    @property
    def count(self) -> int:
        return len(self.calls)


class TestGetWithRetry:
    """Paylasilan retry/backoff yardimcisi — NICEAgent ornek olarak kullanildi,
    ama mantik HealthOrgAgent'ta yasadigi icin tum 6 ajan icin gecerli."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_try_no_retry(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            return httpx.Response(200, text="ok")

        agent = NICEAgent()
        async with _client_with_transport(handler) as client:
            resp = await agent._get_with_retry(client, "https://example.com/x")
        assert resp.status_code == 200
        assert counter.count == 1

    @pytest.mark.asyncio
    async def test_retries_transient_503_then_succeeds(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            if counter.count < 3:
                return httpx.Response(503, text="temporarily unavailable")
            return httpx.Response(200, text="ok on third try")

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01  # testleri yavaslatma
        async with _client_with_transport(handler) as client:
            resp = await agent._get_with_retry(client, "https://example.com/x")
        assert resp.status_code == 200
        assert "third try" in resp.text
        assert counter.count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_permanent_403(self):
        """403 (bot-engelleme) tekrar denemekle duzelmez — WHO IRIS ornegi
        zaten bunu ogretti (bkz. who.py). Tek denemede vazgecmeli."""
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            return httpx.Response(403, text="forbidden")

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01
        async with _client_with_transport(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await agent._get_with_retry(client, "https://example.com/x")
        assert counter.count == 1  # tekrar denenmedi

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises_on_persistent_503(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            return httpx.Response(503, text="still down")

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01
        async with _client_with_transport(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await agent._get_with_retry(client, "https://example.com/x")
        assert counter.count == agent.MAX_RETRIES + 1  # ilk deneme + tum retry'ler

    @pytest.mark.asyncio
    async def test_retries_on_connect_timeout_then_succeeds(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            if counter.count < 2:
                raise httpx.ConnectTimeout("simulated timeout", request=request)
            return httpx.Response(200, text="recovered")

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01
        async with _client_with_transport(handler) as client:
            resp = await agent._get_with_retry(client, "https://example.com/x")
        assert resp.text == "recovered"
        assert counter.count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_404(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            return httpx.Response(404, text="not found")

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01
        async with _client_with_transport(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await agent._get_with_retry(client, "https://example.com/x")
        assert counter.count == 1


class TestWarnIfZeroMatches:
    def test_logs_warning_when_no_matches(self, caplog):
        agent = NICEAgent()
        with caplog.at_level("WARNING"):
            agent._warn_if_zero_matches([], "kahve kolesterolü")
        assert any("0 regex" in r.message for r in caplog.records)

    def test_no_warning_when_matches_present(self, caplog):
        agent = NICEAgent()
        with caplog.at_level("WARNING"):
            agent._warn_if_zero_matches([("a", "b")], "kahve kolesterolü")
        assert not any("0 regex" in r.message for r in caplog.records)


class TestNICEAgentEndToEnd:
    """nice.py hicbir zaman mocklu bir HTTP testine sahip degildi — burada
    hem normal akis hem de retry-uzerinden-basari senaryosu kapsanir."""

    SEARCH_HTML = """
    <a href="/guidance/ng12">Suspected cancer: recognition and referral</a>
    <a href="/guidance/cg189">Obesity: identification, assessment and management</a>
    """
    DETAIL_HTML = '<div class="page-overview">Guideline overview text here.</div>'

    @pytest.mark.asyncio
    async def test_search_parses_results_and_fetches_passages(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/search" in str(request.url) or request.url.path == "/search":
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = NICEAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "obesity", limit=5)

        assert len(results) == 2
        assert results[0]["source"] == "nice"
        assert "cancer" in results[0]["title"].lower()
        assert "overview text" in results[0]["passage"].lower()

    @pytest.mark.asyncio
    async def test_search_recovers_from_transient_failure_via_retry(self):
        counter = _Counter()

        def handler(request: httpx.Request) -> httpx.Response:
            counter(request)
            is_search = request.url.path == "/search"
            if is_search and counter.count == 1:
                return httpx.Response(503, text="temporarily down")
            if is_search:
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = NICEAgent()
        agent.RETRY_BACKOFF_SECONDS = 0.01
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "obesity", limit=5)

        assert len(results) == 2  # ilk 503'e ragmen retry sayesinde basarili

    @pytest.mark.asyncio
    async def test_search_fails_closed_via_public_search_method(self, monkeypatch):
        """Ust seviye search() — kalici bir hata durumunda [] doner, crash etmez."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        transport = httpx.MockTransport(handler)

        class _PatchedClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("evidence.v2.sources.health_base.httpx.AsyncClient", _PatchedClient)

        agent = NICEAgent()
        results = await agent.search("obesity", limit=5)
        assert results == []


class TestGoogleScholarAgentEndToEnd:
    """Google Scholar tek istekli (pasaj icin ikinci cagri yok) ve ozel
    User-Agent kullaniyor — retry sarmalayicisinin bunu bozmadigini dogrular."""

    SEARCH_HTML = """
    <h3 class="gs_rt"><a href="https://doi.org/10.1/abc">Exercise and heart health</a></h3>
    <div class="gs_rs">A randomized trial found significant benefits.</div>
    """

    @pytest.mark.asyncio
    async def test_custom_user_agent_preserved_through_retry_wrapper(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text=self.SEARCH_HTML)

        agent = GoogleScholarAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "exercise heart", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Exercise and heart health"
        assert "Chrome" in captured[0].headers.get("user-agent", "")


class TestECDCAgentEndToEnd:
    SEARCH_HTML = '<a href="/en/publications-data/report-1">Flu Surveillance Report</a>'
    DETAIL_HTML = '<div class="field abstract">Seasonal flu abstract text.</div>'

    @pytest.mark.asyncio
    async def test_search_parses_results(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/en/publications-data":
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = ECDCAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "influenza", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Flu Surveillance Report"
        assert "abstract text" in results[0]["passage"].lower()
