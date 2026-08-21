"""JAMA Agent — Crossref uzerinden JAMA ailesi dergileri aramasi."""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class JAMAAgent(CrossrefJournalAgent):
    name = "jama"
    source_type = "academic"
    organization = "Journal of the American Medical Association"
    CONTAINER_TITLES = (
        "JAMA",
        "JAMA Internal Medicine",
        "JAMA Cardiology",
        "JAMA Neurology",
        "JAMA Psychiatry",
        "JAMA Oncology",
    )
