"""Reference expansion preserves source bytes and cannot conceal changed table rules."""

import hashlib
import io
import subprocess
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.table import Table, TableColumn, TableFormula, TableStyleInfo

from app.application.agent_orchestrator import workbook_recalculation as calc
from app.application.agent_orchestrator.workbook_calculation_inputs import (
    _evaluation_input,
    _materialized_table,
    _name_semantics,
)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def workbook(tmp_path):
    path = tmp_path / "source.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    for row in (
        ("Units", "Price", "Total"),
        (2, 3, "=[@Units]*[@Price]"),
        (4, 5, "=[@Units]*[@Price]"),
    ):
        sheet.append(row)
    sheet["E1"] = '="[@Units]"'
    sheet["E2"] = "=SUM(Sales[Total])"
    table = Table(displayName="Sales", ref="A1:C3", totalsRowShown=False)
    table.tableColumns = [
        TableColumn(id=i, name=name) for i, name in enumerate(("Units", "Price", "Total"), 1)
    ]
    table.tableColumns[2].calculatedColumnFormula = TableFormula(attr_text="[@Units]*[@Price]")
    table.autoFilter = AutoFilter(ref="A1:C3")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)
    book.save(path)
    book.close()
    return path


def test_expansion_is_token_bound_and_preserves_unmodified_members(tmp_path):
    source = workbook(tmp_path).read_bytes()
    with ZipFile(io.BytesIO(source)) as archive:
        result, rewrites = _evaluation_input(
            source, calc._sheet_parts(archive), calc._table_models(archive)
        )
    assert rewrites == {
        ("Data", cell): "=Sales[[#This Row],[Units]]*Sales[[#This Row],[Price]]"
        for cell in ("C2", "C3")
    }
    assert calc._cells(result)[2] == calc._cells(source)[2]
    assert calc._cells(result)[1]["Data", "E1"] == '="[@Units]"'
    assert calc._calculation_context(result) == calc._calculation_context(source)
    with ZipFile(io.BytesIO(source)) as old, ZipFile(io.BytesIO(result)) as new:
        assert old.namelist() == new.namelist()
        for name in old.namelist():
            if name not in {"xl/worksheets/sheet1.xml", "xl/tables/table1.xml"}:
                assert old.read(name) == new.read(name)
    with ZipFile(io.BytesIO(result)) as archive:
        assert _evaluation_input(
            result, calc._sheet_parts(archive), calc._table_models(archive)
        ) == (result, {})


@pytest.mark.parametrize("replacement", [None, "=2*3", "=[@Units]+[@Price]"])
def test_missing_or_changed_data_formula_preserves_declared_rule(tmp_path, replacement):
    source = workbook(tmp_path).read_bytes()
    formulas = calc._cells(source)[1]
    if replacement is None:
        formulas.pop(("Data", "C3"))
    else:
        formulas["Data", "C3"] = replacement
    with ZipFile(io.BytesIO(source)) as archive:
        table = calc._table_models(archive)[0][2]
    _materialized_table(table, "Data", formulas)
    assert table.find(f"{NS}tableColumns/{NS}tableColumn/{NS}calculatedColumnFormula") is not None


def test_defined_name_quoting_does_not_erase_relative_reference():
    assert _name_semantics("'Data'!$A$1:$A$3") == _name_semantics("Data!$A$1:$A$3")
    assert _name_semantics("Data!A1:A3") != _name_semantics("Data!$A$1:$A$3")


@pytest.mark.skipif(not calc._engine_path(), reason="native Calc required")
def test_real_calc_evaluates_shorthand_without_replacing_delivery(tmp_path, monkeypatch):
    engine = calc._engine_path()
    version = subprocess.run(
        [engine, "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", version)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    path = workbook(tmp_path)
    source = path.read_bytes()
    plan = {
        "plan_version": 1,
        "phases": [],
        "expected": {
            "formula_values": [
                {"sheet": "Data", "ref": ref, "value": value}
                for ref, value in (("C2", 6), ("C3", 20), ("E2", 26))
            ]
        },
    }
    report = calc.recalculate_workbook(
        path, plan, artifact_sha256=hashlib.sha256(source).hexdigest()
    )
    assert report["status"] == "verified", report
    assert report["reference_rewrites"] == 2
    assert report["evaluation_completed"] is True
    assert report["evaluation_input_sha256"] != report["artifact_sha256"]
    assert report["source_unchanged"] and path.read_bytes() == source
