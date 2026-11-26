"""Reject unsafe local 3D dependencies before row insertion and independently in QC."""

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"


@pytest.fixture
def engines():
    return (
        load_module(
            "three_d_writer",
            ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
        ),
        load_module("three_d_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"),
    )


def _book(formula):
    book = Workbook()
    book.active.title = "Data"
    for name in ("Middle", "Other", "Outside"):
        book.create_sheet(name)
    for index, sheet in enumerate(book.worksheets, 1):
        sheet["A3"] = index * 10
    book["Outside"]["B1"] = formula
    if "Data one" in formula:
        book["Data"].title, book["Other"].title = "Data one", "Other's"
    return book


def _insert(sheet="Data", row=3, count=1):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": count}


def _paths(tmp_path, book):
    template, output = tmp_path / "template.xlsx", tmp_path / "output.xlsx"
    book.save(template)
    book.close()
    return template, output


def _write(writer, template, output, phases):
    writer.convert_file(
        None,
        output,
        template_path=template,
        payload={"plan": {"phases": phases}},
        ctx={},
        rule_spec={},
    )


def _broken_output(template, output, phases):
    book = load_workbook(template)
    for phase in phases:
        if phase["phase"] == "insert_rows":
            book[phase["sheet"]].insert_rows(phase["row"], phase["count"])
        else:
            for write in phase["writes"]:
                book[write["sheet"]][write["ref"]] = write.get("formula", write.get("value"))
    book.save(output)
    book.close()


def _reject(tmp_path, engines, book, phases, actor):
    template, output = _paths(tmp_path, book)
    if actor == "writer":
        with pytest.raises(engines[0].PlanError, match="三维"):
            _write(engines[0], template, output, phases)
        assert not output.exists()
    else:
        _broken_output(template, output, phases)
        section = engines[1].run_qc(output, {"phases": phases}, template_path=template)["sections"][
            "conformance"
        ]
        assert section["status"] == "fail"
        assert any("三维" in issue["detail"] for issue in section["issues"])


@pytest.mark.parametrize("actor", ["writer", "qc"])
@pytest.mark.parametrize(
    "formula,sheet,row",
    [
        ("=SUM(Data:Other!A3)", "Data", 3),
        ("=SUM(Data:Other!$A$3:$B$5)", "Middle", 4),
        ("=SUM(Data:Other!$3:$4)", "Other", 3),
        ("=SUM(Data:Other!3:3)", "Middle", 1),
        ("=SUM(Other:Data!A$3)", "Middle", 3),
        ("=SUM(data:other!$A3)", "Data", 3),
        ("=SUM('Data one:Other''s'!A3)", "Middle", 3),
        ("=SUM('[archive.xlsx]Data:Other'!A3,Data:Other!A3)", "Middle", 3),
    ],
)
def test_affected_cell_3d_reference_cannot_pass(tmp_path, engines, actor, formula, sheet, row):
    _reject(tmp_path, engines, _book(formula), [_insert(sheet, row)], actor)


@pytest.mark.parametrize(
    "formula,sheet,row",
    [
        ("=SUM(Data:Other!A3)", "Outside", 3),
        ("=SUM(Data:Other!A3)", "Data", 4),
        ("=SUM(Data:Other!$1:$2)", "Middle", 3),
        ("=SUM(Data:Other!$A:$B)", "Middle", 3),
        ("=SUM('[archive.xlsx]Data:Other'!A3)", "Middle", 3),
        ('="Data:Other!A3"', "Data", 3),
    ],
)
def test_unaffected_3d_references_remain_valid(tmp_path, engines, formula, sheet, row):
    template, output = _paths(tmp_path, _book(formula))
    phases = [_insert(sheet, row)]
    _write(engines[0], template, output, phases)
    saved = load_workbook(output)
    assert saved["Outside"]["B1"].value == formula
    saved.close()
    assert (
        engines[1].run_qc(output, {"phases": phases}, template_path=template)["verdict"] == "PASS"
    )


@pytest.mark.parametrize("actor", ["writer", "qc"])
def test_later_insertion_into_middle_sheet_is_checked(tmp_path, engines, actor):
    phases = [_insert("Data", 10, 2), _insert("Middle", 3, 2)]
    _reject(tmp_path, engines, _book("=SUM(Data:Other!A3)"), phases, actor)


