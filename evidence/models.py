"""Provider-independent public contract for evidence verification."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Verdict(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class SourceQuality(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    UNKNOWN = "unknown"


class SourceInput(BaseModel):
    url: HttpUrl


class VerificationRequest(BaseModel):
    claim: Annotated[str, Field(min_length=3, max_length=4_000)]
    sources: Annotated[list[SourceInput], Field(min_length=1, max_length=12)]
    context: Annotated[str | None, Field(default=None, max_length=4_000)] = None

    @field_validator("claim")
    @classmethod
    def claim_must_contain_words(cls, value: str) -> str:
        if len(value.split()) < 2:
            raise ValueError("claim must contain at least two words")
        return value.strip()


class EvidenceItem(BaseModel):
    source_url: str
    source_type: SourceQuality
    title: str | None = None
    passage: str
    relevance: Annotated[float, Field(ge=0, le=1)]
    source_content_hash: str | None = None


class EvidenceSearchResult(BaseModel):
    title: str
    url: HttpUrl
    provider: str
    doi: str | None = None
    pmid: str | None = None
    published_year: int | None = Field(default=None, ge=1000, le=3000)
    source_type: SourceQuality = SourceQuality.UNKNOWN


class EvidenceSearchResponse(BaseModel):
    query: str
    results: list[EvidenceSearchResult]


class VerificationResponse(BaseModel):
    verification_id: str | None = None
    verdict: Verdict
    confidence: Annotated[float, Field(ge=0, le=1)]
    claim: str
    evidence: list[EvidenceItem]
    source_quality: SourceQuality
    checked_at: datetime
    method: str = "evidence_verification"
