"""LLM provider implementations for enhanced evidence verification."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .models import Verdict
from .providers import VerificationProvider

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """You are an evidence verification assistant. Analyze whether the given claim is supported, partially supported, unsupported, or unverified based on the provided evidence passage.

RULES:
1. Return ONLY a JSON object with a single "verdict" key
2. Valid verdict values: "supported", "partially_supported", "unsupported", "unverified"
3. If the evidence directly supports the claim → "supported"
4. If the evidence partially supports or suggests the claim → "partially_supported"
5. If the evidence contradicts the claim → "unsupported"
6. If evidence is insufficient or irrelevant → "unverified"
7. Be conservative: when in doubt, prefer "unverified" over guessing
8. Do NOT add explanations, only return the JSON

Claim: {claim}

Evidence passage: {passage}

{context_section}

Respond with ONLY a JSON object like {{"verdict": "supported"}}"""


class LLMProvider(VerificationProvider, ABC):
    """Base class for LLM-based verification providers."""

    DEFAULT_MODEL: str = ""

    def __init__(self, api_key: str, model: str | None = None, temperature: float = 0.0, max_tokens: int = 256) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        if not passage or not passage.strip():
            return None

        prompt = self._build_prompt(claim, passage, context)
        try:
            response_text = await self._call_llm(prompt)
            return self._parse_verdict(response_text)
        except Exception as e:
            logger.warning(f"LLM provider {self.__class__.__name__} failed: {e}")
            return None

    async def health_check(self) -> dict[str, object]:
        """Send a minimal request to verify the provider is reachable.

        Returns {"status": "ok", "provider": ..., "model": ...} on success,
        or {"status": "error", "error": ...} on failure.
        """
        try:
            result = await self.compare(
                "exercise improves cardiovascular health",
                "Studies show regular exercise is beneficial for heart health.",
            )
            return {"status": "ok", "provider": self.__class__.__name__, "model": self.model, "test_verdict": result.value if result else None}
        except Exception as e:
            return {"status": "error", "error": f"{self.__class__.__name__}: {e}"}

    def _build_prompt(self, claim: str, passage: str, context: str | None) -> str:
        context_section = f"Additional context: {context}" if context else "No additional context provided."
        return VERIFICATION_PROMPT.format(
            claim=claim,
            passage=passage,
            context_section=context_section,
        )

    @abstractmethod
    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM API and return the response text."""
        ...

    def _parse_verdict(self, response_text: str) -> Verdict | None:
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(text)
            verdict_str = data.get("verdict", "").lower()

            verdict_map = {
                "supported": Verdict.SUPPORTED,
                "partially_supported": Verdict.PARTIALLY_SUPPORTED,
                "unsupported": Verdict.UNSUPPORTED,
                "unverified": Verdict.UNVERIFIED,
            }

            return verdict_map.get(verdict_str)
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.warning(f"Failed to parse LLM response as verdict: {e}")
            return None


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider for evidence verification."""

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens)

    async def _call_llm(self, prompt: str) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return ""


class OpenAIProvider(LLMProvider):
    """OpenAI provider for evidence verification."""

    DEFAULT_MODEL = "gpt-4o-mini"
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens)

    async def _call_llm(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""


class GeminiProvider(LLMProvider):
    """Google Gemini provider for evidence verification."""

    DEFAULT_MODEL = "gemini-1.5-flash"
    API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens)

    async def _call_llm(self, prompt: str) -> str:
        url = self.API_URL_TEMPLATE.format(model=self.model)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }

        params = {"key": self.api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, params=params)
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if parts:
                return parts[0].get("text", "")
        return ""
