"""NEJM Agent — searches New England Journal of Medicine."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class NEJMAgent(HealthOrgAgent):
    """Searches NEJM for high-impact medical research.
    
    Flow:
    1. Search NEJM → get article links
    2. Fetch article page → extract abstract
    3. Return metadata + passage
    """
    
    name = "nejm"
    source_type = "academic"
    journal = "New England Journal of Medicine"
    impact_factor = 158.5
    
    SEARCH_URL = "https://www.nejm.org/action/doSearch"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={
            "AllField": query,
            "startPage": 0,
            "pageSize": limit,
        })
        resp.raise_for_status()
        text = resp.text
        
        # Extract article links
        pattern = r'href="(/doi/full/[^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, text, re.DOTALL)
        
        results = []
        for href, title in matches[:limit]:
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if not clean_title:
                continue
            
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "New England Journal of Medicine",
                "title": clean_title,
                "url": f"https://www.nejm.org{href}",
                "passage": passage,
                "source_type": self.source_type,
                "journal": self.journal,
                "impact_factor": self.impact_factor,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await client.get(f"https://www.nejm.org{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
