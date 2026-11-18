"""文档解析路由：Docling 可选、按格式分流、失败回退。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.document_parsing import router


def _legacy() -> tuple[str, str, dict]:
    return "legacy text", "pdfplumber", {"extension": ".pdf"}


def test_docling_used_for_complex_document_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: True)
    monkeypatch.setattr(
        router,
        "parse_with_docling",
        lambda path: router.ParsedDocument("docling text", "docling", {"page_count": 2}),
    )
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")
    text, parser, meta = router.parse_document(path, _legacy)
    assert (text, parser) == ("docling text", "docling")
    assert meta["page_count"] == 2


def test_excel_never_routed_to_docling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: True)
    monkeypatch.setattr(
        router, "parse_with_docling", lambda path: pytest.fail("should not be called")
    )
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"xlsx")
    text, parser, _ = router.parse_document(path, _legacy)
    assert (text, parser) == ("legacy text", "pdfplumber")


def test_falls_back_when_docling_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: False)
    path = tmp_path / "a.docx"
    path.write_bytes(b"docx")
    text, parser, meta = router.parse_document(path, _legacy)
    assert (text, parser) == ("legacy text", "pdfplumber")
    assert meta["docling_skipped"] == "not_installed"


def test_falls_back_when_docling_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: True)

    def boom(path: Path):
        raise ValueError("conversion failed")

    monkeypatch.setattr(router, "parse_with_docling", boom)
    path = tmp_path / "a.pptx"
    path.write_bytes(b"pptx")
    text, parser, meta = router.parse_document(path, _legacy)
    assert (text, parser) == ("legacy text", "pdfplumber")
    assert "conversion failed" in meta["docling_error"]


def test_legacy_mode_skips_docling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "legacy")
    monkeypatch.setattr(router, "docling_available", lambda: True)
    monkeypatch.setattr(
        router, "parse_with_docling", lambda path: pytest.fail("should not be called")
    )
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")
    assert router.parse_document(path, _legacy)[1] == "pdfplumber"


def test_pdf_bytes_helper_returns_none_without_docling(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: False)
    assert router.parse_pdf_bytes_with_docling(b"%PDF-1.4") is None


def test_pdf_bytes_helper_uses_docling(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "auto")
    monkeypatch.setattr(router, "docling_available", lambda: True)
    monkeypatch.setattr(
        router,
        "parse_with_docling",
        lambda path: router.ParsedDocument("# 标题\n正文", "docling", {}),
    )
    assert router.parse_pdf_bytes_with_docling(b"%PDF-1.4") == "# 标题\n正文"


def test_forced_docling_without_install_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_DOC_PARSER", "docling")
    monkeypatch.setattr(router, "docling_available", lambda: False)
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")
    with pytest.raises(RuntimeError, match="未安装 docling"):
        router.parse_document(path, _legacy)
