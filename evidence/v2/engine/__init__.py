"""Evidence Engine — the hakem (referee) that judges evidence.

Includes:
- DeterministicEngine: Main engine
- ContradictionDetector: Finds conflicting evidence
- PassageVerifier: Verifies passages against sources
- SourceQualityRanker: Ranks sources by quality
"""

from .engine import DeterministicEngine
from .contradiction import ContradictionDetector
from .verifier import PassageVerifier

__all__ = [
    "DeterministicEngine",
    "ContradictionDetector",
    "PassageVerifier",
]
