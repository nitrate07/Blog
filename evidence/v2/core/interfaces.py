"""Interfaces — the contracts that all components must follow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# Source Agent Interface
# ---------------------------------------------------------------------------

class SourceAgent(ABC):
    """Every source agent must implement this interface.
    
    Agent responsibilities:
    1. Search the source
    2. Return metadata (title, url, doi, etc.)
    3. Extract passage (relevant text from source)
    4. Return metadata + passage
    
    Agent does NOT:
    - Judge whether evidence supports the claim
    - Generate verdicts or ratings
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this agent."""
        ...
    
    @property
    @abstractmethod
    def source_type(self) -> str:
        """Type of source (academic, government, etc.)."""
        ...
    
    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search the source and return results.
        
        Each result must contain:
        - source: str (agent name)
        - title: str
        - url: str
        - passage: str (relevant text extracted from source)
        - source_type: str
        
        Returns empty list if no results found.
        """
        ...


# ---------------------------------------------------------------------------
# Evidence Engine Interface
# ---------------------------------------------------------------------------

class EvidenceEngine(ABC):
    """The hakem (referee) — judges evidence, never generates it.
    
    Engine responsibilities:
    1. Combine evidence from all sources
    2. Score source quality
    3. Match claim against evidence passages
    4. Compute verdict and confidence
    
    Engine does NOT:
    - Call LLM APIs
    - Generate text
    - Make HTTP requests
    """
    
    @abstractmethod
    def judge(
        self,
        claim: str,
        archive: list[dict[str, Any]],
        external: list[dict[str, Any]],
        health_orgs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Judge the claim against all evidence.
        
        Returns:
            {
                "verdict": str,
                "confidence": float,
                "rating_value": int,
                "matches": list[dict],
                "evidence_items": list[dict],
            }
        """
        ...
