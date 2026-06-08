from __future__ import annotations

import io

import pytest

from modstore_server.knowledge_ingest import parse_upload


def test_parse_upload_reads_xlsx_rows() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "收入"
    ws.merge_cells("A1:B1")
    ws["A1"] = "收入汇总"
    ws.append(["月份", "收入"])
    ws.append(["2025-12", 120000])
    ws["C3"] = "=SUM(B3:B3)"

    raw = io.BytesIO()
    wb.save(raw)

    text = parse_upload("2025年12月收入.xlsx", raw.getvalue())

    assert "## Sheet: 收入" in text
    assert "Used range:" in text
    assert "Merged cells: A1:B1" in text
    assert "A1=收入汇总" in text
    assert "A2=月份" in text
    assert "B2=收入" in text
    assert "A3=2025-12" in text
    assert "B3=120000" in text
    assert "C3: =SUM(B3:B3)" in text