@pytest.mark.parametrize("actor", ["writer", "qc"])
@pytest.mark.parametrize("phase,field", [("cell_writes", "value"), ("formula_writes", "formula")])
def test_formula_created_before_insertion_is_checked(tmp_path, engines, actor, phase, field):
    phases = [
        {
            "phase": phase,
            "writes": [{"sheet": "Outside", "ref": "B1", field: "=SUM(Data:Other!A3)"}],
        },
        _insert(),
    ]
    _reject(tmp_path, engines, _book("=1"), phases, actor)


@pytest.mark.parametrize(
    "before",
    [
        {"phase": "cell_writes", "writes": [{"sheet": "Outside", "ref": "B1", "value": 100}]},
        {
            "phase": "formula_writes",
            "writes": [{"sheet": "Outside", "ref": "B1", "formula": "=SUM(Data!A3)"}],
        },
        {"phase": "clear_ranges", "ranges": ["Outside!B1"]},
        {"phase": "remove_sheets", "names": ["Outside"]},
    ],
)
def test_removed_3d_dependency_does_not_block_later_insertion(tmp_path, engines, before):
    template, output = _paths(tmp_path, _book("=SUM(Data:Other!A3)"))
    phases = [before, _insert()]
    _write(engines[0], template, output, phases)
    assert (
        engines[1].run_qc(output, {"phases": phases}, template_path=template)["verdict"] == "PASS"
    )


def test_formula_created_after_insertion_is_allowed(tmp_path, engines):
    template, output = _paths(tmp_path, _book("=1"))
    phases = [
        _insert(),
        {
            "phase": "formula_writes",
            "writes": [{"sheet": "Outside", "ref": "B1", "formula": "=SUM(Data:Other!A3)"}],
        },
    ]
    _write(engines[0], template, output, phases)
    assert (
        engines[1].run_qc(output, {"phases": phases}, template_path=template)["verdict"] == "PASS"
    )


@pytest.mark.parametrize("actor", ["writer", "qc"])
@pytest.mark.parametrize(
    "kind,field",
    [("custom", "formula1"), ("list", "formula1"), ("whole", "formula2"), ("decimal", "formula2")],
)
def test_validation_3d_formula_is_independently_rejected(tmp_path, engines, actor, kind, field):
    book = _book("=1")
    rule = DataValidation(type=kind, formula1="1", formula2="100")
    setattr(rule, field, "SUM(Data:Other!A3)")
    rule.add("B1:B2")
    book["Outside"].add_data_validation(rule)
    _reject(tmp_path, engines, book, [_insert("Middle")], actor)


@pytest.mark.parametrize("formula", ["SUM(Data:Other!A1)", "SUM('[archive.xlsx]Data:Other'!A3)"])
def test_unaffected_validation_3d_formula_is_preserved(tmp_path, engines, formula):
    book = _book("=1")
    rule = DataValidation(type="custom", formula1=formula)
    rule.add("B1:B2")
    book["Outside"].add_data_validation(rule)
    template, output = _paths(tmp_path, book)
    phases = [_insert("Middle")]
    _write(engines[0], template, output, phases)
    assert (
        engines[1].run_qc(output, {"phases": phases}, template_path=template)["verdict"] == "PASS"
    )


@pytest.mark.parametrize("actor", ["writer", "qc"])
@pytest.mark.parametrize("area", ["B1:B2", "B1 C3:C4"])
def test_validation_3d_relative_rows_include_every_application_endpoint(
    tmp_path, engines, actor, area
):
    book = _book("=1")
    rule = DataValidation(type="custom", formula1="SUM(Data:Other!A2)>0")
    rule.sqref = area
    book["Outside"].add_data_validation(rule)
    _reject(tmp_path, engines, book, [_insert("Middle")], actor)


def test_validation_3d_absolute_rows_do_not_expand_with_application_range(tmp_path, engines):
    book = _book("=1")
    rule = DataValidation(type="custom", formula1="SUM(Data:Other!$A$2)>0")
    rule.add("B1:B9")
    book["Outside"].add_data_validation(rule)
    template, output = _paths(tmp_path, book)
    phases = [_insert("Middle")]
    _write(engines[0], template, output, phases)
    assert (
        engines[1].run_qc(output, {"phases": phases}, template_path=template)["verdict"] == "PASS"
    )
