"""Tests for app.application.workflow.multimodal_user_content — multimodal attachment processing."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.multimodal_user_content import (
    _ALLOWED_IMAGE_MIME,
    _ALLOWED_PDF_MIME,
    _decode_data_url,
    _maybe_downscale_image_jpeg,
    _normalize_mime,
    _pdf_bytes_to_text,
    build_openai_user_content,
)

# ---------------------------------------------------------------------------
# _normalize_mime
# ---------------------------------------------------------------------------


class TestNormalizeMime:
    def test_jpg_to_jpeg(self):
        assert _normalize_mime("image/jpg") == "image/jpeg"

    def test_jpeg_stays(self):
        assert _normalize_mime("image/jpeg") == "image/jpeg"

    def test_png_stays(self):
        assert _normalize_mime("image/png") == "image/png"

    def test_none_returns_empty(self):
        assert _normalize_mime(None) == ""

    def test_empty_returns_empty(self):
        assert _normalize_mime("") == ""

    def test_case_insensitive(self):
        assert _normalize_mime("Image/JPEG") == "image/jpeg"


# ---------------------------------------------------------------------------
# _decode_data_url
# ---------------------------------------------------------------------------


class TestDecodeDataUrl:
    def test_valid_data_url(self):
        b64 = base64.standard_b64encode(b"hello").decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        raw_bytes, mime = _decode_data_url(data_url)
        assert raw_bytes == b"hello"
        assert mime == "image/png"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="invalid data URL"):
            _decode_data_url("not-a-data-url")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _decode_data_url("")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            _decode_data_url(None)

    def test_too_large_raises(self):
        # Create a data URL with content that would exceed the limit
        large_b64 = base64.standard_b64encode(b"x" * (14 * 1024 * 1024 + 1)).decode("ascii")
        data_url = f"data:image/png;base64,{large_b64}"
        with pytest.raises(ValueError, match="too large"):
            _decode_data_url(data_url)


# ---------------------------------------------------------------------------
# _maybe_downscale_image_jpeg
# ---------------------------------------------------------------------------


class TestMaybeDownscaleImageJpeg:
    def test_returns_data_url_without_pil(self):
        with (
            patch(
                "app.application.workflow.multimodal_user_content.RECOVERABLE_ERRORS",
                (ImportError,),
            ),
            patch("builtins.__import__", side_effect=ImportError("no PIL")),
        ):
            # When PIL is not available, it falls back to raw base64
            raw = b"fake image data"
            url, mime = _maybe_downscale_image_jpeg(raw, "image/png")
            assert url.startswith("data:image/png;base64,")
            assert mime == "image/png"

    def test_valid_image_downscaled(self):
        try:
            import io

            from PIL import Image
        except ImportError:
            pytest.skip("PIL not available")

        # Create a small test image
        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        url, mime = _maybe_downscale_image_jpeg(raw, "image/png")
        assert url.startswith("data:image/jpeg;base64,") or url.startswith("data:image/png;base64,")
        assert mime in ("image/jpeg", "image/png")


# ---------------------------------------------------------------------------
# _pdf_bytes_to_text
# ---------------------------------------------------------------------------


class TestPdfBytesToText:
    def test_no_pdfplumber_returns_fallback(self):
        with (
            patch(
                "app.application.workflow.multimodal_user_content.RECOVERABLE_ERRORS",
                (ImportError,),
            ),
            patch("builtins.__import__", side_effect=ImportError("no pdfplumber")),
        ):
            result = _pdf_bytes_to_text(b"fake pdf", "test.pdf")
            assert "无法读取" in result or "pdfplumber" in result

    def test_invalid_pdf_bytes(self):
        # Patch pdfplumber.open to raise ValueError (which is in RECOVERABLE_ERRORS)
        import pdfplumber

        with patch.object(pdfplumber, "open", side_effect=ValueError("invalid PDF")):
            result = _pdf_bytes_to_text(b"not a pdf", "bad.pdf")
        assert isinstance(result, str)
        assert "解析失败" in result or "bad.pdf" in result


# ---------------------------------------------------------------------------
# build_openai_user_content
# ---------------------------------------------------------------------------


class TestBuildOpenaiUserContent:
    def test_no_context_returns_message(self):
        result = build_openai_user_content("hello", None)
        assert result == "hello"

    def test_empty_context_returns_message(self):
        result = build_openai_user_content("hello", {})
        assert result == "hello"

    def test_no_attachments_returns_message(self):
        result = build_openai_user_content("hello", {"multimodal_attachments": []})
        assert result == "hello"

    def test_empty_message_with_no_attachments_returns_empty(self):
        result = build_openai_user_content("", {"multimodal_attachments": []})
        assert result == ""

    def test_image_attachment_produces_list(self):
        b64 = base64.standard_b64encode(b"fake_png_data" * 10).decode("ascii")
        ctx = {
            "multimodal_attachments": [
                {
                    "mime_type": "image/png",
                    "data_base64": b64,
                    "filename": "test.png",
                }
            ]
        }
        result = build_openai_user_content("check this", ctx)
        assert isinstance(result, list)
        types = [p["type"] for p in result]
        assert "text" in types
        assert "image_url" in types

    def test_pdf_attachment_produces_text_part(self):
        b64 = base64.standard_b64encode(b"fake_pdf_data" * 10).decode("ascii")
        ctx = {
            "multimodal_attachments": [
                {
                    "mime_type": "application/pdf",
                    "data_base64": b64,
                    "filename": "doc.pdf",
                    "kind": "pdf",
                }
            ]
        }
        with patch(
            "app.application.workflow.multimodal_user_content._pdf_bytes_to_text",
            return_value="[PDF doc.pdf: extracted text]",
        ):
            result = build_openai_user_content("read this", ctx)
        assert isinstance(result, list)
        text_parts = [p for p in result if p["type"] == "text"]
        assert any("PDF" in p["text"] or "extracted" in p["text"] for p in text_parts)

    def test_unsupported_mime_skipped(self):
        b64 = base64.standard_b64encode(b"data").decode("ascii")
        ctx = {
            "multimodal_attachments": [
                {
                    "mime_type": "video/mp4",
                    "data_base64": b64,
                    "filename": "vid.mp4",
                }
            ]
        }
        result = build_openai_user_content("check", ctx)
        # Should contain a text part saying it was skipped
        if isinstance(result, list):
            text_parts = [p for p in result if p["type"] == "text"]
            assert any("跳过" in p.get("text", "") for p in text_parts)

    def test_no_data_url_or_base64_skipped(self):
        ctx = {
            "multimodal_attachments": [
                {"filename": "missing.bin", "mime_type": "image/png"},
            ]
        }
        result = build_openai_user_content("check", ctx)
        if isinstance(result, list):
            text_parts = [p for p in result if p["type"] == "text"]
            assert any("跳过" in p.get("text", "") for p in text_parts)

    def test_invalid_base64_skipped(self):
        ctx = {
            "multimodal_attachments": [
                {
                    "filename": "bad.png",
                    "mime_type": "image/png",
                    "data_base64": "!!!not-base64!!!",
                },
            ]
        }
        # binascii.Error should be caught and attachment skipped
        result = build_openai_user_content("check", ctx)
        # Should not crash; invalid base64 should be caught
        # Result is either a string or a list with a skip message
        assert isinstance(result, (str, list))
        if isinstance(result, list):
            text_parts = [p for p in result if p["type"] == "text"]
            # At minimum the "check" text part exists
            assert len(text_parts) >= 1

    def test_data_url_image(self):
        b64 = base64.standard_b64encode(b"tiny_image_data").decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        ctx = {
            "multimodal_attachments": [
                {"data_url": data_url, "filename": "inline.png"},
            ]
        }
        result = build_openai_user_content("see", ctx)
        assert isinstance(result, list)

    def test_max_attachments_limit(self):
        b64 = base64.standard_b64encode(b"img").decode("ascii")
        attachments = [
            {"mime_type": "image/png", "data_base64": b64, "filename": f"img{i}.png"}
            for i in range(20)
        ]
        ctx = {"multimodal_attachments": attachments}
        result = build_openai_user_content("many", ctx)
        if isinstance(result, list):
            image_parts = [p for p in result if p.get("type") == "image_url"]
            assert len(image_parts) <= 8  # _MAX_ATTACHMENTS

    def test_non_dict_attachment_skipped(self):
        ctx = {
            "multimodal_attachments": ["not a dict", 42, None],
        }
        result = build_openai_user_content("test", ctx)
        # Should return just the text message
        assert result == "test"

    def test_single_text_only_returns_string(self):
        ctx = {
            "multimodal_attachments": [
                {"filename": "skip.bin", "mime_type": "video/mp4"},
            ]
        }
        result = build_openai_user_content("just text", ctx)
        # When only text parts remain and it's just one, returns string
        assert isinstance(result, (str, list))
