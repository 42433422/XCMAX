"""Saved XLSX regressions; expected coordinates/formulas are independent constants."""

from __future__ import annotations

import importlib.util
from copy import copy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table

FHD_ROOT = Path(__file__).resolve().parents[2]
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@pytest.fixture
def engines():
    modules = []
    for name, filename in (("excel-template-write", "convert"), ("excel-qc", "checks")):
        path = (
            FHD_ROOT
            / f"mods/_employees/{name}-employee/backend/vendor/{name.replace('-', '_')}/{filename}.py"
        )
        spec = importlib.util.spec_from_file_location(f"integrity_{filename}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def _book():
    book = Workbook()
    data = book.active
    data.title = "Data"
    data["A3"], data["A4"] = 10, 20
    other = book.create_sheet("Other")
    other["A3"], other["A4"] = 101, 202
    other["E1"], other["F1"] = "Q1", "Q2"
    other["E2"], other["F2"] = 30, 60
    other.add_table(Table(displayName="Sales", ref="E1:F2"))
    book.defined_names.add(DefinedName("XFE3", attr_text="'Other'!$A$3"))
    return book


def _insert(row=3, count=1, sheet="Data"):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": count}


def _run(tmp_path, writer, book, phases, protected=(), strict=True):
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"plan_version": 1, "phases": phases, "protected_ranges": list(protected)}
    writer.convert_file(
        None,
        output,
        template_path=template,
        payload={"plan": plan, "strict_protected": strict},
        ctx={},
        rule_spec={},
    )
    return template, output, plan


def _xml(path, sheet=1):
    with ZipFile(path) as archive:
        return ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet}.xml"))


