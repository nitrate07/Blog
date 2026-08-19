"""TÜSEB Agent — searches Turkish Health Institutes Authority."""

from __future__ import annotations

import logging
import re
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
        resp = await client.get(self.SEARCH_URL, params={
            "q": query,
        })
        resp.raise_for_status()
        text = resp.text
        
        pattern = r'href="(/[^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, text, re.DOTALL)
        
        results = []
        for href, title in matches[:limit]:
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if not clean_title or len(clean_title) < 10:
                continue
            
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
            resp = await client.get(f"https://www.tuseb.gov.tr{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
