from __future__ import annotations

from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.application.elt.cell_tidy import behead_paths, read_tidy_sheet, read_tidy_workbook
from app.application.elt.parser_structure import detect_table_layout


def _save(workbook, path):
    workbook.save(path)
    workbook.close()
    return path


def _sample_sheet():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["A1"] = "客户"
    worksheet.merge_cells("A1:A2")
    worksheet["B1"] = "数量"
    worksheet.merge_cells("B1:C1")
    worksheet["B2"] = "桶数"
    worksheet["C2"] = "公斤"
    worksheet["A3"] = "张三"
    worksheet["B3"] = 3
    worksheet["C3"] = 90
    worksheet["B1"].font = Font(bold=True)
    worksheet["B1"].fill = PatternFill("solid", fgColor="FFFF00")
    return workbook, worksheet


def test_read_tidy_sheet_keeps_types_styles_and_merges(tmp_path):
    workbook, _worksheet = _sample_sheet()
    path = _save(workbook, tmp_path / "tidy.xlsx")

    sheet = read_tidy_workbook(path)["Sheet"]

    assert sheet.cells[(1, 1)].value == "客户"
    assert sheet.cells[(1, 1)].merge == (1, 1, 2, 1)
    assert sheet.cells[(1, 2)].bold and sheet.cells[(1, 2)].filled
    assert sheet.cells[(3, 2)].data_type == "numeric"
    assert sheet.cells[(3, 2)].value == 3
    assert sheet.cells[(3, 1)].data_type == "character"


def test_read_tidy_sheet_detects_dates(tmp_path):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["A1"] = datetime(2026, 1, 2)
    sheet = read_tidy_sheet(worksheet)

    assert sheet.cells[(1, 1)].data_type == "date"


def test_probe_rows_expands_vertical_merge(tmp_path):
    workbook, _worksheet = _sample_sheet()
    path = _save(workbook, tmp_path / "tidy.xlsx")

    probe = read_tidy_workbook(path)["Sheet"].probe_rows()

    assert probe[0][:3] == ["客户", "数量", "数量"]
    assert probe[1][:3] == ["客户", "桶数", "公斤"]


def test_style_ratios_marks_the_formatted_header_row(tmp_path):
    workbook, _worksheet = _sample_sheet()
    path = _save(workbook, tmp_path / "tidy.xlsx")

    ratios = read_tidy_workbook(path)["Sheet"].style_ratios(3)

    assert ratios[0] >= 0.5
    assert ratios[2] == 0


def test_behead_paths_composes_parent_and_leaf():
    rows = [["客户", "数量", "数量"], ["客户", "桶数", "公斤"]]

    paths = behead_paths(rows)

    assert paths[0] == ["客户"]
    assert paths[1] == ["数量", "桶数"]
    assert paths[2] == ["数量", "公斤"]


def test_behead_paths_supports_left_row_headers():
    rows = [["产品", "一月份", "二月份"], ["销量", 10, 20]]

    paths = behead_paths(rows, direction="left", layers=1)

    assert paths == [["产品"], ["销量"]]


def test_detect_table_layout_uses_merged_and_styled_headers(tmp_path):
    workbook, _worksheet = _sample_sheet()
    path = _save(workbook, tmp_path / "tidy.xlsx")
    sheet = read_tidy_workbook(path)["Sheet"]
    probe = sheet.probe_rows()

    layout = detect_table_layout(
        probe,
        header_hints=["数量", "公斤"],
        style_ratios=sheet.style_ratios(len(probe)),
    )

    assert layout is not None
    assert layout.header_start == 0
    assert layout.header_end == 1
    assert layout.headers == ["客户", "桶数", "公斤"]
    assert "multi_row_header" in layout.reasons
