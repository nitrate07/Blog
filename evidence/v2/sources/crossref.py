"""Crossref Agent — searches Crossref for academic papers and DOIs."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.interfaces import SourceAgent
from .http_retry import get_with_retry

logger = logging.getLogger(__name__)


class CrossrefAgent(SourceAgent):
    """Searches Crossref for academic papers.
    
    Flow:
    1. Search → get items with metadata
    2. Return metadata + passage (title/abstract if available)
    """
    
    name = "crossref"
    source_type = "academic"
    
    API_URL = "https://api.crossref.org/works"
    
    def __init__(self, timeout: float = 30.0, user_agent: str = "AriKaynak/2.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent
    
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.timeout)
        headers = {"User-Agent": self.user_agent}
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            try:
                resp = await get_with_retry(client, self.API_URL, agent_name=self.name, params={
                    "query": query,
                    "rows": limit,
                    "select": "DOI,title,published,URL,type,author,container-title,abstract",
                })
            except Exception as e:
                logger.warning(f"Crossref search failed: {e}")
                return []
        
        items = resp.json().get("message", {}).get("items", [])
        results = []
        for item in items:
            doi = item.get("DOI")
            title = next(iter(item.get("title", [])), None)
            url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)
            if not title or not url:
                continue
            
            dates = item.get("published", {}).get("date-parts", [[]])
            year = dates[0][0] if dates and dates[0] else None
            authors = item.get("author", [])
            first_author = f"{authors[0].get('given', '')} {authors[0].get('family', '')}".strip() if authors else ""
            journal = next(iter(item.get("container-title", [])), "")
            abstract = item.get("abstract", "")
            if abstract:
                import re
                abstract = re.sub(r'<[^>]+>', '', abstract)[:2000]
            
            results.append({
                "source": self.name,
                "doi": doi,
                "title": title,
                "url": url,
                "first_author": first_author,
                "journal": journal,
                "year": year,
                "passage": abstract,
                "source_type": self.source_type,
            })
        return results
