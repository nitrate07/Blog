"""build_search_query birim testleri — Turkce sorudan Ingilizce anahtar kelime uretimi."""

import pytest

from evidence.chat.search_query import build_search_query


class TestKnownTranslations:
    """Sozlukteki terimler dogru Ingilizce karsiliklara donusmeli."""

    def test_documented_example(self):
        assert build_search_query("Kahve kolesterolü yükseltir mi?") == "coffee cholesterol"

    def test_multi_term_query(self):
        assert build_search_query("Zeytinyağı kalp sağlığına faydalı mıdır?") == \
            "olive oil heart cardiovascular"

    @pytest.mark.parametrize("claim, expected", [
        ("Çay içmek iyi mi?", "tea"),
        ("Kreatin böbreğe zarar verir mi?", "creatine"),
        ("Balık yağı omega içerir mi", "fish omega-3"),
        ("Vitamin D3 kemiğe iyi gelir mi?", "vitamin d3"),
    ])
    def test_term_map_translations(self, claim, expected):
        assert build_search_query(claim) == expected


class TestQuestionFillerRemoval:
    """Soru kalip/eki ve doldurucu sozcukler temizlenmeli."""

    def test_nedir_removed(self):
        assert build_search_query("kahve nedir") == "coffee"

    def test_gercekten_and_acaba_removed(self):
        assert build_search_query("Kahve gerçekten kolesterolü yükseltir mi acaba?") == \
            "coffee cholesterol"

    def test_question_particle_dedupes_repeats(self):
        assert build_search_query("kahve mi çay mı kahve") == "coffee tea"


class TestUnknownTerms:
    """Sozlukte olmayan kavramlar elenmeli; hic eslesme yoksa orijinal korunmali."""

    def test_unknown_words_preserved_when_no_match(self):
        claim = "xyzabc krizinden atmak"
        assert build_search_query(claim) == claim

    def test_ascii_english_terms_pass_through(self):
        assert build_search_query("coffee cholesterol") == "coffee cholesterol"

    def test_known_abbreviation_ldl(self):
        assert build_search_query("LDL yükseltir mi tereyağı") == "ldl cholesterol"


class TestPrefixMatching:
    """Cekimli halller kok terime on-eslestirme ile yakalanmali."""

    def test_inflected_kolesterolu(self):
        assert build_search_query("kolesterolü düşürür mü") == "cholesterol"

    def test_inflected_stresi(self):
        assert build_search_query("stresi azaltır mı uyku") == "stress sleep"


class TestSafeInputs:
    """Bos/girdisiz girdi hata firlatmadan guvenli deger donmeli."""

    def test_empty_string(self):
        assert build_search_query("") == ""

    def test_none_argument(self):
        assert build_search_query(None) == ""

    def test_whitespace_only(self):
        assert build_search_query("   ") == ""
