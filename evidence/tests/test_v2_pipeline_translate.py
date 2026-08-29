"""evidence/v2/pipeline/pipeline.py'nin Turkce->Ingilizce sorgu cevirisi icin testler.

Bu modul eskiden kendi bagimsiz sozlugunu (TURKISH_TO_ENGLISH_QUERIES) ve
alt-dize+oran tabanli bir eslestirme kullaniyordu — evidence/chat/search_query.py'deki
sozlukten sapmisti ve orada zaten duzeltilmis olan "bare tek-kelimelik anahtar
alakasiz kelimelerin icinde eslesir" hata sinifini hala tasiyordu (bkz.
docs/ai-infrastructure-roadmap.md, "Ek bulgu"). Bu testler, iki sozlugun
tek bir kaynakta (chat/search_query.py) birlestirilmesinden sonra bu hata
sinifinin geri gelmedigini kilitler.
"""

from __future__ import annotations

from evidence.v2.pipeline.pipeline import get_search_query, translate_query_to_english


class TestTranslateQueryToEnglish:
    def test_bare_goz_does_not_overmatch_unrelated_word(self):
        """'Gözlük' (glasses) icinde 'göz' (eye) alt-dizesi var ama alakasiz
        bir konu — eski alt-dize+oran algoritmasi bunu saglik sorgusuna
        cevirirdi (skor >= 0.5, tek kelimelik anahtar icin kacinilmaz)."""
        query = "Gözlüğümü nereye koyduğumu şaşırdım şimdi böyle"
        result = translate_query_to_english(query)
        assert result == query  # Eslesme yok — orijinal aynen (cevrilmemis) doner

    def test_real_eye_health_phrase_still_matches(self):
        query = "göz sağlığı için hangi vitaminler önemlidir şimdi acaba"
        result = translate_query_to_english(query)
        assert "eye" in result.lower()

    def test_known_term_translates_via_unified_dictionary(self):
        query = "Kahve kolesterolü şişmanlığı artırır mı acaba şimdi"
        result = translate_query_to_english(query)
        assert "coffee" in result.lower()
        assert "cholesterol" in result.lower()

    def test_mostly_english_query_passed_through_unchanged(self):
        query = "Does coffee raise cholesterol levels?"
        result = translate_query_to_english(query)
        assert result == query

    def test_no_dedicated_dictionary_remains_on_this_module(self):
        """Iki ayri sozluk artik tek kaynakta birlesmis olmali — bu modulde
        kendi kopyasi kalmamali (regresyonu onlemek icin)."""
        import evidence.v2.pipeline.pipeline as pipeline_module
        assert not hasattr(pipeline_module, "TURKISH_TO_ENGLISH_QUERIES")


class TestGetSearchQuery:
    def test_returns_question_terminated_string(self):
        result = get_search_query("Kahve kolesterolü şişmanlığı artırır mı acaba şimdi")
        assert result.endswith("?")
