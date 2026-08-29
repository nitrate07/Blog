"""evidence/v2/sources/http_retry.py dogrudan testleri.

Bu modul artik 12+ kaynak ajaninin (HealthOrgAgent alt siniflari, 8 dergi
ajani, PubMed/Crossref/EuropePMC/OpenAlex) paylastigi TEK retry mantigidir.
Buradaki testler ajan-bagimsizdir — dogrudan get_with_retry() sozlesmesini
kilitler.
"""

from __future__ import annotations

import httpx
import pytest

from evidence.v2.sources.http_retry import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_RETRIES,
    RETRYABLE_STATUS_CODES,
    get_with_retry,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestGetWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text="ok")

        async with _client(handler) as client:
            resp = await get_with_retry(client, "https://x.test/y", agent_name="t", backoff_seconds=0.01)
        assert resp.status_code == 200
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_all_retryable_status_codes_are_retried(self):
        for code in RETRYABLE_STATUS_CODES:
            calls = []

            def handler(request: httpx.Request, _code=code) -> httpx.Response:
                calls.append(request)
                if len(calls) < 2:
                    return httpx.Response(_code)
                return httpx.Response(200)

            async with _client(handler) as client:
                resp = await get_with_retry(client, "https://x.test/y", agent_name="t", backoff_seconds=0.01)
            assert resp.status_code == 200, f"status {code} should have been retried"
            assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_non_retryable_statuses_fail_immediately(self):
        for code in (400, 401, 403, 404, 410):
            calls = []

            def handler(request: httpx.Request, _code=code) -> httpx.Response:
                calls.append(request)
                return httpx.Response(_code)

            async with _client(handler) as client:
                with pytest.raises(httpx.HTTPStatusError):
                    await get_with_retry(client, "https://x.test/y", agent_name="t", backoff_seconds=0.01)
            assert len(calls) == 1, f"status {code} should NOT have been retried"

    @pytest.mark.asyncio
    async def test_exhausts_configured_max_retries(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(503)

        async with _client(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await get_with_retry(client, "https://x.test/y", agent_name="t", max_retries=1, backoff_seconds=0.01)
        assert len(calls) == 2  # max_retries=1 -> ilk deneme + 1 tekrar

    @pytest.mark.asyncio
    async def test_default_constants_are_sane(self):
        assert DEFAULT_MAX_RETRIES >= 1
        assert DEFAULT_BACKOFF_SECONDS > 0
        assert 429 in RETRYABLE_STATUS_CODES
        assert 403 not in RETRYABLE_STATUS_CODES
        assert 404 not in RETRYABLE_STATUS_CODES

    @pytest.mark.asyncio
    async def test_kwargs_forwarded_to_underlying_get(self):
        """params/headers gibi ek kwargs client.get()'e dogru gecmeli."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = str(request.url.params)
            captured["header"] = request.headers.get("x-custom")
            return httpx.Response(200)

        async with _client(handler) as client:
            await get_with_retry(
                client, "https://x.test/y", agent_name="t",
                params={"q": "test"}, headers={"x-custom": "abc"},
            )
        assert "q=test" in captured["query"]
        assert captured["header"] == "abc"
