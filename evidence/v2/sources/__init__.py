"""Source agents — all evidence sources in one module."""

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
from .nejm import NEJMAgent
from .jama import JAMAAgent
from .lancet import LancetAgent
from .bmj import BMJAgent
from .nice import NICEAgent
from .aha import AHAAgent
from .esc import ESCAgent
from .tuseb import TUSEBAgent
from .orchestrator import SourceOrchestrator

# All available agents
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
    NEJMAgent,
    JAMAAgent,
    LancetAgent,
    BMJAgent,
    NICEAgent,
    AHAAgent,
    ESCAgent,
    TUSEBAgent,
]

# High-impact journal agents (for premium verification)
HIGH_IMPACT_AGENTS = [
    NEJMAgent,
    JAMAAgent,
    LancetAgent,
    BMJAgent,
]

# Guideline agents (for clinical practice)
GUIDELINE_AGENTS = [
    NICEAgent,
    AHAAgent,
    ESCAgent,
    TUSEBAgent,
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
    "NEJMAgent",
    "JAMAAgent",
    "LancetAgent",
    "BMJAgent",
    "NICEAgent",
    "AHAAgent",
    "ESCAgent",
    "TUSEBAgent",
    "SourceOrchestrator",
    "ALL_AGENTS",
    "HIGH_IMPACT_AGENTS",
    "GUIDELINE_AGENTS",
]
