import pytest
from fastapi import HTTPException

from evidence.security import APIPrincipal, SlidingWindowRateLimiter


def test_rate_limiter_rejects_requests_over_quota():
    limiter = SlidingWindowRateLimiter()
    principal = APIPrincipal(id="key-1", name="test", rate_limit_per_minute=1)
    limiter.check(principal)
    with pytest.raises(HTTPException) as error:
        limiter.check(principal)
    assert error.value.status_code == 429
