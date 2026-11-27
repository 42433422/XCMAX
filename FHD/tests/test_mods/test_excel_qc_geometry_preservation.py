"""Reopen real writer outputs and reject changes to unapproved worksheet geometry."""

from copy import copy

import pytest
from openpyxl import load_workbook
from openpyxl.styles import Font

from tests.test_mods.test_excel_qc_preservation import preserved_workbook as preserved_workbook


@pytest.mark.parametrize(
    "change",
    [
        "column_width",
        "column_hidden",
        "column_group",
        "column_style",
        "row_height",
        "row_hidden",
        "row_group",
        "row_style",
        "default_height",
        "default_width",
        "freeze",
    ],
)
def test_qc_rejects_unapproved_sheet_geometry(preserved_workbook, change):
    source, output, qc, run = preserved_workbook
    baseline, plan = run()
    assert baseline["verdict"] == "PASS", baseline
    book = load_workbook(output, rich_text=True)
    sheet = book["Data"]
    if change == "column_width":
        sheet.column_dimensions["B"].width = 40
    elif change == "column_hidden":
        sheet.column_dimensions["B"].hidden = True
    elif change == "column_group":
        sheet.column_dimensions.group("B", "D", outline_level=2, hidden=True)
    elif change == "column_style":
        sheet.column_dimensions["B"].font = Font(bold=True)
    elif change == "row_height":
        sheet.row_dimensions[1].height = 40
    elif change == "row_hidden":
        sheet.row_dimensions[1].hidden = True
    elif change == "row_group":
        sheet.row_dimensions.group(2, 4, outline_level=2, hidden=True)
    elif change == "row_style":
        sheet.row_dimensions[1].font = Font(bold=True)
    elif change == "default_height":
        sheet.sheet_format.defaultRowHeight = 40
    elif change == "default_width":
        sheet.sheet_format.defaultColWidth = 40
    else:
        sheet.freeze_panes = "C5"
    book.save(output)
    book.close()
    report = qc.run_qc(output, plan, template_path=source)
    assert report["verdict"] == "FAIL", report


def test_row_insertion_preserves_dimensions_and_only_approved_height_changes(preserved_workbook):
    source, output, qc, run = preserved_workbook
    book = load_workbook(source, rich_text=True)
    sheet = book["Data"]
    sheet.row_dimensions[5].height = 18
    sheet.row_dimensions[5].hidden = True
    sheet.row_dimensions[5].font = Font(italic=True)
    sheet.column_dimensions.group("B", "D", outline_level=2, hidden=True)
    sheet.freeze_panes = "B2"
    book.save(source)
    book.close()
    valid, plan = run(
        [
            {"phase": "set_row_height", "sheet": "Data", "row": 5, "height": 25},
            {"phase": "insert_rows", "sheet": "Data", "row": 2, "count": 2},
            {"phase": "freeze_panes", "sheet": "Data", "ref": "C4"},
        ]
    )
    assert valid["verdict"] == "PASS", valid
    book = load_workbook(output, rich_text=True)
    assert book["Data"].row_dimensions[7].height == 25
    assert book["Data"].row_dimensions[7].hidden is True
    book["Data"].row_dimensions[7].hidden = False
    book.save(output)
    book.close()
    assert qc.run_qc(output, plan, template_path=source)["verdict"] == "FAIL"


@pytest.mark.parametrize("ref", ["A1", "B2"])
def test_exact_approved_freeze_and_unfreeze(preserved_workbook, ref):
    source, output, qc, run = preserved_workbook
    book = load_workbook(source, rich_text=True)
    book["Data"].freeze_panes = "C5"
    book.save(source)
    book.close()
    valid, plan = run([{"phase": "freeze_panes", "sheet": "Data", "ref": ref}])
    assert valid["verdict"] == "PASS", valid
    if ref == "B2":
        book = load_workbook(output, rich_text=True)
        pane = copy(book["Data"].sheet_view.pane)
        pane.xSplit = 7
        book["Data"].sheet_view.pane = pane
        assert book["Data"].freeze_panes == "B2"
        book.save(output)
        book.close()
        assert qc.run_qc(output, plan, template_path=source)["verdict"] == "FAIL"


@pytest.mark.parametrize("scope", ["cell", "row", "column"])
def test_native_pivot_style_flag_is_preserved(preserved_workbook, scope):
    source, output, qc, run = preserved_workbook
    book = load_workbook(source, rich_text=True)
    book["Data"].row_dimensions[1].font = Font(italic=True)
    book["Data"].column_dimensions["B"].font = Font(bold=True)
    book.save(source)
    book.close()
    valid, plan = run()
    assert valid["verdict"] == "PASS", valid
    book = load_workbook(output, rich_text=True)
    sheet = book["Data"]
    if scope == "cell":
        target = sheet["A1"]
    elif scope == "row":
        target = sheet.row_dimensions[1]
    else:
        target = sheet.column_dimensions["B"]
    target.pivotButton = True
    book.save(output)
    book.close()
    assert qc.run_qc(output, plan, template_path=source)["verdict"] == "FAIL"


def test_final_geometry_follows_multiple_approved_stages(preserved_workbook):
    source, output, qc, run = preserved_workbook
    valid, plan = run(
        [
            {"phase": "set_row_height", "sheet": "Data", "row": 5, "height": 20},
            {"phase": "freeze_panes", "sheet": "Data", "ref": "B2"},
            {"phase": "insert_rows", "sheet": "Data", "row": 2, "count": 2},
            {"phase": "set_row_height", "sheet": "Data", "row": 7, "height": 25},
            {"phase": "freeze_panes", "sheet": "Data", "ref": "C5"},
        ]
    )
    assert valid["verdict"] == "PASS", valid
    book = load_workbook(output, rich_text=True)
    assert book["Data"].row_dimensions[7].height == 25
    assert book["Data"].freeze_panes == "C5"
    book["Data"].row_dimensions[7].height = 20
    book.save(output)
    book.close()
    assert qc.run_qc(output, plan, template_path=source)["verdict"] == "FAIL"
