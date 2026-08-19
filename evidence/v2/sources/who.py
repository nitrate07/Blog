"""WHO Agent — searches World Health Organization IRIS repository."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class WHOAgent(HealthOrgAgent):
    """Searches WHO IRIS (Institutional Repository).
    
    Flow:
    1. Search IRIS → get handles
    2. Fetch document details → get metadata
    3. Fetch abstract → get passage
    4. Return metadata + passage
    """
    
    name = "who"
    source_type = "international_organization"
    
    SEARCH_URL = "https://iris.who.int/rest/api/search"
    HANDLE_URL = "https://iris.who.int/rest/api/handle"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.SEARCH_URL, params={
            "query": query,
            "dte": "2020-01-01",
            "scope": "WHO archives",
            "sort": "created",
            "rpp": limit,
            "pageRender": "false",
        })
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for item in data.get("resultSet", []):
            metadata = item.get("metadata", [])
            title_text = ""
            doi = None
            handle = item.get("handle", "")
            
            for m in metadata:
                if m.get("key") == "dc.title":
                    title_text = m.get("value", "")
                if m.get("key") == "dc.identifier.doi":
                    doi = m.get("value", "")
            
            if not title_text:
                continue
            
            passage = await self._fetch_passage(client, handle)
            
            results.append({
                "source": self.name,
                "organization": "World Health Organization",
                "title": title_text,
                "url": f"https://iris.who.int/handle/{handle}",
                "doi": doi,
                "passage": passage,
                "source_type": self.source_type,
            })
        return results[:limit]
    
    async def _fetch_passage(self, client: httpx.AsyncClient, handle: str) -> str:
        if not handle:
            return ""
        try:
            resp = await client.get(f"{self.HANDLE_URL}/{handle}", params={"expand": "bitstreams"})
            resp.raise_for_status()
            detail = resp.json()
            for bitstream in detail.get("bitstreams", []):
                if bitstream.get("format", "").startswith("text"):
                    content_resp = await client.get(bitstream.get("retrieveLink", ""))
                    if content_resp.status_code == 200:
                        return content_resp.text[:2000]
        except Exception:
            pass
        return ""
