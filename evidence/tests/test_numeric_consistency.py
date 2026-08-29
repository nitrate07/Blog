"""evidence/engine.py'deki sayisal-tutarlilik guvenlik agi testleri (2026-08-29).

Kullanicinin "GitHub'daki acik kaynaklara bak" talebi uzerine incelenen
humanchaos/factcheck projesinden uyarlandi: bir iddianin vurguladigi sayisal
buyukluk (yuzde/kat) en alakali kanit pasajindaki AYNI BIRIMLI sayidan
buyuk oranda (>=5x) farkliysa, kelime ortusmesi ne kadar yuksek olursa
olsun hukum UNSUPPORTED'a dusurulur — abartili saglik yanlis bilgisi
kaliplarina ("riski %500 artirir" gibi) karsi somut bir koruma.

compare_claim_evidence'in daha once (bu dosyadan once) HIC testi yoktu —
bu dosya hem yeni sayisal-tutarlilik davranisini hem de fonksiyonun genel
sozlesmesini (relevance esigi, negasyon/nitelik tespiti) kapsar.
"""

from __future__ import annotations

from evidence.engine import check_numeric_consistency, compare_claim_evidence
from evidence.models import Verdict


class TestExtractAndCheckNumericConsistency:
    def test_large_percentage_outlier_detected(self):
        result = check_numeric_consistency(
            "Kahve kanser riskini %500 artırır",
            "Çalışmalar kahve tüketiminin kanser riskini yaklaşık %15 artırdığını gösteriyor.",
        )
        assert result["outlier"] is True
        assert result["claim_value"] == 500.0
        assert result["evidence_value"] == 15.0
        assert result["unit"] == "%"

    def test_consistent_percentage_not_flagged(self):
        result = check_numeric_consistency(
            "Kahve kalp krizi riskini %20 artırır",
            "Araştırmaya göre kahve tüketimi kalp krizi riskini %18 artırıyor.",
        )
        assert result["outlier"] is False

    def test_multiplier_outlier_detected(self):
        result = check_numeric_consistency(
            "Bu ilaç kanser riskini 10 kat artırır",
            "Çalışma, ilacın kanser riskini yalnızca 1.2 kat artırdığını buldu.",
        )
        assert result["outlier"] is True
        assert result["unit"] == "kat"

    def test_mismatched_units_not_compared(self):
        """Farkli birimler (yuzde vs kat) kiyaslanmaz — kendi donusum
        varsayimimizin hatasini guvenlik kontrolune sokma riski
        alinmiyor, bilinerek."""
        result = check_numeric_consistency(
            "Kahve riski %50 artırır", "Kahve tüketimi riski 2 kat artırıyor.",
        )
        assert result["outlier"] is False

    def test_no_numbers_in_claim_not_flagged(self):
        result = check_numeric_consistency(
            "Kahve kalp sağlığına iyi gelir", "Çalışmalar kahvenin faydalı olduğunu gösteriyor.",
        )
        assert result["outlier"] is False

    def test_no_numbers_in_evidence_not_flagged(self):
        """Iddia sayi iceriyor ama kanit pasaji icermiyor — bu durumda
        kiyaslanacak bir sey yok, flag edilmemeli (yanlis-pozitif onlemek icin)."""
        result = check_numeric_consistency(
            "Kahve riski %50 artırır", "Kahve tüketimi riski artırıyor genel olarak.",
        )
        assert result["outlier"] is False

    def test_reasonable_rounding_not_flagged(self):
        """'2 kattan fazla' ~ '2.3 kat' gibi makul yuvarlamalar
        yanlislikla yakalanmamali (esik 5x, bu fark ~1.15x)."""
        result = check_numeric_consistency(
            "Risk 2 kat artıyor", "Çalışma 2.3 kat artış buldu.",
        )
        assert result["outlier"] is False

    def test_english_percent_word_recognized(self):
        result = check_numeric_consistency(
            "Coffee increases cancer risk by 500 percent",
            "Studies show coffee increases cancer risk by about 15%.",
        )
        assert result["outlier"] is True

    def test_closest_evidence_value_used_when_multiple_present(self):
        """Kanit pasajinda birden fazla sayi varsa, iddiaya EN YAKIN
        olani kiyaslama icin kullanilmali (en kucugu/buyugu degil)."""
        result = check_numeric_consistency(
            "Risk %20 artıyor",
            "Bir çalışmada %90, başka bir çalışmada ise %22 artış bulundu.",
        )
        assert result["outlier"] is False  # %20 vs %22 -> ratio ~1.1, tutarli


