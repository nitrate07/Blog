import pytest
from pydantic import ValidationError

from evidence.models import SourceInput, SourceQuality, VerificationRequest
from evidence.sources import classify_source, validate_public_url


def test_primary_source_scores_above_secondary_source():
    assert classify_source("https://www.fda.gov/drugs") is SourceQuality.PRIMARY
    assert classify_source("https://example.org/review", "This is a systematic review.") is SourceQuality.SECONDARY


def test_classify_source_recognises_major_journals_and_turkish_institutions():
    for url in (
        "https://www.nejm.org/doi/full/10.1056/example",
        "https://jamanetwork.com/journals/jama/fullarticle/example",
        "https://www.thelancet.com/journals/example",
        "https://www.bmj.com/content/example",
        "https://www.nature.com/articles/example",
        "https://www.cochranelibrary.com/cdsr/doi/10.1002/example",
        "https://hsgm.saglik.gov.tr/rehberler",
        "https://tuseb.gov.tr/yayin",
    ):
        assert classify_source(url) is SourceQuality.PRIMARY, url


def test_classify_source_recognises_academic_tlds():
    for url in (
        "https://www.ox.ac.uk/news/example",
        "https://www.unimelb.edu.au/study",
        "https://example.edu.tr/arastirma",
    ):
        assert classify_source(url) is SourceQuality.PRIMARY, url


def test_classify_source_flags_social_media_as_tertiary():
    for url in ("https://medium.com/@user/post", "https://tiktok.com/@user/video/1", "https://www.quora.com/example"):
        assert classify_source(url) is SourceQuality.TERTIARY, url


def test_invalid_private_url_is_rejected():
    with pytest.raises(ValueError):
        validate_public_url("http://127.0.0.1/admin", resolve_host=False)


def test_request_requires_valid_url():
    with pytest.raises(ValidationError):
        VerificationRequest(claim="This is a test claim", sources=[SourceInput(url="not-a-url")])
