"""Saved native-table regressions with independently resolved structured totals."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.filters import AutoFilter, FilterColumn, Filters, SortState
from openpyxl.worksheet.table import Table, TableColumn, TableFormula, TableStyleInfo

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@pytest.fixture
def engines():
    return [
        load_module(
            name, ROOT / f"{name}-employee/backend/vendor/{name.replace('-', '_')}/{file}.py"
        )
        for name, file in (("excel-template-write", "convert"), ("excel-qc", "checks"))
    ]


def _book(totals=False):
    book = Workbook()
    book.active.title = "Data"
    book.create_sheet("Other")
    for sheet, name, amounts in (("Data", "Sales", (10, 20)), ("Other", "Archive", (100, 200))):
        ws = book[sheet]
        ws.append(["Item", "Amount"])
        ws.append(["A", amounts[0]])
        ws.append(["B", amounts[1]])
        ws["D1"] = "=SUM(Sales[Amount])"
        table = Table(
            displayName=name,
            ref="A1:B3",
            tableColumns=[TableColumn(id=1, name="Item"), TableColumn(id=2, name="Amount")],
            autoFilter=AutoFilter(
                ref="A1:B3",
                filterColumn=[FilterColumn(colId=0, filters=Filters(filter=["A", "B"]))],
            ),
            tableStyleInfo=TableStyleInfo(name="TableStyleMedium2", showRowStripes=True),
        )
        if totals and sheet == "Data":
            ws.append(["Total", "=SUBTOTAL(109,Sales[Amount])"])
            table.ref, table.totalsRowCount, table.totalsRowShown = "A1:B4", 1, True
            table.tableColumns[0].totalsRowLabel = "Total"
            table.tableColumns[1].totalsRowFunction = "sum"
        ws.add_table(table)
    return book


def _insert(row, count=1, sheet="Data"):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": count}


def _run(tmp_path, writer, book, phases):
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"plan_version": 1, "phases": phases}
    writer.convert_file(
        None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
    )
    return template, output, plan


def _amount_total(ws, name):
    table = ws.tables[name]
    left, top, _, bottom = range_boundaries(table.ref)
    column = left + next(i for i, col in enumerate(table.tableColumns) if col.name == "Amount")
    return sum(
        cell.value
        for row in ws.iter_rows(
            min_row=top + (table.headerRowCount or 0),
            max_row=bottom - (table.totalsRowCount or 0),
            min_col=column,
            max_col=column,
        )
        for cell in row
        if isinstance(cell.value, (int, float))
    )


@pytest.mark.parametrize(
    "totals,phases,expected,expected_filter,archive",
    [
        (False, [_insert(2)], "A1:B4", "A1:B4", "A1:B3"),
        (False, [_insert(1)], "A2:B4", "A2:B4", "A1:B3"),
        (False, [_insert(3, 2)], "A1:B5", "A1:B5", "A1:B3"),
        (False, [_insert(4)], "A1:B3", "A1:B3", "A1:B3"),
        (False, [_insert(2), _insert(1, 2), _insert(6)], "A3:B7", "A3:B7", "A1:B3"),
        (False, [_insert(2, 2, "Other")], "A1:B3", "A1:B3", "A1:B5"),
        (True, [_insert(4)], "A1:B5", "A1:B4", "A1:B3"),
        (True, [_insert(2)], "A1:B5", "A1:B4", "A1:B3"),
        (True, [_insert(1)], "A2:B5", "A2:B4", "A1:B3"),
    ],
)
def test_native_table_and_filter_follow_saved_rows(
    engines, tmp_path, totals, phases, expected, expected_filter, archive
):
    writer, qc = engines
    template, output, plan = _run(tmp_path, writer, _book(totals), phases)
    saved = load_workbook(output)
    try:
        table = saved["Data"].tables["Sales"]
        assert table.ref == expected
        assert table.autoFilter.ref == expected_filter
        assert table.autoFilter.filterColumn[0].filters.filter == ["A", "B"]
        assert saved["Other"].tables["Archive"].ref == archive
        assert _amount_total(saved["Data"], "Sales") == 30
        assert _amount_total(saved["Other"], "Archive") == 300
    finally:
        saved.close()
    with ZipFile(output) as zipped:
        root = ET.fromstring(zipped.read("xl/tables/table1.xml"))
        assert root.attrib["ref"] == expected
        assert root.find(f"{NS}autoFilter").attrib["ref"] == expected_filter
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "PASS", report


@pytest.mark.parametrize(
    "tamper",
    [
        "table",
        "filter",
        "missing_filter",
        "condition",
        "column",
        "missing",
        "added",
        "other",
        "header",
    ],
)
def test_independent_qc_rejects_table_corruption(engines, tmp_path, tamper):
    writer, qc = engines
    template, output, plan = _run(tmp_path, writer, _book(), [_insert(2)])
    saved = load_workbook(output)
    table = saved["Data"].tables["Sales"]
    if tamper == "table":
        table.ref = "A1:B3"
    elif tamper == "filter":
        table.autoFilter.ref = "A1:B3"
    elif tamper == "missing_filter":
        table.autoFilter = None
    elif tamper == "condition":
        table.autoFilter.filterColumn[0].filters.filter = ["A"]
    elif tamper == "column":
        table.tableColumns[1].name = "Quantity"
    elif tamper == "missing":
        del saved["Data"].tables["Sales"]
    elif tamper == "added":
        saved["Data"].add_table(Table(displayName="Unexpected", ref="A1:B4"))
    elif tamper == "other":
        saved["Other"].tables["Archive"].ref = "A1:B2"
    else:
        table.headerRowCount = 0
    saved.save(output)
    saved.close()
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "FAIL", report
    assert any("表格" in issue["detail"] for issue in report["sections"]["conformance"]["issues"])


@pytest.mark.parametrize(
    "unsupported",
    [
        "sort",
        "filter_sort",
        "calculated",
        "total_formula",
        "connection",
        "filter",
        "worksheet_filter",
        "overflow",
    ],
)
def test_unsafe_table_metadata_is_rejected_before_output(engines, tmp_path, unsupported):
    writer, qc = engines
    book = _book()
    table = book["Data"].tables["Sales"]
    if unsupported == "sort":
        table.sortState = SortState(ref="A2:B3")
    elif unsupported == "filter_sort":
        table.autoFilter.sortState = SortState(ref="A2:B3")
    elif unsupported == "calculated":
        table.tableColumns[1].calculatedColumnFormula = TableFormula(attr_text="[@Item]*2")
    elif unsupported == "total_formula":
        table.tableColumns[1].totalsRowFormula = TableFormula(attr_text="SUM(B2:B3)")
    elif unsupported == "connection":
        table.connectionId = 1
    elif unsupported == "filter":
        table.autoFilter.ref = "A1:B2"
    elif unsupported == "worksheet_filter":
        book["Data"].auto_filter.ref = "A1:B3"
    else:
        table.ref = table.autoFilter.ref = "A1:B1048576"
    with pytest.raises(writer.PlanError, match="表格"):
        _run(tmp_path, writer, book, [_insert(2)])
    assert not (tmp_path / "filled.xlsx").exists()
    # Bypass the writer to prove QC does not merely trust a successful write report.
    broken = load_workbook(tmp_path / "template.xlsx")
    broken["Data"].insert_rows(2)
    broken.save(tmp_path / "broken.xlsx")
    broken.close()
    report = qc.run_qc(
        tmp_path / "broken.xlsx", {"phases": [_insert(2)]}, template_path=tmp_path / "template.xlsx"
    )
    assert report["verdict"] == "FAIL", report


def test_original_stale_table_changes_structured_sum_but_qc_rejects(engines, tmp_path):
    _, qc = engines
    book = _book()
    template, output = tmp_path / "template.xlsx", tmp_path / "broken.xlsx"
    book.save(template)
    book["Data"].insert_rows(2)
    book.save(output)
    book.close()
    saved = load_workbook(output)
    assert _amount_total(saved["Data"], "Sales") == 10
    assert saved["Data"]["B4"].value == 20
    saved.close()
    report = qc.run_qc(output, {"phases": [_insert(2)]}, template_path=template)
    assert report["verdict"] == "FAIL", report


def _new_table_phase():
    return {
        "phase": "create_table",
        "sheet": "New",
        "name": "Created",
        "range": "A1:B3",
        "sum_column": "Amount",
        "calculated_formula": "=1",
    }


@pytest.mark.parametrize("sequence", ["before", "after", "after_unaffected"])
def test_legal_create_table_and_insert_phases_keep_independent_validation(
    engines, tmp_path, sequence
):
    writer, qc = engines
    book = _book()
    ws = book.create_sheet("New")
    for row in [["Item", "Amount"], ["A", 1], ["B", 1]]:
        ws.append(row)
    create = _new_table_phase()
    phases = [create, _insert(2)] if sequence == "before" else [_insert(2), create]
    if sequence == "after_unaffected":
        phases = [create, _insert(10, sheet="New")]
    template, output, plan = _run(tmp_path, writer, book, phases)
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "PASS", report
    saved = load_workbook(output)
    saved["New"].tables["Created"].ref = "A1:B3"
    saved.save(output)
    saved.close()
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "FAIL"


def test_created_calculated_table_cannot_be_moved_without_final_phase_support(engines, tmp_path):
    writer, _ = engines
    book = _book()
    ws = book.create_sheet("New")
    for row in [["Item", "Amount"], ["A", 1], ["B", 1]]:
        ws.append(row)
    with pytest.raises(writer.PlanError, match="表格"):
        _run(tmp_path, writer, book, [_new_table_phase(), _insert(2, sheet="New")])
    assert not (tmp_path / "filled.xlsx").exists()


def test_table_package_id_renumber_after_sheet_removal_is_not_corruption(engines, tmp_path):
    writer, qc = engines
    book = _book()
    book["Other"]["D1"] = "=SUM(Archive[Amount])"
    template, output, plan = _run(
        tmp_path,
        writer,
        book,
        [{"phase": "remove_sheets", "names": ["Data"]}, _insert(2, sheet="Other")],
    )
    original, saved = load_workbook(template), load_workbook(output)
    assert original["Other"].tables["Archive"].id == 2
    assert saved["Other"].tables["Archive"].id == 1
    assert _amount_total(saved["Other"], "Archive") == 300
    original.close()
    saved.close()
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "PASS", report


@pytest.mark.parametrize("field", ["calculatedColumnFormula", "totalsRowFormula"])
def test_table_metadata_references_on_an_unmoved_sheet_are_not_silently_left_stale(
    engines, tmp_path, field
):
    writer, qc = engines
    book = _book()
    setattr(
        book["Other"].tables["Archive"].tableColumns[1], field, TableFormula(attr_text="Data!B2")
    )
    with pytest.raises(writer.PlanError, match="表格"):
        _run(tmp_path, writer, book, [_insert(2)])
    assert not (tmp_path / "filled.xlsx").exists()
    broken = load_workbook(tmp_path / "template.xlsx")
    broken["Data"].insert_rows(2)
    broken["Data"].tables["Sales"].ref = "A1:B4"
    broken["Data"].tables["Sales"].autoFilter.ref = "A1:B4"
    broken.save(tmp_path / "broken.xlsx")
    broken.close()
    report = qc.run_qc(
        tmp_path / "broken.xlsx", {"phases": [_insert(2)]}, template_path=tmp_path / "template.xlsx"
    )
    assert report["verdict"] == "FAIL", report
