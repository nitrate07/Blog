"""LLM provider implementations for enhanced evidence verification."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import Verdict
from .providers import VerificationProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_EN = """You are Arı Kaynak's evidence verification assistant. You analyze health claims against scientific evidence.

CORE PRINCIPLES:
- Evidence-first: Never generate or assume evidence. Only analyze what is provided.
- Conservative: When uncertain, prefer "unverified" over guessing.
- Transparent: Always cite sources and explain your reasoning.
- Bilingual: You can respond in English or Turkish based on the user's language.

You have access to:
- PubMed/Crossref academic papers
- Existing Arı Kaynak fact-check archive
- Health organization guidelines (WHO, ESC, AHA, etc.)

Your role is to:
1. Verify claims against provided evidence passages
2. Explain verdicts with source citations
3. Never present unverified information as fact"""

SYSTEM_PROMPT_TR = """Sen Arı Kaynak'ın kanıt doğrulama asistanısın. Sağlık iddialarını bilimsel kanıtlara karşı analiz ediyorsun.

TEMEL İLKELER:
- Kanıt öncelikli: Asla kanıt üretme veya varsayma. Yalnızca sağlananı analiz et.
- Muhafazakar: Emin olmadığında, tahmin etmek yerine "doğrulanmamış"ı tercih et.
- Şeffaf: Her zaman kaynakları belirt ve mantığını açıkla.
- İki dilli: Kullanıcının diline göre İngilizce veya Türkçe yanıt verebilirsin.

Erişimin olan kaynaklar:
- PubMed/Crossref akademik makaleleri
- Mevcut Arı Kaynak doğrulama arşivi
- Sağlık kuruluşu kılavuzları (WHO, ESC, AHA, vb.)

Senin görevin:
1. İddiaları sağlanan kanıt pasajlarına göre doğrulamak
2. Kararları kaynak alıntılarıyla açıklamak
3. Doğrulanmamış bilgiyi asla gerçek gibi sunmamak"""

VERIFICATION_PROMPT = """Analyze whether the given claim is supported, partially supported, unsupported, or unverified based on the provided evidence passage.

RULES:
1. Return ONLY a JSON object with "verdict" and optionally "explanation" keys
2. Valid verdict values: "supported", "partially_supported", "unsupported", "unverified"
3. If the evidence directly supports the claim → "supported"
4. If the evidence partially supports or suggests the claim → "partially_supported"
5. If the evidence contradicts the claim → "unsupported"
6. If evidence is insufficient or irrelevant → "unverified"
7. Be conservative: when in doubt, prefer "unverified" over guessing
8. Include a brief explanation referencing the source

Claim: {claim}

Evidence passage: {passage}

{context_section}

Respond with ONLY a JSON object like {{"verdict": "supported", "explanation": "Brief reason..."}}"""


# ---------------------------------------------------------------------------
# Message types for conversation
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A single message in a conversation."""
    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class Conversation:
    """A conversation with history management."""
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    max_history: int = 20  # Keep last N message pairs

    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))
        self._trim()

    def add_assistant(self, content: str) -> None:
        self.messages.append(Message(role="assistant", content=content))
        self._trim()

    def get_messages_for_api(self) -> list[dict[str, str]]:
        """Get messages formatted for API calls."""
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in self.messages:
            result.append({"role": msg.role, "content": msg.content})
        return result

    def _trim(self) -> None:
        """Keep only recent messages to stay within limits."""
        if len(self.messages) > self.max_history * 2:
            # Keep system-related pairs at start, trim middle
            self.messages = self.messages[-(self.max_history * 2):]

    def clear(self) -> None:
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)


