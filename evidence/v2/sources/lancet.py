"""Lancet Agent — searches The Lancet for medical research."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class LancetAgent(HealthOrgAgent):
    """Searches The Lancet for high-impact medical research.
    
    Flow:
    1. Search Lancet → get article links
    2. Fetch article page → extract abstract
    3. Return metadata + passage
    """
    
    name = "lancet"
    source_type = "academic"
    journal = "The Lancet"
    impact_factor = 168.9
    
    SEARCH_URL = "https://www.thelancet.com/searchresults"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={
            "query": query,
            "showAll": "true",
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
                "organization": "The Lancet",
                "title": clean_title,
                "url": f"https://www.thelancet.com{href}",
                "passage": passage,
                "source_type": self.source_type,
                "journal": self.journal,
                "impact_factor": self.impact_factor,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await client.get(f"https://www.thelancet.com{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
