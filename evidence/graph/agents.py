"""Evidence search agents — specialized searchers for each evidence source.

Each agent is a focused searcher for one source type.
EvidenceSearchAgent orchestrates all agents and combines results.

PRINCIPLE: Agents discover and retrieve metadata/evidence from sources.
They do NOT interpret or judge — that's the Evidence Engine's job.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ..config import Settings, settings
from ..models import EvidenceSearchResult, SourceQuality
from ..rag.retriever import ArticleRetriever, RetrievalResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base agent protocol
# ---------------------------------------------------------------------------

class SearchAgent(Protocol):
    name: str
    source_type: str

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search this source and return structured results."""
        ...


# ---------------------------------------------------------------------------
# PubMed Agent
# ---------------------------------------------------------------------------

class PubMedAgent:
    """Searches PubMed for medical and scientific evidence.
    
    Returns: metadata + passage (abstract).
    Does NOT judge — Evidence Engine decides the verdict.
    """
    name = "pubmed"
    source_type = "academic"
    endpoint = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    summary_endpoint = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    abstract_endpoint = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.config.user_agent}) as client:
            # Step 1: Search for IDs
            search_resp = await client.get(self.endpoint, params={
                "db": "pubmed",
                "term": query,
                "retmax": limit,
                "retmode": "json",
            })
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            # Step 2: Fetch summaries for rich metadata
            summary_resp = await client.get(self.summary_endpoint, params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            })
            summary_resp.raise_for_status()
            summaries = summary_resp.json().get("result", {})

            # Step 3: Fetch abstracts (passages) in XML
            passages: dict[str, str] = {}
            try:
                abstract_resp = await client.get(self.abstract_endpoint, params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "rettype": "abstract",
                    "retmode": "xml",
                })
                abstract_resp.raise_for_status()
                root = ET.fromstring(abstract_resp.text)
                for article in root.findall(".//PubmedArticle"):
                    pmid_el = article.find(".//PMID")
                    if pmid_el is None:
                        continue
                    pmid = pmid_el.text or ""
                    abstract_texts = []
                    for abs_el in article.findall(".//AbstractText"):
                        label = abs_el.get("Label", "")
                        text = "".join(abs_el.itertext()).strip()
                        if label:
                            abstract_texts.append(f"{label}: {text}")
                        else:
                            abstract_texts.append(text)
                    if abstract_texts:
                        passages[pmid] = "\n".join(abstract_texts)
            except Exception as e:
                logger.warning(f"PubMed abstract fetch failed: {e}")

        results: list[dict[str, Any]] = []
        for pmid in ids:
            info = summaries.get(pmid, {})
            title = info.get("title", f"PubMed record {pmid}")
            authors = info.get("authors", [])
            first_author = authors[0].get("name", "") if authors else ""
            source = info.get("source", "")
            pub_date = info.get("pubdate", "")
            doi = None
            for article_id in info.get("articleids", []):
                if article_id.get("idtype") == "doi":
                    doi = article_id.get("value")
                    break
            year = None
            if pub_date:
                try:
                    year = int(pub_date.split()[0])
                except (ValueError, IndexError):
                    pass
            results.append({
                "source": "pubmed",
                "pmid": pmid,
                "title": title,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "first_author": first_author,
                "journal": source,
                "year": year,
                "doi": doi,
                "passage": passages.get(pmid, ""),
                "source_type": "academic",
            })
        return results


# ---------------------------------------------------------------------------
# Crossref Agent
# ---------------------------------------------------------------------------

class CrossrefAgent:
    """Searches Crossref for academic papers and DOIs."""
    name = "crossref"
    source_type = "academic"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.config.user_agent}) as client:
            response = await client.get(self.endpoint, params={
                "query": query,
                "rows": limit,
                "select": "DOI,title,published,URL,type,author,container-title",
            })
            response.raise_for_status()

        items = response.json().get("message", {}).get("items", [])
        results: list[dict[str, Any]] = []
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
            results.append({
                "source": "crossref",
                "doi": doi,
                "title": title,
                "url": url,
                "first_author": first_author,
                "journal": journal,
                "year": year,
                "source_type": "academic",
            })
        return results


# ---------------------------------------------------------------------------
# Archive Agent (Arı Kaynak articles via RAG)
# ---------------------------------------------------------------------------

class ArchiveAgent:
    """Searches existing Arı Kaynak articles via RAG retrieval."""
    name = "archive"
    source_type = "primary"

    def __init__(self, retriever: ArticleRetriever) -> None:
        self.retriever = retriever

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        try:
            results = self.retriever.retrieve(query=query, n_results=limit)
        except Exception as e:
            logger.warning(f"Archive search failed: {e}")
            return []
        return [
            {
                "source": "archive",
                "article_id": r.article_id,
                "title": r.title,
                "url": r.source_url,
                "verdict": r.verdict,
                "rating_value": r.rating_value,
                "distance": r.distance,
                "category": r.category,
                "source_type": "primary",
            }
            for r in results
        ]


# ---------------------------------------------------------------------------
# Combined Evidence Search Agent
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    agent_name: str
    source_type: str
    results: list[dict[str, Any]]
    success: bool
    error: str | None = None


@dataclass
class CombinedSearchResult:
    query: str
    agent_results: list[dict[str, Any]]
    total_results: int
    pubmed_count: int
    crossref_count: int
    archive_count: int
    agents_succeeded: int
    agents_failed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "agent_results": self.agent_results,
            "total_results": self.total_results,
            "pubmed_count": self.pubmed_count,
            "crossref_count": self.crossref_count,
            "archive_count": self.archive_count,
            "agents_succeeded": self.agents_succeeded,
            "agents_failed": self.agents_failed,
        }


class EvidenceSearchAgent:
    """Orchestrates all search agents in parallel and combines results.
    
    Each agent searches its own source independently.
    Results are combined, deduplicated, and returned.
    No interpretation — just discovery and retrieval.
    """

    def __init__(
        self,
        retriever: ArticleRetriever,
        config: Settings | None = None,
    ) -> None:
        self.config = config or settings
        self.agents: list[SearchAgent] = [
            PubMedAgent(self.config),
            CrossrefAgent(self.config),
            ArchiveAgent(retriever),
        ]

    async def search(self, query: str, limit_per_agent: int = 5) -> CombinedSearchResult:
        """Run all agents in parallel and combine results."""
        tasks = [agent.search(query, limit_per_agent) for agent in self.agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        pubmed_count = 0
        crossref_count = 0
        archive_count = 0

        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                logger.warning(f"Agent {agent.name} failed: {result}")
                failed += 1
                continue
            succeeded += 1
            for item in result:
                item["agent"] = agent.name
                agent_results.append(item)
                if agent.name == "pubmed":
                    pubmed_count += 1
                elif agent.name == "crossref":
                    crossref_count += 1
                elif agent.name == "archive":
                    archive_count += 1

        # Deduplicate by URL
        seen: dict[str, dict[str, Any]] = {}
        deduplicated: list[dict[str, Any]] = []
        for item in agent_results:
            url = item.get("url", "").rstrip("/").lower()
            if url and url not in seen:
                seen[url] = item
                deduplicated.append(item)
            elif not url:
                deduplicated.append(item)

        return CombinedSearchResult(
            query=query,
            agent_results=deduplicated,
            total_results=len(deduplicated),
            pubmed_count=pubmed_count,
            crossref_count=crossref_count,
            archive_count=archive_count,
            agents_succeeded=succeeded,
            agents_failed=failed,
        )
