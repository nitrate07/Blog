"""Provider registry and factory for creating LLM providers."""

from __future__ import annotations

import logging
from typing import Any

from .llm_providers import ClaudeProvider, GeminiProvider, LLMProvider, OpenAIProvider
from .providers import NullProvider, VerificationProvider

logger = logging.getLogger(__name__)

PROVIDER_MAP: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def create_provider(
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> VerificationProvider:
    """Create an LLM provider based on configuration.

    Args:
        provider_name: Name of the provider ("claude", "openai", "gemini").
                       If None, returns NullProvider.
        api_key: API key for the provider. If None, returns NullProvider.
        model: Optional model override.
        **kwargs: Additional provider-specific arguments.

    Returns:
        A configured VerificationProvider instance.
    """
    if not provider_name or not api_key:
        logger.info("No LLM provider configured, using NullProvider")
        return NullProvider()

    provider_name = provider_name.lower()
    provider_class = PROVIDER_MAP.get(provider_name)

    if not provider_class:
        logger.warning(f"Unknown provider '{provider_name}', using NullProvider")
        return NullProvider()

    try:
        provider = provider_class(api_key=api_key, model=model, **kwargs)
        logger.info(f"Created {provider_name} provider with model {provider.model}")
        return provider
    except Exception as e:
        logger.error(f"Failed to create {provider_name} provider: {e}")
        return NullProvider()


def list_providers() -> list[str]:
    """List available provider names."""
    return list(PROVIDER_MAP.keys())
