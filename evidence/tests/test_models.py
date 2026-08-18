import pytest
from pydantic import ValidationError

from evidence.models import SourceInput, SourceQuality, VerificationRequest
from evidence.sources import classify_source, validate_public_url


def test_primary_source_scores_above_secondary_source():
    assert classify_source("https://www.fda.gov/drugs") is SourceQuality.PRIMARY
    assert classify_source("https://example.org/review", "This is a systematic review.") is SourceQuality.SECONDARY


def test_invalid_private_url_is_rejected():
    with pytest.raises(ValueError):
        validate_public_url("http://127.0.0.1/admin", resolve_host=False)


def test_request_requires_valid_url():
    with pytest.raises(ValidationError):
        VerificationRequest(claim="This is a test claim", sources=[SourceInput(url="not-a-url")])
