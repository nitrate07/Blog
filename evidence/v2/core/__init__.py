"""Core types and models for Evidence Verification Infrastructure."""

from .types import (
    Verdict,
    SourceType,
    Claim,
    Source,
    Passage,
    Evidence,
    VerificationChain,
)
from .interfaces import SourceAgent, EvidenceEngine

__all__ = [
    "Verdict",
    "SourceType",
    "Claim",
    "Source",
    "Passage",
    "Evidence",
    "VerificationChain",
    "SourceAgent",
    "EvidenceEngine",
]
