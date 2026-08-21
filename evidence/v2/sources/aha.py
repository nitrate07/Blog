"""AHA Agent — Crossref uzerinden American Heart Association dergileri."""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class AHAAgent(CrossrefJournalAgent):
    name = "aha"
    source_type = "academic"
    organization = "American Heart Association journals"
    CONTAINER_TITLES = (
        "Circulation",
        "Hypertension",
        "Stroke",
        "Journal of the American Heart Association",
        "Circulation Research",
    )
