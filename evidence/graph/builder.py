"""Evidence Graph builder — populates graph from articles, claims.json, and verification results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..connectors import EvidenceCatalog
from ..rag.parser import parse_all_articles
from .model import (
    Claim, Evidence, Passage, Source, SourceType, VerificationChain, Verdict,
)
from .store import EvidenceGraph

logger = logging.getLogger(__name__)

_VERDICT_MAP = {
    "supported": Verdict.SUPPORTED,
    "mostly supported": Verdict.MOSTLY_SUPPORTED,
    "mostly_supported": Verdict.MOSTLY_SUPPORTED,
    "partly supported": Verdict.PARTLY_SUPPORTED,
    "partly_supported": Verdict.PARTLY_SUPPORTED,
    "misleading": Verdict.MISLEADING,
    "unsupported": Verdict.UNSUPPORTED,
    "unverified": Verdict.UNVERIFIED,
}

_SOURCE_TYPE_MAP = {
    "primary": SourceType.PRIMARY,
    "secondary": SourceType.SECONDARY,
    "tertiary": SourceType.TERTIARY,
    "international_organization": SourceType.TERTIARY,
    "government": SourceType.TERTIARY,
    "academic": SourceType.SECONDARY,
    "systematic_review": SourceType.SECONDARY,
    "clinical_trial": SourceType.SECONDARY,
    "regulatory": SourceType.TERTIARY,
    "unknown": SourceType.UNKNOWN,
}


class GraphBuilder:
    def __init__(self, graph: EvidenceGraph, catalog: EvidenceCatalog | None = None) -> None:
        self.graph = graph
        self.catalog = catalog

    def build_from_claims_json(self, claims_json_path: str | Path) -> dict[str, int]:
        path = Path(claims_json_path)
        if not path.exists():
            return {"claims": 0, "sources": 0, "evidence": 0}
        data = json.loads(path.read_text(encoding="utf-8"))
        claims_data = data.get("claims", [])
        claims_added = 0
        sources_added = 0
        evidence_added = 0
        for entry in claims_data:
            file_number = entry.get("file_number", 0)
            claim_id = f"claim::{file_number}"
            verdict_str = entry.get("verdict", "").lower()
            verdict = _VERDICT_MAP.get(verdict_str, Verdict.UNVERIFIED)
            claim = Claim(
                id=claim_id,
                text=entry.get("claim_reviewed", entry.get("title", "")),
                author=entry.get("claim_author", "Unknown"),
                category=entry.get("category", "Health"),
                date_filed=entry.get("date_filed", ""),
                file_number=file_number,
            )
            self.graph.add_claim(claim)
            claims_added += 1
            source_url = entry.get("source_url", "")
            if source_url:
                source_id = f"source::{source_url.rstrip('/').lower()}"
                source = Source(
                    id=source_id,
                    url=source_url,
                    title=entry.get("title", ""),
                    source_type=SourceType.PRIMARY,
                )
                self.graph.add_source(source)
                sources_added += 1
                passage = Passage(
                    id=f"passage::{claim_id}::0",
                    text=entry.get("description", entry.get("rating_explanation", "")),
                    source_id=source_id,
                    relevance=0.8,
                )
                self.graph.add_passage(passage)
                evidence = Evidence(
                    id=f"evidence::{claim_id}",
                    claim_id=claim_id,
                    passages=[passage],
                    verdict=verdict,
                    confidence=entry.get("rating_value", 0) / 5.0,
                    rating_value=entry.get("rating_value", 0),
                    rating_explanation=entry.get("rating_explanation"),
                )
                self.graph.add_evidence(evidence)
                evidence_added += 1
        return {"claims": claims_added, "sources": sources_added, "evidence": evidence_added}

    def build_from_articles(
        self,
        articles_dir: str | Path,
        tr_dir: str | Path | None = None,
    ) -> dict[str, int]:
        articles_path = Path(articles_dir)
        tr_path = Path(tr_dir) if tr_dir else None
        chunks = parse_all_articles(articles_path, tr_path)
        claims_added = 0
        sources_added = 0
        evidence_added = 0
        seen_claims: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_type != "metadata":
                continue
            if chunk.article_id in seen_claims:
                continue
            seen_claims.add(chunk.article_id)
            claim_id = f"claim::{chunk.file_number}" if chunk.file_number else f"claim::{chunk.article_id}"
            if not self.graph.get_claim(claim_id):
                verdict_str = chunk.verdict.lower()
                verdict = _VERDICT_MAP.get(verdict_str, Verdict.UNVERIFIED)
                claim = Claim(
                    id=claim_id,
                    text=chunk.claim_reviewed or chunk.title,
                    author="Ahmet Ekmekci",
                    category=chunk.category,
                    date_filed="",
                    file_number=chunk.file_number,
                )
                self.graph.add_claim(claim)
                claims_added += 1
            source_url = chunk.source_url
            if source_url:
                source_id = f"source::{source_url.rstrip('/').lower()}"
                if not self.graph.get_source(source_id):
                    source = Source(
                        id=source_id,
                        url=source_url,
                        title=chunk.title,
                        source_type=SourceType.PRIMARY,
                    )
                    self.graph.add_source(source)
                    sources_added += 1
                existing_evidence = self.graph.get_evidence_for_claim(claim_id)
                if not existing_evidence:
                    passage = Passage(
                        id=f"passage::{claim_id}::0",
                        text=chunk.text[:2000],
                        source_id=source_id,
                        relevance=0.7,
                    )
                    self.graph.add_passage(passage)
                    verdict_str = chunk.verdict.lower()
                    verdict = _VERDICT_MAP.get(verdict_str, Verdict.UNVERIFIED)
                    evidence = Evidence(
                        id=f"evidence::{claim_id}",
                        claim_id=claim_id,
                        passages=[passage],
                        verdict=verdict,
                        confidence=chunk.rating_value / 5.0,
                        rating_value=chunk.rating_value,
                    )
                    self.graph.add_evidence(evidence)
                    evidence_added += 1
        return {"claims": claims_added, "sources": sources_added, "evidence": evidence_added}

    async def discover_sources(self, claim_text: str, limit: int = 5) -> list[Source]:
        if not self.catalog:
            return []
        try:
            results = await self.catalog.search(claim_text, limit=limit)
        except Exception as e:
            logger.warning(f"Source discovery failed: {e}")
            return []
        sources: list[Source] = []
        for r in results:
            source_id = f"source::{str(r.url).rstrip('/').lower()}"
            source = Source(
                id=source_id,
                url=str(r.url),
                title=r.title,
                source_type=_SOURCE_TYPE_MAP.get(r.source_type.value, SourceType.UNKNOWN),
                doi=r.doi,
                pmid=r.pmid,
                published_year=r.published_year,
            )
            self.graph.add_source(source)
            sources.append(source)
        return sources

    def add_verification_result(
        self,
        claim_id: str,
        verdict: Verdict,
        confidence: float,
        rating_value: int,
        passages: list[Passage] | None = None,
        rating_explanation: str | None = None,
    ) -> Evidence:
        evidence_id = f"evidence::{claim_id}::v{len(self.graph.get_evidence_for_claim(claim_id))}"
        evidence = Evidence(
            id=evidence_id,
            claim_id=claim_id,
            passages=passages or [],
            verdict=verdict,
            confidence=confidence,
            rating_value=rating_value,
            rating_explanation=rating_explanation,
        )
        self.graph.add_evidence(evidence)
        return evidence

    def get_full_chain(self, claim_id: str) -> VerificationChain | None:
        return self.graph.get_chain(claim_id)