@pytest.mark.parametrize(
    "sheet,ref,formula,result_ref,expected",
    [
        ("Data", "B3", "=Other!A3", "B4", "=Other!A3"),
        ("Data", "B3", "=$A$3+A$4+$A3+A1", "B4", "=$A$4+A$5+$A4+A1"),
        ("Data", "B1", "=SUM(A3:A4)", "B1", "=SUM(A4:A5)"),
        ("Other", "B1", "=SUM(Data!A3:A4)", "B1", "=SUM(Data!A4:A5)"),
        ("Other", "B3", "=A3", "B3", "=A3"),
        ("Data", "B3", "=SUM(Sales[Q1])", "B4", "=SUM(Sales[Q1])"),
        ("Data", "B1", '=IF(A3>0,"Other!A3",A4)', "B1", '=IF(A4>0,"Other!A3",A5)'),
        ("Data", "B3", "='Data'!A3+data!$A$4", "B4", "='Data'!A4+data!$A$5"),
        ("Data", "B1", "=SUM(3:$4)", "B1", "=SUM(4:$5)"),
        ("Data", "B3", "=XFE3", "B4", "=XFE3"),
        ("Data", "B3", "=  SUM(Other!A1)", "B4", "=  SUM(Other!A1)"),
    ],
)
def test_formula_references_follow_only_inserted_sheet(
    engines, tmp_path, sheet, ref, formula, result_ref, expected
):
    writer, qc = engines
    book = _book()
    book[sheet][ref] = formula
    insertion = _insert(row=1 if "Sales[" in formula else 3)
    template, output, plan = _run(tmp_path, writer, book, [insertion])
    saved = load_workbook(output, data_only=False)
    try:
        assert saved[sheet][result_ref].value == expected
        assert (saved["Data"]["A4"].value, saved["Data"]["A5"].value) == (10, 20)
        assert (saved["Other"]["A3"].value, saved["Other"]["A4"].value) == (101, 202)
    finally:
        saved.close()
    root = _xml(output, 1 if sheet == "Data" else 2)
    assert root.find(f".//x:c[@r='{result_ref}']/x:f", NS).text == expected[1:]
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def test_quoted_sheet_names_and_escaped_apostrophes(engines, tmp_path):
    writer, qc = engines
    book = _book()
    book["Data"].title = "O'Brien data"
    book["Other"]["B1"] = "='O''Brien data'!$A$3+'Other'!A3"
    template, output, plan = _run(tmp_path, writer, book, [_insert(sheet="O'Brien data")])
    expected = "'O''Brien data'!$A$4+'Other'!A3"
    assert _xml(output, 2).find(".//x:c[@r='B1']/x:f", NS).text == expected
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "insert_row,expected_range,anchor,bottom",
    [
        (3, "A4:B5", "A4", "B5"),
        (4, "A3:B5", "A3", "B5"),
    ],
)
def test_vertical_merge_preserves_value_style_and_edges(
    engines, tmp_path, insert_row, expected_range, anchor, bottom
):
    writer, qc = engines
    book = _book()
    data = book["Data"]
    data["A3"] = "original merged value"
    data["A4"] = None
    data["A3"].font = Font(name="Arial", bold=True, italic=True, color="123456", size=13)
    data["A3"].fill = PatternFill("solid", fgColor="FEEABC")
    data["A3"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    data["A3"].number_format = "0.00"
    data["A3"].border = Border(
        left=Side(style="thin", color="112233"), top=Side(style="double", color="445566")
    )
    data["B4"].border = Border(
        right=Side(style="medium", color="778899"), bottom=Side(style="thick", color="AABBCC")
    )
    data.merge_cells("A3:B4")
    data.row_dimensions[3].height = 31
    template, output, plan = _run(tmp_path, writer, book, [_insert(row=insert_row)])
    original, saved = load_workbook(template), load_workbook(output)
    try:
        src, dst = original["Data"]["A3"], saved["Data"][anchor]
        assert dst.value == "original merged value"
        for attr in ("font", "fill", "alignment", "number_format", "protection"):
            assert copy(getattr(dst, attr)) == copy(getattr(src, attr)), attr
        assert {str(r) for r in saved["Data"].merged_cells.ranges} == {expected_range}
        for edge in ("top", "bottom", "left", "right"):
            assert getattr(dst.border, edge) == getattr(src.border, edge), edge
        assert saved["Data"][bottom].border.bottom == original["Data"]["B4"].border.bottom
        assert saved["Data"][bottom].border.right == original["Data"]["B4"].border.right
        assert saved["Data"].row_dimensions[dst.row].height == 31
    finally:
        original.close()
        saved.close()
    root = _xml(output)
    assert root.find(f".//x:c[@r='{anchor}']/x:is/x:t", NS).text == "original merged value"
    assert root.find("x:mergeCells/x:mergeCell", NS).attrib["ref"] == expected_range
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("tampered_value", [999, 10.0000001])
def test_multiple_insertions_and_protection_use_final_coordinates(
    engines, tmp_path, tampered_value
):
    writer, qc = engines
    book = _book()
    book["Data"]["B1"] = "=SUM($A$3:$A$4)"
    template, output, plan = _run(
        tmp_path, writer, book, [_insert(), _insert()], ["Data!A3:A4", "Data!B1"]
    )
    root = _xml(output)
    assert root.find(".//x:c[@r='A5']/x:v", NS).text == "10"
    assert root.find(".//x:c[@r='A6']/x:v", NS).text == "20"
    assert root.find(".//x:c[@r='B1']/x:f", NS).text == "SUM($A$5:$A$6)"
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "PASS", report
    saved = load_workbook(output)
    saved["Data"]["A5"] = tampered_value
    saved.save(output)
    saved.close()
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "FAIL"
    assert report["sections"]["protection"]["status"] == "fail"


def test_overlapping_single_column_merge_keeps_original_anchor(engines, tmp_path):
    writer, qc = engines
    book = _book()
    book["Data"]["A4"] = None
    book["Data"].merge_cells("A3:A4")
    template, output, plan = _run(tmp_path, writer, book, [_insert()])
    root = _xml(output)
    assert root.find(".//x:c[@r='A4']/x:v", NS).text == "10"
    assert root.find("x:mergeCells/x:mergeCell", NS).attrib["ref"] == "A4:A5"
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "phase", ["cell_writes", "formula_writes", "clear_ranges", "cell_styles", "merge_cells"]
)
def test_inserted_protected_cells_cannot_be_overwritten(engines, tmp_path, phase):
    writer, _ = engines
    action = {"phase": phase, "sheet": "Data", "range": "A5:B5", "bold": True}
    if phase in ("cell_writes", "formula_writes"):
        action["writes"] = [{"sheet": "Data", "ref": "A5", "value": 999, "formula": "=999"}]
    if phase == "clear_ranges":
        action["ranges"] = ["Data!A5:A6"]
    with pytest.raises(writer.PlanError, match="保护区"):
        _run(tmp_path, writer, _book(), [_insert(), _insert(), action], ["Data!A3:A4"])
    assert not (tmp_path / "filled.xlsx").exists()
    assert _xml(tmp_path / "template.xlsx").find(".//x:c[@r='A3']/x:v", NS).text == "10"


