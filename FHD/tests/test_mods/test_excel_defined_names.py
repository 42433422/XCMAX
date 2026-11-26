"""Saved-workbook named destinations follow insertions and remain independently checked."""

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"


@pytest.fixture
def engines():
    writer = load_module(
        "names_writer",
        ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
    )
    qc = load_module("names_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py")
    return writer, qc


def _book():
    book = Workbook()
    data = book.active
    data.title = "Data"
    data["A3"], data["A4"], data["B1"] = 10, 20, "=SUM(Amounts)"
    other = book.create_sheet("Other")
    other["A3"], other["A4"], other["B1"] = 101, 202, "=SUM(Amounts)"
    for name, expression in (
        ("Amounts", "Data!$A$3:$A$4"),
        ("Union", "'Data'!$A$3,'Other'!$A$4"),
        ("Shadow", "Other!$A$3:$A$4"),
        ("Scalar", "42"),
        ("Text", '"Data!A3"'),
        ("Alias", "Amounts"),
        ("Columns", "Data!$A:$A"),
        ("External", "'[archive.xlsx]Data'!$A$3:$A$4"),
    ):
        book.defined_names.add(DefinedName(name, attr_text=expression))
    data.defined_names.add(DefinedName("Shadow", attr_text="$A$3:$A$4"))
    other.defined_names.add(DefinedName("Shadow", attr_text="Other!$A$3:$A$4"))
    other.defined_names.add(DefinedName("Cross", attr_text="Data!$A$3:$A$4"))
    return book


def _insert(row=3, count=1, sheet="Data"):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": count}


def _run(tmp_path, engines, book, phases):
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": phases}
    engines[0].convert_file(
        None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
    )
    return template, output, plan


@pytest.mark.parametrize(
    "phases,data_range,other_range,union",
    [
        ([_insert()], "$A$4:$A$5", "$A$3:$A$4", "'Data'!$A$4,'Other'!$A$4"),
        ([_insert(4, 2)], "$A$3:$A$6", "$A$3:$A$4", "'Data'!$A$3,'Other'!$A$4"),
        (
            [_insert(), _insert(1, 2), _insert(4, 1, "Other")],
            "$A$6:$A$7",
            "$A$3:$A$5",
            "'Data'!$A$6,'Other'!$A$5",
        ),
        ([_insert(10)], "$A$3:$A$4", "$A$3:$A$4", "'Data'!$A$3,'Other'!$A$4"),
    ],
)
def test_scoped_names_follow_cross_sheet_and_repeated_insertions(
    tmp_path, engines, phases, data_range, other_range, union
):
    template, output, plan = _run(tmp_path, engines, _book(), phases)
    result = load_workbook(output)
    try:
        assert result.defined_names["Amounts"].attr_text == "Data!" + data_range
        assert result.defined_names["Union"].attr_text == union
        assert result.defined_names["Shadow"].attr_text == "Other!" + other_range
        assert result["Data"].defined_names["Shadow"].attr_text == data_range
        assert result["Other"].defined_names["Shadow"].attr_text == "Other!" + other_range
        assert result["Other"].defined_names["Cross"].attr_text == "Data!" + data_range
        for name, expected in (
            ("Scalar", "42"),
            ("Text", '"Data!A3"'),
            ("Alias", "Amounts"),
            ("Columns", "Data!$A:$A"),
            ("External", "'[archive.xlsx]Data'!$A$3:$A$4"),
        ):
            assert result.defined_names[name].attr_text == expected
        # Resolve the actual persisted destination, not only the formula spelling.
        rows = result["Data"][data_range.replace("$", "")]
        assert sum(cell.value or 0 for row in rows for cell in row) == 30
        assert result["Other"]["B1"].value == "=SUM(Amounts)"
    finally:
        result.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "corruption", ["global", "local", "cross", "unaffected", "missing", "shadow"]
)
def test_qc_rejects_named_destination_tampering(tmp_path, engines, corruption):
    template, output, plan = _run(tmp_path, engines, _book(), [_insert()])
    result = load_workbook(output)
    if corruption == "global":
        result.defined_names["Amounts"].attr_text = "Data!$A$3:$A$4"
    elif corruption == "local":
        result["Data"].defined_names["Shadow"].attr_text = "$A$3:$A$4"
    elif corruption == "cross":
        result["Other"].defined_names["Cross"].attr_text = "Data!$A$1:$A$2"
    elif corruption == "unaffected":
        result.defined_names["Shadow"].attr_text = "Other!$A$1:$A$2"
    elif corruption == "missing":
        del result.defined_names["Amounts"]
    else:
        result["Data"].defined_names.add(DefinedName("Amounts", attr_text="Data!$A$1"))
    result.save(output)
    result.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("定义名称" in issue["detail"] for issue in section["issues"])


