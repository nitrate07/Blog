"""Core types — the single source of truth for all data models.

Includes:
- Claim, Source, Passage, Evidence, Verdict
- VerificationHistory, VerificationRecord
- Contradiction, SourceQuality
- PassageVerification, MethodologicalEvidence
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    PRIMARY = "primary"           # RCTs, clinical trials
    SECONDARY = "secondary"       # Reviews, meta-analyses
    TERTIARY = "tertiary"         # Guidelines, government reports
    UNKNOWN = "unknown"


class StudyDesign(str, Enum):
    """Methodological hierarchy of evidence."""
    SYSTEMATIC_REVIEW_META = "systematic_review_meta_analysis"
    RCT = "randomized_controlled_trial"
    COHORT = "cohort_study"
    CASE_CONTROL = "case_control_study"
    CROSS_SECTIONAL = "cross_sectional_study"
    CASE_REPORT = "case_report"
    EXPERT_OPINION = "expert_opinion"
    UNKNOWN = "unknown"


class ContradictionType(str, Enum):
    DIRECT = "direct"           # Same claim, opposite verdicts
    METHODOLOGICAL = "methodological"  # Different study designs
    POPULATION = "population"   # Different populations studied
    TEMPORAL = "temporal"       # Different time periods
    PARTIAL = "partial"         # Overlapping but not identical


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
    journal: str | None = None
    impact_factor: float | None = None
    study_design: StudyDesign = StudyDesign.UNKNOWN
    authors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "source_type": self.source_type.value,
            "doi": self.doi,
            "pmid": self.pmid,
            "published_year": self.published_year,
            "journal": self.journal,
            "impact_factor": self.impact_factor,
            "study_design": self.study_design.value,
            "authors": self.authors,
        }


@dataclass
class Passage:
    id: str
    text: str
    source_id: str
    relevance: float
    content_hash: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    verified: bool = False
    verification_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source_id": self.source_id,
            "relevance": self.relevance,
            "content_hash": self.content_hash,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "verified": self.verified,
            "verification_url": self.verification_url,
        }


@dataclass
class PassageVerification:
    """Result of verifying a passage against the original source."""
    passage_id: str
    source_url: str
    verified: bool
    original_text: str | None = None
    similarity_score: float | None = None
    verification_method: str = "url_match"
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "passage_id": self.passage_id,
            "source_url": self.source_url,
            "verified": self.verified,
            "original_text": self.original_text,
            "similarity_score": self.similarity_score,
            "verification_method": self.verification_method,
            "verified_at": self.verified_at,
        }


@dataclass
class MethodologicalEvidence:
    """Methodological assessment of a source."""
    source_id: str
    study_design: StudyDesign
    sample_size: int | None = None
    bias_risk: str | None = None  # low, moderate, high
    evidence_level: int | None = None  # 1-5 (Oxford hierarchy)
    strengths: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "study_design": self.study_design.value,
            "sample_size": self.sample_size,
            "bias_risk": self.bias_risk,
            "evidence_level": self.evidence_level,
            "strengths": self.strengths,
            "limitations": self.limitations,
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
    methodological_evidence: list[MethodologicalEvidence] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)
    contradicting_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "passages": [p.to_dict() for p in self.passages],
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "rating_value": self.rating_value,
            "rating_explanation": self.rating_explanation,
            "methodological_evidence": [m.to_dict() for m in self.methodological_evidence],
            "supporting_sources": self.supporting_sources,
            "contradicting_sources": self.contradicting_sources,
        }


@dataclass
class Contradiction:
    """Detected contradiction between sources."""
    id: str
    source1_id: str
    source2_id: str
    claim_id: str
    contradiction_type: ContradictionType
    description: str
    source1_verdict: str
    source2_verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source1_id": self.source1_id,
            "source2_id": self.source2_id,
            "claim_id": self.claim_id,
            "contradiction_type": self.contradiction_type.value,
            "description": self.description,
            "source1_verdict": self.source1_verdict,
            "source2_verdict": self.source2_verdict,
        }


@dataclass
class VerificationRecord:
    """Record of a single verification run."""
    id: str
    query: str
    claim_text: str
    verdict: str
    confidence: float
    rating_value: int
    sources_count: int
    passages_count: int
    contradictions_count: int
    created_at: str
    steps: list[dict[str, Any]]
    cited_response: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "claim_text": self.claim_text,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rating_value": self.rating_value,
            "sources_count": self.sources_count,
            "passages_count": self.passages_count,
            "contradictions_count": self.contradictions_count,
            "created_at": self.created_at,
            "steps": self.steps,
            "cited_response": self.cited_response,
        }


@dataclass
class VerificationChain:
    claim: Claim
    evidence: Evidence
    sources: list[Source]
    contradictions: list[Contradiction] = field(default_factory=list)
    verification_record: VerificationRecord | None = None


# ---------------------------------------------------------------------------
# Source Quality Rankings
# ---------------------------------------------------------------------------

# Journal impact factors (approximate 2024 values)
JOURNAL_IMPACT_FACTORS: dict[str, float] = {
    "new england journal of medicine": 158.5,
    "nejm": 158.5,
    "the lancet": 168.9,
    "lancet": 168.9,
    "jama": 120.7,
    "jama - journal of the american medical association": 120.7,
    "bmj": 105.0,
    "bmj (clinical research ed.)": 105.0,
    "nature medicine": 82.9,
    "nature": 64.8,
    "the british medical journal": 105.0,
    "cochrane database of systematic reviews": 8.8,
    "pubmed": 0.0,
    "world health organization": 0.0,
    "cdc": 0.0,
    "fda": 0.0,
    "ema": 0.0,
    "nice": 0.0,
    "aha": 0.0,
    "american heart association": 0.0,
    "esc": 0.0,
    "european society of cardiology": 0.0,
    "tuseb": 0.0,
    "türkisha sağlık enstitüleri başkanlığı": 0.0,
}

# Study design evidence levels (Oxford hierarchy)
STUDY_DESIGN_LEVELS: dict[StudyDesign, int] = {
    StudyDesign.SYSTEMATIC_REVIEW_META: 1,
    StudyDesign.RCT: 2,
    StudyDesign.COHORT: 3,
    StudyDesign.CASE_CONTROL: 4,
    StudyDesign.CROSS_SECTIONAL: 5,
    StudyDesign.CASE_REPORT: 5,
    StudyDesign.EXPERT_OPINION: 5,
    StudyDesign.UNKNOWN: 6,
}

# Source quality weights
SOURCE_QUALITY_WEIGHTS: dict[SourceType, float] = {
    SourceType.PRIMARY: 1.0,
    SourceType.SECONDARY: 0.75,
    SourceType.TERTIARY: 0.35,
    SourceType.UNKNOWN: 0.5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """SHA-256 hash of text for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def make_verification_id() -> str:
    """Generate a unique verification ID."""
    return f"verif::{uuid.uuid4().hex[:12]}"


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


