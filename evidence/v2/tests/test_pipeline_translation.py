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
        result = translate_query_to_english("GLP-1 kilo kaybı gerçekten işe yarıyor mu?")
        assert result == "GLP-1 weight loss semaglutide obesity"

    def test_short_query_returned_unchanged(self):
        # Az sayida Turkce ozel karakter -> ceviri denenmez (mevcut davranis).
        assert translate_query_to_english("coffee cholesterol") == "coffee cholesterol"