@pytest.mark.parametrize(
    "expression",
    [
        "Data:Other!$A$3:$A$4",
        "Before:After!$A$3:$A$4",
        "OFFSET(Data!$A$1,2,0,2,1)",
        'INDIRECT("Data!A3:A4")',
        "$A$3:$A$4",
        "Data!$A$3#",
        "Data!$A$1048576",
    ],
)
def test_unsupported_affected_names_fail_before_output_and_cannot_pass_qc(
    tmp_path, engines, expression
):
    book = Workbook()
    book.active.title = "Data"
    book.active["A3"], book.active["A4"] = 10, 20
    book.create_sheet("Other")
    book.create_sheet("Before", 0)
    book.create_sheet("After")
    book.defined_names.add(DefinedName("Unsafe", attr_text=expression))
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_insert()]}
    with pytest.raises(engines[0].PlanError, match="定义名称"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    # A manually produced XLSX with unshifted/unsupported names must fail independent QC.
    broken = load_workbook(template)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("定义名称" in issue["detail"] for issue in section["issues"])


def test_unaffected_dynamic_and_three_dimensional_names_are_retained(tmp_path, engines):
    book = _book()
    book.create_sheet("Last")
    expressions = {
        "OtherOffset": "OFFSET(Other!$A$1,2,0,2,1)",
        "OtherSum": "SUM(Other!$A$3:$A$4)",
        "OtherSheets": "Other:Last!$A$3:$A$4",
        "BeforeInsertion": "Data!$A$1",
    }
    for name, expression in expressions.items():
        book.defined_names.add(DefinedName(name, attr_text=expression))
    template, output, plan = _run(tmp_path, engines, book, [_insert()])
    saved = load_workbook(output)
    try:
        for name, expression in expressions.items():
            assert saved.defined_names[name].attr_text == expression
    finally:
        saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def test_quoted_names_and_case_insensitive_local_aliases(tmp_path, engines):
    book = Workbook()
    sheet = book.active
    sheet.title = "O'Brien data"
    sheet["A3"], sheet["A4"] = 10, 20
    sheet.defined_names.add(DefinedName("LocalOnly", attr_text="'O''Brien data'!$A$3:$A$4"))
    book.defined_names.add(DefinedName("Shared", attr_text="'O''BRIEN DATA'!LocalOnly"))
    template, output, plan = _run(tmp_path, engines, book, [_insert(sheet=sheet.title)])
    saved = load_workbook(output)
    try:
        assert (
            saved[sheet.title].defined_names["LocalOnly"].attr_text == "'O''Brien data'!$A$4:$A$5"
        )
        assert saved.defined_names["Shared"].attr_text == "'O''BRIEN DATA'!LocalOnly"
    finally:
        saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def _dropdown(sheet="Data", source_sheet="Data", source_range="A4:A5", target="D1:D2"):
    return {
        "phase": "data_validation",
        "sheet": sheet,
        "range": target,
        "rule": "list",
        "source_sheet": source_sheet,
        "source_range": source_range,
        "name": "ProductNames",
        "error": "Choose a product",
    }


@pytest.mark.parametrize(
    "phases,expected",
    [
        ([_insert(), _dropdown()], "'Data'!$A$4:$A$5"),
        ([_dropdown("Other", "Other", "A3:A4"), _insert()], "'Other'!$A$3:$A$4"),
        ([_dropdown(source_range="A1:A2"), _insert()], "'Data'!$A$1:$A$2"),
    ],
)
def test_declared_dropdown_names_are_authorized_at_their_phase(tmp_path, engines, phases, expected):
    template, output, plan = _run(tmp_path, engines, _book(), phases)
    saved = load_workbook(output)
    assert saved.defined_names["ProductNames"].attr_text == expected
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    saved.defined_names["ProductNames"].attr_text = "'Other'!$A$1"
    saved.save(output)
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "dropdown",
    [_dropdown("Other", "Data", "A3:A4"), _dropdown("Data", "Other", "A3:A4", "D3:D4")],
)
@pytest.mark.parametrize("insert_sheet", ["Data", "'Data'", " Data "])
def test_unsupported_insert_after_named_dropdown_is_rejected_before_output(
    tmp_path, engines, dropdown, insert_sheet
):
    from app.mod_sdk.workbook_controls import write_control

    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book = _book()
    book.save(template)
    book.close()
    plan = {"phases": [dropdown, _insert(sheet=insert_sheet)]}
    with pytest.raises(engines[0].PlanError, match="定义名称.*下拉"):
        engines[0].convert_file(
            None,
            output,
            template_path=template,
            payload={"plan": plan},
            ctx={},
            rule_spec={},
        )
    assert not output.exists()
    broken = load_workbook(template)
    write_control(broken, dropdown)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("定义名称下拉" in item["detail"] for item in section["issues"])


