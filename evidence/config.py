"""Safe defaults for retrieval, persistence, and public API access."""

from dataclasses import dataclass, field
import os
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float = float(os.getenv("EVIDENCE_REQUEST_TIMEOUT_SECONDS", "8"))
    max_response_bytes: int = int(os.getenv("EVIDENCE_MAX_RESPONSE_BYTES", "1000000"))
    max_redirects: int = int(os.getenv("EVIDENCE_MAX_REDIRECTS", "3"))
    user_agent: str = os.getenv("EVIDENCE_USER_AGENT", "AriKaynakEvidence/0.1 (+https://github.com/nitrate07/Blog)")
    database_path: str = os.getenv("EVIDENCE_DATABASE_PATH", "evidence/data/evidence.db")
    require_api_key: bool = _env_bool("EVIDENCE_REQUIRE_API_KEY", True)
    bootstrap_api_key: str | None = os.getenv("EVIDENCE_BOOTSTRAP_API_KEY") or None
    api_rate_limit_per_minute: int = int(os.getenv("EVIDENCE_API_RATE_LIMIT_PER_MINUTE", "30"))

    # Generic LLM settings (fallback when provider-specific not set)
    llm_provider: str | None = os.getenv("EVIDENCE_LLM_PROVIDER") or None
    llm_api_key: str | None = os.getenv("EVIDENCE_LLM_API_KEY") or None
    llm_model: str | None = os.getenv("EVIDENCE_LLM_MODEL") or None
    llm_temperature: float = float(os.getenv("EVIDENCE_LLM_TEMPERATURE", "0.0"))
    llm_max_tokens: int = int(os.getenv("EVIDENCE_LLM_MAX_TOKENS", "256"))

    # Provider-specific settings (override generic when set)
    claude_api_key: str | None = os.getenv("EVIDENCE_CLAUDE_API_KEY") or None
    claude_model: str | None = os.getenv("EVIDENCE_CLAUDE_MODEL") or None
    openai_api_key: str | None = os.getenv("EVIDENCE_OPENAI_API_KEY") or None
    openai_model: str | None = os.getenv("EVIDENCE_OPENAI_MODEL") or None
    gemini_api_key: str | None = os.getenv("EVIDENCE_GEMINI_API_KEY") or None
    gemini_model: str | None = os.getenv("EVIDENCE_GEMINI_MODEL") or None

    def get_provider_config(self, provider_name: str) -> dict[str, Any]:
        """Get config for a specific provider. Provider-specific vars override generic."""
        provider_name = provider_name.lower()

        api_key = getattr(self, f"{provider_name}_api_key", None) or self.llm_api_key
        model = getattr(self, f"{provider_name}_model", None) or self.llm_model

        return {
            "api_key": api_key,
            "model": model,
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
        }

    def get_active_provider(self) -> str | None:
        """Return the first configured provider name, or None."""
        if self.llm_provider:
            return self.llm_provider.lower()
        for name in ("claude", "openai", "gemini"):
            if getattr(self, f"{name}_api_key", None):
                return name
        return None


settings = Settings()
