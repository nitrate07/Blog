"""evidence/chat/image_claim.py testleri.

Bu modul evidence.vision.ocr'a bagimlidir; o da opsiyonel bagimliliklar
gerektirir (pytesseract, Pillow, sistemde Tesseract). Bu testler hem
gercek OCR ile (kurulu ise) hem de is_ocr_available'i sahte olarak
False dondurerek (her zaman calisan) davranisi dogrular.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from evidence.chat.image_claim import ImageClaimResult, extract_claim_from_image  # noqa: E402
from evidence.vision.ocr import OcrResult, is_ocr_available  # noqa: E402


def _font(size: int = 36):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )
    except Exception:
        return ImageFont.load_default()


def _make_text_image(text: str, size=(900, 200)) -> Image.Image:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, size[1] // 2 - 20), text, fill="black", font=_font())
    return img


class TestExtractClaimFromImageWithoutOcr:
    """OCR kullanilamadigi durumda (kurulu degil) her ortamda calisan testler."""

    def test_returns_graceful_error_when_ocr_unavailable(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=False):
            result = extract_claim_from_image("irrelevant.png")
        assert isinstance(result, ImageClaimResult)
        assert not result.success
        assert result.error
        assert not result.ready_for_verification

    def test_ocr_failure_propagates_as_readable_error(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=True), \
             patch(
                 "evidence.chat.image_claim.extract_text_from_image",
                 return_value=OcrResult(success=False, error="bozuk dosya"),
             ):
            result = extract_claim_from_image("irrelevant.png")
        assert not result.success
        assert result.error == "bozuk dosya"

    def test_empty_ocr_text_treated_as_failure_with_guidance(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=True), \
             patch(
                 "evidence.chat.image_claim.extract_text_from_image",
                 return_value=OcrResult(success=True, text="   ", confidence=0.0),
             ):
            result = extract_claim_from_image("irrelevant.png")
        assert not result.success
        assert not result.ready_for_verification

    def test_recognized_topic_flag_true_for_known_health_term(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=True), \
             patch(
                 "evidence.chat.image_claim.extract_text_from_image",
                 return_value=OcrResult(
                     success=True, text="Kahve kolesterolü yükseltir mi?", confidence=85.0
                 ),
             ):
            result = extract_claim_from_image("irrelevant.png")
        assert result.success
        assert result.ready_for_verification
        assert result.has_recognized_topic
        assert not result.low_confidence

    def test_recognized_topic_flag_false_for_unrelated_text(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=True), \
             patch(
                 "evidence.chat.image_claim.extract_text_from_image",
                 return_value=OcrResult(
                     success=True, text="Bugün hava çok güzel dışarıda", confidence=90.0
                 ),
             ):
            result = extract_claim_from_image("irrelevant.png")
        assert result.success  # OCR basarili — sadece saglik konusu yok
        assert result.ready_for_verification
        assert not result.has_recognized_topic

    def test_low_confidence_flag_set_below_threshold(self):
        with patch("evidence.chat.image_claim.is_ocr_available", return_value=True), \
             patch(
                 "evidence.chat.image_claim.extract_text_from_image",
                 return_value=OcrResult(
                     success=True, text="kolesterol kahve", confidence=15.0
                 ),
             ):
            result = extract_claim_from_image("irrelevant.png")
        assert result.success
        assert result.low_confidence


@pytest.mark.skipif(
    not is_ocr_available(),
    reason="Tesseract binary or tur/eng language data not installed on this system",
)
class TestExtractClaimFromImageEndToEnd:
    """Gercek Tesseract kurulu oldugunda uctan uca dogrulama."""

    def test_real_turkish_health_claim_image(self):
        img = _make_text_image("Vitamin D eksikliği kemik sağlığını etkiler")
        result = extract_claim_from_image(img)
        assert result.success
        assert result.ready_for_verification
        assert result.has_recognized_topic
        assert "vitamin" in result.claim_text.lower()

    def test_blank_image_fails_gracefully(self):
        img = Image.new("RGB", (400, 200), color="white")
        result = extract_claim_from_image(img)
        assert not result.success
        assert result.error