@pytest.mark.parametrize("kind", ["print_area", "print_title_rows", "auto_filter"])
def test_affected_reserved_names_fail_explicitly(tmp_path, engines, kind):
    book = _book()
    sheet = book["Data"]
    if kind == "auto_filter":
        sheet.auto_filter.ref = "A1:B4"
    else:
        setattr(sheet, kind, "2:4" if kind == "print_title_rows" else "A1:B4")
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_insert()]}
    with pytest.raises(engines[0].PlanError, match="定义名称|工作表级筛选"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    broken = load_workbook(template)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("保留定义名称" in item["detail"] for item in section["issues"])


def test_unaffected_reserved_names_do_not_block_insertions(tmp_path, engines):
    book = _book()
    sheet = book["Data"]
    sheet.print_area = "A1:B2"
    sheet.print_title_rows = "1:2"
    sheet.auto_filter.ref = "A1:B2"
    template, output, plan = _run(tmp_path, engines, book, [_insert()])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "attribute,changed",
    [("print_area", "A1:B99"), ("print_title_rows", "1:99"), ("print_title_cols", "A:Z")],
)
def test_qc_rejects_tampering_with_unaffected_print_names(tmp_path, engines, attribute, changed):
    book = _book()
    sheet = book["Data"]
    sheet.print_area, sheet.print_title_rows, sheet.print_title_cols = "A1:B2", "1:2", "A:B"
    template, output, plan = _run(tmp_path, engines, book, [_insert(6)])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    setattr(saved["Data"], attribute, changed)
    saved.save(output)
    saved.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("保留定义名称" in item["detail"] for item in section["issues"])


