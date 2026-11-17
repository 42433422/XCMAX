"""扫描件 PDF OCR 兜底的单元测试（不加载真实模型）。"""

from __future__ import annotations

from app.application.document_parsing import ocr
from app.application.dataset_rag.document_parser import _pdf_ocr_enabled


def test_ocr_mode_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("XCAGI_PDF_OCR", raising=False)
    assert ocr.ocr_mode() == "auto"


def test_ocr_mode_off_disables_parser(monkeypatch):
    monkeypatch.setenv("XCAGI_PDF_OCR", "off")
    assert ocr.ocr_mode() == "off"
    assert _pdf_ocr_enabled() is False


def test_ocr_mode_force_enables_parser(monkeypatch):
    monkeypatch.setenv("XCAGI_PDF_OCR", "force")
    assert _pdf_ocr_enabled() is True


def test_ocr_page_text_without_engine_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "_engine_or_none", lambda: None)
    assert ocr.ocr_page_text(object()) == ""


def test_ocr_result_lines_are_joined(monkeypatch):
    class FakeEngine:
        def __call__(self, array):
            return ([[None, "第一行"], [None, "第二行"]], None)

    class FakeImage:
        def to_image(self, resolution):
            class Rendered:
                original = self

            return Rendered()

        def convert(self, mode):
            return self

    monkeypatch.setattr(ocr, "_engine_or_none", lambda: FakeEngine())
    monkeypatch.setitem(__import__("sys").modules, "numpy", __import__("numpy"))
    assert ocr.ocr_page_text(FakeImage()) == "第一行\n第二行"
