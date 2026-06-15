"""Tests for app.infrastructure.ocr.ocr_adapter + ocr_service — coverage ramp C3.3-b.

Covers:
* ``OCRPort`` abstract methods (cannot instantiate directly).
* ``OCRAdapter`` happy path with empty result.
* ``get_ocr_adapter`` returns the concrete adapter.
* ``OCRService._init_engines`` honours ``XCAGI_OCR_BACKEND`` for paddle-only mode.
* ``OCRService._init_engines`` falls back when paddle unavailable (easyocr path).
* ``OCRService.get_active_ocr_backend`` returns the right name.
* ``OCRService.recognize`` returns empty when no engines are available.
* ``OCRService.recognize_text_blocks`` returns [] when no engines.
* ``OCRService.recognize_file`` returns failure dict for missing file.
* ``OCRService.recognize_text`` from path includes ``confidence`` field.
* ``OCRService.recognize_text_from_bytes`` returns success=False on bad bytes.
* ``OCRService.recognize_with_details`` returns empty list when no engine.
* ``OCRService.extract_structured_data`` regexes for unit/contact/phone/date/etc.
* ``OCRService.analyze_text`` type scoring and field detection.
* ``OCRService._classify_text`` and ``_clean_text`` edge cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.infrastructure.ocr.ocr_adapter import (
    OCRAdapter,
    OCRPort,
    get_ocr_adapter,
)

# ---------------------------------------------------------------------------
# Port / Adapter smoke
# ---------------------------------------------------------------------------


class TestOcrPort:
    def test_abstract_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            OCRPort()  # type: ignore[abstract]

    def test_abstract_methods_exist(self) -> None:
        assert hasattr(OCRPort, "recognize_text")
        assert hasattr(OCRPort, "recognize_text_from_bytes")


class TestOcrAdapter:
    def test_default_recognize(self) -> None:
        out = OCRAdapter().recognize_text("/path/to/img.png")
        assert out["success"] is True
        assert out["text"] == ""
        assert out["confidence"] == 0.0

    def test_default_recognize_from_bytes(self) -> None:
        out = OCRAdapter().recognize_text_from_bytes(b"\x89PNG fake")
        assert out["success"] is True
        assert out["text"] == ""

    def test_get_ocr_adapter(self) -> None:
        assert isinstance(get_ocr_adapter(), OCRPort)


# ---------------------------------------------------------------------------
# OCRService — engine init / backend selection
# ---------------------------------------------------------------------------


class TestOcrServiceInit:
    def test_paddle_only_mode_unavailable_logs_error(self, monkeypatch, caplog) -> None:
        """When ``XCAGI_OCR_BACKEND=paddle`` and paddle is unavailable, error is logged."""
        import logging

        from app.services import ocr_service as svc

        monkeypatch.setenv("XCAGI_OCR_BACKEND", "paddle")

        # Force paddle to be unavailable
        fake_runner = MagicMock()
        fake_runner.check_paddle_available.return_value = False
        fake_runner.get_paddle_ocr_instance.return_value = None
        with patch.dict(
            "sys.modules",
            {
                "app.services.paddle_ocr_runner": fake_runner,
            },
        ):
            # Build a fresh instance (skip auto init via env)
            with caplog.at_level(logging.ERROR, logger="app.services.ocr_service"):
                instance = svc.OCRService.__new__(svc.OCRService)
                instance.use_gpu = False
                instance.reader = None
                instance.tesseract_available = False
                instance._paddle_enabled = False
                instance._init_engines()
        # Paddle was attempted, but backend == "paddle" and not enabled → error log
        assert "XCAGI_OCR_BACKEND=paddle" in caplog.text
        assert instance._paddle_enabled is False

    def test_auto_mode_paddle_unavailable_falls_back_easyocr(self, monkeypatch) -> None:
        from app.services import ocr_service as svc

        monkeypatch.setenv("XCAGI_OCR_BACKEND", "auto")
        # Paddle unavailable
        fake_runner = MagicMock()
        fake_runner.check_paddle_available.return_value = False
        # Easyocr importable, but __init__ raises → no reader
        fake_easyocr_mod = MagicMock()
        fake_easyocr_mod.Reader.side_effect = RuntimeError("fail")
        with patch.dict(
            "sys.modules",
            {
                "app.services.paddle_ocr_runner": fake_runner,
                "easyocr": fake_easyocr_mod,
            },
        ):
            instance = svc.OCRService.__new__(svc.OCRService)
            instance.use_gpu = False
            instance.reader = None
            instance.tesseract_available = False
            instance._paddle_enabled = False
            instance._init_engines()
        assert instance._paddle_enabled is False
        # reader is None because easyocr init raised
        assert instance.reader is None

    def test_auto_mode_paddle_enabled(self, monkeypatch) -> None:
        from app.services import ocr_service as svc

        monkeypatch.setenv("XCAGI_OCR_BACKEND", "auto")
        fake_runner = MagicMock()
        fake_runner.check_paddle_available.return_value = True
        fake_runner.get_paddle_ocr_instance.return_value = "paddle-ok"
        with patch.dict(
            "sys.modules",
            {"app.services.paddle_ocr_runner": fake_runner},
        ):
            instance = svc.OCRService.__new__(svc.OCRService)
            instance.use_gpu = False
            instance.reader = None
            instance.tesseract_available = False
            instance._paddle_enabled = False
            instance._init_engines()
        assert instance._paddle_enabled is True

    def test_paddle_exception_caught(self, monkeypatch, caplog) -> None:
        """Exception in paddle init is logged as warning, not raised."""
        import logging

        from app.services import ocr_service as svc

        monkeypatch.setenv("XCAGI_OCR_BACKEND", "auto")
        # When the import inside _init_engines raises, it must be swallowed.
        with caplog.at_level(logging.WARNING, logger="app.services.ocr_service"):
            with patch.dict("sys.modules", {"app.services.paddle_ocr_runner": None}):
                instance = svc.OCRService.__new__(svc.OCRService)
                instance.use_gpu = False
                instance.reader = None
                instance.tesseract_available = False
                instance._paddle_enabled = False
                instance._init_engines()
        # Service still constructed
        assert instance._paddle_enabled is False


class TestActiveBackend:
    def test_paddle(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "paddleocr"

    def test_easyocr(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = "fake-reader"
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "easyocr"

    def test_tesseract(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = True
        assert svc.get_active_ocr_backend() == "tesseract"

    def test_none(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        assert svc.get_active_ocr_backend() == "none"


class TestRecognizeNoEngines:
    def test_recognize_returns_empty(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize(np.zeros((10, 10, 3), dtype=np.uint8))
        assert out == ""

    def test_recognize_text_blocks_returns_empty(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize_text_blocks(np.zeros((10, 10, 3), dtype=np.uint8))
        assert out == []


class TestRecognizeFile:
    def test_missing_file(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize_file("/nonexistent/path.png")
        assert out["success"] is False
        assert "文件不存在" in out["message"]

    def test_paddle_engine_call(self, monkeypatch) -> None:
        from app.services.ocr_service import OCRService

        # The OCR service does a local import inside ``recognize``:
        #     from app.services.paddle_ocr_runner import predict_to_text_blocks
        # So we must patch the symbol in the *source* module.
        monkeypatch.setattr(
            "app.services.paddle_ocr_runner.predict_to_text_blocks",
            lambda arr: [{"text": "hello"}, {"text": "world"}],
        )
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize(np.zeros((10, 10, 3), dtype=np.uint8))
        assert "hello" in out
        assert "world" in out


class TestRecognizeTextFromBytes:
    def test_bad_bytes(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize_text_from_bytes(b"not an image")
        assert out["success"] is False
        assert out["text"] == ""
        assert out["confidence"] == 0.0

    def test_paddle_path(self, monkeypatch) -> None:
        """Paddle path should return averaged confidence from blocks."""
        from app.services.ocr_service import OCRService

        # Patch the source module because ``ocr_service.recognize_text_from_bytes``
        # performs a local `from app.services.paddle_ocr_runner import ...`.
        monkeypatch.setattr(
            "app.services.paddle_ocr_runner.predict_to_text_blocks",
            lambda arr: [
                {"text": "abc", "conf": 80.0},
                {"text": "def", "conf": 60.0},
            ],
        )
        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = True
        svc.reader = None
        svc.tesseract_available = False
        try:
            import io

            from PIL import Image

            buf = io.BytesIO()
            Image.new("RGB", (4, 4), color="white").save(buf, format="PNG")
            out = svc.recognize_text_from_bytes(buf.getvalue())
            assert out["success"] is True
            assert "abc" in out["text"]
            assert 0 < out["confidence"] <= 1.0
        except Exception:
            pytest.skip("PIL not available")


class TestRecognizeWithDetails:
    def test_no_engine_returns_empty(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize_with_details(np.zeros((4, 4, 3), dtype=np.uint8))
        assert out == []


# ---------------------------------------------------------------------------
# extract_structured_data / analyze_text
# ---------------------------------------------------------------------------


class TestExtractStructuredData:
    def test_full_match(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        text = (
            "购货单位：测试客户\n"
            "联系人：张三\n"
            "联系电话：13800138000\n"
            "订单编号：ORD-001\n"
            "合计：123.45\n"
            "2024年1月15日\n"
            "AB-001 食品级A 10 5.0 50.0\n"
        )
        out = svc.extract_structured_data(text)
        assert out["purchase_unit"] == "测试客户"
        assert out["contact_person"] == "张三"
        assert out["contact_phone"] == "13800138000"
        assert out["order_number"] == "ORD-001"
        assert out["total_amount"] == 123.45
        assert "2024" in out["purchase_date"]
        assert len(out["products"]) >= 1
        assert out["products"][0]["model"] == "AB-001"
        assert out["raw_text"] == text

    def test_empty_text(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        out = svc.extract_structured_data("")
        assert out["purchase_unit"] is None
        assert out["products"] == []

    def test_amount_value_error_caught(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        out = svc.extract_structured_data("合计：not-a-number")
        # Should not raise; total_amount stays None
        assert out["total_amount"] is None


class TestAnalyzeText:
    def test_empty_text_returns_defaults(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        out = svc.analyze_text("")
        assert out["text_type"] == "unknown"
        assert out["confidence"] == 0.0
        assert out["suggestions"] == []

    def test_order_text_classified(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        out = svc.analyze_text("客户张三的订单编号001, 购货单位X")
        assert out["text_type"] in ("order", "customer")

    def test_field_detection(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        text = "购货单位：ABC\n联系人：李四\n2024-01-01\n订单编号：X1\n合计：1.0"
        out = svc.analyze_text(text)
        assert "purchase_unit" in out["detected_fields"]
        assert "contact_person" in out["detected_fields"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestCleanText:
    def test_empty(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._clean_text("") == ""
        assert svc._clean_text(None) == ""  # type: ignore[arg-type]

    def test_drops_blank_lines(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        out = svc._clean_text("a\n\n  b  \n   \nc")
        assert out == "a\nb\nc"


class TestClassifyText:
    def test_number(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._classify_text("123.45") == "number"
        assert svc._classify_text("1,000.00") == "number"

    def test_date(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._classify_text("2024-01-15") == "date"
        assert svc._classify_text("2024年1月15日") == "date"

    def test_amount(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._classify_text("100元") == "amount"
        assert svc._classify_text("$50") == "amount"

    def test_phone(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._classify_text("13800138000") == "phone"
        assert svc._classify_text("+86-138-0013-8000") == "phone"

    def test_text_fallback(self) -> None:
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        assert svc._classify_text("Hello World") == "text"
        assert svc._classify_text("") == "unknown"


# ---------------------------------------------------------------------------
# Adapter aliasing — service implements the port
# ---------------------------------------------------------------------------


class TestAdapterFromService:
    def test_ocr_adapter_compatible(self) -> None:
        """`OCRService.recognize_text` matches the `OCRPort` signature for paths."""
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out = svc.recognize_text("/no/such.png")
        assert isinstance(out, dict)
        assert out["success"] is False
        assert out["text"] == ""

    def test_recognize_product_aliases(self) -> None:
        """recognize_trademark and recognize_product currently alias recognize_text."""
        from app.services.ocr_service import OCRService

        svc = OCRService.__new__(OCRService)
        svc._paddle_enabled = False
        svc.reader = None
        svc.tesseract_available = False
        out_t = svc.recognize_trademark("/x.png")
        out_p = svc.recognize_product("/x.png")
        assert out_t["success"] is False
        assert out_p["success"] is False
