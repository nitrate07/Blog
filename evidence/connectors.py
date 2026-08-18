"""Provider-agnostic academic source discovery (metadata only, never evidence by itself)."""

from __future__ import annotations

from typing import Protocol
import httpx

from .config import Settings, settings
from .models import EvidenceSearchResult, SourceQuality


class EvidenceSearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[EvidenceSearchResult]:
        """Return citable metadata. Callers must still retrieve and compare source text."""


class CrossrefProvider:
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    async def search(self, query: str, limit: int) -> list[EvidenceSearchResult]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.config.user_agent}) as client:
            response = await client.get(self.endpoint, params={"query": query, "rows": limit, "select": "DOI,title,published,URL,type"})
            response.raise_for_status()
        return self.parse(response.json())

    @staticmethod
    def parse(payload: dict) -> list[EvidenceSearchResult]:
        results = []
        for item in payload.get("message", {}).get("items", []):
            doi = item.get("DOI")
            title = next(iter(item.get("title", [])), None)
            url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)
            if not title or not url:
                continue
            dates = item.get("published", {}).get("date-parts", [[]])
            year = dates[0][0] if dates and dates[0] else None
            results.append(EvidenceSearchResult(title=title, url=url, provider="crossref", doi=doi, published_year=year, source_type=SourceQuality.UNKNOWN))
        return results


class PubMedProvider:
    name = "pubmed"
    endpoint = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    async def search(self, query: str, limit: int) -> list[EvidenceSearchResult]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.config.user_agent}) as client:
            response = await client.get(self.endpoint, params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"})
            response.raise_for_status()
        ids = response.json().get("esearchresult", {}).get("idlist", [])
        return [EvidenceSearchResult(title=f"PubMed record {pmid}", url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", provider="pubmed", pmid=pmid, source_type=SourceQuality.UNKNOWN) for pmid in ids]


class EvidenceCatalog:
    """Combines independent discovery providers and removes duplicate records."""
    def __init__(self, providers: list[EvidenceSearchProvider] | None = None) -> None:
        self.providers = providers or [PubMedProvider(), CrossrefProvider()]

    async def search(self, query: str, limit: int = 5) -> list[EvidenceSearchResult]:
        results: list[EvidenceSearchResult] = []
        # Individual provider failure must not make a multi-provider search fail closed.
        for provider in self.providers:
            try:
                results.extend(await provider.search(query, limit))
            except (httpx.HTTPError, ValueError):
                continue
        unique: dict[str, EvidenceSearchResult] = {}
        for result in results:
            key = result.doi.lower() if result.doi else result.url.rstrip("/").lower()
            unique.setdefault(key, result)
        return list(unique.values())[:limit]