@pytest.mark.parametrize(
    "tamper",
    [
        "upper_formula",
        "cross_formula",
        "foreign_formula",
        "merge",
        "value",
        "font",
        "border",
        "inserted_value",
    ],
)
def test_qc_rejects_saved_structural_corruption(engines, tmp_path, tamper):
    writer, qc = engines
    book = _book()
    book["Data"]["B1"] = "=SUM(A3:A4)"
    book["Data"]["C3"] = "=Other!A3"
    book["Other"]["B1"] = "=Data!A3"
    book["Data"]["D3"] = "merged original"
    book["Data"]["D3"].font = Font(bold=True)
    book["Data"]["D3"].border = Border(bottom=Side(style="thick"))
    book["Data"].merge_cells("D3:E4")
    template, output, plan = _run(tmp_path, writer, book, [_insert()])
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    data = saved["Data"]
    if tamper == "upper_formula":
        data["B1"] = "=SUM(A3:A4)"
    elif tamper == "cross_formula":
        saved["Other"]["B1"] = "=Data!A3"
    elif tamper == "foreign_formula":
        data["C4"] = "=Other!A4"
    elif tamper == "merge":
        data.unmerge_cells("D4:E5")
    elif tamper == "value":
        data["D4"] = None
    elif tamper == "font":
        data["D4"].font = Font(bold=False)
    elif tamper == "inserted_value":
        data["A3"] = 999
    else:
        for row in data["D4:E5"]:
            for cell in row:
                cell.border = Border()
    saved.save(output)
    saved.close()
    report = qc.run_qc(output, plan, template_path=template)
    assert report["verdict"] == "FAIL", report
    assert report["sections"]["conformance"]["status"] == "fail"


def test_phase_writes_before_insertions_are_verified_at_final_locations(engines, tmp_path):
    writer, qc = engines
    book = _book()
    phases = [
        {"phase": "cell_writes", "writes": [{"sheet": "Data", "ref": "A3", "value": 99}]},
        {
            "phase": "formula_writes",
            "writes": [{"sheet": "Other", "ref": "B1", "formula": "=Data!$A$3"}],
        },
        {"phase": "cell_styles", "sheet": "Data", "range": "A3", "bold": True},
        _insert(),
        _insert(),
    ]
    template, output, plan = _run(tmp_path, writer, book, phases)
    assert _xml(output).find(".//x:c[@r='A5']/x:v", NS).text == "99"
    assert _xml(output, 2).find(".//x:c[@r='B1']/x:f", NS).text == "Data!$A$5"
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("feature", ["cell", "formula", "row_height"])
def test_insertions_cannot_overflow_xlsx_row_limit(engines, tmp_path, feature):
    writer, _ = engines
    book = _book()
    if feature == "cell":
        book["Data"]["A1048576"] = "last row"
    elif feature == "formula":
        book["Other"]["B1"] = "=Data!$A$1048576"
    else:
        book["Data"].row_dimensions[1048576].height = 42
    with pytest.raises(writer.PlanError, match="上限"):
        _run(tmp_path, writer, book, [_insert(row=1)])
    assert not (tmp_path / "filled.xlsx").exists()


def test_null_style_fields_do_not_exempt_original_format(engines, tmp_path):
    writer, qc = engines
    phases = [
        {
            "phase": "cell_styles",
            "sheet": "Data",
            "range": "A3",
            "bold": True,
            "font_size": None,
            "fill_color": "",
        },
        _insert(),
    ]
    template, output, plan = _run(tmp_path, writer, _book(), phases)
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    saved["Data"]["A4"].fill = PatternFill("solid", fgColor="FF0000")
    saved.save(output)
    saved.close()
    assert qc.run_qc(output, plan, template_path=template)["verdict"] == "FAIL"
