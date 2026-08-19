"""CDC Agent — searches US Centers for Disease Control and Prevention."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class CDCAgent(HealthOrgAgent):
    """Searches CDC MMWR and guidelines.
    
    Flow:
    1. Search CDC → get results with content snippets
    2. Return metadata + passage (content snippet)
    """
    
    name = "cdc"
    source_type = "government"
    
    SEARCH_URL = "https://search.cdc.gov/search/"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={
            "query": query,
            "t": "true",
            "s": "relevance",
            "d": "",
            "action": "search",
            "output": "json",
        })
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for item in data.get("results", [])[:limit]:
            results.append({
                "source": self.name,
                "organization": "US Centers for Disease Control and Prevention",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "passage": item.get("content", "")[:2000],
                "source_type": self.source_type,
            })
        return results
