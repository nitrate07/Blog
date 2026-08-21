"""CDC Agent — Crossref uzerinden CDC'nin MMWR yayinlari.

search.cdc.gov JSON ucu HTML dondurmeye basladigi icin artik CDC'nin
hakemli yayini MMWR, Crossref meta verisi üzerinden taranir.
"""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class CDCAgent(CrossrefJournalAgent):
    name = "cdc"
    source_type = "government"
    organization = "US Centers for Disease Control and Prevention"
    CONTAINER_TITLES = (
        "Morbidity and Mortality Weekly Report",
        "Preventing Chronic Disease",
        "Emerging Infectious Diseases",
    )
