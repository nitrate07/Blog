import pytest

from evidence.engine import EvidenceVerifier
from evidence.models import SourceQuality, VerificationRequest
from evidence.sources import RetrievedSource


class FakeFetcher:
    def __init__(self, text: str, quality: SourceQuality = SourceQuality.PRIMARY):
        self.text = text
        self.quality = quality

    async def fetch(self, url: str) -> RetrievedSource:
        return RetrievedSource(url=url, title="Test source", text=self.text, quality=self.quality)


async def verify(claim: str, text: str):
    request = VerificationRequest(claim=claim, sources=[{"url": "https://example.com/source"}])
    return await EvidenceVerifier(fetcher=FakeFetcher(text)).verify(request)


@pytest.mark.asyncio
async def test_supported_claim():
    result = await verify("Vitamin C reduces cold duration", "A randomized trial found that vitamin C reduces cold duration in adults.")
    assert result.verdict.value == "supported"
    assert result.evidence[0].passage


@pytest.mark.asyncio
async def test_partially_supported_claim():
    result = await verify("Vitamin C reduces cold duration", "The review suggests vitamin C may reduce cold duration for some adults.")
    assert result.verdict.value == "partially_supported"


@pytest.mark.asyncio
async def test_contradicted_claim():
    result = await verify("Vitamin C reduces cold duration", "The controlled study found vitamin C does not reduce cold duration.")
    assert result.verdict.value == "unsupported"


@pytest.mark.asyncio
async def test_insufficient_evidence_is_unverified():
    result = await verify("Vitamin C reduces cold duration", "The archive discusses exercise and sleep habits.")
    assert result.verdict.value == "unverified"
