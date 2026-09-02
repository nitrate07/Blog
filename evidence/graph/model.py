"""Evidence Graph — core verification chain: claim → evidence → source → passage → verdict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    SUPPORTED = "supported"
    MOSTLY_SUPPORTED = "mostly_supported"
    PARTLY_SUPPORTED = "partly_supported"
    MISLEADING = "misleading"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class SourceType(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    UNKNOWN = "unknown"


@dataclass
class Claim:
    id: str
    text: str
    author: str
    category: str
    date_filed: str
    file_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "author": self.author,
            "category": self.category,
            "date_filed": self.date_filed,
            "file_number": self.file_number,
        }


@dataclass
class Source:
    id: str
    url: str
    title: str
    source_type: SourceType
    doi: str | None = None
    pmid: str | None = None
    published_year: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "source_type": self.source_type.value,
            "doi": self.doi,
            "pmid": self.pmid,
            "published_year": self.published_year,
        }


@dataclass
class Passage:
    id: str
    text: str
    source_id: str
    relevance: float
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source_id": self.source_id,
            "relevance": self.relevance,
            "content_hash": self.content_hash,
        }


@dataclass
class Evidence:
    id: str
    claim_id: str
    passages: list[Passage]
    verdict: Verdict
    confidence: float
    rating_value: int
    rating_explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "passages": [p.to_dict() for p in self.passages],
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "rating_value": self.rating_value,
            "rating_explanation": self.rating_explanation,
        }


@dataclass
class VerificationChain:
    claim: Claim
    evidence: Evidence
    sources: list[Source]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "evidence": self.evidence.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
        }
