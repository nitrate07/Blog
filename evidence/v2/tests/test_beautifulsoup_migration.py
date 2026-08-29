"""BeautifulSoup gecisi (2026-08-29) icin testler.

6 HTML-scraping ajani (nice, ecdc, ema, esc, tuseb, google_scholar) ham
regex yerine BeautifulSoup kullanacak sekilde tasindi — gerekce:
docs/ai-infrastructure-inventory.md'deki "scraping kirilganligi" maddesi
ve canli veriyle dogrulanan bulgu (tamamen alakasiz sorgular bazen
gercek eslesmelerden daha yuksek skor alabiliyordu — ayri bir konu, ama
ayni kok neden sinifindan: kirilgan/kaba ayristirma).

Bu dosya iki seyi test eder:
1. EMA/ESC/TUSEB icin (daha once hic testi olmayan 3 ajan) temel
   ayristirma dogrulugu.
2. BeautifulSoup'un DEGER KATTIGI somut senaryolar — regex'in kirilacagi
   ama BeautifulSoup'un sorunsuz isleyecegi HTML varyasyonlari (farkli
   attribute sirasi, ic ice span'ler, ekstra class'lar, whitespace).
"""

from __future__ import annotations

import httpx
import pytest

from evidence.v2.sources.ema import EMAAgent
from evidence.v2.sources.esc import ESCAgent
from evidence.v2.sources.health_base import HealthOrgAgent
from evidence.v2.sources.tuseb import TUSEBAgent


