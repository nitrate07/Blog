"""ESC Agent — searches European Society of Cardiology."""

from __future__ import annotations

import logging
import re
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
        resp = await client.get(self.SEARCH_URL)
        resp.raise_for_status()
        text = resp.text
        
        pattern = r'href="(/Guidelines/Clinical-Practice-Guidelines/[^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, text, re.DOTALL)
        
        results = []
        for href, title in matches[:limit]:
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if not clean_title:
                continue
            
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
            resp = await client.get(f"https://www.escardio.org{href}")
            if resp.status_code == 200:
                match = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
                if match:
                    return re.sub(r'<[^>]+>', '', match.group(1)).strip()[:2000]
        except Exception:
            pass
        return ""
