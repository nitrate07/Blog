"""Base class for health organization agents."""

from __future__ import annotations

import logging
from typing import Any

import httpx

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