def test_declared_print_layout_after_insertion_can_replace_print_names(tmp_path, engines):
    book = _book()
    book["Data"].print_area, book["Data"].print_title_rows = "A1:B2", "1:2"
    layout = {
        "phase": "print_layout",
        "sheet": "Data",
        "range": "A1:D20",
        "orientation": "landscape",
        "paper": "A4",
        "margins": "narrow",
        "title_first_row": 1,
        "title_last_row": 3,
        "fit_width": 1,
        "footer": "Page &P",
    }
    template, output, plan = _run(tmp_path, engines, book, [_insert(6), layout])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def test_affected_existing_named_dropdown_is_rejected_and_cannot_pass_qc(tmp_path, engines):
    from app.mod_sdk.workbook_controls import write_control

    book = _book()
    write_control(book, _dropdown("Data", "Other", "A1:A2", "C3:C4"))
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_insert()]}
    with pytest.raises(engines[0].PlanError, match="既有.*下拉"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    broken = load_workbook(template)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("既有" in item["detail"] and "下拉" in item["detail"] for item in section["issues"])


@pytest.mark.parametrize(
    "attribute,value", [("sqref", "C3:C99"), ("formula1", "Amounts"), ("error", "tampered")]
)
def test_qc_preserves_unaffected_existing_dropdown_metadata(tmp_path, engines, attribute, value):
    from app.mod_sdk.workbook_controls import write_control

    book = _book()
    write_control(book, _dropdown("Other", "Other", "A1:A2", "C3:C4"))
    template, output, plan = _run(tmp_path, engines, book, [_insert()])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    setattr(saved["Other"].data_validations.dataValidation[0], attribute, value)
    saved.save(output)
    saved.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("验证元数据" in item["detail"] for item in section["issues"])


def test_declared_dropdown_can_be_appended_without_hiding_existing_metadata(tmp_path, engines):
    from app.mod_sdk.workbook_controls import write_control

    book = _book()
    write_control(book, _dropdown("Other", "Other", "A1:A2", "C3:C4"))
    phases = [_insert(), _dropdown("Other", "Other", "A1:A2", "D1:D2")]
    template, output, plan = _run(tmp_path, engines, book, phases)
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def _existing_validation(book, kind, sheet="Data", area="B3:B4"):
    from openpyxl.worksheet.datavalidation import DataValidation

    options = (
        {"formula1": "ISNUMBER(B3)"}
        if kind == "custom"
        else {"operator": "between", "formula1": "1", "formula2": "100"}
    )
    validation = DataValidation(
        type=kind, showErrorMessage=True, errorStyle="stop", error="Invalid value", **options
    )
    validation.add(area)
    book[sheet].add_data_validation(validation)


@pytest.mark.parametrize("kind", ["whole", "decimal", "date", "custom"])
def test_affected_non_list_validation_is_rejected_and_cannot_pass_qc(tmp_path, engines, kind):
    book = Workbook()
    book.active.title = "Data"
    book["Data"]["B3"], book["Data"]["B4"] = 10, 20
    _existing_validation(book, kind)
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_insert()]}
    with pytest.raises(engines[0].PlanError, match="既有.*验证"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    broken = load_workbook(template)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any(
        "验证" in item["detail"] and "应用范围" in item["detail"] for item in section["issues"]
    )


@pytest.mark.parametrize(
    "kind,attribute,value",
    [
        ("whole", "sqref", "B3:B99"),
        ("decimal", "formula1", "999"),
        ("date", "showErrorMessage", False),
        ("custom", "error", "tampered"),
    ],
)
def test_qc_preserves_non_list_validation_metadata(tmp_path, engines, kind, attribute, value):
    book = _book()
    _existing_validation(book, kind, "Other")
    template, output, plan = _run(tmp_path, engines, book, [_insert()])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    setattr(saved["Other"].data_validations.dataValidation[0], attribute, value)
    saved.save(output)
    saved.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("验证元数据" in item["detail"] for item in section["issues"])


def _whole_validation(area="D3:D4"):
    return {
        "phase": "data_validation",
        "rule": "whole",
        "sheet": "Data",
        "range": area,
        "minimum": 1,
        "maximum": 100,
        "error": "Quantity must be 1-100",
    }


def test_declared_integer_and_list_validations_preserve_existing_rules(tmp_path, engines):
    book = _book()
    _existing_validation(book, "decimal", "Data", "C1:C2")
    _existing_validation(book, "custom", "Other")
    phases = [
        _whole_validation("D1:D2"),
        _insert(),
        _whole_validation(),
        _dropdown("Other", "Other", "A1:A2", "D1:D2"),
    ]
    template, output, plan = _run(tmp_path, engines, book, phases)
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def test_declared_integer_validation_cannot_precede_affected_insertion(tmp_path, engines):
    from app.mod_sdk.workbook_controls import write_control

    book = Workbook()
    book.active.title = "Data"
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_whole_validation(), _insert()]}
    with pytest.raises(engines[0].PlanError, match="验证"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    broken = load_workbook(template)
    write_control(broken, _whole_validation())
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any(
        "验证" in item["detail"] and "应用范围" in item["detail"] for item in section["issues"]
    )


@pytest.mark.parametrize(
    "sheet,kind,attribute,formula",
    [
        ("Data", "custom", "formula1", "A4>0"),
        ("Other", "custom", "formula1", "'Data'!$A$4>0"),
        ("Data", "whole", "formula2", "$A$4"),
        ("Other", "decimal", "formula2", "Data!$A$4"),
    ],
)
def test_validation_formula_cannot_silently_keep_shifted_cell_reference(
    tmp_path, engines, sheet, kind, attribute, formula
):
    book = Workbook()
    book.active.title = "Data"
    book.create_sheet("Other")
    book["Data"]["A4"] = 10
    _existing_validation(book, kind, sheet, "B1:B2")
    setattr(book[sheet].data_validations.dataValidation[0], attribute, formula)
    template, output = tmp_path / "template.xlsx", tmp_path / "filled.xlsx"
    book.save(template)
    book.close()
    plan = {"phases": [_insert()]}
    with pytest.raises(engines[0].PlanError, match="验证.*公式引用"):
        engines[0].convert_file(
            None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
        )
    assert not output.exists()
    broken = load_workbook(template)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any(
        "验证" in item["detail"] and "公式引用" in item["detail"] for item in section["issues"]
    )


@pytest.mark.parametrize(
    "sheet,formula",
    [
        ("Data", "SUM(Amounts)>0"),
        ("Data", "Other!$A$4>0"),
        ("Other", "A4>0"),
        ("Data", '"A4"="A4"'),
    ],
)
def test_validation_preserves_names_constants_and_unaffected_references(
    tmp_path, engines, sheet, formula
):
    book = _book()
    _existing_validation(book, "custom", sheet, "B1:B2")
    book[sheet].data_validations.dataValidation[0].formula1 = formula
    template, output, plan = _run(tmp_path, engines, book, [_insert()])
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"
    saved = load_workbook(output)
    assert saved[sheet].data_validations.dataValidation[0].formula1 == formula
    assert saved.defined_names["Amounts"].attr_text == "Data!$A$4:$A$5"
    saved.close()
