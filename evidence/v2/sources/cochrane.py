"""Cochrane Agent — searches Cochrane Library for systematic reviews."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class CochraneAgent(HealthOrgAgent):
    """Searches Cochrane Library for systematic reviews.
    
    Flow:
    1. Search Cochrane API → get results with abstracts
    2. Return metadata + passage (abstract)
    """
    
    name = "cochrane"
    source_type = "systematic_review"
    
    API_URL = "https://api.cochrane.com/search"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.API_URL, params={
            "search": query,
            "page": 1,
            "pagesize": limit,
        })
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for item in data.get("results", []):
            results.append({
                "source": self.name,
                "organization": "Cochrane Collaboration",
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "doi": item.get("doi"),
                "passage": item.get("abstract", "")[:2000],
                "source_type": self.source_type,
            })
        return results
