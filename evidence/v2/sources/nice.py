"""NICE Agent — searches UK National Institute for Health and Care Excellence."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class NICEAgent(HealthOrgAgent):
    """Searches NICE for clinical guidelines and evidence summaries.
    
    Flow:
    1. Search NICE → get guideline links
    2. Fetch guideline page → extract summary
    3. Return metadata + passage
    """
    
    name = "nice"
    source_type = "tertiary"
    organization = "National Institute for Health and Care Excellence"
    
    SEARCH_URL = "https://www.nice.org.uk/search"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.SEARCH_URL, params={
            "q": query,
            "type": "guidance,files",
        })

        matches = self._extract_links(resp.text, "/guidance/", limit)
        self._warn_if_zero_matches(matches, query)

        results = []
        for href, clean_title in matches:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": self.organization,
                "title": clean_title,
                "url": f"https://www.nice.org.uk{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await self._get_with_retry(client, f"https://www.nice.org.uk{href}")
            return self._extract_passage(resp.text, "overview")
        except Exception as e:
            logger.debug(f"{self.name}: passage fetch failed for {href!r}: {e}")
        return ""
