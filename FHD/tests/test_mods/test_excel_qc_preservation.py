"""A valid approved write must not authorize changes elsewhere in the workbook."""

from copy import copy
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.styles import Border, Font, Protection, Side

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"


@pytest.fixture
def preserved_workbook(tmp_path):
    writer = load_module(
        "preservation_writer",
        ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
    )
    qc = load_module(
        "preservation_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"
    )
    source, output = tmp_path / "original.xlsx", tmp_path / "output.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet["A1"], sheet["B1"], sheet["C1"], sheet["D1"] = "old", 10, False, "=B1+1"
    sheet["E1"].font = Font(italic=True)
    sheet["F1"].hyperlink = "https://example.invalid/original"
    sheet["G1"].comment = Comment("original", "author")
    sheet["H1"] = CellRichText([TextBlock(InlineFont(b=True), "bold"), " plain"])
    book.create_sheet("Untouched")["A1"] = "keep"
    book.save(source)
    book.close()

    def run(extra=()):
        plan = {
            "phases": [
                {
                    "phase": "cell_writes",
                    "writes": [{"sheet": "Data", "ref": "A1", "value": "new"}],
                },
                *extra,
            ]
        }
        writer.convert_file(
            None,
            output,
            template_path=source,
            payload={"plan": plan, "strict_protected": True},
            ctx={},
            rule_spec={},
        )
        return qc.run_qc(output, plan, template_path=source), plan

    return source, output, qc, run


@pytest.mark.parametrize(
    "change",
    [
        "value",
        "type",
        "formula",
        "style",
        "write_style",
        "number_format",
        "quote_prefix",
        "blank_style",
        "new_cell",
        "new_style",
        "missing_cell",
        "comment",
        "link",
        "sheet_missing",
        "sheet_extra",
        "sheet_hidden",
        "merge",
        "rich_text",
    ],
)
def test_qc_rejects_changes_outside_approved_cell_fields(preserved_workbook, change):
    source, output, qc, run = preserved_workbook
    original_bytes = source.read_bytes()
    valid, plan = run()
    assert valid["verdict"] == "PASS", valid
    assert valid["sections"]["conformance"]["stats"]["original_content_checked"] is True
    book = load_workbook(output, rich_text=True)
    ws = book["Data"]
    if change == "value":
        ws["B1"] = 999
    elif change == "type":
        ws["C1"] = 0
    elif change == "formula":
        ws["D1"] = "=10+1"
    elif change in {"style", "write_style"}:
        cell = ws["B1" if change == "style" else "A1"]
        font = copy(cell.font)
        font.bold = True
        cell.font = font
    elif change == "number_format":
        ws["B1"].number_format = "0.00"
    elif change == "quote_prefix":
        ws["B1"].quotePrefix = True
    elif change == "blank_style":
        ws["E1"].font = Font()
    elif change == "new_cell":
        ws["Z100"] = "injected"
    elif change == "new_style":
        ws["Z100"].font = Font(bold=True)
    elif change == "missing_cell":
        ws["B1"] = None
    elif change == "comment":
        ws["G1"].comment = Comment("changed", "author")
    elif change == "link":
        ws["F1"].hyperlink = "https://example.invalid/changed"
    elif change == "sheet_missing":
        del book["Untouched"]
    elif change == "sheet_extra":
        book.create_sheet("Injected")
    elif change == "sheet_hidden":
        book["Untouched"].sheet_state = "hidden"
    elif change == "rich_text":
        ws["H1"] = str(ws["H1"].value)
    else:
        ws.merge_cells("I1:J1")
    book.save(output)
    book.close()
    result = qc.run_qc(output, plan, template_path=source)
    assert result["verdict"] == "FAIL", result
    assert result["sections"]["conformance"]["status"] == "fail"
    assert source.read_bytes() == original_bytes


