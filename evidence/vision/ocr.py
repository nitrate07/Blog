"""OCR tabanli metin cikarimi — Tesseract uzerinden.

Bu proje genelinde kurulu desen (bkz. NullProvider, LLMProvider.compare):
opsiyonel bir yetenek eksikse veya basarisiz olursa, cagiran taraf asla
exception yakalamak zorunda kalmaz — sonuc nesnesi `success=False` ve
insan-okunabilir bir `error` ile doner. Bu modul de ayni deseni izler:
Tesseract ikili dosyasi veya dil verisi kurulu degilse, ya da goruntu
bozuksa/cok buyukse, `extract_text_from_image` crash etmez.

Bagimlilik: pytesseract + Pillow (evidence/requirements-vision.txt,
opsiyonel — bkz. requirements-rag-chroma.txt ile ayni "opt-in, varsayilan
davranis degismez" deseni). Sistem tarafinda Tesseract'in kendisi + dil
verisi (apt/brew ile) ayrica gerekir; bu bir Python paketi degildir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Guvenlik/kaynak siniri: asiri buyuk goruntuler Tesseract'i uzun sure
# kilitleyebilir (bkz. evidence/config.py'deki max_response_bytes ile ayni
# felsefe — dis girdiye guvenmeyip ust sinir koymak).
_MAX_IMAGE_BYTES = 15_000_000  # 15 MB
_MAX_IMAGE_DIMENSION = 6000  # piksel, uzun kenar

DEFAULT_LANGUAGES = ("tur", "eng")


@dataclass
class OcrResult:
    """Bir OCR cagrisinin sonucu — her zaman doner, asla exception firlatmaz."""

    success: bool
    text: str = ""
    confidence: float = 0.0  # 0-100, kelime-guven ortalamasi
    languages: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def is_ocr_available(languages: tuple[str, ...] = DEFAULT_LANGUAGES) -> bool:
    """Tesseract ikili dosyasi VE istenen dil verisi kurulu mu kontrol eder.

    pytesseract kurulu olsa bile (Python paketi), Tesseract'in kendisi veya
    "tur" dil verisi sistemde eksik olabilir — ikisi de ayri kurulum adimlari.
    """
    try:
        import pytesseract
    except ImportError:
        return False

    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception as e:
        logger.warning(f"Tesseract binary not usable: {e}")
        return False

    missing = [lang for lang in languages if lang not in available]
    if missing:
        logger.warning(f"Tesseract missing language data: {missing} (available: {sorted(available)})")
        return False
    return True


def _load_image(image: Any) -> Any:
    """str/Path/bytes girdisini bir PIL Image nesnesine cevirir.

    Zaten bir PIL Image ise oldugu gibi doner (test kolayligi icin).
    """
    from PIL import Image as PILImage

    if hasattr(image, "size") and hasattr(image, "mode"):
        # Zaten bir PIL Image nesnesi.
        return image
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise FileNotFoundError(f"Goruntu dosyasi bulunamadi: {path}")
        if path.stat().st_size > _MAX_IMAGE_BYTES:
            raise ValueError(
                f"Goruntu cok buyuk: {path.stat().st_size} bayt "
                f"(sinir: {_MAX_IMAGE_BYTES})"
            )
        return PILImage.open(path)
    if isinstance(image, (bytes, bytearray)):
        if len(image) > _MAX_IMAGE_BYTES:
            raise ValueError(
                f"Goruntu cok buyuk: {len(image)} bayt (sinir: {_MAX_IMAGE_BYTES})"
            )
        import io
        return PILImage.open(io.BytesIO(image))
    raise TypeError(f"Desteklenmeyen goruntu girdisi tipi: {type(image)!r}")


def extract_text_from_image(
    image: Any,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
) -> OcrResult:
    """Bir goruntudeki metni cikarir (ekran goruntusu, fotograf vb.).

    Args:
        image: Dosya yolu (str/Path), ham bayt (bytes), ya da zaten acilmis
               bir PIL.Image nesnesi.
        languages: Tesseract dil kodlari, oncelik sirasiyla birlestirilir
                   (varsayilan: Turkce + Ingilizce birlikte — "tur+eng").

    Returns:
        OcrResult — basarisizlikta bile (eksik bagimlilik, bozuk dosya,
        Tesseract hatasi) exception firlatmaz; `success=False` + `error`
        ile doner.
    """
    try:
        import pytesseract
    except ImportError:
        return OcrResult(
            success=False,
            error=(
                "pytesseract kurulu degil — opsiyonel bagimlilik, bkz. "
                "evidence/requirements-vision.txt"
            ),
        )

    try:
        pil_image = _load_image(image)
    except (FileNotFoundError, ValueError, TypeError) as e:
        return OcrResult(success=False, error=str(e))
    except Exception as e:
        return OcrResult(success=False, error=f"Goruntu acilamadi: {e}")

    if max(pil_image.size) > _MAX_IMAGE_DIMENSION:
        return OcrResult(
            success=False,
            error=(
                f"Goruntu boyutu cok buyuk: {pil_image.size} "
                f"(uzun kenar sinir: {_MAX_IMAGE_DIMENSION}px)"
            ),
        )

    lang_string = "+".join(languages)

    try:
        data = pytesseract.image_to_data(
            pil_image, lang=lang_string, output_type=pytesseract.Output.DICT
        )
    except pytesseract.TesseractNotFoundError:
        return OcrResult(
            success=False,
            error=(
                "Tesseract ikili dosyasi bulunamadi — sistem paketi kurulu "
                "degil (apt-get install tesseract-ocr tesseract-ocr-tur)"
            ),
        )
    except Exception as e:
        # Tesseract dil verisi eksikse de burada TesseractError firlar —
        # net bir mesajla sar, crash etme.
        return OcrResult(success=False, error=f"Tesseract hatasi: {e}")

    words: list[str] = []
    confidences: list[float] = []
    for word, conf in zip(data.get("text", []), data.get("conf", [])):
        word = word.strip()
        if not word:
            continue
        words.append(word)
        try:
            conf_value = float(conf)
        except (TypeError, ValueError):
            continue
        if conf_value >= 0:  # Tesseract -1 = "guven hesaplanamadi" icin kullanir
            confidences.append(conf_value)

    text = " ".join(words)
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return OcrResult(
        success=True,
        text=text,
        confidence=round(avg_confidence, 1),
        languages=languages,
    )
