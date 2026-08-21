import pytest

from evidence.connectors import CrossrefProvider, EvidenceCatalog, EuropePMCProvider
from evidence.models import EvidenceSearchResult


def test_crossref_metadata_is_normalised():
    results = CrossrefProvider.parse({"message": {"items": [{"DOI": "10.1000/example", "title": ["Evidence first"], "URL": "https://doi.org/10.1000/example", "published": {"date-parts": [[2026]]}}]}})
    assert results[0].doi == "10.1000/example"
    assert results[0].published_year == 2026
    assert results[0].provider == "crossref"


def test_europepmc_parse_prefers_pmid_url_and_keeps_metadata():
    payload = {"resultList": {"result": [
        {"title": "Coffee and cholesterol", "pmid": "12345", "doi": "10.1000/coffee", "pubYear": "2024"},
        {"title": "Preprint only", "doi": "10.1000/preprint", "pubYear": "2025"},
        {"title": None, "pmid": "99999"},
    ]}}
    results = EuropePMCProvider.parse(payload)
    assert [r.provider for r in results] == ["europepmc", "europepmc"]
    assert str(results[0].url) == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert results[0].pmid == "12345"
    assert results[0].doi == "10.1000/coffee"
    assert results[0].published_year == 2024
    assert str(results[1].url) == "https://doi.org/10.1000/preprint"
    assert results[1].pmid is None


def test_default_catalog_includes_europepmc():
    names = [p.name for p in EvidenceCatalog().providers]
    assert "europepmc" in names


class FakeProvider:
    name = "fake"

    async def search(self, query: str, limit: int):
        return [
            EvidenceSearchResult(title="First", url="https://doi.org/10.1/duplicate", provider="fake", doi="10.1/duplicate"),
            EvidenceSearchResult(title="Duplicate", url="https://doi.org/10.1/duplicate", provider="fake", doi="10.1/duplicate"),
        ]


@pytest.mark.asyncio
async def test_catalog_deduplicates_results():
    results = await EvidenceCatalog([FakeProvider()]).search("evidence", limit=5)
    assert len(results) == 1
