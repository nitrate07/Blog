"""ECDC Agent — searches European Centre for Disease Prevention and Control."""

from __future__ import annotations

import logging
import re
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
        resp = await client.get(self.PUBLICATIONS_URL, params={"search": query})
        resp.raise_for_status()
        text = resp.text
        
        pattern = r'href="(/en/publications-data/[^"]+)"[^>]*>([^<]+)<'
        matches = re.findall(pattern, text)
        
        results = []
        for href, title in matches[:limit]:
            passage = await self._fetch_passage(client, href)
            results.append({
                "source": self.name,
                "organization": "European Centre for Disease Prevention and Control",
                "title": title.strip(),
                "url": f"https://www.ecdc.europa.eu{href}",
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
    
    async def _fetch_passage(self, client: httpx.AsyncClient, href: str) -> str:
        try:
            resp = await client.get(f"https://www.ecdc.europa.eu{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
