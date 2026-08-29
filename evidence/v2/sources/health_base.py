"""Base class for health organization agents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..core.interfaces import SourceAgent

logger = logging.getLogger(__name__)


class HealthOrgAgent(SourceAgent):
    """Base class for all health organization agents.
    
    Subclasses must implement:
    - name
    - source_type
    - _search(client, query, limit) -> list[dict]
    """

    # Gecici sayilan HTTP durum kodlari — bunlar icin tekrar denenir.
    # 403/404 gibi kalici hatalar burada YOK: WHO IRIS'in bot-korumasi
    # (403) ornegi gosteriyor ki bunlar tekrar denemekle duzelmez, yalnizca
    # arastirma turunun zaman butcesini bosa harcar (bkz. who.py, cochrane.py
    # docstring'leri — o iki kaynak zaten kalici HTML->Crossref gecisi
    # yapti; bu siniflandirma NEDEN yaptiklarini genellestirir).
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
    MAX_RETRIES = 2  # ilk deneme + en fazla 2 tekrar = en fazla 3 toplam deneme
    RETRY_BACKOFF_SECONDS = 0.4  # denemeler arasi: 0.4s, 0.8s (ustel)

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
        """GET + gecici hatalar icin ustel geri-cekilmeli tekrar deneme.

        Bu projedeki HTML-scraping ajanlari (NICE, ECDC, EMA, ESC, TUSEB,
        Google Scholar) tek bir client.get() + raise_for_status() cagrisina
        dayaniyordu — bir aginin zaman asimi ya da gecici bir 503, o turdaki
        aramayi tek seferde bosa cikariyordu (bkz. docs/ai-infrastructure-
        inventory.md, "Scraping kirilganligi"). Bu yardimci YALNIZCA gecici
        sinifina giren hatalari (baglanti zaman asimi/kopmasi, 429/5xx)
        tekrar dener; kalici hatalari (403 bot-engelleme gibi) TEKRAR
        DENEMEZ — hemen firlatir, ustteki search() bunu her zamanki gibi
        yakalayip [] doner.

        Cagiran taraf acisindan davranis degismedi: basarisizlikta ayni
        exception turleri firlar (httpx.HTTPStatusError / TimeoutException /
        ConnectError), yalnizca gecici hatalarda birden fazla deneme
        yapilmis olur.
        """
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                last_exc = e
            else:
                if resp.status_code not in self.RETRYABLE_STATUS_CODES:
                    resp.raise_for_status()
                    return resp
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} (retryable status)",
                    request=resp.request,
                    response=resp,
                )

            if attempt < self.MAX_RETRIES:
                delay = self.RETRY_BACKOFF_SECONDS * (2 ** attempt)
                logger.debug(
                    f"{self.name}: retryable failure on attempt {attempt + 1} "
                    f"for {url!r}, retrying in {delay}s: {last_exc}"
                )
                await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

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

