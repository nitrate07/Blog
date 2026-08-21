"""Sosyal niyet ve konusma akisi testleri — botun 'acemi' davranislari icin regresyon."""

import pytest

from evidence.chat.conversation import ConversationManager
from evidence.chat.intent import IntentAnalyzer, IntentType
from evidence.chat.response import ChatResponse, ResponseBuilder


class TestSocialIntentDetection:
    def setup_method(self):
        self.analyzer = IntentAnalyzer()

    @pytest.mark.parametrize("query", [
        "selam", "merhaba", "Merhabalar", "Selamünaleyküm".lower(),
        "günaydın", "hello", "hey",
    ])
    def test_greetings(self, query):
        intent = self.analyzer.analyze(query)
        assert intent.type == IntentType.GREETING, f"{query!r} -> {intent.type}"

    @pytest.mark.parametrize("query", ["nasılsın?", "nasıl gidiyor", "how are you"])
    def test_smalltalk(self, query):
        intent = self.analyzer.analyze(query)
        assert intent.type == IntentType.SMALLTALK, f"{query!r} -> {intent.type}"

    @pytest.mark.parametrize("query", ["kimsin?", "sen kimsin", "adın ne?", "who are you", "bot musun?"])
    def test_identity(self, query):
        intent = self.analyzer.analyze(query)
        assert intent.type == IntentType.IDENTITY, f"{query!r} -> {intent.type}"

    @pytest.mark.parametrize("query", ["teşekkürler", "sağol", "eyvallah", "thanks!"])
    def test_thanks(self, query):
        intent = self.analyzer.analyze(query)
        assert intent.type == IntentType.THANKS, f"{query!r} -> {intent.type}"

    @pytest.mark.parametrize("query", ["görüşürüz", "hoşça kal", "bye bye"])
    def test_farewell(self, query):
        intent = self.analyzer.analyze(query)
        assert intent.type == IntentType.FAREWELL, f"{query!r} -> {intent.type}"


class TestMixedMessagesAreClaims:
    """Selamlasma iceren ama gercek iddia tasiyan mesajlar VERIFY_CLAIM olmali."""

    def setup_method(self):
        self.analyzer = IntentAnalyzer()

    def test_greeting_plus_claim(self):
        intent = self.analyzer.analyze("selam, kahve kolesterolü yükseltir mi?")
        assert intent.type == IntentType.VERIFY_CLAIM

    def test_health_question_not_social(self):
        # "naber" pattern'i icerse bile saglik konusu varsa iddiadir
        intent = self.analyzer.analyze("merhaba, vitamin d eksikliği kemik erimesi yapar mı?")
        assert intent.type == IntentType.VERIFY_CLAIM


class TestNewClaimSameTopicNotFollowUp:
    """Ayni konuda YENI soru sorusu follow-up sanilmamali (regresyon: 'neden None?')."""

    def setup_method(self):
        self.analyzer = IntentAnalyzer()
        self.history = [
            {"role": "user", "content": "kahve kolesterolü yükseltir mi?"},
            {"role": "assistant", "content": "Hüküm: mostly supported..."},
        ]

    def test_new_question_same_topic(self):
        intent = self.analyzer.analyze(
            "kreatin böbreğe zarar verir mi?",
            conversation_history=self.history,
            last_claim="kahve kolesterolü yükseltir mi?",
            last_verdict="mostly_supported",
        )
        assert intent.type == IntentType.VERIFY_CLAIM

    def test_short_nonquestion_same_topic_is_followup(self):
        # Soru degil, ayni topic, kisa -> follow-up makul
        intent = self.analyzer.analyze(
            "kolesterol için daha fazla kanıt verir misin",
            conversation_history=self.history,
            last_claim="kahve kolesterolü yükseltir mi?",
            last_verdict="mostly_supported",
        )
        assert intent.type in {
            IntentType.FOLLOW_UP_WHY,
            IntentType.FOLLOW_UP_MORE,
        }


class TestSocialResponses:
    def setup_method(self):
        self.builder = ResponseBuilder()

    def _social(self, itype):
        return self.builder.build_social(
            IntentAnalyzer().analyze({"greeting": "selam", "smalltalk": "nasılsın",
                                      "identity": "kimsin?", "thanks": "sağol",
                                      "farewell": "görüşürüz"}[itype])
        )

    def test_all_social_intents_have_expert_text(self):
        for itype in ["greeting", "smalltalk", "identity", "thanks", "farewell"]:
            r = self._social(itype)
            assert isinstance(r, ChatResponse)
            assert len(r.text) > 40, f"{itype} cevabi cok kisa"
            assert r.confidence == 1.0
            assert r.sources_cited == 0

    def test_greeting_introduces_persona(self):
        r = self._social("greeting")
        assert "Arı Kaynak" in r.text
        assert len(r.follow_up_suggestions) >= 2

    def test_identity_explains_method(self):
        r = self._social("identity")
        assert "PubMed" in r.text or "Cochrane" in r.text


class TestConversationFlow:
    @pytest.mark.asyncio
    async def test_greeting_does_not_pollute_state(self):
        m = ConversationManager()
        await m.handle_message("selam")
        assert m.state.current_claim is None
        assert m.state.current_verdict is None

    @pytest.mark.asyncio
    async def test_full_flow_no_broken_output(self):
        m = ConversationManager()
        answers = []
        for q in ["selam", "merhaba", "nasılsın?", "kimsin?", "teşekkürler"]:
            r = await m.handle_message(q)
            answers.append(r.text)
        for text in answers:
            assert "None" not in text, f"Bozuk cikti: {text[:100]}"
            assert "Kullaniciya sor" not in text

    @pytest.mark.asyncio
    async def test_insufficient_evidence_message_is_user_friendly(self):
        m = ConversationManager()
        r = await m.handle_message("kahve kolesterolü yükseltir mi?")
        assert "henüz yeterli kanıt toplayamadım" in r.text
        assert "Kullaniciya sor" not in r.text
        assert "Nedenler:" not in r.text

    @pytest.mark.asyncio
    async def test_follow_up_why_without_context_is_graceful(self):
        m = ConversationManager()
        await m.handle_message("kahve kolesterolü yükseltir mi?")
        r = m.response_builder.build_social.__self__ if False else None  # noqa: F841
        # follow_up_why yolu context olmadan cagrilabilir mi kontrol et
        from evidence.chat.intent import Intent, Topic
        intent = Intent(
            type=IntentType.FOLLOW_UP_WHY,
            confidence=0.7,
            topic=Topic.GENERAL,
            original_query="neden böyle?",
            cleaned_query="neden böyle?",
        )
        resp = m.response_builder.build(intent, None, None, None)
        assert "None" not in resp.text
