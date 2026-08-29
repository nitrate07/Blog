"""PubMed Agent — searches PubMed for medical/scientific evidence."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..core.interfaces import SourceAgent
from .http_retry import get_with_retry

logger = logging.getLogger(__name__)


class PubMedAgent(SourceAgent):
    """Searches PubMed for medical and scientific evidence.
    
    Flow:
    1. Search → get PMIDs
    2. Fetch summaries → get metadata (title, authors, DOI)
    3. Fetch abstracts → get passage (full abstract)
    4. Return metadata + passage

    NOT (2026-08-29): Bu ucu ajanin en onemli tekli kaynagi (PubMed) — ama
    canli veriyle dogrulandi ki 3 ardisik cagrisinin (_search_ids,
    _fetch_summaries, _fetch_abstracts) hicbirinde retry yoktu; herhangi
    birinde gecici bir zaman asimi/503 o adimi (ve genelde tum aramayi)
    tek seferde kaybettiriyordu. Artik hepsi get_with_retry kullaniyor
    (bkz. .http_retry).
    """
    
    name = "pubmed"
    source_type = "academic"
    
    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    ABSTRACT_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    
    def __init__(self, timeout: float = 30.0, user_agent: str = "AriKaynak/2.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent
    
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.timeout)
        headers = {"User-Agent": self.user_agent}
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            # Step 1: Search for IDs
            ids = await self._search_ids(client, query, limit)
            if not ids:
                return []
            
            # Step 2: Fetch summaries (metadata)
            summaries = await self._fetch_summaries(client, ids)
            
            # Step 3: Fetch abstracts (passages)
            passages = await self._fetch_abstracts(client, ids)
            
            # Step 4: Combine metadata + passage
            return self._build_results(ids, summaries, passages)
    
    async def _search_ids(self, client: httpx.AsyncClient, query: str, limit: int) -> list[str]:
        try:
            resp = await get_with_retry(client, self.SEARCH_URL, agent_name=self.name, params={
                "db": "pubmed",
                "term": query,
                "retmax": limit,
                "retmode": "json",
            })
            return resp.json().get("esearchresult", {}).get("idlist", [])
        except Exception as e:
            logger.warning(f"PubMed search failed: {e}")
            return []
    
    async def _fetch_summaries(self, client: httpx.AsyncClient, ids: list[str]) -> dict[str, dict]:
        try:
            resp = await get_with_retry(client, self.SUMMARY_URL, agent_name=self.name, params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            })
            return resp.json().get("result", {})
        except Exception as e:
            logger.warning(f"PubMed summary fetch failed: {e}")
            return {}
    
    async def _fetch_abstracts(self, client: httpx.AsyncClient, ids: list[str]) -> dict[str, str]:
        passages: dict[str, str] = {}
        try:
            resp = await get_with_retry(client, self.ABSTRACT_URL, agent_name=self.name, params={
                "db": "pubmed",
                "id": ",".join(ids),
                "rettype": "abstract",
                "retmode": "xml",
            })
            root = ET.fromstring(resp.text)
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                if pmid_el is None:
                    continue
                pmid = pmid_el.text or ""
                texts = []
                for abs_el in article.findall(".//AbstractText"):
                    label = abs_el.get("Label", "")
                    text = "".join(abs_el.itertext()).strip()
                    texts.append(f"{label}: {text}" if label else text)
                if texts:
                    passages[pmid] = "\n".join(texts)
        except Exception as e:
            logger.warning(f"PubMed abstract fetch failed: {e}")
        return passages
    
    def _build_results(
        self,
        ids: list[str],
        summaries: dict[str, dict],
        passages: dict[str, str],
    ) -> list[dict[str, Any]]:
        results = []
        for pmid in ids:
            info = summaries.get(pmid, {})
            title = info.get("title", f"PubMed record {pmid}")
            authors = info.get("authors", [])
            first_author = authors[0].get("name", "") if authors else ""
            source = info.get("source", "")
            pub_date = info.get("pubdate", "")
            doi = None
            for aid in info.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = aid.get("value")
                    break
            year = None
            if pub_date:
                try:
                    year = int(pub_date.split()[0])
                except (ValueError, IndexError):
                    pass
            
            results.append({
                "source": self.name,
                "pmid": pmid,
                "title": title,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "first_author": first_author,
                "journal": source,
                "year": year,
                "doi": doi,
                "passage": passages.get(pmid, ""),
                "source_type": self.source_type,
            })
        return results
