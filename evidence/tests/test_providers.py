import pytest

from evidence.config import Settings
from evidence.models import Verdict
from evidence.providers import (
    DEFAULT_VERIFIER_MODEL,
    AnthropicVerificationProvider,
    NullProvider,
    default_provider,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _ToolUseResponse(_FakeResponse):
    @staticmethod
    def verdict_payload(verdict: str) -> dict:
        return {"content": [{"type": "tool_use", "name": "report_verdict", "input": {"verdict": verdict}}]}


class _TextOnlyResponse(_FakeResponse):
    def __init__(self) -> None:
        super().__init__({"content": [{"type": "text", "text": "I cannot answer that."}]})


class FakeAnthropicClient:
    """httpx.AsyncClient stand-in that records request payloads."""

    def __init__(self, payload: dict | Exception) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.calls.append(json)
        if isinstance(self._payload, Exception):
            raise self._payload
        return _ToolUseResponse(self._payload)


@pytest.mark.asyncio
async def test_anthropic_provider_returns_reported_verdict():
    client = FakeAnthropicClient(_ToolUseResponse.verdict_payload("partially_supported"))
    provider = AnthropicVerificationProvider(api_key="test-key", client=client)
    result = await provider.compare("Exercise improves heart health", "A trial suggests exercise may improve heart health.")
    assert result is Verdict.PARTIALLY_SUPPORTED
    sent = client.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "report_verdict"}
    assert sent["temperature"] == 0
    assert any(tool["name"] == "report_verdict" for tool in sent["tools"])
    assert "CLAIM:" in sent["messages"][0]["content"]


@pytest.mark.asyncio
async def test_anthropic_provider_includes_context_in_prompt():
    client = FakeAnthropicClient(_ToolUseResponse.verdict_payload("supported"))
    provider = AnthropicVerificationProvider(api_key="test-key", client=client)
    await provider.compare("Claim text", "Passage text.", context="User added context")
    assert "CONTEXT:" in client.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_anthropic_provider_fails_closed_on_upstream_error():
    client = FakeAnthropicClient(RuntimeError("upstream failure"))
    provider = AnthropicVerificationProvider(api_key="test-key", client=client)
    assert await provider.compare("Exercise improves heart health", "Some passage.") is None


@pytest.mark.asyncio
async def test_anthropic_provider_fails_closed_without_tool_use():
    client = FakeAnthropicClient({"content": [{"type": "text", "text": "refusing"}]})
    provider = AnthropicVerificationProvider(api_key="test-key", client=client)
    assert await provider.compare("Claim", "Passage.") is None


@pytest.mark.asyncio
async def test_anthropic_provider_fails_closed_on_unknown_verdict():
    client = FakeAnthropicClient(_ToolUseResponse.verdict_payload("definitely_true"))
    provider = AnthropicVerificationProvider(api_key="test-key", client=client)
    assert await provider.compare("Claim", "Passage.") is None


def test_default_provider_is_null_without_api_key():
    assert isinstance(default_provider(Settings()), NullProvider)


def test_default_provider_is_anthropic_with_claude_key():
    provider = default_provider(Settings(claude_api_key="sk-test"))
    assert isinstance(provider, AnthropicVerificationProvider)
    assert provider.model == DEFAULT_VERIFIER_MODEL


def test_default_provider_respects_configured_model():
    provider = default_provider(Settings(claude_api_key="sk-test", claude_model="claude-sonnet-x"))
    assert isinstance(provider, AnthropicVerificationProvider)
    assert provider.model == "claude-sonnet-x"


def test_default_provider_ignores_non_claude_llm_provider():
    config = Settings(llm_provider="openai", openai_api_key="sk-oai")
    assert isinstance(default_provider(config), NullProvider)
