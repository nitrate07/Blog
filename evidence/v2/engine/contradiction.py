"""Contradiction detection — finds conflicting evidence between sources."""

from __future__ import annotations

import logging
from typing import Any

from ..core.types import (
    Contradiction,
    ContradictionType,
    Source,
    make_contradiction_id,
)

logger = logging.getLogger(__name__)


class ContradictionDetector:
    """Detects contradictions between sources.
    
    Types of contradictions:
    - DIRECT: Same claim, opposite verdicts
    - METHODOLOGICAL: Different study designs
    - POPULATION: Different populations studied
    - TEMPORAL: Different time periods
    - PARTIAL: Overlapping but not identical
    """
    
    def detect(
        self,
        claim_id: str,
        sources: list[Source],
        matches: list[dict[str, Any]],
    ) -> list[Contradiction]:
        """Detect contradictions between sources."""
        contradictions: list[Contradiction] = []
        
        # Group matches by source
        source_matches: dict[str, list[dict]] = {}
        for m in matches:
            source_id = m.get("source_id", m.get("url", ""))
            if source_id not in source_matches:
                source_matches[source_id] = []
            source_matches[source_id].append(m)
        
        # Compare each pair of sources
        source_ids = list(source_matches.keys())
        for i, sid1 in enumerate(source_ids):
            for sid2 in source_ids[i + 1:]:
                contradiction = self._compare_sources(
                    claim_id, sid1, sid2,
                    source_matches[sid1], source_matches[sid2],
                )
                if contradiction:
                    contradictions.append(contradiction)
        
        return contradictions
    
    def _compare_sources(
        self,
        claim_id: str,
        source1_id: str,
        source2_id: str,
        matches1: list[dict],
        matches2: list[dict],
    ) -> Contradiction | None:
        """Compare two sources for contradictions."""
        if not matches1 or not matches2:
            return None
        
        # Get verdicts
        verdict1 = matches1[0].get("verdict")
        verdict2 = matches2[0].get("verdict")
        
        # Direct contradiction: opposite verdicts
        if verdict1 and verdict2:
            if self._are_opposite(verdict1, verdict2):
                return Contradiction(
                    id=make_contradiction_id(source1_id, source2_id),
                    source1_id=source1_id,
                    source2_id=source2_id,
                    claim_id=claim_id,
                    contradiction_type=ContradictionType.DIRECT,
                    description=f"Direct contradiction: {verdict1} vs {verdict2}",
                    source1_verdict=verdict1,
                    source2_verdict=verdict2,
                )
        
        # Methodological contradiction: different study designs
        design1 = matches1[0].get("study_design", "unknown")
        design2 = matches2[0].get("study_design", "unknown")
        if design1 != "unknown" and design2 != "unknown" and design1 != design2:
            if self._has_higher_evidence(design1, design2):
                return Contradiction(
                    id=make_contradiction_id(source1_id, source2_id),
                    source1_id=source1_id,
                    source2_id=source2_id,
                    claim_id=claim_id,
                    contradiction_type=ContradictionType.METHODOLOGICAL,
                    description=f"Methodological difference: {design1} vs {design2}",
                    source1_verdict=verdict1 or "unknown",
                    source2_verdict=verdict2 or "unknown",
                )
        
        return None
    
    def _are_opposite(self, verdict1: str, verdict2: str) -> bool:
        """Check if two verdicts are opposite."""
        opposites = {
            "supported": ["unsupported", "misleading"],
            "mostly_supported": ["unsupported", "misleading"],
            "unsupported": ["supported", "mostly_supported"],
            "misleading": ["supported", "mostly_supported"],
        }
        v1 = verdict1.lower().replace(" ", "_")
        v2 = verdict2.lower().replace(" ", "_")
        return v2 in opposites.get(v1, [])
    
    def _has_higher_evidence(self, design1: str, design2: str) -> bool:
        """Check if design1 has higher evidence than design2."""
        hierarchy = [
            "systematic_review_meta_analysis",
            "randomized_controlled_trial",
            "cohort_study",
            "case_control_study",
            "cross_sectional_study",
            "case_report",
            "expert_opinion",
            "unknown",
        ]
        try:
            idx1 = hierarchy.index(design1)
            idx2 = hierarchy.index(design2)
            return idx1 < idx2  # Lower index = higher evidence
        except ValueError:
            return False
