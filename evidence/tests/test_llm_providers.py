"""Tests for LLM providers and provider registry."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evidence.llm_providers import ClaudeProvider, GeminiProvider, LLMProvider, OpenAIProvider
from evidence.models import Verdict
from evidence.provider_registry import create_provider, list_providers
from evidence.providers import NullProvider


class TestLLMProviderParsing:
    """Test verdict parsing logic."""

    def test_parse_supported_verdict(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('{"verdict": "supported"}')
        assert result == Verdict.SUPPORTED

    def test_parse_partially_supported_verdict(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('{"verdict": "partially_supported"}')
        assert result == Verdict.PARTIALLY_SUPPORTED

    def test_parse_unsupported_verdict(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('{"verdict": "unsupported"}')
        assert result == Verdict.UNSUPPORTED

    def test_parse_unverified_verdict(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('{"verdict": "unverified"}')
        assert result == Verdict.UNVERIFIED

    def test_parse_json_with_markdown_code_block(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('```json\n{"verdict": "supported"}\n```')
        assert result == Verdict.SUPPORTED

    def test_parse_invalid_json_returns_none(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict("not valid json")
        assert result is None

    def test_parse_invalid_verdict_returns_none(self):
        provider = ClaudeProvider(api_key="test-key")
        result = provider._parse_verdict('{"verdict": "invalid"}')
        assert result is None


class TestLLMProviderCompare:
    """Test the compare method with mocked LLM calls."""

    @pytest.mark.asyncio
    async def test_compare_returns_none_for_empty_passage(self):
        provider = ClaudeProvider(api_key="test-key")
        result = await provider.compare("claim", "")
        assert result is None

    @pytest.mark.asyncio
    async def test_compare_returns_verdict_on_success(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm = AsyncMock(return_value='{"verdict": "supported"}')

        result = await provider.compare("Exercise improves health", "Exercise is beneficial for cardiovascular health.")
        assert result == Verdict.SUPPORTED

    @pytest.mark.asyncio
    async def test_compare_returns_none_on_llm_failure(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm = AsyncMock(side_effect=Exception("API error"))

        result = await provider.compare("Exercise improves health", "Exercise is beneficial for cardiovascular health.")
        assert result is None

    @pytest.mark.asyncio
    async def test_compare_with_context(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm = AsyncMock(return_value='{"verdict": "supported"}')

        result = await provider.compare(
            "claim",
            "evidence passage",
            context="Additional context",
        )
        assert result == Verdict.SUPPORTED


class TestClaudeProvider:
    """Test Claude-specific provider."""

    @pytest.mark.asyncio
    async def test_call_llm_returns_response_text(self):
        provider = ClaudeProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"text": '{"verdict": "supported"}'}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await provider._call_llm("test prompt")

        assert result == '{"verdict": "supported"}'


class TestOpenAIProvider:
    """Test OpenAI-specific provider."""

    @pytest.mark.asyncio
    async def test_call_llm_returns_response_text(self):
        provider = OpenAIProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"verdict": "unsupported"}'}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await provider._call_llm("test prompt")

        assert result == '{"verdict": "unsupported"}'


class TestGeminiProvider:
    """Test Gemini-specific provider."""

    @pytest.mark.asyncio
    async def test_call_llm_returns_response_text(self):
        provider = GeminiProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"verdict": "unverified"}'}]
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await provider._call_llm("test prompt")

        assert result == '{"verdict": "unverified"}'


class TestProviderRegistry:
    """Test provider registry and factory."""

    def test_list_providers(self):
        providers = list_providers()
        assert "claude" in providers
        assert "openai" in providers
        assert "gemini" in providers

    def test_create_provider_returns_null_when_no_name(self):
        provider = create_provider(provider_name=None)
        assert isinstance(provider, NullProvider)

    def test_create_provider_returns_null_when_no_api_key(self):
        provider = create_provider(provider_name="claude", api_key=None)
        assert isinstance(provider, NullProvider)

    def test_create_provider_returns_null_for_unknown_provider(self):
        provider = create_provider(provider_name="unknown", api_key="test-key")
        assert isinstance(provider, NullProvider)

    def test_create_claude_provider(self):
        provider = create_provider(provider_name="claude", api_key="test-key")
        assert isinstance(provider, ClaudeProvider)
        assert provider.model == "claude-sonnet-4-20250514"

    def test_create_openai_provider(self):
        provider = create_provider(provider_name="openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-4o-mini"

    def test_create_gemini_provider(self):
        provider = create_provider(provider_name="gemini", api_key="test-key")
        assert isinstance(provider, GeminiProvider)
        assert provider.model == "gemini-1.5-flash"

    def test_create_provider_with_custom_model(self):
        provider = create_provider(
            provider_name="claude",
            api_key="test-key",
            model="claude-3-opus-20240229",
        )
        assert isinstance(provider, ClaudeProvider)
        assert provider.model == "claude-3-opus-20240229"

    def test_create_provider_case_insensitive(self):
        provider = create_provider(provider_name="CLAUDE", api_key="test-key")
        assert isinstance(provider, ClaudeProvider)