def _client_with_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestEMAAgentParsing:
    SEARCH_HTML = '<a href="/en/medicines/human/EPAR/aspirin-x">Aspirin X 100mg</a>'
    DETAIL_HTML = '<div class="field field--name-body">Cardiovascular prevention summary.</div>'

    @pytest.mark.asyncio
    async def test_search_parses_results_and_fetches_passage(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/en/search":
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = EMAAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "aspirin", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Aspirin X 100mg"
        assert "cardiovascular" in results[0]["passage"].lower()


class TestESCAgentParsing:
    SEARCH_HTML = (
        '<a href="/Guidelines/Clinical-Practice-Guidelines/Heart-Failure">'
        "Heart Failure Guidelines</a>"
    )
    DETAIL_HTML = '<div class="content abstract-body">Guideline abstract text.</div>'

    @pytest.mark.asyncio
    async def test_search_parses_results_and_fetches_passage(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/Guidelines/Clinical-Practice-Guidelines":
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = ESCAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "heart failure", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Heart Failure Guidelines"
        assert "abstract text" in results[0]["passage"].lower()


class TestTUSEBAgentParsing:
    SEARCH_HTML = """
    <a href="/">Ana Sayfa</a>
    <a href="/haberler/saglik-arastirmasi-2026">Yeni Sağlık Araştırması Yayınlandı 2026</a>
    """
    DETAIL_HTML = '<div class="page-content">Araştırma özeti burada.</div>'

    @pytest.mark.asyncio
    async def test_search_filters_short_menu_links_by_title_length(self):
        """min_title_len=10 kurali korunmus olmali — 'Ana Sayfa' gibi
        menu baglantilari elenmeli, gercek yayin basligi kalmali."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/arama":
                return httpx.Response(200, text=self.SEARCH_HTML)
            return httpx.Response(200, text=self.DETAIL_HTML)

        agent = TUSEBAgent()
        async with _client_with_transport(handler) as client:
            results = await agent._search(client, "sağlık araştırması", limit=5)

        assert len(results) == 1
        assert "Yeni Sağlık Araştırması" in results[0]["title"]
        assert "özeti" in results[0]["passage"]


class _DummyAgent(HealthOrgAgent):
    """_extract_links/_extract_passage'i dogrudan test etmek icin minimal ajan."""
    name = "dummy"
    source_type = "test"

    async def _search(self, client, query, limit):
        raise NotImplementedError


class TestSharedExtractLinksRobustness:
    """BeautifulSoup gecisinin degerini kanitlayan senaryolar. Durustluk
    notu: bunlarin bir kismini (attribute sirasi, ic ice span) eski regex +
    ayri bir temizlik regex'i (re.sub(r'<[^>]+>', ...)) ikilisi de dogru
    isliyordu — bu dogrulandi, asagida abartilmadi. Kanitlanmis, somut fark
    BOZUK/KAPANMAMIS HTML'de (test_malformed_html_does_not_crash) — eski
    regex bunda TAMAMEN BOS DONUYORDU (dogrulandi), BeautifulSoup dogru
    ayikliyor. Digerlerinin degeri fonksiyonel esitlikten çok mimari:
    tek adimda (get_text) hem cikarma hem temizlik yapiliyor, ayri bir
    cleanup regex'ine bagimlilik ortadan kalkiyor — bu da bakim yukunu ve
    gelecekte "iki regex'i senkron tutma" sinifi hatalari azaltir."""

    def setup_method(self):
        self.agent = _DummyAgent()

    def test_attribute_order_reversed(self):
        html = '<a class="link-style" id="x1" href="/guidance/ng1" data-track="true">Guideline One</a>'
        results = self.agent._extract_links(html, "/guidance/", limit=5)
        assert results == [("/guidance/ng1", "Guideline One")]

    def test_nested_span_inside_link_text(self):
        html = '<a href="/guidance/ng2"><span class="bold">Diabetes</span> <strong>Guideline</strong></a>'
        results = self.agent._extract_links(html, "/guidance/", limit=5)
        assert results == [("/guidance/ng2", "Diabetes Guideline")]

    def test_multiline_and_extra_whitespace(self):
        """Gercek dunyada HTML sik sik satir sonlari/girintilerle gelir —
        regex'in re.DOTALL bayragi buna kismen dayanikliydi ama metin
        temizligi hala kirilgandi. BeautifulSoup get_text(strip=True) ile
        fazla bosluklari da normalize eder."""
        html = """
        <a href="/guidance/ng3">
            Obesity
            Management
        </a>
        """
        results = self.agent._extract_links(html, "/guidance/", limit=5)
        assert len(results) == 1
        assert results[0][0] == "/guidance/ng3"
        assert "Obesity" in results[0][1] and "Management" in results[0][1]

    def test_duplicate_href_deduplicated(self):
        html = (
            '<a href="/guidance/ng1">Guideline One</a>'
            '<a href="/guidance/ng1">Guideline One (mirror link)</a>'
        )
        results = self.agent._extract_links(html, "/guidance/", limit=5)
        assert len(results) == 1

    def test_limit_respected(self):
        html = "".join(f'<a href="/guidance/ng{i}">Title {i}</a>' for i in range(10))
        results = self.agent._extract_links(html, "/guidance/", limit=3)
        assert len(results) == 3

    def test_malformed_html_does_not_crash(self):
        """Dogrulandi: eski regex bu girdide TAMAMEN BOS liste donuyordu
        (kapanmamis <a> etiketleri onu sasirtiyordu). BeautifulSoup'un
        html.parser'i gecerli olmayan HTML'i de makul sekilde agaca
        cevirir, en azindan ilk gercek linki dogru cikarir."""
        html = '<div><a href="/guidance/ng1">Broken <b>markup<a></div>'
        results = self.agent._extract_links(html, "/guidance/", limit=5)
        assert len(results) >= 1
        assert results[0][0] == "/guidance/ng1"


class TestSharedExtractPassageRobustness:
    def setup_method(self):
        self.agent = _DummyAgent()

    def test_extra_classes_around_target_still_matches(self):
        """Orijinal regex class="[^"]*overview[^"]*" ile alt-dize araniyordu
        — bu kismen esnekti ama class siralamasi/bosluklarindaki en ufak
        farklilikta kirilabilirdi. BeautifulSoup'ta class listesi
        normalize edilip her token ayri kontrol edilir."""
        html = '<div class="container page-overview-wrapper mt-4">Guideline summary text.</div>'
        passage = self.agent._extract_passage(html, "overview")
        assert "summary text" in passage.lower()

    def test_nested_tags_inside_passage_cleaned(self):
        html = '<div class="abstract">Background: <em>coffee</em> and <strong>cholesterol</strong>.</div>'
        passage = self.agent._extract_passage(html, "abstract")
        assert passage == "Background: coffee and cholesterol ."

    def test_no_matching_element_returns_empty_string(self):
        html = '<div class="unrelated">Nothing relevant here.</div>'
        assert self.agent._extract_passage(html, "overview") == ""

    def test_truncates_to_max_len(self):
        html = f'<div class="overview">{"x" * 3000}</div>'
        passage = self.agent._extract_passage(html, "overview", max_len=100)
        assert len(passage) == 100
