"""Source agents — all 11 evidence sources in one module."""

from .pubmed import PubMedAgent
from .crossref import CrossrefAgent
from .archive import ArchiveAgent
from .who import WHOAgent
from .cdc import CDCAgent
from .ecdc import ECDCAgent
from .cochrane import CochraneAgent
from .clinicaltrials import ClinicalTrialsAgent
from .fda import FDAAgent
from .ema import EMAAgent
from .google_scholar import GoogleScholarAgent
from .orchestrator import SourceOrchestrator

ALL_AGENTS = [
    PubMedAgent,
    CrossrefAgent,
    ArchiveAgent,
    WHOAgent,
    CDCAgent,
    ECDCAgent,
    CochraneAgent,
    ClinicalTrialsAgent,
    FDAAgent,
    EMAAgent,
    GoogleScholarAgent,
]

__all__ = [
    "PubMedAgent",
    "CrossrefAgent",
    "ArchiveAgent",
    "WHOAgent",
    "CDCAgent",
    "ECDCAgent",
    "CochraneAgent",
    "ClinicalTrialsAgent",
    "FDAAgent",
    "EMAAgent",
    "GoogleScholarAgent",
    "SourceOrchestrator",
    "ALL_AGENTS",
]
