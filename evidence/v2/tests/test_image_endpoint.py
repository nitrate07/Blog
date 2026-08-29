"""POST /v1/investigator/chat/image testleri.

evidence/vision/ocr.py + evidence/chat/image_claim.py (onceki oturumda
eklendi) bilerek HTTP katmanina baglanmamisti. Bu dosya, o baglantiyi
tamamlayan endpoint'i test eder. Gercek Tesseract kurulu olmayabilir —
testler is_ocr_available() sonucuna gore ayarlanir; mock'lanan senaryolar
her ortamda calisir, gercek OCR gerektirenler Tesseract kuruluysa calisir.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from evidence.v2.api.app import create_app
from evidence.vision.ocr import is_ocr_available


def _tiny_png_bytes() -> bytes:
    """1x1 beyaz piksellik gecerli bir PNG — OCR metin bulamaz ama dosya
    gecerlidir, boyut/format kontrollerini test etmek icin yeterlidir."""
    import struct
    import zlib

    width, height = 1, 1
    raw = b"\x00\xff\xff\xff"  # filter byte + 1 beyaz piksel (RGB)
    compressed = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


class TestImageEndpointGuardClauses:
    """Bunlar Tesseract kurulu olsun olmasin her ortamda calismali —
    gecersiz girdi HTTP katmaninda yakalaniyor, OCR'a hic ulasmiyor."""

    @pytest.mark.asyncio
    async def test_empty_file_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat/image",
                files={"image": ("empty.png", b"", "image/png")},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_non_image_content_type_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat/image",
                files={"image": ("evil.exe", b"not an image", "application/x-executable")},
            )
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_oversized_upload_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        oversized = b"\x00" * (15_000_001)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat/image",
                files={"image": ("big.png", oversized, "image/png")},
            )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_missing_file_field_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/investigator/chat/image")
        assert resp.status_code == 422  # FastAPI validation — zorunlu alan eksik


class TestImageEndpointWithMockedOcr:
    """OCR sonucunu mock'layarak — kurulu Tesseract'a bagimli olmadan —
    endpoint'in OCR sonucunu dogru isledigini ve arastirma hattina dogru
    besledigini dogrular."""

    @pytest.mark.asyncio
    async def test_successful_ocr_triggers_full_verification_flow(self):
        from evidence.chat.image_claim import ImageClaimResult

        app = create_app()
        transport = ASGITransport(app=app)
        with patch(
            "evidence.chat.image_claim.extract_claim_from_image",
            return_value=ImageClaimResult(
                success=True,
                claim_text="Kahve kolesterolü yükseltir mi?",
                ocr_confidence=85.0,
                has_recognized_topic=True,
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/investigator/chat/image",
                    files={"image": ("claim.png", _tiny_png_bytes(), "image/png")},
                    data={"session_id": "img-test-1"},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ocr"]["success"] is True
        assert body["ocr"]["claim_text"] == "Kahve kolesterolü yükseltir mi?"
        assert body["response"] is not None
        assert body["response"]["intent"] == "verify_claim"

    @pytest.mark.asyncio
    async def test_ocr_failure_returns_diagnostic_without_crashing(self):
        from evidence.chat.image_claim import ImageClaimResult

        app = create_app()
        transport = ASGITransport(app=app)
        with patch(
            "evidence.chat.image_claim.extract_claim_from_image",
            return_value=ImageClaimResult(success=False, error="Tesseract kurulu değil"),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/investigator/chat/image",
                    files={"image": ("claim.png", _tiny_png_bytes(), "image/png")},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ocr"]["success"] is False
        assert body["ocr"]["error"] == "Tesseract kurulu değil"
        assert body["response"] is None

    @pytest.mark.asyncio
    async def test_unrecognized_topic_still_returns_ocr_text_but_no_verification(self):
        """OCR basarili ama metin bir saglik konusu icermiyor — yine de
        cikan metni geri dondurmeli (kullanici ne okundugunu gorsun),
        ama tam arastirmayi tetiklememeli (has_recognized_topic=False
        olsa bile ready_for_verification True olabilir — bu durumda
        conversation manager kendi 'tanıyamadım' kapisini uygular)."""
        from evidence.chat.image_claim import ImageClaimResult

        app = create_app()
        transport = ASGITransport(app=app)
        with patch(
            "evidence.chat.image_claim.extract_claim_from_image",
            return_value=ImageClaimResult(
                success=True,
                claim_text="bugün hava çok güzel",
                ocr_confidence=90.0,
                has_recognized_topic=False,
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/investigator/chat/image",
                    files={"image": ("claim.png", _tiny_png_bytes(), "image/png")},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ocr"]["claim_text"] == "bugün hava çok güzel"
        assert body["response"] is not None  # manager.handle_message hala cagrilir


@pytest.mark.skipif(
    not is_ocr_available(),
    reason="Tesseract binary or tur/eng language data not installed on this system",
)
class TestImageEndpointRealOcr:
    """Gercek Tesseract kurulu oldugunda uctan uca (sentetik goruntu, mock yok)."""

    @pytest.mark.asyncio
    async def test_real_turkish_claim_image_end_to_end(self):
        from PIL import Image, ImageDraw, ImageFont

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except Exception:
            font = ImageFont.load_default()

        img = Image.new("RGB", (900, 200), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 80), "Kahve kolesterolü yükseltir mi?", fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat/image",
                files={"image": ("claim.png", buf.getvalue(), "image/png")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ocr"]["success"] is True
        assert "kolesterol" in body["ocr"]["claim_text"].lower()
        assert body["response"] is not None
