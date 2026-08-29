"""EMA Agent — searches European Medicines Agency."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class EMAAgent(HealthOrgAgent):
    """Searches EMA for European drug assessments.
    
    Flow:
    1. Search EMA website → get product links
    2. Fetch each product page → extract summary
    3. Return metadata + passage
    """
    
    name = "ema"
    source_type = "regulatory"
    
    SEARCH_URL = "https://www.ema.europa.eu/en/search"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.SEARCH_URL, params={
            "search_api_fulltext": query,
            "f%5B0%5D": "sm_type:ema_search_result",
        })

        matches = self._extract_links(resp.text, "/en/medicines/", limit)
        self._warn_if_zero_matches(matches, query)

        results = []
        for href, title in matches:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "European Medicines Agency",
                "title": title,
                "url": f"https://www.ema.europa.eu{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await self._get_with_retry(client, f"https://www.ema.europa.eu{href}")
            return self._extract_passage(resp.text, "field--name-body")
        except Exception as e:
            logger.debug(f"{self.name}: passage fetch failed for {href!r}: {e}")
        return ""
