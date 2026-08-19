"""Core types — the single source of truth for all data models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    SUPPORTED = "supported"
    MOSTLY_SUPPORTED = "mostly_supported"
    PARTLY_SUPPORTED = "partly_supported"
    MISLEADING = "misleading"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class SourceType(str, Enum):
    PRIMARY = "primary"           # First-hand: clinical trials, RCTs
    SECONDARY = "secondary"       # Reviews, meta-analyses
    TERTIARY = "tertiary"         # Guidelines, government reports
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """SHA-256 hash of text for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def make_source_id(url: str) -> str:
    """Canonical source ID from URL."""
    return f"source::{url.rstrip('/').lower()}"


def make_passage_id(claim_id: str, index: int) -> str:
    """Canonical passage ID."""
    return f"passage::{claim_id}::{index}"


def make_evidence_id(claim_id: str) -> str:
    """Canonical evidence ID."""
    return f"evidence::{claim_id}"


def make_claim_id(text: str, prefix: str = "pipeline") -> str:
    """Canonical claim ID from text."""
    return f"claim::{prefix}::{hash(text) % 100000}"
