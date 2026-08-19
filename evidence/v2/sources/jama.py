"""JAMA Agent — searches Journal of the American Medical Association."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class JAMAAgent(HealthOrgAgent):
    """Searches JAMA for medical research.
    
    Flow:
    1. Search JAMA → get article links
    2. Fetch article page → extract abstract
    3. Return metadata + passage
    """
    
    name = "jama"
    source_type = "academic"
    journal = "JAMA - Journal of the American Medical Association"
    impact_factor = 120.7
    
    SEARCH_URL = "https://jamanetwork.com/searchresults"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={
            "query": query,
            "pageSize": limit,
        })
        resp.raise_for_status()
        text = resp.text
        
        pattern = r'href="(/journals/[^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, text, re.DOTALL)
        
        results = []
        for href, title in matches[:limit]:
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if not clean_title:
                continue
            
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "JAMA Network",
                "title": clean_title,
                "url": f"https://jamanetwork.com{href}",
                "passage": passage,
                "source_type": self.source_type,
                "journal": self.journal,
                "impact_factor": self.impact_factor,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await client.get(f"https://jamanetwork.com{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
