"""Aciklayici (narrate_verdict) + Duzenleyici (edit_and_validate) testleri."""

import pytest

from evidence.chat.editor import edit_and_validate, narrate_verdict


class FakeProvider:
    def __init__(self, response: str | None = None, raises: bool = False):
        self.response = response
        self.raises = raises
        self.last_prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        if self.raises:
            raise RuntimeError("provider unavailable")
        return self.response


MATCHES = [
    {"title": "WHO Report", "url": "https://who.int/report-1", "source_type": "international_organization", "quality_score": 0.95, "text": "..."},
    {"title": "PubMed Study", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "source_type": "academic", "quality_score": 0.85, "text": "..."},
]


class TestNarrateVerdict:
    @pytest.mark.asyncio
    async def test_none_when_no_provider(self):
        result = await narrate_verdict("claim", "supported", 0.8, MATCHES, provider=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_no_matches(self):
        provider = FakeProvider(response="some text")
        result = await narrate_verdict("claim", "supported", 0.8, [], provider=provider)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_provider_text_when_cited_correctly(self):
        provider = FakeProvider(response="Kanıt WHO raporunu destekliyor (https://who.int/report-1).")
        result = await narrate_verdict("claim", "supported", 0.8, MATCHES, provider=provider)
        assert result == "Kanıt WHO raporunu destekliyor (https://who.int/report-1)."
        assert "who.int/report-1" in provider.last_prompt
        assert "pubmed.ncbi.nlm.nih.gov" in provider.last_prompt

    @pytest.mark.asyncio
    async def test_none_when_provider_raises(self):
        provider = FakeProvider(raises=True)
        result = await narrate_verdict("claim", "supported", 0.8, MATCHES, provider=provider)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_provider_returns_empty(self):
        provider = FakeProvider(response="   ")
        result = await narrate_verdict("claim", "supported", 0.8, MATCHES, provider=provider)
        assert result is None


class TestEditAndValidate:
    def test_accepts_text_citing_only_provided_urls(self):
        draft = "Kanıt destekliyor (https://who.int/report-1) ve (https://pubmed.ncbi.nlm.nih.gov/12345/)."
        result = edit_and_validate(draft, MATCHES)
        assert result == draft

    def test_accepts_text_with_no_urls(self):
        draft = "Kanıt yetersiz, net bir hüküm verilemiyor."
        result = edit_and_validate(draft, MATCHES)
        assert result == draft

    def test_rejects_hallucinated_url(self):
        draft = "Bu iddia (https://example.com/made-up-study) tarafından destekleniyor."
        result = edit_and_validate(draft, MATCHES)
        assert result is None

    def test_rejects_mixed_real_and_hallucinated_urls(self):
        draft = "Gerçek kaynak (https://who.int/report-1) ve uydurma kaynak (https://fake-journal.example/x)."
        result = edit_and_validate(draft, MATCHES)
        assert result is None

    def test_rejects_empty_draft(self):
        assert edit_and_validate("", MATCHES) is None
        assert edit_and_validate("   ", MATCHES) is None

    def test_tolerates_trailing_punctuation_on_url(self):
        draft = "Kaynak: https://who.int/report-1."
        result = edit_and_validate(draft, MATCHES)
        assert result is not None

    def test_collapses_excess_blank_lines(self):
        draft = "Birinci satır.\n\n\n\nİkinci satır (https://who.int/report-1)."
        result = edit_and_validate(draft, MATCHES)
        assert "\n\n\n" not in result
