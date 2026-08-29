"""translate_query_to_english testleri — Turkce->Ingilizce sorgu cevirisi.

Bu dosyanin varligi bilincli: fonksiyon daha once hic test edilmemisti.
"""

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
