"""Tests for LLM providers and provider registry."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evidence.config import Settings
from evidence.llm_providers import ClaudeProvider, GeminiProvider, GroqProvider, LLMProvider, OpenAIProvider
from evidence.models import Verdict
from evidence.provider_registry import (
    ProviderStatus,
    create_provider,
    create_provider_from_config,
    get_provider_statuses,
    list_providers,
    check_provider_health,
)
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


class TestHealthCheck:
    """Test the health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm = AsyncMock(return_value='{"verdict": "supported"}')

        result = await provider.health_check()
        assert result["status"] == "ok"
        assert result["provider"] == "ClaudeProvider"
        assert result["model"] == "claude-sonnet-5"

    @pytest.mark.asyncio
    async def test_health_check_error(self):
        provider = ClaudeProvider(api_key="test-key")
        provider.compare = AsyncMock(return_value=None)

        result = await provider.health_check()
        assert result["status"] == "ok"
        assert result["test_verdict"] is None


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


class TestGroqProvider:
    """Test Groq-specific provider."""

    @pytest.mark.asyncio
    async def test_call_llm_returns_response_text(self):
        provider = GroqProvider(api_key="test-key")

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


class TestGenerateWithHistory:
    """generate_with_history() sends real role-tagged messages via _call_llm_with_messages."""

    @pytest.mark.asyncio
    async def test_prepends_history_before_prompt(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm_with_messages = AsyncMock(return_value="ok")
        history = [{"role": "user", "content": "Kahve zararlı mı?"}, {"role": "assistant", "content": "Kanıtlar karışık."}]

        result = await provider.generate_with_history("peki çocuklarda?", history)

        assert result == "ok"
        sent = provider._call_llm_with_messages.call_args[0][0]
        assert sent == history + [{"role": "user", "content": "peki çocuklarda?"}]

    @pytest.mark.asyncio
    async def test_empty_history_still_includes_prompt(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm_with_messages = AsyncMock(return_value="ok")

        await provider.generate_with_history("selam", [])

        sent = provider._call_llm_with_messages.call_args[0][0]
        assert sent == [{"role": "user", "content": "selam"}]


class TestGenerateWithTool:
    """generate_with_tool() — fail-closed like compare()/generate()."""

    @pytest.mark.asyncio
    async def test_returns_none_when_provider_does_not_support_tools(self):
        provider = GroqProvider(api_key="test-key")
        provider.supports_tools = False  # simulate a future provider without tool support
        result = await provider.generate_with_tool("prompt", {"name": "x", "input_schema": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm_with_tool = AsyncMock(side_effect=RuntimeError("boom"))
        result = await provider.generate_with_tool("prompt", {"name": "x", "input_schema": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_parsed_input_on_success(self):
        provider = ClaudeProvider(api_key="test-key")
        provider._call_llm_with_tool = AsyncMock(return_value={"explanation": "ok", "source_urls_used": []})
        result = await provider.generate_with_tool("prompt", {"name": "x", "input_schema": {}})
        assert result == {"explanation": "ok", "source_urls_used": []}


class TestCallLlmWithToolPerProvider:
    """Verify the actual request/response shape per provider's tool-forcing API."""

    TOOL = {
        "name": "report_explanation",
        "description": "desc",
        "input_schema": {
            "type": "object",
            "properties": {"explanation": {"type": "string"}, "source_urls_used": {"type": "array", "items": {"type": "string"}}},
            "required": ["explanation", "source_urls_used"],
        },
    }

    @pytest.mark.asyncio
    async def test_claude_parses_tool_use_block(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "tool_use", "name": "report_explanation", "input": {"explanation": "hi", "source_urls_used": ["https://who.int/x"]}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider._call_llm_with_tool("prompt", self.TOOL)

        assert result == {"explanation": "hi", "source_urls_used": ["https://who.int/x"]}

    @pytest.mark.asyncio
    async def test_claude_returns_none_when_tool_not_called(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {"content": [{"type": "text", "text": "no tool call"}]}
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider._call_llm_with_tool("prompt", self.TOOL)

        assert result is None

    @pytest.mark.asyncio
    async def test_openai_parses_tool_call_arguments(self):
        provider = OpenAIProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"tool_calls": [{"function": {"name": "report_explanation", "arguments": json.dumps({"explanation": "hi", "source_urls_used": []})}}]}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider._call_llm_with_tool("prompt", self.TOOL)

        assert result == {"explanation": "hi", "source_urls_used": []}

    @pytest.mark.asyncio
    async def test_openai_returns_none_on_malformed_arguments(self):
        provider = OpenAIProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"tool_calls": [{"function": {"name": "report_explanation", "arguments": "not json"}}]}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider._call_llm_with_tool("prompt", self.TOOL)

        assert result is None

    @pytest.mark.asyncio
    async def test_gemini_parses_function_call_args(self):
        provider = GeminiProvider(api_key="test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"functionCall": {"name": "report_explanation", "args": {"explanation": "hi", "source_urls_used": []}}}]}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("evidence.llm_providers.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider._call_llm_with_tool("prompt", self.TOOL)

        assert result == {"explanation": "hi", "source_urls_used": []}


class TestProviderRegistry:
    """Test provider registry and factory."""

    def test_list_providers(self):
        providers = list_providers()
        assert "claude" in providers
        assert "openai" in providers
        assert "gemini" in providers
        assert "groq" in providers

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
        assert provider.model == "claude-sonnet-5"

    def test_create_openai_provider(self):
        provider = create_provider(provider_name="openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-5.6-terra"

    def test_create_groq_provider(self):
        provider = create_provider(provider_name="groq", api_key="test-key")
        assert isinstance(provider, GroqProvider)
        assert provider.model == "llama-3.3-70b-versatile"

    def test_create_gemini_provider(self):
        provider = create_provider(provider_name="gemini", api_key="test-key")
        assert isinstance(provider, GeminiProvider)
        assert provider.model == "gemini-3.7-flash"

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


class TestProviderConfig:
    """Test Settings.get_provider_config and get_active_provider."""

    def test_provider_specific_overrides_generic(self):
        config = Settings(
            llm_api_key="generic-key",
            llm_model="generic-model",
            claude_api_key="claude-specific-key",
            claude_model="claude-specific-model",
        )
        result = config.get_provider_config("claude")
        assert result["api_key"] == "claude-specific-key"
        assert result["model"] == "claude-specific-model"

    def test_falls_back_to_generic(self):
        config = Settings(
            llm_api_key="generic-key",
            llm_model="generic-model",
        )
        result = config.get_provider_config("claude")
        assert result["api_key"] == "generic-key"
        assert result["model"] == "generic-model"

    def test_get_active_provider_from_llm_provider(self):
        config = Settings(llm_provider="claude", claude_api_key="key")
        assert config.get_active_provider() == "claude"

    def test_get_active_provider_auto_detects(self):
        config = Settings(openai_api_key="key")
        assert config.get_active_provider() == "openai"

    def test_get_active_provider_returns_none_when_empty(self):
        config = Settings()
        assert config.get_active_provider() is None


class TestGetProviderStatuses:
    """Test get_provider_statuses."""

    def test_statuses_include_all_providers(self):
        config = Settings()
        statuses = get_provider_statuses(config)
        names = [s.name for s in statuses]
        assert "claude" in names
        assert "openai" in names
        assert "gemini" in names

    def test_configured_provider_marked(self):
        config = Settings(claude_api_key="key")
        statuses = get_provider_statuses(config)
        claude = next(s for s in statuses if s.name == "claude")
        assert claude.configured is True

    def test_active_provider_marked(self):
        config = Settings(claude_api_key="key")
        statuses = get_provider_statuses(config)
        claude = next(s for s in statuses if s.name == "claude")
        assert claude.is_active is True


class TestCreateProviderFromConfig:
    """Test create_provider_from_config."""

    def test_returns_null_when_nothing_configured(self):
        config = Settings()
        provider = create_provider_from_config(config)
        assert isinstance(provider, NullProvider)

    def test_creates_provider_from_specific_key(self):
        config = Settings(claude_api_key="key")
        provider = create_provider_from_config(config)
        assert isinstance(provider, ClaudeProvider)

    def test_creates_provider_from_generic_key(self):
        config = Settings(llm_provider="openai", llm_api_key="key")
        provider = create_provider_from_config(config)
        assert isinstance(provider, OpenAIProvider)


class TestCheckProviderHealth:
    """Test the check_provider_health async function."""

    @pytest.mark.asyncio
    async def test_not_configured(self):
        config = Settings()
        result = await check_provider_health("claude", config)
        assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_provider_ok(self):
        config = Settings(claude_api_key="key")
        with patch("evidence.provider_registry.create_provider") as mock_create:
            mock_provider = MagicMock()
            mock_provider.health_check = AsyncMock(return_value={"status": "ok", "model": "test"})
            mock_provider.__class__ = ClaudeProvider
            mock_create.return_value = mock_provider

            result = await check_provider_health("claude", config)
            assert result["status"] == "ok"
