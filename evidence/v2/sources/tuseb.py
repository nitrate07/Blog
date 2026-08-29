"""TÜSEB Agent — searches Turkish Health Institutes Authority."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class TUSEBAgent(HealthOrgAgent):
    """Searches TÜSEB for Turkish health research and guidelines.
    
    Flow:
    1. Search TÜSEB → get publication links
    2. Fetch publication page → extract summary
    3. Return metadata + passage
    """
    
    name = "tuseb"
    source_type = "tertiary"
    organization = "Türkiye Sağlık Enstitüleri Başkanlığı"
    
    SEARCH_URL = "https://www.tuseb.gov.tr/arama"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.SEARCH_URL, params={
            "q": query,
        })

        # min_title_len=10: TÜSEB sitesindeki cok kisa/menu baglantilarini
        # (ör. "Ana Sayfa", "İletişim") gercek yayin basliklarindan ayirt
        # etmek icin — bu ozel kural regex donemindeydi de vardi, korundu.
        matches = self._extract_links(resp.text, "/", limit, min_title_len=10)
        self._warn_if_zero_matches(matches, query)

        results = []
        for href, clean_title in matches:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": self.organization,
                "title": clean_title,
                "url": f"https://www.tuseb.gov.tr{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await self._get_with_retry(client, f"https://www.tuseb.gov.tr{href}")
            return self._extract_passage(resp.text, "content")
        except Exception as e:
            logger.debug(f"{self.name}: passage fetch failed for {href!r}: {e}")
        return ""
