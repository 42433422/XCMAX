"""app/infrastructure/documents/price_list_export 辅助函数单测（独立文件便于 Phase 2 追踪）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from docx.oxml.ns import qn

from app.infrastructure.documents.price_list_export import (
    _border_el_effective,
    _tbl_row_count,
    build_sales_contract_template_preview_json,
    resolve_price_list_docx_template,
)


class _Cell:
    text: str

    def __init__(self, text: str) -> None:
        self.text = text


class _Row:
    def __init__(self, texts: list[str]) -> None:
        self.cells = [_Cell(t) for t in texts]


class _Table:
    def __init__(self, n: int) -> None:
        self.rows = [_Row([f"c{i}"]) for i in range(n)]
        self._tbl = MagicMock()


def test_tbl_row_count() -> None:
    class _Tr:
        tag = qn("w:tr")

    table = _Table(0)
    table._tbl = [_Tr(), _Tr(), _Tr()]
    assert _tbl_row_count(table) == 3


def test_border_el_effective_none() -> None:
    assert _border_el_effective(None) is False


@patch("app.infrastructure.documents.price_list_export.resolve_template_path_with_meta")
@patch("app.infrastructure.documents.price_list_export.read_excel_sales_contract_preview")
def test_build_sales_contract_preview(mock_read: MagicMock, mock_resolve: MagicMock) -> None:
    mock_resolve.return_value = ("/tmp/c.xlsx", "rel")
    mock_read.return_value = {"headers": []}
    out = build_sales_contract_template_preview_json("demo")
    assert out["template_hint"] == "/tmp/c.xlsx"


@patch("app.infrastructure.documents.price_list_export.resolve_template_path_with_meta")
def test_resolve_price_list_docx_template(mock_resolve: MagicMock) -> None:
    mock_resolve.return_value = ("/tmp/p.docx", "templates/p.docx")
    path, rel = resolve_price_list_docx_template()
    assert str(path) == "/tmp/p.docx"
    assert rel == "templates/p.docx"
