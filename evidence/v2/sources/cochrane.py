"""Cochrane Agent — Crossref uzerinden Cochrane sistematik derlemeleri.

api.cochrane.com adresi cozumlenmiyordu (DNS); Cochrane Database of
Systematic Reviews kayitlari Crossref meta verisinde mevcut ve kararli.
"""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class CochraneAgent(CrossrefJournalAgent):
    name = "cochrane"
    source_type = "systematic_review"
    organization = "Cochrane Collaboration"
    CONTAINER_TITLES = (
        "Cochrane Database of Systematic Reviews",
        "Evidence-based Child Health",
    )
