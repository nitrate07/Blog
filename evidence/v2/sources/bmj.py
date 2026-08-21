"""BMJ Agent — Crossref uzerinden BMJ ailesi aramasi."""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class BMJAgent(CrossrefJournalAgent):
    name = "bmj"
    source_type = "academic"
    organization = "The BMJ"
    CONTAINER_TITLES = (
        "BMJ",
        "BMJ Evidence-Based Medicine",
        "BMJ Nutrition Prevention & Health",
        "BMJ Open",
    )
