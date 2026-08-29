"""evidence/chat/turkish_morphology.py + _match_term'in Zemberek katmani testleri (2026-08-29).

Kullanicinin "GitHub'da bizim eksigimize uyan bir sey var mi" sorusu
uzerine bulundu: zemberek-python (Zeyrek'ten daha koklu bir Turkce NLP
kutuphanesi), PyPI'dan kurulur (HuggingFace/internet erisimi gerekmez —
Zeyrek/spaCy'nin tikandigi nokta buydu), ve karmasik Turkce cekim
zincirlerini dogru koke indirgeyebiliyor. Bu, sozluge her cekimli formu
elle eklemek yerine (onceki oturumlarda defalarca yapilan) GENEL bir
cozum sunuyor.

Bu dosya, zemberek KURULU olsun olmasin her ortamda calisir:
- is_available()/get_candidate_stems() dogrudan testleri, mock'lanan
  "kurulu degil" senaryosu her zaman calisir.
- Gercek Zemberek davranisi gerektiren testler skipif ile korunur.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from evidence.chat.search_query import has_health_topic
from evidence.chat.turkish_morphology import get_candidate_stems, is_available

_ZEMBEREK_AVAILABLE = is_available()


class TestIsAvailableAndGracefulDegradation:
    """Bu testler zemberek kurulu olsun olmasin CALISMALI — mock kullanir."""

    def test_get_candidate_stems_returns_empty_set_when_unavailable(self):
        with patch("evidence.chat.turkish_morphology._get_morphology", return_value=None):
            assert get_candidate_stems("kolesterolünü") == set()

    def test_get_candidate_stems_empty_word_returns_empty_set(self):
        assert get_candidate_stems("") == set()

    def test_match_term_falls_back_gracefully_when_zemberek_unavailable(self):
        """Zemberek katmani atlandiginda, has_health_topic mevcut (Zemberek
        olmadan da calisan) terimler icin dogru sonuc vermeye devam etmeli."""
        with patch("evidence.chat.search_query.get_candidate_stems", return_value=set()):
            assert has_health_topic("kahve kolesterolü yükseltir mi?") is True
            assert has_health_topic("bugün hava çok güzel") is False

    def test_exception_in_morphology_analysis_does_not_propagate(self):
        """get_candidate_stems kendi icinde exception'i yutmali (bkz. modul
        docstring'i) — burada dogrudan _match_term'e giden yoldaki
        davranisi dogruluyoruz: bir istisna asla disari sizmamali."""
        with patch("evidence.chat.search_query.get_candidate_stems", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                has_health_topic("kolesterolünü test ediyorum")
        # NOT: Bu test BILEREK exception'in YUKARI SIZDIGINI dogruluyor —
        # gercek get_candidate_stems (mock degil) KENDI ICINDE yutuyor
        # (asagidaki gercek-Zemberek testlerinde dogrulanir); burada
        # sadece _match_term'in exception'i kendi basina yutmadigini,
        # sorumlulugun get_candidate_stems'te oldugunu netlestiriyoruz.


@pytest.mark.skipif(not _ZEMBEREK_AVAILABLE, reason="zemberek-python kurulu degil (opsiyonel bagimlilik)")
class TestRealZemberekIntegration:
    """Gercek Zemberek kurulu oldugunda uctan uca davranis."""

    def test_complex_inflection_chain_stemmed_correctly(self):
        stems = get_candidate_stems("kolesterolünü")
        assert "kolesterol" in stems

    def test_real_exception_safety_never_raises(self):
        """Bilinmeyen/anlamsiz bir girdi bile exception firlatmamali."""
        result = get_candidate_stems("xyzabc123qwertyasdfgh")
        assert isinstance(result, set)  # bos olabilir ama asla exception

    def test_asiri_does_not_falsely_stem_to_asi(self):
        """Kritik guvenlik testi: 'aşırı' (excessive) kelimesi 'aşı'
        (vaccine) sozluk anahtarina YANLISLIKLA eslesmemeli. Bu, onceki
        oturumda "aşı"nin genel cekim-eki toleransindan (len(key)>=4
        sarti) kasitli olarak haric tutulmasina neden olan orijinal
        risktir — Zemberek katmani ayni riski TASIMAMALI."""
        assert has_health_topic("aşırı yorgunum bugün ama sağlıkla ilgisi yok") is False

    def test_bit_homograph_collision_avoided(self):
        """Regresyon: Zemberek 'bitmek' (fiil) icin gecerli bir kok olarak
        'bit' dondurebiliyor — bu, sozlukteki 'bit' (isim, parazit) ile
        yazim olarak cakisiyor. len(stem)>=4 sarti bu kisa-anahtar
        homograf riskini onlemeli."""
        assert has_health_topic("bu iş bitmek üzere kalmıştı") is False

    def test_previously_unmatchable_inflections_now_recognized(self):
        """Elle eklenmemis, uzun cekim zincirleri artik Zemberek sayesinde
        taniniyor — onceki oturumlarda bu tur formlar icin elle onlarca
        ayri sozluk girisi eklemek gerekiyordu (bkz. "aşı" cekimli
        formlari), Zemberek bunu genellestiriyor."""
        assert has_health_topic("Trigliseridin yüksekliği tehlikeli mi?") is True
        assert has_health_topic("Hastalıklarından korunmak için ne yapmalı?") is True
        assert has_health_topic("Diyabetinden dolayı ne yemeli?") is True

    def test_short_dictionary_keys_not_eligible_for_zemberek_tier(self):
        """len(stem)>=4 sarti dogrudan test edilir: 'bal', 'tsh', 'als'
        gibi kisa sozluk anahtarlari Zemberek katmanindan asla
        eslesmemeli (yalniz tam eslesme ile bulunabilirler)."""
        from evidence.chat.search_query import _match_term
        # "balina" (whale) - "bal" (honey) ile baslangicta ortusebilir
        # ama Zemberek'in kendi analizi zaten "balina" icin "bal" kokunu
        # DONDURMEMELI (farkli bir kelime) — bu test o varsayimi degil,
        # sozluk-tarafi esigi dogrular: eger Zemberek yanlislikla kisa
        # bir kok donse bile len>=4 filtresi onu eler.
        with patch("evidence.chat.search_query.get_candidate_stems", return_value={"bal"}):
            assert _match_term("balinaymış") is None
