"""Conditional rules must survive insertions or fail before a workbook is published."""

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import (
    CellIsRule,
    ColorScale,
    DataBar,
    FormatObject,
    FormulaRule,
    IconSet,
    Rule,
)
from openpyxl.styles import PatternFill

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"


@pytest.fixture
def engines():
    return (
        load_module(
            "conditional_writer",
            ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
        ),
        load_module("conditional_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"),
    )


def _book():
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A3"], ws["A4"], ws["B1"], ws["B2"] = 4, 7, 1, 2
    ws["B3"], ws["B4"] = -10, -20
    other = wb.create_sheet("Other")
    other["A3"], other["A4"], other["B1"], other["B2"] = 40, 70, 10, 20
    return wb


def _insert(row=3, sheet="Data"):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": 1}


def _formula(text):
    return FormulaRule(formula=[text], fill=PatternFill("solid", fgColor="FFFF0000"))


def _threshold(kind, formula):
    values = [FormatObject(type="formula", val=formula), FormatObject(type="max")]
    if kind == "colorScale":
        return Rule(
            type=kind,
            colorScale=ColorScale(cfvo=values, color=["FFFF0000", "FF00FF00"]),
        )
    if kind == "dataBar":
        return Rule(type=kind, dataBar=DataBar(cfvo=values, color="FFFF0000"))
    return Rule(
        type="iconSet",
        iconSet=IconSet(
            iconSet="3Arrows",
            cfvo=[values[0], FormatObject(type="num", val=5), FormatObject(type="num", val=9)],
        ),
    )


def _write(writer, template, output, plan):
    return writer.convert_file(
        None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
    )


@pytest.mark.parametrize("lane", ["writer", "qc"])
@pytest.mark.parametrize(
    "case",
    [
        "range",
        "formula",
        "relative",
        "cross",
        "cross_relative",
        "multi",
        "colorScale",
        "dataBar",
        "iconSet",
        "offset",
        "indirect",
        "three_d",
    ],
)
def test_affected_conditional_formats_cannot_be_published_or_pass_qc(tmp_path, engines, lane, case):
    wb = _book()
    ws = wb["Other" if case.startswith("cross") else "Data"]
    area = "B3:B4" if case == "range" else "B1:B2 D4:D5" if case == "multi" else "B1:B2"
    if case in {"colorScale", "dataBar", "iconSet"}:
        rule = _threshold(case, "A4")
    elif case in {"range", "multi"}:
        rule = CellIsRule(operator="lessThan", formula=["0"])
    elif case in {"offset", "indirect", "three_d"}:
        rule = _formula(
            {
                "offset": "OFFSET(A1,3,0)>0",
                "indirect": 'INDIRECT("Data!A4")>0',
                "three_d": "SUM(Data:Other!A4)>0",
            }[case]
        )
    else:
        ref = "A2" if case in {"relative", "cross_relative"} else "A4"
        rule = _formula(("Data!" if case.startswith("cross") else "") + ref + ">0")
    ws.conditional_formatting.add(area, rule)
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}

    if lane == "writer":
        with pytest.raises(engines[0].PlanError, match="条件格式"):
            _write(engines[0], template, output, plan)
        assert not output.exists()
    else:
        broken = load_workbook(template)
        broken["Data"].insert_rows(3)
        broken.save(output)
        broken.close()
        report = engines[1].run_qc(output, plan, template_path=template)
        section = report["sections"]["conformance"]
        assert section["status"] == "fail", report
        assert any("条件格式" in item["detail"] for item in section["issues"])


