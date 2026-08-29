"""OpenAlex Agent — acik bilimsel grafik API'si (250M+ kayit).

Europe PMC/PubMed'in kapsamadigi dergileri de tarar; kararlil JSON,
anahtar-kelime aramasi icin 'search' parametresi alir.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..core.interfaces import SourceAgent
from .http_retry import get_with_retry

logger = logging.getLogger(__name__)


class OpenAlexAgent(SourceAgent):
    name = "openalex"
    source_type = "academic"

    SEARCH_URL = "https://api.openalex.org/works"

    def __init__(self, timeout: float = 20.0, user_agent: str = "AriKaynak/2.0 (mailto:research@arikaynak.org)") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query:
            return []
        timeout = httpx.Timeout(self.timeout)
        params = {
            "search": query,
            "per-page": limit,
            "filter": "type:article",
            "select": "id,doi,title,publication_year,primary_location,abstract_inverted_index",
            "mailto": "research@arikaynak.org",
        }
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.user_agent}) as client:
            try:
                resp = await get_with_retry(client, self.SEARCH_URL, agent_name=self.name, params=params)
            except Exception as e:
                logger.warning(f"openalex search failed: {e}")
                return []

        results: list[dict[str, Any]] = []
        for item in resp.json().get("results", []):
            doi = (item.get("doi") or "").replace("https://doi.org/", "")
            title = item.get("title")
            url = f"https://doi.org/{doi}" if doi else None
            if not title or not url:
                continue
            location = item.get("primary_location") or {}
            source_info = location.get("source") or {}
            results.append({
                "source": self.name,
                "title": title,
                "url": url,
                "doi": doi,
                "journal": source_info.get("display_name", ""),
                "published_year": item.get("publication_year"),
                "passage": self._abstract_text(item.get("abstract_inverted_index"))[:2000],
                "source_type": self.source_type,
            })
        return results

    @staticmethod
    def _abstract_text(inverted: dict[str, list[int]] | None) -> str:
        """OpenAlex'in ters-endeks ozetini duz metne cevirir."""
        if not inverted:
            return ""
        positions: list[tuple[int, str]] = []
        for word, idxs in inverted.items():
            for idx in idxs:
                positions.append((idx, word))
        positions.sort()
        return re.sub(r"\s+", " ", " ".join(w for _, w in positions)).strip()
