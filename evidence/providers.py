"""Provider seam. No LLM provider is required for the deterministic MVP."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from .config import Settings, settings
from .models import Verdict

logger = logging.getLogger(__name__)


class VerificationProvider(Protocol):
    """Optional future provider for comparing a claim with an extracted passage."""

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        """Return a constrained verdict, or None when unable to determine one."""


class NullProvider:
    """Makes the evidence-first deterministic path explicit when no LLM is configured."""

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        return None


_VERDICT_TOOL = {
    "name": "report_verdict",
    "description": "Report whether the passage supports the claim, using only the passage text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": [item.value for item in Verdict],
                "description": (
                    "supported: the passage confirms the claim as stated. "
                    "partially_supported: the passage is relevant but the claim overreaches or only part of it holds. "
                    "unsupported: the passage contradicts the claim. "
                    "unverified: the passage does not address the claim clearly enough to judge."
                ),
            }
        },
        "required": ["verdict"],
    },
}

_SYSTEM_PROMPT = (
    "You are a conservative evidence-comparison tool for a fact-checking pipeline. "
    "You will be given a CLAIM and a PASSAGE extracted from a single already-retrieved source. "
    "Judge only whether the PASSAGE's own wording supports, partially supports, contradicts, or fails "
    "to address the CLAIM. Base your judgment strictly on the PASSAGE text given to you — never on "
    "outside knowledge, training data, or what you believe is generally true about the topic. If the "
    "passage does not clearly address the claim, report 'unverified' rather than guessing. Call the "
    "report_verdict tool exactly once with your answer."
)

DEFAULT_VERIFIER_MODEL = "claude-haiku-4-5-20251001"


class AnthropicVerificationProvider:
    """Evidence-first LLM provider: proposes a verdict only from an already-retrieved passage.

    Never fetches sources or introduces outside knowledge itself — that stays the job of
    SourceFetcher/EvidenceVerifier. Any failure (network, auth, malformed response) is swallowed
    and reported as None so the deterministic comparison in engine.py is always the fallback,
    matching this project's "no evidence, no confident verdict" rule.
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str = DEFAULT_VERIFIER_MODEL, client: Any | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        try:
            user_content = f"CLAIM: {claim}\n\nPASSAGE: {passage}"
            if context:
                user_content += f"\n\nCONTEXT: {context}"
            payload = {
                "model": self.model,
                "max_tokens": 256,
                "temperature": 0,
                "system": _SYSTEM_PROMPT,
                "tools": [_VERDICT_TOOL],
                "tool_choice": {"type": "tool", "name": "report_verdict"},
                "messages": [{"role": "user", "content": user_content}],
            }
            headers = {"x-api-key": self._api_key, "anthropic-version": self.API_VERSION, "content-type": "application/json"}
            response = await self._get_client().post(self.API_URL, json=payload, headers=headers)
            response.raise_for_status()
            for block in response.json().get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "report_verdict":
                    return Verdict(block["input"]["verdict"])
        except Exception as exc:
            logger.warning("LLM verification failed closed: %s", exc)
            return None
        return None


def default_provider(config: Settings = settings) -> VerificationProvider:
    """Anthropic-backed provider when a Claude API key is configured, deterministic-only otherwise."""
    if config.get_active_provider() == "claude":
        provider_config = config.get_provider_config("claude")
        return AnthropicVerificationProvider(
            api_key=provider_config["api_key"],
            model=provider_config["model"] or DEFAULT_VERIFIER_MODEL,
        )
    return NullProvider()
