"""narrate_social() testleri — fail-closed garantisi ve sinir durumlari."""

import pytest

from evidence.chat.social_chat import narrate_social


class FakeProvider:
    def __init__(self, response: str | None = None, raises: bool = False):
        self.response = response
        self.raises = raises
        self.last_prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        if self.raises:
            raise RuntimeError("provider unavailable")
        return self.response


class TestNarrateSocial:
    @pytest.mark.asyncio
    async def test_none_when_no_provider(self):
        result = await narrate_social("greeting", "selam", [], provider=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_provider_raises(self):
        provider = FakeProvider(raises=True)
        result = await narrate_social("greeting", "selam", [], provider=provider)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_response_empty(self):
        provider = FakeProvider(response="   ")
        result = await narrate_social("greeting", "selam", [], provider=provider)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_response_too_long(self):
        provider = FakeProvider(response="x" * 501)
        result = await narrate_social("greeting", "selam", [], provider=provider)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_stripped_provider_text(self):
        provider = FakeProvider(response="  Merhaba! Nasıl yardımcı olabilirim?  ")
        result = await narrate_social("greeting", "selam", [], provider=provider)
        assert result == "Merhaba! Nasıl yardımcı olabilirim?"

    @pytest.mark.asyncio
    async def test_prompt_includes_user_message(self):
        provider = FakeProvider(response="ok")
        await narrate_social("smalltalk", "nasılsın?", [], provider=provider)
        assert "nasılsın?" in provider.last_prompt

    @pytest.mark.asyncio
    async def test_prompt_forbids_health_verdicts(self):
        """Prompt, LLM'in sohbet sirasinda saglik hukmu vermesini acikca yasaklamali —
        bu, sosyal katmanin claim-verification akisinin yerine gecmemesini saglar."""
        provider = FakeProvider(response="ok")
        await narrate_social("greeting", "selam", [], provider=provider)
        assert "hukum verme" in provider.last_prompt.lower() or "iddia" in provider.last_prompt.lower()

    @pytest.mark.asyncio
    async def test_includes_recent_history(self):
        provider = FakeProvider(response="ok")
        history = [
            {"role": "user", "content": "Kahve kolesterolü yükseltir mi?"},
            {"role": "assistant", "content": "Kanıtlar karışık..."},
        ]
        await narrate_social("thanks", "teşekkürler", history, provider=provider)
        assert "Kahve kolesterolü yükseltir mi?" in provider.last_prompt

    @pytest.mark.asyncio
    async def test_unknown_intent_type_falls_back_to_generic_label(self):
        provider = FakeProvider(response="ok")
        result = await narrate_social("some_future_intent", "hey", [], provider=provider)
        assert result == "ok"
