"""Deterministic Evidence Engine — the hakem (referee).

PRINCIPLE: This engine is deterministic. No LLM involvement.
It processes, scores, and judges evidence based on:
- Source quality (primary > secondary > tertiary)
- Recency (newer sources score higher)
- Text overlap (claim words vs evidence words)
- Archive verdict (if available, strong signal)
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.interfaces import EvidenceEngine
from ..core.types import SourceType, Verdict

logger = logging.getLogger(__name__)

# Source quality scores
SOURCE_QUALITY: dict[SourceType, float] = {
    SourceType.PRIMARY: 1.0,
    SourceType.SECONDARY: 0.75,
    SourceType.TERTIARY: 0.35,
    SourceType.UNKNOWN: 0.5,
}

# Map string source_type to SourceType enum
SOURCE_TYPE_MAP: dict[str, SourceType] = {
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


class DeterministicEngine(EvidenceEngine):
    """The hakem: combines evidence, scores, matches, computes verdict.
    
    This is deterministic. No LLM involvement.
    """
    
    def judge(
        self,
        claim: str,
        archive: list[dict[str, Any]],
        external: list[dict[str, Any]],
        health_orgs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Judge the claim against all evidence."""
        # Step 1: Combine all evidence
        evidence_items = self._combine_evidence(archive, external, health_orgs)
        
        # Step 2: Score sources
        scored = self._score_sources(evidence_items)
        
        # Step 3: Match claim against evidence
        matches = self._match_claim_evidence(claim, scored)
        
        # Step 4: Compute verdict
        verdict, confidence, rating = self._compute_verdict(matches)
        
        return {
            "evidence_items": scored,
            "matches": matches,
            "verdict": verdict,
            "confidence": confidence,
            "rating_value": rating,
        }
    
    def _combine_evidence(
        self,
        archive: list[dict[str, Any]],
        external: list[dict[str, Any]],
        health_orgs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Combine evidence from all sources into a single list."""
        combined: list[dict[str, Any]] = []
        
        # Archive results (RAG)
        for r in archive:
            combined.append({
                "source": "archive",
                "title": r.get("title", ""),
                "url": r.get("source_url", r.get("url", "")),
                "text": r.get("text", ""),
                "verdict": r.get("verdict"),
                "rating_value": r.get("rating_value"),
                "distance": r.get("distance"),
                "source_type": "primary",
            })
        
        # External results (PubMed, Crossref)
        for s in external:
            combined.append({
                "source": "external",
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "text": s.get("passage", ""),
                "verdict": None,
                "rating_value": None,
                "distance": None,
                "source_type": s.get("source_type", "unknown"),
                "doi": s.get("doi"),
                "pmid": s.get("pmid"),
                "published_year": s.get("year"),
            })
        
        # Health org results
        for h in health_orgs:
            combined.append({
                "source": "health_org",
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "text": h.get("passage", ""),
                "verdict": None,
                "rating_value": None,
                "distance": None,
                "source_type": h.get("source_type", "international_organization"),
                "organization": h.get("organization", ""),
            })
        
        return combined
    
    def _score_sources(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score each evidence item based on source quality and recency."""
        for item in evidence:
            st_str = item.get("source_type", "unknown")
            source_type = SOURCE_TYPE_MAP.get(st_str, SourceType.UNKNOWN)
            quality_score = SOURCE_QUALITY.get(source_type, 0.5)
            
            recency_bonus = 0.0
            year = item.get("published_year")
            if year and year >= 2020:
                recency_bonus = 0.1
            
            item["quality_score"] = round(min(1.0, quality_score + recency_bonus), 3)
        
        evidence.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        return evidence
    
    def _match_claim_evidence(self, claim: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Match claim words against evidence text/title."""
        claim_words = set(claim.lower().split())
        matches: list[dict[str, Any]] = []
        
        for item in evidence:
            text = (item.get("text", "") + " " + item.get("title", "")).lower()
            if not text:
                matches.append({**item, "relevance": 0.3, "match_type": "metadata"})
                continue
            
            text_words = set(text.split())
            overlap = len(claim_words & text_words) / max(len(claim_words), 1)
            matches.append({**item, "relevance": round(min(1.0, overlap * 2), 3), "match_type": "text"})
        
        matches.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return matches
    
    def _compute_verdict(self, matches: list[dict[str, Any]]) -> tuple[str, float, int]:
        """Compute verdict from matches."""
        if not matches:
            return "unverified", 0.0, 0
        
        # Check archive matches first (strongest signal)
        archive_matches = [m for m in matches if m.get("source") == "archive"]
        if archive_matches:
            best = archive_matches[0]
            verdict_str = best.get("verdict", "unverified")
            rating = best.get("rating_value", 0)
            confidence = max(0.3, 1.0 - best.get("distance", 0.5))
            return verdict_str, confidence, rating or 0
        
        # No archive — use text overlap
        high_relevance = [m for m in matches if m.get("relevance", 0) >= 0.5]
        if len(high_relevance) >= 3:
            return "supported", 0.6, 4
        elif len(high_relevance) >= 2:
            return "mostly_supported", 0.5, 3
        elif high_relevance:
            return "partly_supported", 0.4, 2
        elif matches:
            return "partly_supported", 0.3, 1
        else:
            return "unverified", 0.0, 0
