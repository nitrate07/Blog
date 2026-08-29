"""Base class for health organization agents."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..core.interfaces import SourceAgent
from .http_retry import DEFAULT_BACKOFF_SECONDS, DEFAULT_MAX_RETRIES, get_with_retry

logger = logging.getLogger(__name__)


class HealthOrgAgent(SourceAgent):
    """Base class for all health organization agents.
    
    Subclasses must implement:
    - name
    - source_type
    - _search(client, query, limit) -> list[dict]
    """

    def __init__(self, timeout: float = 30.0, user_agent: str = "AriKaynak/2.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent
    
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        ) as client:
            try:
                return await self._search(client, query, limit)
            except Exception as e:
                logger.warning(f"{self.name} search failed: {e}")
                return []
    
    async def _search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Subclasses must implement this method."""
        raise NotImplementedError

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        """Bkz. .http_retry.get_with_retry — bu, paylasilan fonksiyona ince bir
        sarmalayici (agent_name'i otomatik gecirir, mevcut cagri yerlerini
        degistirmeden geriye donuk uyumlu tutar).

        Alt siniflar/testler `self.RETRY_BACKOFF_SECONDS` / `self.MAX_RETRIES`
        instance ozniteligini ayarlayarak (ör. testlerde hizlandirmak icin)
        varsayilanlari gecersiz kilabilir; kwargs ile acikca verilen deger
        her zaman kazanir.
        """
        kwargs.setdefault("backoff_seconds", getattr(self, "RETRY_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS))
        kwargs.setdefault("max_retries", getattr(self, "MAX_RETRIES", DEFAULT_MAX_RETRIES))
        return await get_with_retry(client, url, agent_name=self.name, **kwargs)

    def _warn_if_zero_matches(self, matches: list[Any], query: str) -> None:
        """HTTP 200 alindi ama regex hicbir sey bulamadiysa ayirt edici uyari.

        "Bu konuda gercekten kaynak yok" ile "sitenin HTML yapisi degisti,
        regex'imiz artik kirik" arasindaki fark, sessiz bos-sonuc donuslerinde
        kaybolur — ikisi de disaridan ayni gorunur (0 sonuc). Bu, en azindan
        loglarda ayirt edilebilir hale getirir; regex'i otomatik duzeltmez.
        """
        if not matches:
            logger.warning(
                f"{self.name}: HTTP 200 alindi ama sorgu icin 0 regex eslesmesi "
                f"bulundu (query={query!r}) — ya gercekten sonuc yok ya da "
                f"sitenin HTML yapisi degisti (scraper curumesi olasi)"
            )

    def _extract_links(
        self, html: str, href_prefix: str, limit: int, min_title_len: int = 1
    ) -> list[tuple[str, str]]:
        """href'i verilen onekle baslayan tum <a> etiketlerini (href, temiz
        baslik) cifti olarak dondurur — BeautifulSoup ile.

        NOT (2026-08-29): Bu 6 ajan (nice, ecdc, ema, esc, tuseb,
        google_scholar) daha once ham regex ile HTML ayristiriyordu
        (ör. r'href="(/guidance/[^"]+)"[^>]*>(.*?)</a>'). Regex, HTML
        yapisinin TAM olarak beklenen sekilde olmasina bagimlidir — ic ice
        gecmis etiketler, farkli attribute sirasi, kendi kendini kapatmayan
        etiketler gibi gercek dunyada sik goruelen HTML varyasyonlarinda
        sessizce 0 sonuc donmeye baslar (bkz. _warn_if_zero_matches — bu
        durumu en azindan loglarda ayirt edilebilir kilan onceki duzeltme).
        BeautifulSoup gercek bir HTML parser'i oldugu icin bu varyasyonlarin
        cogunda calismaya devam eder; site tamamen farkli bir URL yapisina
        gecmedigi surece (ki bu durumda zaten sadece href_prefix'i
        guncellemek yeterli olur) daha dayaniklidir.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.warning(f"{self.name}: HTML ayristirma hatasi: {e}")
            return []

        results: list[tuple[str, str]] = []
        seen_hrefs: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith(href_prefix) or href in seen_hrefs:
                continue
            title = a.get_text(separator=" ", strip=True)
            if len(title) < min_title_len:
                continue
            seen_hrefs.add(href)
            results.append((href, title))
            if len(results) >= limit:
                break
        return results

    def _extract_passage(self, html: str, class_substring: str, max_len: int = 2000) -> str:
        """Class attribute'unde verilen alt-diziyi iceren ilk elementin
        duz metnini dondurur — BeautifulSoup ile (bkz. _extract_links notu,
        ayni regex-kirilganligi gerekcesi burada da gecerli).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.debug(f"{self.name}: HTML ayristirma hatasi (pasaj): {e}")
            return ""

        def _matches(tag: Any) -> bool:
            if not tag.has_attr("class"):
                return False
            joined = " ".join(tag.get("class") or [])
            return class_substring in joined

        el = soup.find(_matches)
        if el is None:
            return ""
        return el.get_text(separator=" ", strip=True)[:max_len]

