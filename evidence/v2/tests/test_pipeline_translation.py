"""translate_query_to_english testleri — Turkce->Ingilizce sorgu cevirisi.

Bu dosyanin varligi bilincli: fonksiyon daha once hic test edilmemisti.
"""

import pytest

from evidence.v2.pipeline.pipeline import translate_query_to_english


class TestNoFalsePositiveOnGoz:
    """Regresyon: bare 'göz' -> 'eye health...' eslesmesi 'gözlük'/'göz
    atmak' gibi alakasiz kelime/deyimleri de yakaliyordu. Bu fonksiyonun
    skor tabanli eslestirmesi yuzunden 'göz sağlığı' gibi bir bilesik
    eklemek de yetersizdi (bkz. pipeline.py'deki yorum) — bare girdi
    tamamen kaldirildi."""

    def test_gozluk_not_translated(self):
        q = "gözlüğümü kaybettim, yardım eder misin?"
        assert translate_query_to_english(q) == q

    def test_goz_atmak_idiom_not_translated(self):
        q = "şu ürüne bir göz atar mısın acaba?"
        assert translate_query_to_english(q) == q


class TestKnownTranslationsStillWork:
    """Sozlukteki diger girdiler hala calismali (regresyon)."""

    def test_glp1_translation(self):
        """GLP-1 kavrami + kilo/obezite kavrami sorguda gecmeli.

        NOT (2026-08-29): Bu assertion eskiden tam bir string esitligiydi
        ("GLP-1 weight loss semaglutide obesity") — bu, o zaman bu
        fonksiyonun kendi bagimsiz sozlugundeki (TURKISH_TO_ENGLISH_QUERIES,
        o zamandan beri kaldirildi — bkz. docs/ai-infrastructure-roadmap.md
        "Ek bulgu") tam kelime secimine bagliydi. Iki sozluk
        evidence/chat/search_query.py'deki tek sozlukte birlestirildikten
        sonra (farkli kelime secimiyle ama ayni kavramlarla) bu tam metin
        esitligi kirildi. Kavram-varligi kontrolüne gecmek, hangi sozlugun
        aktif oldugundan bagimsiz olarak dogru davranisi (glp-1 + kilo/obezite
        kavramlarinin sorguya girmesi) test eder.
        """
        result = translate_query_to_english("GLP-1 kilo kaybı gerçekten işe yarıyor mu?")
        result_lower = result.lower()
        assert "glp-1" in result_lower
        assert "weight" in result_lower or "obesity" in result_lower

    def test_short_query_returned_unchanged(self):
        # Az sayida Turkce ozel karakter -> ceviri denenmez (mevcut davranis).
        assert translate_query_to_english("coffee cholesterol") == "coffee cholesterol"


class TestDailyExposureClaimsTranslated:
    """Regresyon (2026-09-27): kullanicinin bildirdigi "saglik sorulari
    arastirilmiyor" vakasinda sozluk bosluğu vardi. Bu fonksiyon
    has_health_topic()u bir TRIC olarak kullaniyor (bkz. pipeline.py), yani
    ayni bosluk burada da Turkce sorguyu OLDUGU gibi birakmak demekti.
    Bilesik sozluk duzelmesinden sonra bu ucu de ceviriyor."""

    @pytest.mark.parametrize("query, expected", [
        ("zerdeçal iltihabı azaltır mı", "turmeric"),
        ("soğuk duş bağışıklığı güçlendirir mi", "shower"),
        ("mikrodalga yemeği zehirler mi", "microwave"),
    ])
    def test_reported_claims_reach_pubmed_in_english(self, query, expected):
        result = translate_query_to_english(query)
        assert result != query, f"{query!r} cevrilmedi (Turkce kaldi)"
        assert expected in result.lower(), f"{query!r} -> {result!r}"

    def test_ascii_typed_turkish_claim_translated(self):
        """Diyakritik kullanmayan Turkce kullanicilari (ozellikle mobil
        klavye/klavyeler arası gecis) icin de sozlukten gecis calismali —
        eskiden "soguk"/"algınligi" yazimi butun sozlugu atliyordu."""
        result = translate_query_to_english("c vitamini soguk alginligina iyi gelir mi")
        assert result == "vitamin c"

    def test_english_query_still_passes_through_unchanged(self):
        """Turkce iddialari sozlukten gecirmek Ingilizce sorgulari
        BOZMAMALI. Ingilizce metin sozlukte anahtar (terim) degil, deger
        iceriyor; bu yuzden has_turkish_term() False verir ve kestirim
        devreye girer (bkz. pipeline.py NOT 2026-09-27). Ayni sart
        evidence/tests/test_v2_pipeline_translate.py'da da sabitlenmistir."""
        query = "Does coffee raise cholesterol levels?"
        assert translate_query_to_english(query) == query

    def test_gibberish_unchanged(self):
        """Taninmayan metin sozlukten gecirilmez."""
        query = "asdkfjaslkdfj qwerty zxcvbn"
        assert translate_query_to_english(query) == query
