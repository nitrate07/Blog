"""Google Scholar Agent — searches Google Scholar for academic papers."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

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

        # NOT (2026-08-29): Diger 5 ajanin aksine burasi paylasilan
        # _extract_links/_extract_passage'a uymuyor — baslik (h3.gs_rt) ve
        # snippet (div.gs_rs) AYRI elementler; orijinal regex de bunlari
        # ayri ayri toplayip indekse gore esliyordu (title_matches[i] <->
        # snippets[i]) — ayni yaklasim burada BeautifulSoup ile korundu,
        # yalnizca ayristirma motoru degisti.
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            logger.warning(f"{self.name}: HTML ayristirma hatasi: {e}")
            return []

        title_elements = soup.find_all("h3", class_="gs_rt")
        self._warn_if_zero_matches(title_elements, query)
        snippet_elements = soup.find_all("div", class_="gs_rs")

        results = []
        for i, title_el in enumerate(title_elements[:limit]):
            link_el = title_el.find("a", href=True)
            if link_el is None:
                continue
            clean_title = title_el.get_text(separator=" ", strip=True)
            passage = snippet_elements[i].get_text(separator=" ", strip=True)[:2000] if i < len(snippet_elements) else ""

            results.append({
                "source": self.name,
                "organization": "Google Scholar",
                "title": clean_title,
                "url": link_el["href"],
                "passage": passage,
                "source_type": self.source_type,
            })
        return results
