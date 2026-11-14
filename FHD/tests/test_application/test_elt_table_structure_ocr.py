from __future__ import annotations

from openpyxl import load_workbook

from app.application.elt.table_structure_ocr import (
    TableGrid,
    html_to_grid,
    recognize_table_structures,
)
from app.application.shipment_excel_etl_ocr import tables_to_workbook_path

_TABLE_HTML = """
<table>
  <tr><td rowspan="2">客户</td><td colspan="2">数量</td></tr>
  <tr><td>桶数</td><td>公斤</td></tr>
  <tr><td>张三</td><td>3</td><td>90</td></tr>
</table>
"""


class _FakePipeline:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def predict(self, input=None, **kwargs):
        self.calls += 1
        return [{"res": self.payload}]


def test_html_to_grid_keeps_spans_and_merge_ranges():
    grid, merges = html_to_grid(_TABLE_HTML)

    assert grid == [
        ["客户", "数量", ""],
        ["", "桶数", "公斤"],
        ["张三", "3", "90"],
    ]
    assert merges == [(1, 1, 2, 1), (1, 2, 1, 3)]


def test_recognize_table_structures_reads_pipeline_payload():
    pipeline = _FakePipeline(
        {
            "table_res_list": [{"pred_html": _TABLE_HTML}],
            "parsing_res_list": [
                {"block_label": "text", "block_content": "客户：张三"},
                {"block_label": "text", "block_content": "无关说明"},
            ],
        }
    )

    tables = recognize_table_structures([object()], pipeline=pipeline)

    assert pipeline.calls == 1
    assert len(tables) == 1
    assert tables[0].page == 1
    assert tables[0].meta_lines == ["客户：张三"]
    assert tables[0].merges == [(1, 1, 2, 1), (1, 2, 1, 3)]


def test_recognize_table_structures_returns_empty_without_a_pipeline(monkeypatch):
    monkeypatch.setattr(
        "app.application.elt.table_structure_ocr.get_table_structure_pipeline",
        lambda: None,
    )

    assert recognize_table_structures([object()]) == []


def test_tables_to_workbook_path_writes_each_table_with_merges(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    tables = [
        TableGrid(grid=[["客户", "数量"], ["张三", "3"]], page=1),
        TableGrid(
            grid=[["客户", "数量", "数量"], ["", "桶数", "公斤"], ["张三", "3", "90"]],
            merges=[(1, 1, 2, 1), (1, 2, 1, 3)],
            page=2,
        ),
    ]

    path = tables_to_workbook_path(
        tables,
        output_path=tmp_path / "structured.xlsx",
        sheet_name="OCR",
        meta_lines=["客户：张三"],
    )

    workbook = load_workbook(path)
    try:
        assert workbook.sheetnames == ["OCR_1", "OCR_2"]
        first = workbook["OCR_1"]
        assert first["A1"].value == "客户：张三"
        assert first["A2"].value == "客户"
        second = workbook["OCR_2"]
        assert sorted(str(item) for item in second.merged_cells.ranges) == ["A1:A2", "B1:C1"]
    finally:
        workbook.close()
