"""Cift dilli (TR/EN) cevap uretimi testleri (2026-08-29).

Kullanicinin canli bir ekran goruntusunde fark ettigi karisik-dil
deneyimi uzerine eklendi: backend'in tum sabit sablon metinleri
(hukum etiketleri, oneri dugmeleri, durum mesajlari) hardcoded
Turkce'ydi, hangi sayfadan (ask.html EN / tr/ask.html TR) istek
geldigine bakilmiyordu. Bu dosya:
1. i18n.py'nin temel sozlesmesini (t(), normalize_language()).
2. response.py'nin her iki dilde de dogru calistigini.
3. ConversationManager'in language parametresini dogru akittigini.
"""

from __future__ import annotations

import pytest

from evidence.chat.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language, t
from evidence.chat.intent import Intent, IntentType, Topic
from evidence.chat.response import ResponseBuilder
from evidence.chat.sufficiency import SufficiencyLevel, SufficiencyResult


class TestI18nCore:
    def test_normalize_language_accepts_supported(self):
        assert normalize_language("tr") == "tr"
        assert normalize_language("en") == "en"
        assert normalize_language("EN") == "en"  # buyuk/kucuk harf duyarsiz

    def test_normalize_language_falls_back_to_default_for_unsupported(self):
        assert normalize_language("fr") == DEFAULT_LANGUAGE
        assert normalize_language("de") == DEFAULT_LANGUAGE

    def test_normalize_language_falls_back_to_default_for_none(self):
        assert normalize_language(None) == DEFAULT_LANGUAGE

    def test_default_language_is_turkish(self):
        """Geriye donuk uyumluluk: dil belirtilmezse mevcut (Turkce) davranis korunmali."""
        assert DEFAULT_LANGUAGE == "tr"

    def test_t_returns_correct_language(self):
        assert t("verdict.supported", "tr") == "Destekleniyor"
        assert t("verdict.supported", "en") == "Supported"

    def test_t_falls_back_to_default_for_unsupported_language(self):
        assert t("verdict.supported", "fr") == t("verdict.supported", "tr")

    def test_t_never_raises_on_unknown_key(self):
        """Bilinmeyen bir anahtar exception firlatmamali — anahtarin
        kendisini gorunur bir 'eksik ceviri' isareti olarak dondurur."""
        result = t("nonexistent.key.xyz", "en")
        assert result == "nonexistent.key.xyz"

    def test_t_formats_placeholders(self):
        result = t("verify.verdict_line", "en", verdict="Supported", confidence="90")
        assert result == "**Verdict:** Supported (confidence 90%)"

    def test_t_never_raises_on_missing_format_kwargs(self):
        """Format placeholder eksikse ham metni dondurur, exception firlatmaz."""
        result = t("verify.verdict_line", "en")  # verdict/confidence eksik
        assert isinstance(result, str)

    def test_all_keys_have_both_supported_languages(self):
        """Her ceviri anahtarinin TR ve EN'in ikisi de olmali — eksik bir
        ceviri sessizce Turkce'ye duser (fallback), ama bu testin amaci
        eksik cevirileri PROAKTIF olarak yakalamak."""
        from evidence.chat.i18n import _T
        incomplete = []
        for key, translations in _T.items():
            missing = [lang for lang in SUPPORTED_LANGUAGES if lang not in translations]
            if missing:
                incomplete.append((key, missing))
        assert incomplete == [], f"Eksik ceviriler: {incomplete}"


def _intent(query: str = "test", intent_type: IntentType = IntentType.GREETING) -> Intent:
    return Intent(
        type=intent_type,
        confidence=0.9,
        topic=Topic.GENERAL,
        original_query=query,
        cleaned_query=query,
    )


def _sufficient() -> SufficiencyResult:
    return SufficiencyResult(level=SufficiencyLevel.SUFFICIENT, confidence=0.8)