def test_writer_preserves_unapproved_rich_text_runs(preserved_workbook):
    _, output, _, run = preserved_workbook
    result, _ = run()
    assert result["verdict"] == "PASS"
    book = load_workbook(output, rich_text=True)
    try:
        value = book["Data"]["H1"].value
        assert isinstance(value, CellRichText)
        assert value[0].font.b is True and str(value) == "bold plain"
    finally:
        book.close()


@pytest.mark.parametrize(
    "phase",
    [
        {"phase": "clear_ranges", "ranges": ["Data!B1:C1"]},
        {"phase": "cell_styles", "sheet": "Data", "range": "B1", "bold": True},
        {"phase": "merge_cells", "sheet": "Data", "range": "B1:B2"},
        {"phase": "remove_sheets", "names": ["Untouched"]},
        {
            "phase": "cell_writes",
            "writes": [{"sheet": "Data", "ref": "A3", "value": "2026-11-27", "value_type": "date"}],
        },
    ],
)
def test_qc_accepts_explicit_cell_changes_and_sheet_removal(preserved_workbook, phase):
    result, _ = preserved_workbook[3]([phase])
    assert result["verdict"] == "PASS", result


def test_qc_rejects_far_cell_without_expanding_empty_rectangle(preserved_workbook, monkeypatch):
    from openpyxl.worksheet.worksheet import Worksheet

    source, output, qc, run = preserved_workbook
    result, plan = run()
    assert result["verdict"] == "PASS"
    book = load_workbook(output, rich_text=True)
    book["Data"]["XFD1048576"] = "=1+1"
    book.save(output)
    book.close()
    monkeypatch.setattr(Worksheet, "iter_rows", lambda *a, **kw: pytest.fail("dense QC scan"))
    result = qc.run_qc(output, plan, template_path=source)
    assert result["verdict"] == "FAIL"
    assert result["sections"]["conformance"]["stats"]["original_and_output_cells_checked"] < 20
    assert result["sections"]["formulas"]["stats"]["formulas_total"] == 2


@pytest.fixture
def approved_styles(tmp_path):
    writer = load_module(
        "style_writer",
        ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
    )
    qc = load_module("style_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py")

    def run(book, phases):
        source, output = tmp_path / "styles-original.xlsx", tmp_path / "styles-output.xlsx"
        book.active.title = "Data"
        book.save(source)
        book.close()
        plan = {"phases": phases}
        writer.convert_file(
            None,
            output,
            template_path=source,
            payload={"plan": plan, "strict_protected": True},
            ctx={},
            rule_spec={},
        )
        result = qc.run_qc(output, plan, template_path=source)
        assert result["verdict"] == "PASS", result
        return source, output, plan, qc

    return run


@pytest.mark.parametrize(
    "value_type,original_format,explicit_format,expected",
    [
        ("date", "General", None, "yyyy-mm-dd"),
        ("date", "0.00", None, "yyyy-mm-dd"),
        ("date", "dd/mm/yyyy", None, "dd/mm/yyyy"),
        ("date", "General", "yyyy/mm/dd", "yyyy/mm/dd"),
        ("datetime", "General", None, "yyyy-mm-dd h:mm:ss"),
        ("datetime", "yyyy-mm-dd hh:mm", None, "yyyy-mm-dd hh:mm"),
    ],
)
def test_date_formats_follow_exact_openpyxl_assignment(
    approved_styles, value_type, original_format, explicit_format, expected
):
    book = Workbook()
    book.active["A1"].number_format = original_format
    write = {
        "sheet": "Data",
        "ref": "A1",
        "value_type": value_type,
        "value": "2026-11-27" + (" 12:34:56" if value_type == "datetime" else ""),
    }
    if explicit_format:
        write["number_format"] = explicit_format
    source, output, plan, qc = approved_styles(book, [{"phase": "cell_writes", "writes": [write]}])
    saved = load_workbook(output)
    assert saved.active["A1"].number_format == expected
    saved.active["A1"].number_format = "dd-mm-yyyy hh:mm:ss"
    saved.save(output)
    saved.close()
    result = qc.run_qc(output, plan, template_path=source)
    assert result["sections"]["conformance"]["status"] == "fail", result


