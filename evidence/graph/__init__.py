"""Evidence Graph — unified data layer for claims, evidence, sources, passages, and verdicts."""

from .builder import GraphBuilder
from .model import Claim, Evidence, Passage, Source, SourceType, VerificationChain, Verdict
from .pipeline import (
    extract_claim,
    run_pipeline,
    discover_sources,
    evidence_engine,
    interpret_with_llm,
    update_graph,
)
from .store import EvidenceGraph

__all__ = [
    "EvidenceGraph",
    "GraphBuilder",
    "Claim",
    "Evidence",
    "Passage",
    "Source",
    "SourceType",
    "VerificationChain",
    "Verdict",
    "extract_claim",
    "run_pipeline",
    "discover_sources",
    "evidence_engine",
    "interpret_with_llm",
    "update_graph",
]