class TestResponseBuilderBilingual:
    """response.py'nin her iki dilde de dogru calistigini dogrular."""

    def setup_method(self):
        self.rb = ResponseBuilder()

    def test_social_greeting_turkish_default(self):
        r = self.rb.build_social(_intent(intent_type=IntentType.GREETING))
        assert "Merhaba" in r.text
        assert "Kahve kolesterolü yükseltir mi?" in r.follow_up_suggestions

    def test_social_greeting_english(self):
        r = self.rb.build_social(_intent(intent_type=IntentType.GREETING), language="en")
        assert "Hello" in r.text
        assert "Does coffee raise cholesterol?" in r.follow_up_suggestions

    def test_social_identity_bilingual(self):
        r_tr = self.rb.build_social(_intent(intent_type=IntentType.IDENTITY))
        r_en = self.rb.build_social(_intent(intent_type=IntentType.IDENTITY), language="en")
        assert "Soruşturucusu" in r_tr.text
        assert "Investigator" in r_en.text

    def test_unrecognized_claim_bilingual_with_interpolation(self):
        """Kullanicinin orijinal sorgusu her iki dilde de dogru enjekte edilmeli."""
        r_tr = self.rb._unrecognized_claim(_intent(query="asdkfj"))
        r_en = self.rb._unrecognized_claim(_intent(query="asdkfj"), language="en")
        assert "asdkfj" in r_tr.text and "tanıyamadım" in r_tr.text
        assert "asdkfj" in r_en.text and "couldn't recognize" in r_en.text

    def test_insufficient_response_bilingual(self):
        intent = _intent(query="Xyz claim")
        suff = SufficiencyResult(level=SufficiencyLevel.INSUFFICIENT, confidence=0.2)
        r_tr = self.rb._build_insufficient_response(intent, suff)
        r_en = self.rb._build_insufficient_response(intent, suff, language="en")
        assert "yeterli kanıt toplayamadım" in r_tr.text
        assert "haven't gathered enough evidence" in r_en.text
        assert "Xyz claim" in r_tr.text and "Xyz claim" in r_en.text

    def test_verify_claim_no_results_bilingual(self):
        intent = _intent(query="Test claim")
        r_tr = self.rb._respond_verify_claim(intent, _sufficient(), None, None)
        r_en = self.rb._respond_verify_claim(intent, _sufficient(), None, None, language="en")
        assert "kanit bulunamadi" in r_tr.text.lower()
        assert "no evidence found" in r_en.text.lower()

    def test_verify_claim_full_response_bilingual(self):
        """Gercek bir hukum-uretilmis cevabin her iki dilde de dogru
        etiketler kullandigini dogrular — VERDICT_TR'nin yerini alan
        i18n katmaninin dogru calistigi ana senaryo."""
        intent = _intent(query="Coffee claim")
        results = {
            "archive_results": [],
            "external_results": [
                {"title": "Some Study", "journal": "J Med", "published_year": 2024, "url": "https://example.com/1"},
            ],
            "health_org_results": [],
            "total_sources": 1,
            "verdict": "mostly_supported",
            "verdict_confidence": 0.75,
        }
        r_tr = self.rb._respond_verify_claim(intent, _sufficient(), results, None)
        r_en = self.rb._respond_verify_claim(intent, _sufficient(), results, None, language="en")
        assert "Büyük Ölçüde Destekleniyor" in r_tr.text
        assert "güven %75" in r_tr.text
        assert "Largely Supported" in r_en.text
        assert "confidence 75%" in r_en.text
        assert "kaynak" in r_tr.text.lower() and "incelendi" in r_tr.text.lower()
        assert "sources" in r_en.text.lower() and "examined" in r_en.text.lower()

    def test_follow_up_why_bilingual(self):
        intent = _intent(query="Test", intent_type=IntentType.FOLLOW_UP_WHY)
        context = {
            "claim_text": "Test claim",
            "verdict": "supported",
            "confidence": 0.8,
            "sources_count": 3,
        }
        r_tr = self.rb._respond_follow_up_why(intent, _sufficient(), None, context)
        r_en = self.rb._respond_follow_up_why(intent, _sufficient(), None, context, language="en")
        assert "hüküm gerekçesi" in r_tr.text.lower()
        assert "reasoning for the verdict" in r_en.text.lower()
        assert "Destekleniyor" in r_tr.text
        assert "Supported" in r_en.text

    def test_challenge_verdict_bilingual(self):
        intent = _intent(query="Test", intent_type=IntentType.CHALLENGE_VERDICT)
        results = {"contradictions": [], "total_sources": 5}
        r_tr = self.rb._respond_challenge_verdict(intent, _sufficient(), results, None)
        r_en = self.rb._respond_challenge_verdict(intent, _sufficient(), results, None, language="en")
        assert "Itiraziniz degerlendirildi" in r_tr.text
        assert "objection was considered" in r_en.text
        assert "Toplam 5 kaynak" in r_tr.text
        assert "5 sources" in r_en.text

    def test_meta_question_bilingual(self):
        intent = _intent(intent_type=IntentType.META_QUESTION)
        r_tr = self.rb._respond_meta_question(intent, _sufficient(), None, None)
        r_en = self.rb._respond_meta_question(intent, _sufficient(), None, None, language="en")
        assert "Arı Kaynak Evidence Engine" in r_tr.text
        assert "Arı Kaynak Evidence Engine" in r_en.text
        assert "kanit uretmez" in r_tr.text.lower()
        assert "never generates evidence" in r_en.text.lower()

    def test_unknown_language_falls_back_to_turkish(self):
        """Desteklenmeyen bir dil kodu gonderilirse Turkce'ye duser,
        exception firlatmaz."""
        r = self.rb.build_social(_intent(intent_type=IntentType.GREETING), language="fr")
        assert "Merhaba" in r.text


class TestConversationManagerLanguagePropagation:
    """ConversationManager'in language parametresini dogru akittigini dogrular."""

    def test_default_language_is_turkish(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager()
        assert m.language == "tr"

    def test_explicit_english_language_stored(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager(language="en")
        assert m.language == "en"

    def test_unsupported_language_normalized_at_construction(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager(language="fr")
        assert m.language == "tr"

    @pytest.mark.asyncio
    async def test_english_manager_produces_english_greeting(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager(language="en")
        r = await m.handle_message("hello")
        assert "Hello" in r.text

    @pytest.mark.asyncio
    async def test_turkish_manager_produces_turkish_greeting(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager(language="tr")
        r = await m.handle_message("merhaba")
        assert "Merhaba" in r.text

    @pytest.mark.asyncio
    async def test_english_manager_unrecognized_claim_in_english(self):
        from evidence.chat.conversation import ConversationManager
        m = ConversationManager(language="en")
        r = await m.handle_message("Bu doğru mu?")
        assert "couldn't recognize" in r.text.lower()
