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


class TestArchiveFirstResponse:
    """Iddia cevabi arsiv dosyasini link + damga ile on plana almali."""

    def setup_method(self):
        self.builder = ResponseBuilder()
        self.analyzer = IntentAnalyzer()

    def _results(self):
        return {
            "archive_results": [{
                "source": "archive",
                "title": "Filtresiz Kahve Gerçekten Kolesterolünüzü Yükseltiyor mu? — Arı Kaynak",
                "url": "https://nitrate07.github.io/Blog/tr/makaleler/turk-kahvesi.html",
                "passage": "Bir gönderi Türk kahvesinin filtresiz demleme yöntemini savunuyor",
                "verdict": "Büyük Ölçüde Desteklendi",
                "rating_value": 4,
                "distance": 0.42,
            }],
            "external_results": [{"title": "Coffee study", "journal": "J Nutr", "published_year": 2025}],
            "health_org_results": [],
            "contradictions": [],
            "total_sources": 5,
            "verdict": "unverified",
            "verdict_confidence": 0,
        }

    def _respond(self):
        intent = self.analyzer.analyze("kahve kolesterolü yükseltir mi?")
        from evidence.chat.sufficiency import SufficiencyResult, SufficiencyLevel
        suff = SufficiencyResult(level=SufficiencyLevel.SUFFICIENT, confidence=0.8)
        return self.builder.build(intent, suff, self._results(), None)

    def test_archive_link_in_response(self):
        r = self._respond()
        assert "[Filtresiz Kahve" in r.text and "](https://" in r.text

    def test_archive_verdict_used_when_engine_unverified(self):
        r = self._respond()
        assert "Büyük Ölçüde Desteklendi" in r.text
        assert "Unverified" not in r.text

    def test_stamp_and_stars_shown(self):
        r = self._respond()
        assert "Damga:" in r.text and "●●●●○" in r.text

    def test_followup_offers_article(self):
        r = self._respond()
        assert any("makale" in s for s in r.follow_up_suggestions)

    def test_no_archive_falls_back_cleanly(self):
        results = self._results()
        results["archive_results"] = []
        intent = self.analyzer.analyze("bilinmeyen bir iddia burada")
        from evidence.chat.sufficiency import SufficiencyResult, SufficiencyLevel
        suff = SufficiencyResult(level=SufficiencyLevel.SUFFICIENT, confidence=0.5)
        r = self.builder.build(intent, suff, results, None)
        assert "Doğrulanamadı" in r.text
        assert "📁" not in r.text


class FakeNarratorProvider:
    """narrate_verdict icin sahte LLM saglayicisi — gercek API cagrisi yapmaz."""

    def __init__(self, response: str | None = None, raises: bool = False):
        self.response = response
        self.raises = raises

    async def generate(self, prompt: str) -> str:
        if self.raises:
            raise RuntimeError("provider down")
        return self.response


class TestNarrationWiring:
    """ConversationManager._narrate_response — aciklayici + duzenleyici entegrasyonu."""

    def _results_dict(self):
        return {
            "archive_results": [],
            "external_results": [
                {"title": "Coffee Study", "url": "https://pubmed.ncbi.nlm.nih.gov/999/", "source": "pubmed", "source_type": "academic", "passage": "..."}
            ],
            "health_org_results": [],
        }

    @pytest.mark.asyncio
    async def test_no_llm_provider_returns_rule_based_text_unchanged(self):
        m = ConversationManager()
        assert m.llm_provider is None
        text = await m._narrate_response(
            claim="kahve kolesterolü yükseltir mi?",
            verdict_info={"verdict": "supported", "confidence": 0.8},
            results_dict=self._results_dict(),
            rule_based_text="KURAL TABANLI METIN",
        )
        assert text == "KURAL TABANLI METIN"

    @pytest.mark.asyncio
    async def test_no_verdict_returns_rule_based_text_even_with_provider(self):
        m = ConversationManager(llm_provider=FakeNarratorProvider(response="LLM metni (https://pubmed.ncbi.nlm.nih.gov/999/)"))
        text = await m._narrate_response(
            claim="kahve kolesterolü yükseltir mi?",
            verdict_info={"verdict": None, "confidence": 0.0},
            results_dict=self._results_dict(),
            rule_based_text="KURAL TABANLI METIN",
        )
        assert text == "KURAL TABANLI METIN"

    @pytest.mark.asyncio
    async def test_valid_llm_narration_replaces_rule_based_text(self):
        m = ConversationManager(llm_provider=FakeNarratorProvider(
            response="Kanıt destekliyor (https://pubmed.ncbi.nlm.nih.gov/999/)."
        ))
        text = await m._narrate_response(
            claim="kahve kolesterolü yükseltir mi?",
            verdict_info={"verdict": "supported", "confidence": 0.8},
            results_dict=self._results_dict(),
            rule_based_text="KURAL TABANLI METIN",
        )
        assert text == "Kanıt destekliyor (https://pubmed.ncbi.nlm.nih.gov/999/)."

    @pytest.mark.asyncio
    async def test_hallucinated_citation_falls_back_to_rule_based_text(self):
        m = ConversationManager(llm_provider=FakeNarratorProvider(
            response="Kanıt destekliyor (https://uydurma-kaynak.example/x)."
        ))
        text = await m._narrate_response(
            claim="kahve kolesterolü yükseltir mi?",
            verdict_info={"verdict": "supported", "confidence": 0.8},
            results_dict=self._results_dict(),
            rule_based_text="KURAL TABANLI METIN",
        )
        assert text == "KURAL TABANLI METIN"

    @pytest.mark.asyncio
    async def test_provider_failure_falls_back_to_rule_based_text(self):
        m = ConversationManager(llm_provider=FakeNarratorProvider(raises=True))
        text = await m._narrate_response(
            claim="kahve kolesterolü yükseltir mi?",
            verdict_info={"verdict": "supported", "confidence": 0.8},
            results_dict=self._results_dict(),
            rule_based_text="KURAL TABANLI METIN",
        )
        assert text == "KURAL TABANLI METIN"

    @pytest.mark.asyncio
    async def test_full_flow_with_llm_provider_stays_unbroken(self):
        """llm_provider ayarliyken bile tam handle_message akisi kirilmamali."""
        m = ConversationManager(llm_provider=FakeNarratorProvider(response="LLM yaniti."))
        r = await m.handle_message("selam")
        assert "None" not in r.text
