"""ECDC Agent — searches European Centre for Disease Prevention and Control."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class ECDCAgent(HealthOrgAgent):
    """Searches ECDC publications.
    
    Flow:
    1. Search publications page → get links
    2. Fetch each publication → extract abstract
    3. Return metadata + passage
    """
    
    name = "ecdc"
    source_type = "international_organization"
    
    PUBLICATIONS_URL = "https://www.ecdc.europa.eu/en/publications-data"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.PUBLICATIONS_URL, params={"search": query})

        matches = self._extract_links(resp.text, "/en/publications-data/", limit)
        self._warn_if_zero_matches(matches, query)

        results = []
        for href, title in matches:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "European Centre for Disease Prevention and Control",
                "title": title,
                "url": f"https://www.ecdc.europa.eu{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await self._get_with_retry(client, f"https://www.ecdc.europa.eu{href}")
            return self._extract_passage(resp.text, "abstract")
        except Exception as e:
            logger.debug(f"{self.name}: passage fetch failed for {href!r}: {e}")
        return ""
