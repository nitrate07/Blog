"""ESC Agent — searches European Society of Cardiology."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class ESCAgent(HealthOrgAgent):
    """Searches ESC for cardiovascular guidelines and research.
    
    Flow:
    1. Search ESC → get guideline links
    2. Fetch guideline page → extract summary
    3. Return metadata + passage
    """
    
    name = "esc"
    source_type = "tertiary"
    organization = "European Society of Cardiology"
    
    SEARCH_URL = "https://www.escardio.org/Guidelines/Clinical-Practice-Guidelines"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.SEARCH_URL)

        matches = self._extract_links(resp.text, "/Guidelines/Clinical-Practice-Guidelines/", limit)
        self._warn_if_zero_matches(matches, query)

        results = []
        for href, clean_title in matches:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": self.organization,
                "title": clean_title,
                "url": f"https://www.escardio.org{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await self._get_with_retry(client, f"https://www.escardio.org{href}")
            return self._extract_passage(resp.text, "abstract")
        except Exception as e:
            logger.debug(f"{self.name}: passage fetch failed for {href!r}: {e}")
        return ""