@pytest.mark.parametrize(
    "formula", ["A1>0", "$A$2>0", "Other!A4>0", "OFFSET(Other!A1,3,0)>0", "SUM(Data:Other!$A$1)>0"]
)
def test_unaffected_rules_keep_their_saved_semantics(tmp_path, engines, formula):
    wb = _book()
    rule = _formula(formula)
    rule.priority, rule.stopIfTrue = 7, True
    wb["Data"].conditional_formatting.add("B1:B2", rule)
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    actual = saved["Data"].conditional_formatting["B1:B2"][0]
    assert actual.formula == [formula]
    assert actual.priority == 7 and actual.stopIfTrue is True
    assert actual.dxf.fill.fgColor.rgb == "FFFF0000"
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def _phase(kind, area="B1:B2", sheet="Data"):
    return {
        "phase": "conditional_format",
        "sheet": sheet,
        "range": area,
        "rule": kind,
        "color": "00FF00",
        **{
            "top_percent": {"percent": 10},
            "less_than": {"threshold": 0},
            "duplicate_rows": {"key_column": area[0]},
        }[kind],
    }


@pytest.mark.parametrize("kind", ["top_percent", "less_than", "duplicate_rows"])
@pytest.mark.parametrize("placement", ["before", "after", "other"])
def test_authorized_conditionals_keep_original_rules_and_phase_order(
    tmp_path, engines, kind, placement
):
    wb = _book()
    original = _formula("$A$1>0")
    original.priority = 7
    wb["Data"].conditional_formatting.add("B1:B2", original)
    declared = _phase(
        kind,
        "B3:B4" if placement in {"after", "other"} else "B1:B2",
        "Other" if placement == "other" else "Data",
    )
    phases = [_insert(), declared] if placement == "after" else [declared, _insert()]
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": phases}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    preserved = saved["Data"].conditional_formatting["B1:B2"][0]
    assert preserved.formula == ["$A$1>0"] and preserved.priority == 7
    assert preserved.dxf.fill.fgColor.rgb == "FFFF0000"
    added = saved[declared["sheet"]].conditional_formatting[declared["range"]][-1]
    assert added.priority == (1 if placement == "other" else 2)
    saved.close()
    report = engines[1].run_qc(output, plan, template_path=template)
    assert report["verdict"] == "PASS", report


@pytest.mark.parametrize("kind", ["top_percent", "less_than", "duplicate_rows"])
def test_new_conditional_before_affected_insertion_is_rejected(tmp_path, engines, kind):
    wb = _book()
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    declared = _phase(kind, "B3:B4")
    plan = {"phases": [declared, _insert(sheet=" 'Data' ")]}
    with pytest.raises(engines[0].PlanError, match="条件格式"):
        _write(engines[0], template, output, plan)
    assert not output.exists()
    _write(engines[0], template, output, {"phases": [declared]})
    broken = load_workbook(output)
    broken["Data"].insert_rows(3)
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("条件格式" in item["detail"] for item in section["issues"])


@pytest.mark.parametrize(
    "tamper", ["range", "formula", "style", "priority", "stop", "missing", "added", "pivot", "cfvo"]
)
def test_independent_qc_rejects_conditional_metadata_tampering(tmp_path, engines, tamper):
    wb = _book()
    rule = _threshold("colorScale", "$A$1") if tamper == "cfvo" else _formula("$A$1>0")
    rule.priority = 7
    wb["Data"].conditional_formatting.add("B1:B2", rule)
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    formats = saved["Data"].conditional_formatting
    actual = formats["B1:B2"][0]
    if tamper in {"range", "missing"}:
        del formats["B1:B2"]
        if tamper == "range":
            formats.add("C1:C2", actual)
    elif tamper == "formula":
        actual.formula = ["$A$2>0"]
    elif tamper == "style":
        actual.dxf.fill.fgColor = "FF00FF00"
    elif tamper == "priority":
        actual.priority = 8
    elif tamper == "stop":
        actual.stopIfTrue = True
    elif tamper == "added":
        formats.add("C1:C2", _formula("$A$1>0"))
    elif tamper == "pivot":
        next(iter(formats)).pivot = True
    else:
        actual.colorScale.cfvo[0].val = "$A$2"
    saved.save(output)
    saved.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("条件格式元数据" in item["detail"] for item in section["issues"])