@pytest.mark.parametrize("original_format,expected", [("General", "$#,##0.00"), ("0.00", "0.00")])
def test_table_total_format_only_inherits_when_original_is_general(
    approved_styles, original_format, expected
):
    book = Workbook()
    sheet = book.active
    sheet.append(["label", "amount"])
    sheet.append(["one", 2])
    sheet["B2"].number_format = "$#,##0.00"
    sheet["B3"].number_format = original_format
    source, output, plan, qc = approved_styles(
        book,
        [
            {
                "phase": "create_table",
                "sheet": "Data",
                "range": "A1:B2",
                "name": "Orders",
                "sum_column": "amount",
                "calculated_formula": "=1+1",
            }
        ],
    )
    saved = load_workbook(output)
    assert saved.active["B3"].number_format == expected
    saved.active["B3"].number_format = "0.0000"
    saved.save(output)
    saved.close()
    result = qc.run_qc(output, plan, template_path=source)
    assert result["sections"]["conformance"]["status"] == "fail", result


@pytest.mark.parametrize("with_template", [True, False])
def test_explicit_formula_number_format_is_checked(approved_styles, with_template):
    book = Workbook()
    source, output, plan, qc = approved_styles(
        book,
        [
            {
                "phase": "formula_writes",
                "writes": [
                    {
                        "sheet": "Data",
                        "ref": "A1",
                        "formula": "=1+1",
                        "number_format": "0.00",
                    }
                ],
            }
        ],
    )
    saved = load_workbook(output)
    saved.active["A1"].number_format = "$#,##0.00"
    saved.save(output)
    saved.close()
    result = qc.run_qc(output, plan, template_path=source if with_template else None)
    assert result["sections"]["conformance"]["status"] == "fail", result
    assert any(
        "number_format" in issue["detail"] for issue in result["sections"]["conformance"]["issues"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "left_color",
        "right_style",
        "diagonal",
        "diagonalUp",
        "diagonalDown",
        "start",
        "end",
        "outline",
        "vertical",
        "horizontal",
    ],
)
def test_declared_four_borders_preserve_all_other_border_fields(approved_styles, change):
    book = Workbook()
    book.active["A1"] = "keep"
    original = Border(
        left=Side(style="double", color="FF112233"),
        diagonal=Side(style="dashDot", color="FF445566"),
        diagonalUp=True,
        diagonalDown=True,
        start=Side(style="medium", color="FF778899"),
        end=Side(style="thick", color="FFAABBCC"),
        vertical=Side(style="dotted"),
        horizontal=Side(style="dashed"),
        outline=False,
    )
    book.active["A1"].border = original
    source, output, plan, qc = approved_styles(
        book,
        [
            {
                "phase": "cell_styles",
                "sheet": "Data",
                "range": "A1",
                "border": "thin",
            }
        ],
    )
    saved = load_workbook(output)
    border = copy(saved.active["A1"].border)
    for field in (
        "diagonal",
        "diagonalUp",
        "diagonalDown",
        "start",
        "end",
        "outline",
        "vertical",
        "horizontal",
    ):
        assert getattr(border, field) == getattr(original, field), field
    assert all(
        getattr(border, edge) == Side(style="thin") for edge in ("left", "right", "top", "bottom")
    )
    if change == "left_color":
        border.left = Side(style="thin", color="FFFF0000")
    elif change == "right_style":
        border.right = Side(style="thick")
    elif change in {"diagonalUp", "diagonalDown", "outline"}:
        setattr(border, change, not getattr(border, change))
    else:
        setattr(border, change, Side(style="hair", color="FF00FF00"))
    saved.active["A1"].border = border
    saved.save(output)
    saved.close()
    result = qc.run_qc(output, plan, template_path=source)
    assert result["sections"]["conformance"]["status"] == "fail", result


