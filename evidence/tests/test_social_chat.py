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


class HistoryCapableProvider:
    """Fake provider that also supports real multi-turn history (generate_with_history)."""

    def __init__(self, response: str = "ok"):
        self.response = response
        self.last_prompt: str | None = None
        self.last_history: list | None = None
        self.generate_called = False

    async def generate(self, prompt: str) -> str:
        self.generate_called = True
        self.last_prompt = prompt
        return self.response

    async def generate_with_history(self, prompt: str, history: list) -> str:
        self.last_prompt = prompt
        self.last_history = history
        return self.response


class TestNarrateSocialHistory:
    @pytest.mark.asyncio
    async def test_uses_generate_with_history_when_available_and_history_present(self):
        provider = HistoryCapableProvider()
        history = [{"role": "user", "content": "önceki soru"}, {"role": "assistant", "content": "önceki cevap"}]
        result = await narrate_social("thanks", "teşekkürler", history, provider=provider)
        assert result == "ok"
        assert provider.last_history == history
        assert provider.generate_called is False

    @pytest.mark.asyncio
    async def test_falls_back_to_generate_when_no_history(self):
        provider = HistoryCapableProvider()
        result = await narrate_social("greeting", "selam", [], provider=provider)
        assert result == "ok"
        assert provider.generate_called is True

    @pytest.mark.asyncio
    async def test_plain_fake_provider_without_generate_with_history_still_works(self):
        """Backward-compat: FakeProvider (no generate_with_history) always uses generate()."""
        provider = FakeProvider(response="ok")
        history = [{"role": "user", "content": "x"}]
        result = await narrate_social("thanks", "teşekkürler", history, provider=provider)
        assert result == "ok"


class TestNarrateSocialLanguage:
    """Regresyon (2026-08-29): narrate_social eskiden dili KULLANICI
    MESAJINDAN tahmin etmeye calisiyordu ("mesajin dilinde yanit ver") —
    ConversationManager.language'dan gelen ACIK sinyal yerine. Kisa/
    belirsiz mesajlarda (ör. "hi") yanlis dilde cevap riski vardi."""

    @pytest.mark.asyncio
    async def test_default_language_instructs_turkish(self):
        provider = FakeProvider(response="Merhaba!")
        await narrate_social("greeting", "hi", [], provider=provider)
        assert "Turkce yaz." in provider.last_prompt

    @pytest.mark.asyncio
    async def test_explicit_english_instructs_english(self):
        provider = FakeProvider(response="Hello!")
        await narrate_social("greeting", "hi", [], provider=provider, language="en")
        assert "Write in English." in provider.last_prompt
        assert "Turkce yaz." not in provider.last_prompt

    @pytest.mark.asyncio
    async def test_unsupported_language_falls_back_to_turkish_instruction(self):
        provider = FakeProvider(response="Merhaba!")
        await narrate_social("greeting", "bonjour", [], provider=provider, language="fr")
        assert "Turkce yaz." in provider.last_prompt
