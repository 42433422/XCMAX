import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet
from openpyxl.worksheet.worksheet import Worksheet

from app.application.elt.parser_structure import probe_sheet_rows
from app.application.elt.parsers import parse_file
from app.infrastructure.excel.sparse_rows import iter_present_cells, iter_present_rows


def _forbid_rectangles(*args, **kwargs):
    pytest.fail("sparse business projection must not scan a rectangular worksheet")


def test_read_only_row_iterator_keeps_sparse_coordinates_and_types(tmp_path, monkeypatch):
    path = tmp_path / "sparse.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["B1000000"] = False
    worksheet["XFD1000000"] = 0
    worksheet["A1048576"] = "last"
    workbook.save(path)
    workbook.close()
    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", _forbid_rectangles)
    loaded = load_workbook(path, read_only=True, data_only=True)
    try:
        cells = list(iter_present_cells(loaded.active))
        assert [(cell.coordinate, cell.value) for cell in cells] == [
            ("B1000000", False),
            ("XFD1000000", 0),
            ("A1048576", "last"),
        ]
        rows = list(iter_present_rows(loaded.active))
        assert [number for number, _ in rows] == [1000000, 1048576]
        assert rows[0][1][1].value is False
        assert rows[0][1][-1].value == 0
        assert len(rows[0][1]) == 16384
        assert rows[1][1][0].value == "last"
    finally:
        loaded.close()


def test_probe_finds_late_header_without_filling_missing_rows(tmp_path, monkeypatch):
    path = tmp_path / "late.xlsx"
    book = Workbook()
    book.active["A900000"] = "客户名称"
    book.active["B900000"] = "联系电话"
    book.active["A900002"] = "客户甲"
    book.active["B900002"] = "12345"
    book.save(path)
    book.close()
    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", _forbid_rectangles)
    loaded = load_workbook(path, read_only=True, data_only=True)
    try:
        rows, first = probe_sheet_rows(loaded.active)
        assert first == 900000
        assert rows == [["客户名称", "联系电话"], [], ["客户甲", "12345"]]
    finally:
        loaded.close()


def test_elt_keeps_original_rows_and_compact_gap_accounting(tmp_path, monkeypatch):
    path = tmp_path / "customers.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["客户名称", "联系电话", "地址"])
    worksheet["A1000000"] = "客户甲"
    worksheet["B1000000"] = "12345"
    worksheet["C1000000"] = "成都"
    workbook.save(path)
    workbook.close()
    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", _forbid_rectangles)
    monkeypatch.setattr(Worksheet, "iter_rows", _forbid_rectangles)
    dataset = parse_file(path, target_type="customers")
    try:
        assert len(dataset.rows) == 1
        assert dataset.rows[0].row_number == 1000000
        assert dataset.rows[0].values["客户名称"] == "客户甲"
        blanks = next(item for item in dataset.warnings if item["code"] == "ELT_BLANK_ROWS_SKIPPED")
        assert blanks["count"] == 999998
        assert blanks["rows"] == [
            {"sheet": "Sheet", "row_start": 2, "row_end": 999999, "row_count": 999998}
        ]
        assert dataset.source_features["row_reconciliation"]["original_rows"] == 999999
    finally:
        dataset.rows.close()


def test_structure_budget_degradation_is_visible(tmp_path, monkeypatch):
    from app.application.elt import parser_table_structure, parsers

    path = tmp_path / "customers.xlsx"
    workbook = Workbook()
    workbook.active.append(["客户名称", "联系电话", "地址"])
    workbook.active.append(["客户甲", "12345", "成都"])
    workbook.save(path)
    workbook.close()
    monkeypatch.setattr(parsers, "MAX_STRUCTURE_BYTES", 1)
    monkeypatch.setattr(parser_table_structure, "MAX_STRUCTURE_BYTES", 1)
    dataset = parse_file(path, target_type="customers")
    try:
        assert len(dataset.rows) == 1
        assert dataset.source_features["structure_status"] == "partial"
        assert dataset.source_features["raw_content_scope"] == "business_projection_only"
        assert any(item["code"] == "ELT_STRUCTURE_BUDGET_EXCEEDED" for item in dataset.warnings)
    finally:
        dataset.rows.close()
