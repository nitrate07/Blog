import pytest

from evidence.connectors import CrossrefProvider, EvidenceCatalog
from evidence.models import EvidenceSearchResult


def test_crossref_metadata_is_normalised():
    results = CrossrefProvider.parse({"message": {"items": [{"DOI": "10.1000/example", "title": ["Evidence first"], "URL": "https://doi.org/10.1000/example", "published": {"date-parts": [[2026]]}}]}})
    assert results[0].doi == "10.1000/example"
    assert results[0].published_year == 2026
    assert results[0].provider == "crossref"


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
