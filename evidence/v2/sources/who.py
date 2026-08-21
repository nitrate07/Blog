"""WHO Agent — Crossref uzerinden WHO yayinlari.

IRIS REST API'si bot korumasi (403) dondurdugu icin WHO'nun hakemli
yayinlari Crossref meta verisi uzerinden taranir; kararli ve DOI'li.
"""

from __future__ import annotations

from .journal_base import CrossrefJournalAgent


class WHOAgent(CrossrefJournalAgent):
    name = "who"
    source_type = "international_organization"
    organization = "World Health Organization"
    CONTAINER_TITLES = (
        "Bulletin of the World Health Organization",
        "Weekly Epidemiological Record",
        "WHO Technical Report Series",
        "International Journal of Public Health",
    )