class LLMProvider(VerificationProvider, ABC):
    """Base class for LLM-based verification providers."""

    DEFAULT_MODEL: str = ""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        language: str = "en",
    ) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.language = language
        self._conversation = Conversation(
            system_prompt=SYSTEM_PROMPT_TR if language == "tr" else SYSTEM_PROMPT_EN
        )

    @property
    def conversation(self) -> Conversation:
        """Access the conversation history."""
        return self._conversation

    def reset_conversation(self) -> None:
        """Reset conversation history."""
        self._conversation.clear()

    async def chat(self, message: str, keep_history: bool = True) -> str:
        """Send a message and get a response (with conversation history).

        Args:
            message: The user message.
            keep_history: If True, maintains conversation history.

        Returns:
            The assistant's response text.
        """
        self._conversation.add_user(message)

        messages = self._conversation.get_messages_for_api()
        response = await self._call_llm_with_messages(messages)

        if keep_history:
            self._conversation.add_assistant(response)

        return response

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        """Compare a claim against evidence (verification mode)."""
        if not passage or not passage.strip():
            return None

        prompt = self._build_verification_prompt(claim, passage, context)
        try:
            response_text = await self._call_llm(prompt)
            return self._parse_verdict(response_text)
        except Exception as e:
            logger.warning(f"LLM provider {self.__class__.__name__} failed: {e}")
            return None

    async def generate(self, prompt: str) -> str:
        """Generate a response for a given prompt (interpreter mode)."""
        return await self._call_llm(prompt)

    async def health_check(self) -> dict[str, object]:
        """Send a minimal request to verify the provider is reachable."""
        try:
            result = await self.compare(
                "exercise improves cardiovascular health",
                "Studies show regular exercise is beneficial for heart health.",
            )
            return {
                "status": "ok",
                "provider": self.__class__.__name__,
                "model": self.model,
                "test_verdict": result.value if result else None,
            }
        except Exception as e:
            return {"status": "error", "error": f"{self.__class__.__name__}: {e}"}

    def _build_verification_prompt(self, claim: str, passage: str, context: str | None) -> str:
        context_section = f"Additional context: {context}" if context else "No additional context provided."
        return VERIFICATION_PROMPT.format(
            claim=claim,
            passage=passage,
            context_section=context_section,
        )

    @abstractmethod
    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM API with a single prompt (no history)."""
        ...

    @abstractmethod
    async def _call_llm_with_messages(self, messages: list[dict[str, str]]) -> str:
        """Call the LLM API with message history."""
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
    """Anthropic Claude provider for evidence verification and chat."""

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        language: str = "en",
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens, language)

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

    async def _call_llm(self, prompt: str) -> str:
        """Single prompt call (no history)."""
        messages = [{"role": "user", "content": prompt}]
        return await self._call_llm_with_messages(messages)

    async def _call_llm_with_messages(self, messages: list[dict[str, str]]) -> str:
        """Call Claude API with message history."""
        headers = self._get_headers()

        # Separate system message if present
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": user_messages,
        }

        if system_msg:
            payload["system"] = system_msg

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return ""


class OpenAIProvider(LLMProvider):
    """OpenAI provider for evidence verification and chat."""

    DEFAULT_MODEL = "gpt-4o-mini"
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        language: str = "en",
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens, language)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _call_llm(self, prompt: str) -> str:
        """Single prompt call (no history)."""
        messages = [{"role": "user", "content": prompt}]
        return await self._call_llm_with_messages(messages)

    async def _call_llm_with_messages(self, messages: list[dict[str, str]]) -> str:
        """Call OpenAI API with message history."""
        headers = self._get_headers()

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""


class GeminiProvider(LLMProvider):
    """Google Gemini provider for evidence verification and chat."""

    DEFAULT_MODEL = "gemini-1.5-flash"
    API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        language: str = "en",
    ) -> None:
        super().__init__(api_key, model, temperature, max_tokens, language)

    async def _call_llm(self, prompt: str) -> str:
        """Single prompt call (no history)."""
        contents = [{"parts": [{"text": prompt}]}]
        return await self._call_llm_with_contents(contents)

    async def _call_llm_with_messages(self, messages: list[dict[str, str]]) -> str:
        """Call Gemini API with message history (converted to contents)."""
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        return await self._call_llm_with_contents(contents)

    async def _call_llm_with_contents(self, contents: list[dict[str, Any]]) -> str:
        """Call Gemini API with contents format."""
        url = self.API_URL_TEMPLATE.format(model=self.model)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }

        params = {"key": self.api_key}

        async with httpx.AsyncClient(timeout=60.0) as client:
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
