"""build_search_query birim testleri — Turkce sorudan Ingilizce anahtar kelime uretimi."""

import pytest

from evidence.chat.search_query import build_search_query, has_health_topic


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


class TestHasHealthTopic:
    """has_health_topic — build_search_query'nin aksine, eslesme yoksa False
    doner (fallback metni degil). Guvenlik kapisi icin dogru sinyal budur."""

    def test_true_for_real_health_claim(self):
        assert has_health_topic("Kahve kolesterolü yükseltir mi?") is True

    def test_false_for_name_introduction(self):
        # Regresyon: eskiden "adım" (step) sozlukte tekti ve "benim adım
        # Ümit" gibi bir isim tanitimini "steps walking" saglik konusuyla
        # eslestirip botun sahte bir hukum uretmesine yol aciyordu.
        assert has_health_topic("benim adım Ümit") is False

    def test_false_for_unrelated_smalltalk(self):
        assert has_health_topic("bugün hava çok güzel") is False

    def test_false_for_empty(self):
        assert has_health_topic("") is False
        assert has_health_topic(None) is False

    def test_true_for_step_count_compound(self):
        # "adim sayisi"/"gunluk adim" gibi belirgin iki-kelimelik kaliplar
        # hala taniniyor olmali — sadece tek basina "adim" kaldirildi.
        assert has_health_topic("günlük adım sayısı yeterli mi?") is True

    def test_false_for_goz_atmak_idiom(self):
        # Regresyon: bare "göz" -> "eye vision" eslesmesi "göz atmak" (bir
        # seye bakmak) gibi cok yaygin, saglikla alakasiz bir deyimi de
        # yakaliyordu.
        assert has_health_topic("şu ürüne bir göz atar mısın?") is False

    def test_true_for_goz_sagligi_compound(self):
        assert has_health_topic("göz sağlığı için havuç yemeli miyim?") is True

    def test_false_for_bare_letter_c(self):
        # Regresyon: bare "c" -> "c" eslesmesi herhangi bir yalniz "c"
        # harfini vitamin C sanıyordu.
        assert has_health_topic("c harfi ile başlayan bir kelime söyle") is False

    def test_true_for_vitamin_c_compound(self):
        assert has_health_topic("vitamin c bağışıklığa iyi gelir mi?") is True
        assert has_health_topic("c vitamini soğuk algınlığına iyi gelir mi?") is True