class TestCompareClaimEvidenceWithNumericGuard:
    """compare_claim_evidence'in tam sozlesmesi — sayisal guvenlik agi dahil."""

    def test_exaggerated_percentage_downgrades_supported_to_unsupported(self):
        """Kelime ortusmesi yuksek (SUPPORTED verirdi normalde) ama sayi
        30x farkli — hukum UNSUPPORTED'a dusurulmeli."""
        verdict, passage, relevance = compare_claim_evidence(
            "Kahve kanser riskini yüzde 500 artırır ciddi şekilde",
            "Çalışmalar kahve tüketiminin kanser riskini yüzde 15 artırdığını "
            "gösteriyor ciddi şekilde ve genel olarak.",
        )
        assert verdict == Verdict.UNSUPPORTED
        assert relevance >= 0.5  # kelime ortusmesi gercekten yuksekti

    def test_consistent_numbers_still_supported(self):
        verdict, passage, relevance = compare_claim_evidence(
            "Kahve kalp krizi riskini yüzde 20 artırır ciddi şekilde",
            "Çalışmalar kahve tüketiminin kalp krizi riskini yüzde 18 artırdığını "
            "gösteriyor ciddi şekilde ve genel olarak.",
        )
        assert verdict == Verdict.SUPPORTED

    def test_low_relevance_returns_unverified_before_numeric_check_runs(self):
        """Alakasiz bir pasaj icin, sayisal kontrol hic calismadan once
        UNVERIFIED donmeli — mevcut esik-once-davranisi bozulmamali."""
        verdict, passage, relevance = compare_claim_evidence(
            "Kahve kanser riskini yüzde 500 artırır",
            "Bu paragraf tamamen alakasiz bir konudan bahsediyor, hiçbir ortak kelime yok.",
        )
        assert verdict == Verdict.UNVERIFIED

    def test_no_numbers_falls_through_to_normal_lexical_logic(self):
        """Sayisal iddia yoksa, davranis eskisi gibi (kelime ortusmesi
        bazli) olmali — regresyon korumasi."""
        verdict, passage, relevance = compare_claim_evidence(
            "Kahve kalp sağlığına iyi gelir gerçekten çok",
            "Çalışmalar kahvenin kalp sağlığına iyi geldiğini gösteriyor gerçekten çok.",
        )
        assert verdict == Verdict.SUPPORTED

    def test_negation_still_detected_when_no_numbers_involved(self):
        """NOT: "değil" gibi bagimsiz olumsuzlama kelimeleri artik
        yakalaniyor (bkz. _NEGATIONS genisletmesi). Fiil-eki-tabanli
        olumsuzlama ("gelmediğini" gibi) ayri, daha buyuk bir problem —
        tam Turkce morfoloji gerektirir (bkz. Zeyrek sinirlamasi,
        docs/ai-infrastructure-roadmap.md) — bu PR'in kapsami disinda."""
        verdict, passage, relevance = compare_claim_evidence(
            "Kahve kalp sağlığı için iyi gerçekten çok",
            "Çalışmalar kahvenin kalp sağlığı için iyi değil olduğunu gösteriyor asla gerçekten çok.",
        )
        assert verdict == Verdict.UNSUPPORTED


class TestTurkishTokenizerFix:
    """_tokens — eskiden ASCII-only regex ([a-z0-9]) Turkce ozel
    karakterleri (ç,ğ,ı,ö,ş,ü) kelime siniri sayip kelimeleri
    parcaliyordu. Bu, compare_claim_evidence'in TUM Turkce metin
    karsilastirmasini sessizce bozuyordu."""

    def test_turkish_diacritic_words_preserved_intact(self):
        from evidence.engine import _tokens
        tokens = _tokens("Kahve kalp sağlığına iyi gelmediğini gösteriyor")
        assert "sağlığına" in tokens
        assert "gösteriyor" in tokens
        assert "gelmediğini" in tokens
        # Eskiden bunlarin yerine parcalanmis kalintilar geliyordu:
        assert "steriyor" not in tokens

    def test_turkish_word_overlap_correctly_detected(self):
        """Iki Turkce cumle arasindaki gercek kelime ortusmesi artik
        dogru tespit ediliyor — eskiden parcalanma yuzunden kacirilirdi."""
        verdict, passage, relevance = compare_claim_evidence(
            "D vitamini eksikliği kemik sağlığını olumsuz etkiler ciddi biçimde",
            "Araştırmalar D vitamini eksikliğinin kemik sağlığını olumsuz "
            "etkilediğini gösteriyor ciddi biçimde ve genel olarak.",
        )
        assert verdict == Verdict.SUPPORTED
        assert relevance >= 0.5
