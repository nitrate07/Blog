"""Lancet Agent — Crossref uzerinden The Lancet ailesi aramasi."""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class LancetAgent(CrossrefJournalAgent):
    name = "lancet"
    source_type = "academic"
    organization = "The Lancet"
    CONTAINER_TITLES = (
        "The Lancet",
        "The Lancet Diabetes & Endocrinology",
        "The Lancet Public Health",
        "The Lancet Neurology",
    )
