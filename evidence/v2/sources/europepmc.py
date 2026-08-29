"""Europe PMC Agent — EBI'nin acik hayat-bilimleri arama REST API'si.

PubMed'in kapsamadigi preprint ve tam-metin endeksli kayitlari getirir;
kararli JSON API, bot korumasi yok.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.interfaces import SourceAgent
from .http_retry import get_with_retry

logger = logging.getLogger(__name__)


class EuropePMCAgent(SourceAgent):
    name = "europepmc"
    source_type = "academic"

    SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, timeout: float = 20.0, user_agent: str = "AriKaynak/2.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query:
            return []
        timeout = httpx.Timeout(self.timeout)
        params = {
            "query": f"{query} AND (SRC:MED OR SRC:PMC)",
            "format": "json",
            "pageSize": limit,
            "resultType": "core",
        }
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.user_agent}) as client:
            try:
                resp = await get_with_retry(client, self.SEARCH_URL, agent_name=self.name, params=params)
            except Exception as e:
                logger.warning(f"europepmc search failed: {e}")
                return []

        results: list[dict[str, Any]] = []
        for item in resp.json().get("resultList", {}).get("result", []):
            title = item.get("title")
            pmid = item.get("pmid")
            pmcid = item.get("pmcid")
            doi = item.get("doi")
            if pmid:
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            elif pmcid:
                url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
            elif doi:
                url = f"https://doi.org/{doi}"
            else:
                continue
            if not title:
                continue
            abstract = item.get("abstractText", "")[:2000]
            year = item.get("firstPublicationDate", "")[:4] or None
            results.append({
                "source": self.name,
                "title": title,
                "url": url,
                "doi": doi,
                "journal": item.get("journalTitle", ""),
                "published_year": int(year) if year and year.isdigit() else None,
                "passage": abstract,
                "source_type": self.source_type,
            })
        return results
