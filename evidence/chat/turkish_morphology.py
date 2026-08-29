"""Zemberek tabanli Turkce morfolojik kok bulma — opsiyonel, guvenli bir katman.

NOT (2026-08-29): Bu oturumda daha once Zeyrek denenmisti (bkz. git gecmisi/
docs/ai-infrastructure-roadmap.md) ve tek basina yetersiz bulunmustu — context-
tabanli disambiguation gerektiren belirsizlikleri (ör. "adım" = isim mi, adim
sayisi mi) cozmuyordu. Kullanicinin "GitHub'da bizim eksigimize uyan bir sey
var mi" sorusu uzerine `zemberek-python` (Turkiye'nin en koklu acik kaynak
Turkce NLP projesinin Python porti) bulundu ve test edildi:

- pip ile PyPI'dan kurulur (HuggingFace/internet erisimi GEREKMEZ — Zeyrek/
  spaCy'nin tikandigi nokta buydu).
- Ham morfolojik analiz kalitesi Zeyrek'ten belirgin sekilde daha iyi: karmasik
  cekim zincirlerini ("kolesterolünü", "aşılarını", "hastalıklarından") dogru
  koke indirgeyebiliyor — bu, sozluge her cekimli formu (aşılar/aşıyı/aşının...)
  tek tek elle eklemek yerine GENEL bir cozum sunuyor.
- "aşırı" (excessive) kelimesi test edildi ve doğru sekilde KENDI kokunde
  kaliyor, "aşı"ya kaymiyor — bu, önceki oturumda "aşı"nin genel cekim-eki
  toleransindan (len(key)>=4 sarti) bilerek haric tutulmasina neden olan
  cakisma riskini TASIMIYOR.
- Zemberek'in KENDI cumle-bazli disambiguator'i de "Benim adım Ahmet"
  ornegini test edildiginde yanlis kok seciyordu — yani tam disambiguation
  sorunu hala cozulmedi. Bu modul bu yuzden BILEREK disambiguation
  YAPMIYOR — yalnizca "bu kelimenin olasi koklerinden HERHANGI biri sozlukte
  var mi" sorusuna cevap veriyor (bkz. get_candidate_stems). Bu, mevcut
  sozlukte "göz" gibi riskli bare anahtarlarin OLMAMASI sayesinde guvenli:
  "gözlüğümü" belirsiz sekilde hem "gözlük" hem "göz" kokunu dondurebiliyor,
  ama "göz" sozlukte bare bir anahtar olarak olmadigi icin bu yeni bir
  yanlis-pozitif riski YARATMIYOR.

Opsiyonel bagimlilik (bkz. evidence/requirements-turkish-nlp.txt) — kurulu
degilse is_available() False doner, cagiran taraf mevcut (char-bazli
suffix-tolerans) davranisina geri duser. ~95MB paket + ~4s tek-seferlik
baslatma maliyeti oldugu icin core requirements.txt'e DAHIL EDILMEDI.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_morphology():
    """Zemberek TurkishMorphology tekil ornegini tembel-yukler (~4s, bir kez).

    Basarisizlikta None doner — cagiran taraf is_available() ile kontrol
    etmeli, exception hic disari sizmaz.
    """
    try:
        from zemberek import TurkishMorphology
        return TurkishMorphology.create_with_defaults()
    except Exception as e:
        logger.info(f"Zemberek kullanilamiyor (opsiyonel bagimlilik): {e}")
        return None


def is_available() -> bool:
    """zemberek-python kurulu ve baslatilabilir mi?"""
    return _get_morphology() is not None


def get_candidate_stems(word: str) -> set[str]:
    """Bir kelimenin TUM olasi morfolojik koklerini (belirsizlik dahil) dondurur.

    NOT: Disambiguation YAPILMAZ (bkz. modul docstring'i) — birden fazla
    olasi kok dondurulebilir. Cagiran taraf bunlari yalnizca EXACT MATCH
    icin bir sozlukte arama gibi guvenli, dar bir amacla kullanmali;
    "bu kelime kesin olarak X anlamina gelir" gibi bir yorum YAPILMAMALI.

    zemberek kurulu degilse veya herhangi bir hata olursa bos kume doner
    — asla exception firlatmaz (fail-closed, cagiran tarafin mevcut
    davranisina sessizce geri donmesini saglar).
    """
    morphology = _get_morphology()
    if morphology is None or not word:
        return set()

    try:
        result = morphology.analyze(word)
        return {
            r.get_stem()
            for r in result.analysis_results
            if not r.is_unknown() and r.get_stem()
        }
    except Exception as e:
        logger.debug(f"Zemberek analiz hatasi ({word!r}): {e}")
        return set()
