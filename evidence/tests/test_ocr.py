"""evidence/vision/ocr.py testleri.

pytesseract + Pillow (evidence/requirements-vision.txt) VE sistemde kurulu
Tesseract ikili dosyasi + "tur"/"eng" dil verisi gerektirir. Herhangi biri
eksikse otomatik atlanir (pytest.importorskip + is_ocr_available kontrolu) —
varsayilan test kurulumu bundan etkilenmez.

Harici bir goruntu dosyasina bagimli degil: PIL ile testler kendi sentetik
goruntulerini uretir (kendine yeterli, agininkip indirme gerekmez).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytesseract")
pytest.importorskip("PIL")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from evidence.vision.ocr import (  # noqa: E402
    OcrResult,
    _MAX_IMAGE_BYTES,
    _MAX_IMAGE_DIMENSION,
    extract_text_from_image,
    is_ocr_available,
)

_OCR_READY = is_ocr_available()
pytestmark = pytest.mark.skipif(
    not _OCR_READY,
    reason="Tesseract binary or tur/eng language data not installed on this system",
)


def _font(size: int = 36):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _make_text_image(text: str, size=(900, 200)) -> Image.Image:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, size[1] // 2 - 20), text, fill="black", font=_font())
    return img


class TestExtractTextFromImage:
    def test_extracts_turkish_text_with_diacritics(self):
        img = _make_text_image("Kahve kolesterolü düşürür mü?")
        result = extract_text_from_image(img, languages=("tur",))
        assert result.success
        assert "kolesterol" in result.text.lower()

    def test_extracts_english_text(self):
        img = _make_text_image("Does coffee lower cholesterol?")
        result = extract_text_from_image(img, languages=("eng",))
        assert result.success
        assert "cholesterol" in result.text.lower()

    def test_blank_image_returns_success_with_empty_text(self):
        img = Image.new("RGB", (400, 200), color="white")
        result = extract_text_from_image(img, languages=("eng",))
        assert result.success
        assert result.is_empty

    def test_accepts_bytes_input(self):
        import io
        img = _make_text_image("vitamin d eksikliği")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = extract_text_from_image(buf.getvalue(), languages=("tur",))
        assert result.success
        assert "vitamin" in result.text.lower()

    def test_accepts_file_path_input(self, tmp_path):
        img = _make_text_image("magnezyum")
        path = tmp_path / "claim.png"
        img.save(path)
        result = extract_text_from_image(str(path), languages=("tur",))
        assert result.success
        assert "magnezyum" in result.text.lower()

    def test_nonexistent_path_fails_closed(self):
        result = extract_text_from_image("/tmp/does-not-exist-ocr-test.png")
        assert not result.success
        assert result.error

    def test_oversized_dimension_rejected(self):
        img = Image.new("RGB", (_MAX_IMAGE_DIMENSION + 100, 50), color="white")
        result = extract_text_from_image(img)
        assert not result.success
        assert "buyuk" in (result.error or "").lower()

    def test_oversized_bytes_rejected(self):
        # Gercek bir goruntu olmasi gerekmiyor — bayt sinirinin dosyayi
        # acmadan once kontrol edildigini dogrular.
        oversized = b"\x00" * (_MAX_IMAGE_BYTES + 1)
        result = extract_text_from_image(oversized)
        assert not result.success

    def test_confidence_is_populated_for_clear_text(self):
        img = _make_text_image("probiyotik bağırsak sağlığı")
        result = extract_text_from_image(img, languages=("tur",))
        assert result.success
        assert 0.0 <= result.confidence <= 100.0
        assert result.confidence > 0  # Net, buyuk metin icin sifir olmamali

    def test_result_never_raises_on_unsupported_type(self):
        result = extract_text_from_image(12345)  # int — desteklenmeyen tip
        assert isinstance(result, OcrResult)
        assert not result.success


class TestIsOcrAvailable:
    def test_returns_true_when_tur_and_eng_installed(self):
        assert is_ocr_available(("tur", "eng")) is True

    def test_returns_false_for_unsupported_language(self):
        assert is_ocr_available(("this-lang-does-not-exist",)) is False
