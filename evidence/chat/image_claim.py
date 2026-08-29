"""Ekran goruntusu -> dogrulanabilir iddia metni koprusu.

evidence/vision/ocr.py yalnizca ham metin cikarir; bu modul o metni mevcut
sohbet/dogrulama hattina (ConversationManager.handle_message, has_health_topic)
sokulmaya hazir hale getirir: OCR basarisiz olursa, metin bossa, ya da
cikan metinde bilinen hicbir saglik/tibbi kavram yoksa (yanlislikla
yuklenen alakasiz bir ekran goruntusu gibi) kullanicidan netlestirme
istenmesi gereken net bir durum doner — sessizce bos/anlamsiz bir sorguyu
arastirma hattina sokmaz.

Kapsam disi (bilerek, bkz. evidence/vision/__init__.py): API upload
endpoint'i (multipart form, boyut/rate-limit, guvenlik taramasi) burada
DEGIL — bu modul yalnizca "goruntu -> metin -> dogrulanabilir mi" mantigini
saglar; HTTP katmani ayri, kendi PR'ini hak eden bir istir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .search_query import has_health_topic
from ..vision.ocr import OcrResult, extract_text_from_image, is_ocr_available

# OCR guvenilirligi bu esigin altindaysa metni oldugu gibi kabul etmek yerine
# uyari isaretlenir (kullaniciya "OCR emin degil" bilgisini tasimak icin) —
# yine de arastirma hattina sokulur, sadece dusuk-guven bayragi eklenir.
_LOW_CONFIDENCE_THRESHOLD = 40.0


@dataclass
class ImageClaimResult:
    """Bir goruntuden iddia cikarma girisiminin sonucu."""

    success: bool
    claim_text: str = ""
    ocr_confidence: float = 0.0
    low_confidence: bool = False
    has_recognized_topic: bool = False
    error: str | None = None

    @property
    def ready_for_verification(self) -> bool:
        """Bu sonuc dogrudan ConversationManager.handle_message'a beslenebilir mi?"""
        return self.success and bool(self.claim_text.strip())


def extract_claim_from_image(image: Any) -> ImageClaimResult:
    """Bir goruntudeki (ekran goruntusu vb.) metni cikarip dogrulamaya hazirlar.

    OCR basarisiz olursa (Tesseract kurulu degil, bozuk dosya, cok buyuk
    goruntu vb.) ya da metin bossa, `success=False` + insan-okunabilir
    `error` doner — cagiran taraf bunu dogrudan kullaniciya gosterebilir.
    """
    if not is_ocr_available():
        return ImageClaimResult(
            success=False,
            error=(
                "Goruntu isleme su an kullanilamiyor (Tesseract OCR kurulu "
                "degil veya Turkce dil verisi eksik). Iddiayi yazili olarak "
                "sorabilirsiniz."
            ),
        )

    result: OcrResult = extract_text_from_image(image)
    if not result.success:
        return ImageClaimResult(success=False, error=result.error)

    if result.is_empty:
        return ImageClaimResult(
            success=False,
            error=(
                "Goruntude okunabilir metin bulunamadi. Net, odaklanmis bir "
                "ekran goruntusu deneyin ya da iddiayi yazili olarak sorun."
            ),
        )

    claim_text = result.text.strip()
    low_confidence = result.confidence < _LOW_CONFIDENCE_THRESHOLD
    recognized = has_health_topic(claim_text)

    return ImageClaimResult(
        success=True,
        claim_text=claim_text,
        ocr_confidence=result.confidence,
        low_confidence=low_confidence,
        has_recognized_topic=recognized,
    )
