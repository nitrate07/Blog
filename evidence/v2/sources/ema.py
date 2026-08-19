"""EMA Agent — searches European Medicines Agency."""

from __future__ import annotations

import logging
import re
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
        resp = await client.get(self.SEARCH_URL, params={
            "search_api_fulltext": query,
            "f%5B0%5D": "sm_type:ema_search_result",
        })
        resp.raise_for_status()
        
        pattern = r'href="(/en/medicines/[^"]+)"[^>]*>([^<]+)<'
        matches = re.findall(pattern, resp.text)
        
        results = []
        for href, title in matches[:limit]:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "European Medicines Agency",
                "title": title.strip(),
                "url": f"https://www.ema.europa.eu{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await client.get(f"https://www.ema.europa.eu{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*field--name-body[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