@pytest.mark.parametrize("styled", ["none", "before", "after"])
@pytest.mark.parametrize("change", ["left", "diagonalUp", "protection"])
def test_merge_allows_only_exact_native_edge_projection(approved_styles, styled, change):
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "anchor"
    sheet["A1"].border = Border(left=Side(style="thin", color="FF112233"), top=Side(style="double"))
    sheet["A1"].protection = Protection(locked=False, hidden=True)
    sheet["C3"].border = Border(
        right=Side(style="medium"), bottom=Side(style="thick", color="FF445566")
    )
    sheet["B2"].font = Font(italic=True)
    phases = [{"phase": "merge_cells", "sheet": "Data", "range": "A1:C3"}]
    style = {
        "phase": "cell_styles",
        "sheet": "Data",
        "range": "A1:C3",
        "border": "thin",
        "bold": True,
    }
    if styled == "before":
        phases.insert(0, style)
    elif styled == "after":
        phases.append(style)
    source, output, plan, qc = approved_styles(book, phases)
    saved = load_workbook(output)
    if change == "protection":
        saved.active["A1"].protection = Protection(locked=True, hidden=False)
    else:
        border = copy(saved.active["A1"].border)
        if change == "left":
            border.left = Side(style="thick", color="FFFF0000")
        else:
            border.diagonalUp = True
        saved.active["A1"].border = border
    saved.save(output)
    saved.close()
    result = qc.run_qc(output, plan, template_path=source)
    assert result["sections"]["conformance"]["status"] == "fail", result


def test_merge_styles_remain_valid_through_multiple_insertions(approved_styles):
    book = Workbook()
    sheet = book.active
    sheet["A3"] = "anchor"
    sheet["A3"].border = Border(left=Side(style="thin", color="FF112233"))
    sheet["C4"].border = Border(bottom=Side(style="double", color="FF445566"))
    sheet["A3"].protection = Protection(locked=False)
    approved_styles(
        book,
        [
            {"phase": "merge_cells", "sheet": "Data", "range": "A3:C4"},
            {"phase": "insert_rows", "sheet": "Data", "row": 4, "count": 2},
            {"phase": "insert_rows", "sheet": "Data", "row": 4, "count": 1},
            {"phase": "cell_styles", "sheet": "Data", "range": "A3", "horizontal": "center"},
        ],
    )


def test_merge_projection_never_materializes_the_declared_rectangle(monkeypatch):
    from openpyxl.worksheet.worksheet import Worksheet

    qc = load_module(
        "bounded_style_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"
    )
    source, output = Workbook(), Workbook()
    source.active.title = output.active.title = "Data"
    source.active["A1"].border = Border(bottom=Side(style="double"), right=Side(style="thin"))
    merge = Worksheet.merge_cells
    calls = []

    def bounded(self, *args, **kwargs):
        calls.append((kwargs["end_row"], kwargs["end_column"]))
        assert kwargs["end_row"] <= 3 and kwargs["end_column"] <= 3
        return merge(self, *args, **kwargs)

    monkeypatch.setattr(Worksheet, "merge_cells", bounded)
    monkeypatch.setattr(
        Worksheet, "iter_rows", lambda *a, **kw: pytest.fail("dense style projection")
    )
    projection = qc.StyleProjection(
        output,
        source,
        {
            "phases": [
                {
                    "phase": "merge_cells",
                    "sheet": "Data",
                    "range": "A1:XFD1048576",
                }
            ]
        },
        qc._coerce_planned,
    )
    expected = projection("Data", 1_048_576, 16_384)
    assert expected.border.right.style == "thin"
    assert expected.border.bottom.style == "double"
    assert calls and len(source.active._cells) == 1
