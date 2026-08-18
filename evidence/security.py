"""API-key authentication and process-local rate limiting for the public API."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hmac
import time

from fastapi import HTTPException, status

from .config import Settings
from .storage import VerificationStore


@dataclass(frozen=True)
class APIPrincipal:
    id: str
    name: str
    rate_limit_per_minute: int


class APIKeyAuthenticator:
    def __init__(self, store: VerificationStore, config: Settings) -> None:
        self.store = store
        if config.bootstrap_api_key:
            store.ensure_api_key(config.bootstrap_api_key, "bootstrap", config.api_rate_limit_per_minute)

    def authenticate(self, raw_key: str | None) -> APIPrincipal:
        if not raw_key or len(raw_key) < 16:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid X-API-Key required")
        row = self.store.find_api_key(raw_key)
        if not row or not bool(row["enabled"]) or not hmac.compare_digest(row["key_hash"], self.store.hash_secret(raw_key)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="valid X-API-Key required")
        return APIPrincipal(id=str(row["id"]), name=str(row["name"]), rate_limit_per_minute=int(row["rate_limit_per_minute"]))


class SlidingWindowRateLimiter:
    """Conservative per-process limiter; deploy Redis/API gateway for multi-worker limits."""
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, principal: APIPrincipal) -> None:
        now = time.monotonic()
        window = self._requests[principal.id]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= principal.rate_limit_per_minute:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded", headers={"Retry-After": "60"})
        window.append(now)