def make_contradiction_id(source1_id: str, source2_id: str) -> str:
    """Canonical contradiction ID."""
    return f"contradiction::{source1_id}::{source2_id}"


def get_journal_impact_factor(journal_name: str) -> float:
    """Get impact factor for a journal."""
    if not journal_name:
        return 0.0
    name_lower = journal_name.lower()
    for key, value in JOURNAL_IMPACT_FACTORS.items():
        if key in name_lower or name_lower in key:
            return value
    return 0.0


def get_study_design_level(design: StudyDesign) -> int:
    """Get evidence level for a study design (1=highest)."""
    return STUDY_DESIGN_LEVELS.get(design, 6)


def calculate_source_quality_score(
    source_type: SourceType,
    study_design: StudyDesign,
    impact_factor: float,
    published_year: int | None,
) -> float:
    """Calculate overall source quality score (0.0 - 1.0)."""
    base_score = SOURCE_QUALITY_WEIGHTS.get(source_type, 0.5)
    
    # Study design bonus (0.0 - 0.3)
    design_level = get_study_design_level(study_design)
    design_bonus = max(0.0, 0.3 * (6 - design_level) / 5)
    
    # Impact factor bonus (0.0 - 0.2)
    if impact_factor > 100:
        if_bonus = 0.2
    elif impact_factor > 50:
        if_bonus = 0.15
    elif impact_factor > 20:
        if_bonus = 0.1
    elif impact_factor > 5:
        if_bonus = 0.05
    else:
        if_bonus = 0.0
    
    # Recency bonus (0.0 - 0.1)
    recency_bonus = 0.0
    if published_year:
        if published_year >= 2024:
            recency_bonus = 0.1
        elif published_year >= 2020:
            recency_bonus = 0.08
        elif published_year >= 2015:
            recency_bonus = 0.05
    
    return round(min(1.0, base_score + design_bonus + if_bonus + recency_bonus), 3)
