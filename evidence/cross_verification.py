"""Cross-verification: multi-source evidence discovery and consolidation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .connectors import CrossrefProvider, EvidenceCatalog, PubMedProvider
from .config import Settings, settings
from .models import EvidenceSearchResult
from .rag.retriever import ArticleRetriever, RetrievalResult

logger = logging.getLogger(__name__)


@dataclass
class CrossVerifySource:
    provider: str
    title: str
    url: str
    doi: str | None = None
    pmid: str | None = None
    published_year: int | None = None
    source_type: str = "unknown"
    relevance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "title": self.title,
            "url": self.url,
            "doi": self.doi,
            "pmid": self.pmid,
            "published_year": self.published_year,
            "source_type": self.source_type,
            "relevance": round(self.relevance, 3),
        }


@dataclass
class CrossVerifyResult:
    claim: str
    existing_articles: list[dict]
    academic_sources: list[dict]
    source_count: int
    pubmed_count: int
    crossref_count: int
    existing_count: int
    coverage_score: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "existing_articles": self.existing_articles,
            "academic_sources": self.academic_sources,
            "source_count": self.source_count,
            "pubmed_count": self.pubmed_count,
            "crossref_count": self.crossref_count,
            "existing_count": self.existing_count,
            "coverage_score": round(self.coverage_score, 3),
            "summary": self.summary,
        }


class CrossVerifier:
    def __init__(
        self,
        catalog: EvidenceCatalog | None = None,
        retriever: ArticleRetriever | None = None,
        config: Settings | None = None,
    ) -> None:
        self.config = config or settings
        self.catalog = catalog or EvidenceCatalog(
            providers=[PubMedProvider(self.config), CrossrefProvider(self.config)]
        )
        self.retriever = retriever

    async def verify(
        self,
        claim: str,
        academic_limit: int = 5,
        article_limit: int = 5,
    ) -> CrossVerifyResult:
        academic_task = self._search_academic(claim, academic_limit)
        article_task = self._search_articles(claim, article_limit)
        academic_results, article_results = await asyncio.gather(
            academic_task, article_task, return_exceptions=True
        )
        if isinstance(academic_results, Exception):
            logger.warning(f"Academic search failed: {academic_results}")
            academic_results = []
        if isinstance(article_results, Exception):
            logger.warning(f"Article search failed: {article_results}")
            article_results = []
        academic_sources = self._process_academic(academic_results)
        existing_articles = self._process_articles(article_results)
        source_count = len(academic_sources) + len(existing_articles)
        pubmed_count = sum(1 for s in academic_sources if s.provider == "pubmed")
        crossref_count = sum(1 for s in academic_sources if s.provider == "crossref")
        existing_count = len(existing_articles)
        coverage_score = self._compute_coverage(
            pubmed_count, crossref_count, existing_count
        )
        summary = self._build_summary(
            claim, pubmed_count, crossref_count, existing_count, coverage_score
        )
        return CrossVerifyResult(
            claim=claim,
            existing_articles=[a.to_dict() for a in existing_articles],
            academic_sources=[s.to_dict() for s in academic_sources],
            source_count=source_count,
            pubmed_count=pubmed_count,
            crossref_count=crossref_count,
            existing_count=existing_count,
            coverage_score=coverage_score,
            summary=summary,
        )

    async def _search_academic(
        self, claim: str, limit: int
    ) -> list[EvidenceSearchResult]:
        return await self.catalog.search(claim, limit=limit)

    async def _search_articles(
        self, claim: str, limit: int
    ) -> list[RetrievalResult]:
        if not self.retriever:
            return []
        return self.retriever.retrieve(query=claim, n_results=limit)

    def _process_academic(
        self, results: list[EvidenceSearchResult] | Exception
    ) -> list[CrossVerifySource]:
        if isinstance(results, Exception):
            return []
        sources: list[CrossVerifySource] = []
        for r in results:
            sources.append(CrossVerifySource(
                provider=r.provider,
                title=r.title,
                url=str(r.url),
                doi=r.doi,
                pmid=r.pmid,
                published_year=r.published_year,
                source_type=r.source_type.value,
                relevance=0.5,
            ))
        return sources

    def _process_articles(
        self, results: list[RetrievalResult] | Exception
    ) -> list[CrossVerifySource]:
        if isinstance(results, Exception):
            return []
        sources: list[CrossVerifySource] = []
        for r in results:
            sources.append(CrossVerifySource(
                provider="ari_kaynak",
                title=r.title,
                url=r.source_url,
                source_type="primary",
                relevance=1.0 - r.distance,
            ))
        return sources

    def _compute_coverage(
        self, pubmed: int, crossref: int, existing: int
    ) -> float:
        score = 0.0
        if pubmed > 0:
            score += 0.4
        if crossref > 0:
            score += 0.3
        if existing > 0:
            score += 0.3
        if pubmed >= 2:
            score = min(1.0, score + 0.1)
        if existing >= 2:
            score = min(1.0, score + 0.1)
        return score

    def _build_summary(
        self,
        claim: str,
        pubmed: int,
        crossref: int,
        existing: int,
        coverage: float,
    ) -> str:
        total = pubmed + crossref + existing
        if total == 0:
            return (
                f"No sources found for: '{claim[:100]}...'. "
                "Consider broadening the search query or checking manually."
            )
        parts: list[str] = []
        if existing > 0:
            parts.append(f"{existing} existing Arı Kaynak article(s)")
        if pubmed > 0:
            parts.append(f"{pubmed} PubMed record(s)")
        if crossref > 0:
            parts.append(f"{crossref} Crossref record(s)")
        sources_str = " + ".join(parts)
        confidence = (
            "high" if coverage >= 0.7
            else "moderate" if coverage >= 0.4
            else "low"
        )
        return (
            f"Found {total} source(s) for: '{claim[:100]}...' — "
            f"{sources_str}. "
            f"Coverage confidence: {confidence} ({coverage:.0%})."
        )
