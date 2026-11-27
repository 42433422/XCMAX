from __future__ import annotations

import pytest
from openpyxl import load_workbook

from app.application.elt.table_structure_ocr import (
    TableGrid,
    html_to_grid,
    recognize_table_pages,
    recognize_table_structures,
)
from app.application.shipment_excel_elt_ocr import tables_to_workbook_path

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
            meta_lines=["客户：李四"],
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
        assert not list(first.merged_cells.ranges)
        second = workbook["OCR_2"]
        # 每张表自带 meta 行，合并区域随之下移一行
        assert second["A1"].value == "客户：李四"
        assert second["A2"].value == "客户"
        assert sorted(str(item) for item in second.merged_cells.ranges) == ["A2:A3", "B2:C2"]
    finally:
        workbook.close()


def test_blank_and_merged_trailing_rows_are_not_discarded():
    grid, merges = html_to_grid(
        '<table><tr><td rowspan="2">x</td><td>y</td></tr><tr><td></td></tr></table>'
    )
    assert grid == [["x", "y"], ["", ""]]
    assert merges == [(1, 1, 2, 1)]


def test_overlapping_and_unbounded_spans_rejected():
    with pytest.raises(ValueError, match="overlapping_table_spans"):
        html_to_grid(
            '<table><tr><td>x</td><td rowspan="2">y</td></tr>'
            '<tr><td colspan="2">z</td></tr></table>'
        )
    with pytest.raises(ValueError, match="table_grid_limit"):
        html_to_grid('<table><tr><td rowspan="999999">x</td></tr></table>')


def test_page_reports_keep_duplicates_only_across_distinct_table_entries():
    class Engine:
        def predict(self, input=None):
            if input == "broken":
                raise OSError("backend failed")
            yield {"res": {
                "table_res_list": [{"pred_html": _TABLE_HTML}, {"pred_html": _TABLE_HTML}],
                "parsing_res_list": [{"block_label": "table", "block_content": _TABLE_HTML}],
                "overall_ocr_res": {
                    "rec_texts": ["张三"], "rec_scores": [0.9], "rec_boxes": [[1, 2, 5, 8]],
                },
            }}

    reports = recognize_table_pages(["good", "broken", "good"], pipeline=Engine())
    assert [report.status for report in reports] == ["recognized", "failed", "recognized"]
    assert [[(table.page, table.index) for table in report.tables] for report in reports] == [
        [(1, 0), (1, 1)], [], [(3, 0), (3, 1)]
    ]
    assert reports[0].blocks[0]["confidence"] == 0.9
    assert reports[0].blocks[0]["width"] == 4
    assert reports[0].tables[0].source_html == _TABLE_HTML


def test_ocr_workbook_preserves_formula_like_text(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    path = tables_to_workbook_path(
        [TableGrid(grid=[["=1+1", "普通文本"]])], output_path=tmp_path / "literal.xlsx"
    )
    workbook = load_workbook(path)
    try:
        assert workbook.active["A1"].value == "=1+1"
        assert workbook.active["A1"].data_type == "s"
    finally:
        workbook.close()
