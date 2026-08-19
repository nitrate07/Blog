"""Provider registry, factory, status, and health-check utilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import Settings, settings
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


def create_provider_from_config(config: Settings | None = None) -> VerificationProvider:
    """Create a provider automatically from Settings.

    Checks provider-specific env vars first, falls back to generic LLM vars.
    """
    config = config or settings
    active = config.get_active_provider()
    if not active:
        return NullProvider()

    provider_config = config.get_provider_config(active)
    return create_provider(
        provider_name=active,
        api_key=provider_config["api_key"],
        model=provider_config["model"],
        temperature=provider_config["temperature"],
        max_tokens=provider_config["max_tokens"],
    )


def list_providers() -> list[str]:
    """List available provider names."""
    return list(PROVIDER_MAP.keys())


@dataclass
class ProviderStatus:
    """Status information for a single provider."""

    name: str
    configured: bool
    model: str | None
    is_active: bool


def get_provider_statuses(config: Settings | None = None) -> list[ProviderStatus]:
    """Return status of all known providers."""
    config = config or settings
    active_name = config.get_active_provider()
    statuses: list[ProviderStatus] = []
    for name in PROVIDER_MAP:
        provider_config = config.get_provider_config(name)
        statuses.append(ProviderStatus(
            name=name,
            configured=bool(provider_config["api_key"]),
            model=provider_config["model"] or PROVIDER_MAP[name].DEFAULT_MODEL,
            is_active=(name == active_name),
        ))
    return statuses


async def test_provider(provider_name: str, config: Settings | None = None) -> dict[str, Any]:
    """Run a lightweight connectivity check against a provider.

    Returns {"status": "ok", ...} or {"status": "error", "error": "..."}.
    """
    config = config or settings
    provider_config = config.get_provider_config(provider_name)
    if not provider_config["api_key"]:
        return {"status": "not_configured", "error": f"No API key for {provider_name}"}

    provider = create_provider(
        provider_name=provider_name,
        api_key=provider_config["api_key"],
        model=provider_config["model"],
    )

    if isinstance(provider, NullProvider):
        return {"status": "error", "error": f"Failed to create {provider_name} provider"}

    result = await provider.health_check()
    return {"provider": provider_name, **result}
