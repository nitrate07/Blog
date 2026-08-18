"""Deterministic, evidence-first verification engine for the MVP."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from .models import EvidenceItem, SourceQuality, Verdict, VerificationRequest, VerificationResponse
from .providers import NullProvider, VerificationProvider
from .sources import RetrievedSource, SourceFetcher

_STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with"}
_NEGATIONS = {"not", "no", "never", "neither", "none", "without", "doesn't", "doesnt", "didn't", "didnt"}
_QUALIFIERS = {"may", "might", "possible", "possibly", "associated", "association", "limited", "uncertain", "preliminary", "suggests", "suggest"}


def _tokens(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2 and word not in _STOPWORDS}


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


def compare_claim_evidence(claim: str, text: str) -> tuple[Verdict, str, float]:
    """Return a conservative deterministic comparison and the most relevant sentence."""
    claim_tokens = _tokens(claim)
    ranked = []
    for sentence in _sentences(text):
        overlap = len(claim_tokens & _tokens(sentence)) / max(len(claim_tokens), 1)
        ranked.append((overlap, sentence))
    relevance, passage = max(ranked, default=(0.0, ""), key=lambda item: item[0])
    passage_tokens = _tokens(passage)
    if relevance < 0.28:
        return Verdict.UNVERIFIED, passage, round(relevance, 2)
    if _NEGATIONS & passage_tokens:
        return Verdict.UNSUPPORTED, passage, round(relevance, 2)
    if _QUALIFIERS & passage_tokens:
        return Verdict.PARTIALLY_SUPPORTED, passage, round(relevance, 2)
    if relevance >= 0.5:
        return Verdict.SUPPORTED, passage, round(relevance, 2)
    return Verdict.PARTIALLY_SUPPORTED, passage, round(relevance, 2)


_QUALITY_SCORE = {SourceQuality.PRIMARY: 1.0, SourceQuality.SECONDARY: 0.75, SourceQuality.TERTIARY: 0.35, SourceQuality.UNKNOWN: 0.5}


class EvidenceVerifier:
    def __init__(self, fetcher: SourceFetcher | None = None, provider: VerificationProvider | None = None) -> None:
        self.fetcher = fetcher or SourceFetcher()
        self.provider = provider or NullProvider()

    async def verify(self, request: VerificationRequest) -> VerificationResponse:
        evidence: list[EvidenceItem] = []
        comparisons: list[tuple[Verdict, float, SourceQuality]] = []
        for source_input in request.sources:
            try:
                source: RetrievedSource = await self.fetcher.fetch(str(source_input.url))
            except Exception:
                continue
            deterministic, passage, relevance = compare_claim_evidence(request.claim, source.text)
            provider_verdict = await self.provider.compare(request.claim, passage, request.context)
            verdict = provider_verdict or deterministic
            if passage and relevance >= 0.28:
                evidence.append(EvidenceItem(source_url=source.url, source_type=source.quality, title=source.title, passage=passage, relevance=relevance))
                comparisons.append((verdict, relevance, source.quality))
        if not comparisons:
            return self._response(request.claim, Verdict.UNVERIFIED, 0.0, [], SourceQuality.UNKNOWN)
        # A direct contradiction has priority: never average it away with a weak match.
        unsupported = [item for item in comparisons if item[0] is Verdict.UNSUPPORTED]
        best = max(comparisons, key=lambda item: item[1] * _QUALITY_SCORE[item[2]])
        verdict = Verdict.UNSUPPORTED if unsupported and max(item[1] for item in unsupported) >= best[1] - 0.1 else best[0]
        quality = max((item[2] for item in comparisons), key=lambda q: _QUALITY_SCORE[q])
        confidence = round(min(0.95, best[1] * (0.55 + 0.4 * _QUALITY_SCORE[quality])), 2)
        if verdict is Verdict.UNVERIFIED:
            confidence = 0.0
        return self._response(request.claim, verdict, confidence, evidence, quality)

    @staticmethod
    def _response(claim: str, verdict: Verdict, confidence: float, evidence: list[EvidenceItem], quality: SourceQuality) -> VerificationResponse:
        return VerificationResponse(verdict=verdict, confidence=confidence, claim=claim, evidence=evidence, source_quality=quality, checked_at=datetime.now(timezone.utc))
