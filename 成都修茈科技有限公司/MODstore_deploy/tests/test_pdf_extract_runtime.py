from __future__ import annotations

from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate


def test_pdf_read_then_generate_routes_to_generate() -> None:
    brief = "读取 report.pdf 并生成 PDF"

    assert is_pdf_generate(brief) is True
    assert is_pdf_full_read(brief) is False


def test_pdf_read_only_does_not_route_to_generate() -> None:
    brief = "只读取 report.pdf 的原生文字"

    assert is_pdf_generate(brief) is False
    assert is_pdf_full_read(brief) is True
