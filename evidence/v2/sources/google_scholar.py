"""Google Scholar Agent — searches Google Scholar for academic papers."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class GoogleScholarAgent(HealthOrgAgent):
    """Searches Google Scholar for academic papers.
    
    Flow:
    1. Search Google Scholar → parse HTML
    2. Extract titles, URLs, snippets
    3. Return metadata + passage (snippet)
    """
    
    name = "google_scholar"
    source_type = "academic"
    
    SEARCH_URL = "https://scholar.google.com/scholar"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._get_with_retry(client, self.SEARCH_URL, params={
            "q": query,
            "hl": "en",
            "num": limit,
        }, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        text = resp.text
        
        # Extract results
        title_pattern = r'<h3[^>]*class="gs_rt"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        title_matches = re.findall(title_pattern, text, re.DOTALL)
        self._warn_if_zero_matches(title_matches, query)
        
        # Extract snippets
        snippet_pattern = r'<div[^>]*class="gs_rs"[^>]*>(.*?)</div>'
        snippets = re.findall(snippet_pattern, text, re.DOTALL)
        
        results = []
        for i, (url, title) in enumerate(title_matches[:limit]):
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            passage = re.sub(r'<[^>]+>', '', snippets[i]).strip()[:2000] if i < len(snippets) else ""
            
            results.append({
                "source": self.name,
                "organization": "Google Scholar",
                "title": clean_title,
                "url": url,
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
