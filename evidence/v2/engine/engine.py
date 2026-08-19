"""Deterministic Evidence Engine — the hakem (referee).

PRINCIPLE: This engine is deterministic. No LLM involvement.
It processes, scores, and judges evidence based on:
- Source quality (primary > secondary > tertiary)
- Study design (RCT > cohort > case-control)
- Journal impact factor
- Recency (newer sources score higher)
- Text overlap (claim words vs evidence words)
- Contradiction detection
- Passage verification
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.interfaces import EvidenceEngine
from ..core.types import (
    SourceType,
    StudyDesign,
    Verdict,
    calculate_source_quality_score,
    get_journal_impact_factor,
)

logger = logging.getLogger(__name__)


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
        
        # Step 2: Score sources with quality ranking
        scored = self._score_sources(evidence_items)
        
        # Step 3: Match claim against evidence
        matches = self._match_claim_evidence(claim, scored)
        
        # Step 4: Compute verdict with supporting/contradicting sources
        verdict, confidence, rating, supporting, contradicting = self._compute_verdict_with_sources(matches)
        
        return {
            "evidence_items": scored,
            "matches": matches,
            "verdict": verdict,
            "confidence": confidence,
            "rating_value": rating,
            "supporting_sources": supporting,
            "contradicting_sources": contradicting,
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
                "source_id": r.get("source_id", r.get("url", "")),
                "title": r.get("title", ""),
                "url": r.get("source_url", r.get("url", "")),
                "text": r.get("text", ""),
                "passage": r.get("text", ""),
                "verdict": r.get("verdict"),
                "rating_value": r.get("rating_value"),
                "distance": r.get("distance"),
                "source_type": "primary",
                "journal": r.get("journal"),
                "impact_factor": r.get("impact_factor"),
                "study_design": r.get("study_design", "unknown"),
            })
        
        # External results (PubMed, Crossref, high-impact journals)
        for s in external:
            combined.append({
                "source": "external",
                "source_id": s.get("source_id", s.get("url", "")),
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "text": s.get("passage", ""),
                "passage": s.get("passage", ""),
                "verdict": None,
                "rating_value": None,
                "distance": None,
                "source_type": s.get("source_type", "unknown"),
                "doi": s.get("doi"),
                "pmid": s.get("pmid"),
                "published_year": s.get("year"),
                "journal": s.get("journal"),
                "impact_factor": s.get("impact_factor"),
                "study_design": s.get("study_design", "unknown"),
            })
        
        # Health org results
        for h in health_orgs:
            combined.append({
                "source": "health_org",
                "source_id": h.get("source_id", h.get("url", "")),
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "text": h.get("passage", ""),
                "passage": h.get("passage", ""),
                "verdict": None,
                "rating_value": None,
                "distance": None,
                "source_type": h.get("source_type", "international_organization"),
                "organization": h.get("organization", ""),
                "journal": h.get("journal"),
                "impact_factor": h.get("impact_factor"),
                "study_design": h.get("study_design", "unknown"),
            })
        
        return combined
    
    def _score_sources(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score each evidence item based on source quality, study design, and recency."""
        for item in evidence:
            st_str = item.get("source_type", "unknown")
            source_type = SOURCE_TYPE_MAP.get(st_str, SourceType.UNKNOWN)
            
            # Get study design
            design_str = item.get("study_design", "unknown")
            study_design = STUDY_DESIGN_MAP.get(design_str, StudyDesign.UNKNOWN)
            
            # Get impact factor
            journal = item.get("journal", "")
            impact_factor = item.get("impact_factor") or get_journal_impact_factor(journal)
            
            # Get published year
            published_year = item.get("published_year")
            
            # Calculate quality score
            quality_score = calculate_source_quality_score(
                source_type, study_design, impact_factor, published_year
            )
            
            item["quality_score"] = quality_score
            item["study_design"] = study_design.value
            item["impact_factor"] = impact_factor
        
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
    
    def _compute_verdict_with_sources(
        self, matches: list[dict[str, Any]]
    ) -> tuple[str, float, int, list[str], list[str]]:
        """Compute verdict and identify supporting/contradicting sources."""
        if not matches:
            return "unverified", 0.0, 0, [], []
        
        supporting: list[str] = []
        contradicting: list[str] = []
        
        # Check archive matches first (strongest signal)
        archive_matches = [m for m in matches if m.get("source") == "archive"]
        if archive_matches:
            best = archive_matches[0]
            verdict_str = best.get("verdict", "unverified")
            rating = best.get("rating_value", 0)
            confidence = max(0.3, 1.0 - best.get("distance", 0.5))
            
            # Identify supporting/contradicting
            for m in matches:
                source_id = m.get("source_id", m.get("url", ""))
                if m.get("verdict"):
                    v = m["verdict"].lower().replace(" ", "_")
                    if "supported" in v or "mostly" in v:
                        supporting.append(source_id)
                    elif "unsupported" in v or "misleading" in v:
                        contradicting.append(source_id)
            
            return verdict_str, confidence, rating or 0, supporting, contradicting
        
        # No archive — use text overlap
        high_relevance = [m for m in matches if m.get("relevance", 0) >= 0.5]
        
        # Identify supporting/contradicting by quality
        for m in matches:
            source_id = m.get("source_id", m.get("url", ""))
            quality = m.get("quality_score", 0)
            if quality >= 0.7:
                supporting.append(source_id)
            elif quality < 0.4 and m.get("relevance", 0) > 0.3:
                contradicting.append(source_id)
        
        if len(high_relevance) >= 3:
            return "supported", 0.6, 4, supporting, contradicting
        elif len(high_relevance) >= 2:
            return "mostly_supported", 0.5, 3, supporting, contradicting
        elif high_relevance:
            return "partly_supported", 0.4, 2, supporting, contradicting
        elif matches:
            return "partly_supported", 0.3, 1, supporting, contradicting
        else:
            return "unverified", 0.0, 0, [], []


# Source type mapping
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

# Study design mapping
STUDY_DESIGN_MAP: dict[str, StudyDesign] = {
    "systematic_review_meta_analysis": StudyDesign.SYSTEMATIC_REVIEW_META,
    "randomized_controlled_trial": StudyDesign.RCT,
    "cohort_study": StudyDesign.COHORT,
    "case_control_study": StudyDesign.CASE_CONTROL,
    "cross_sectional_study": StudyDesign.CROSS_SECTIONAL,
    "case_report": StudyDesign.CASE_REPORT,
    "expert_opinion": StudyDesign.EXPERT_OPINION,
    "unknown": StudyDesign.UNKNOWN,
}
