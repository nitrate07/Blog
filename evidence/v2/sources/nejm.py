"""NEJM Agent — Crossref uzerinden New England Journal of Medicine aramasi."""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class NEJMAgent(CrossrefJournalAgent):
    name = "nejm"
    source_type = "academic"
    organization = "New England Journal of Medicine"
    CONTAINER_TITLES = ("New England Journal of Medicine", "NEJM Evidence")
