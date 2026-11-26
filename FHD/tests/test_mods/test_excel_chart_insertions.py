"""Chart sources are checked against the original workbook and each plan phase."""

from copy import deepcopy
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, BubbleChart, LineChart, Reference, Series
from openpyxl.chart.data_source import AxDataSource, MultiLevelStrRef, NumDataSource, NumRef, StrRef
from openpyxl.chart.error_bar import ErrorBars
from openpyxl.chart.series import SeriesLabel
from openpyxl.chart.text import Text
from openpyxl.chart.title import Title
from openpyxl.workbook.defined_name import DefinedName

from tests.test_mods._excel_runtime import load_module

ROOT = Path(__file__).resolve().parents[2] / "mods/_employees"


@pytest.fixture
def engines():
    return (
        load_module(
            "chart_writer",
            ROOT / "excel-template-write-employee/backend/vendor/excel_template_write/convert.py",
        ),
        load_module("chart_qc", ROOT / "excel-qc-employee/backend/vendor/excel_qc/checks.py"),
    )


def _book():
    wb = Workbook()
    wb.active.title = "Data"
    wb.create_sheet("Before", 0)
    wb.create_sheet("After")
    wb.create_sheet("Other")
    for ws in wb:
        for row in range(1, 5):
            ws.append([row, row * 10, row / 10, f"label-{row}"])
    return wb


def _bar(ws):
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=2))
    chart.set_categories(Reference(ws, min_col=1, min_row=1, max_row=2))
    return chart


def _with_source(wb, carrier):
    source = wb["Data"]
    chart = _bar(source)
    series = chart.ser[0]
    if carrier == "values":
        series.val.numRef.f = "'Data'!$B$3:$B$4"
    elif carrier == "categories":
        series.cat.numRef.f = "'Data'!$A$3:$A$4"
    elif carrier == "string_categories":
        series.cat = AxDataSource(strRef=StrRef(f="'Data'!$D$3:$D$4"))
    elif carrier == "multi_categories":
        series.cat = AxDataSource(multiLvlStrRef=MultiLevelStrRef(f="'Data'!$A$3:$B$4"))
    elif carrier in {"x", "y", "bubble"}:
        chart = BubbleChart()
        chart.series.append(
            Series(
                Reference(source, min_col=2, min_row=1, max_row=2),
                xvalues=Reference(source, min_col=1, min_row=1, max_row=2),
                zvalues=Reference(source, min_col=3, min_row=1, max_row=2),
            )
        )
        field, column = {"x": ("xVal", "A"), "y": ("yVal", "B"), "bubble": ("bubbleSize", "C")}[
            carrier
        ]
        getattr(chart.ser[0], field).numRef.f = f"'Data'!${column}$3:${column}$4"
    elif carrier == "series_title":
        series.tx = SeriesLabel(strRef=StrRef(f="'Data'!$D$3"))
    elif carrier in {"chart_title", "axis_title"}:
        title = Title(tx=Text(strRef=StrRef(f="'Data'!$D$3")))
        if carrier == "chart_title":
            chart.title = title
        else:
            chart.y_axis.title = title
    elif carrier in {"error_plus", "error_minus"}:
        series.errBars = ErrorBars(
            errDir="y",
            errBarType="both",
            errValType="cust",
            plus=NumDataSource(numRef=NumRef(f="'Data'!$C$1:$C$2")),
            minus=NumDataSource(numRef=NumRef(f="'Data'!$C$1:$C$2")),
        )
        getattr(series.errBars, carrier.removeprefix("error_")).numRef.f = "'Data'!$C$3:$C$4"
    elif carrier == "combo":
        line = LineChart()
        line.add_data(Reference(source, min_col=3, min_row=3, max_row=4))
        chart += line
    else:
        series.val.numRef.f = "'Before:After'!$B$3:$B$4"
    wb["Other"].add_chart(chart, "E1")


def _insert(row=3, sheet="Data"):
    return {"phase": "insert_rows", "sheet": sheet, "row": row, "count": 1}


def _write(writer, template, output, plan):
    return writer.convert_file(
        None, output, template_path=template, payload={"plan": plan}, ctx={}, rule_spec={}
    )


@pytest.mark.parametrize("lane", ["writer", "qc"])
@pytest.mark.parametrize(
    "carrier",
    [
        "values",
        "categories",
        "string_categories",
        "multi_categories",
        "x",
        "y",
        "bubble",
        "series_title",
        "chart_title",
        "axis_title",
        "error_plus",
        "error_minus",
        "combo",
        "three_d",
    ],
)
def test_affected_chart_reference_cannot_be_published_or_pass_qc(tmp_path, engines, lane, carrier):
    wb = _book()
    _with_source(wb, carrier)
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    if lane == "writer":
        with pytest.raises(engines[0].PlanError, match="图表"):
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
        assert any("图表" in item["detail"] for item in section["issues"])


@pytest.mark.parametrize(
    "source",
    [
        "before",
        "other",
        "local",
        "external",
        "named",
        "three_d_above",
        "three_d_outside",
        "dynamic_other",
        "dynamic_external",
    ],
)
def test_unaffected_chart_sources_remain_usable(tmp_path, engines, source):
    wb = _book()
    chart = _bar(wb["Data"])
    reference = {
        "before": "'Data'!$B$1:$B$2",
        "other": "'After'!$B$3:$B$4",
        "local": "B3:B4",
        "external": "'[archive.xlsx]Data'!$B$3:$B$4",
        "named": "Amounts",
        "three_d_above": "'Before:After'!$B$1:$B$2",
        "three_d_outside": "'After:Other'!$B$3:$B$4",
        "dynamic_other": "OFFSET('After'!$B$1,2,0,2,1)",
        "dynamic_external": "OFFSET('[archive.xlsx]Data'!$B$1,2,0,2,1)",
    }[source]
    if source == "named":
        wb.defined_names.add(DefinedName("Amounts", attr_text="Data!$B$3:$B$4"))
    chart.ser[0].val.numRef.f = reference
    wb["Other"].add_chart(chart, "E1")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    assert saved["Other"]._charts[0].ser[0].val.numRef.f == reference
    if source == "named":
        assert saved.defined_names["Amounts"].attr_text == "Data!$B$4:$B$5"
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


def _combo(first=1, last=2, source="Data"):
    return {
        "phase": "create_combo_chart",
        "sheet": "Chart",
        "source_sheet": source,
        "categories": f"A{first}:A{last}",
        "bar_values": f"B{first}:B{last}",
        "line_values": f"C{first}:C{last}",
        "title": "Values",
        "bar_title": "Amount",
        "line_title": "Share",
    }


@pytest.mark.parametrize("order", ["before", "after", "cross_sheet"])
def test_declared_new_chart_and_original_chart_survive_legal_phases(tmp_path, engines, order):
    wb = _book()
    wb["Other"].add_chart(_bar(wb["Data"]), "E1")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    phases = {
        "before": [_combo(), _insert()],
        "after": [_insert(), _combo(4, 5)],
        "cross_sheet": [_combo(3, 4, "After"), _insert()],
    }[order]
    plan = {"phases": phases}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    assert len(saved["Chart"]._charts) == len(saved["Other"]._charts) == 1
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("before", [True, False])
def test_declared_single_point_chart_uses_saved_reference_shape(tmp_path, engines, before):
    wb = Workbook()
    wb.active.title = "Data"
    wb.active.append([1, 10, 0.1])
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    phases = [_combo(1, 1), _insert()] if before else [_insert(), _combo(1, 1)]
    plan = {"phases": phases}
    _write(engines[0], template, output, plan)
    saved = load_workbook(output)
    assert saved["Chart"]._charts[0].ser[0].val.numRef.f == "'Data'!$B$1"
    saved.close()
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("lane", ["writer", "qc"])
@pytest.mark.parametrize("prior_insert", [False, True])
def test_created_chart_is_checked_at_each_later_insertion(tmp_path, engines, lane, prior_insert):
    wb = _book()
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    initial = ([_insert(10)] if prior_insert else []) + [_combo(3, 4)]
    plan = {"phases": initial + [_insert()]}
    if lane == "writer":
        with pytest.raises(engines[0].PlanError, match="图表"):
            _write(engines[0], template, output, plan)
        assert not output.exists()
    else:
        _write(engines[0], template, output, {"phases": initial})
        broken = load_workbook(output)
        broken["Data"].insert_rows(3)
        broken.save(output)
        broken.close()
        section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
        assert section["status"] == "fail"
        assert any("图表来源引用受插行影响" in issue["detail"] for issue in section["issues"])


@pytest.mark.parametrize("kind", ["remove_sheets", "retain_sheets"])
def test_removing_original_chart_before_insertion_is_allowed(tmp_path, engines, kind):
    wb = _book()
    _with_source(wb, "values")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    names = ["Other"] if kind == "remove_sheets" else ["Before", "Data", "After"]
    plan = {"phases": [{"phase": kind, "names": names}, _insert()]}
    _write(engines[0], template, output, plan)
    assert engines[1].run_qc(output, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("lane", ["writer", "qc"])
def test_later_chart_removal_does_not_bypass_earlier_insertion(tmp_path, engines, lane):
    wb = _book()
    _with_source(wb, "values")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert(), {"phase": "remove_sheets", "names": ["Other"]}]}
    if lane == "writer":
        with pytest.raises(engines[0].PlanError, match="图表"):
            _write(engines[0], template, output, plan)
        assert not output.exists()
    else:
        broken = load_workbook(template)
        broken["Data"].insert_rows(3)
        del broken["Other"]
        broken.save(output)
        broken.close()
        section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
        assert section["status"] == "fail"
        assert any("图表来源引用受插行影响" in issue["detail"] for issue in section["issues"])


@pytest.mark.parametrize(
    "change",
    ["source", "swap", "missing_ref", "extra_ref", "missing_chart", "extra_chart", "missing_sheet"],
)
def test_independent_qc_rejects_undeclared_chart_source_changes(tmp_path, engines, change):
    wb = _book()
    wb["Other"].add_chart(_bar(wb["Data"]), "E1")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    _write(engines[0], template, output, plan)
    broken = load_workbook(output)
    chart = broken["Other"]._charts[0]
    if change == "source":
        chart.ser[0].val.numRef.f = "'Data'!$B$1"
    elif change == "swap":
        chart.ser[0].cat.numRef.f, chart.ser[0].val.numRef.f = (
            chart.ser[0].val.numRef.f,
            chart.ser[0].cat.numRef.f,
        )
    elif change == "missing_ref":
        chart.ser[0].cat = None
    elif change == "extra_ref":
        chart.ser[0].tx = SeriesLabel(strRef=StrRef(f="'After'!$D$1"))
    elif change == "missing_chart":
        broken["Other"]._charts.clear()
    elif change == "extra_chart":
        broken["Other"].add_chart(deepcopy(chart), "K1")
    else:
        del broken["Other"]
    broken.save(output)
    broken.close()
    section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "fail"
    assert any("图表" in issue["detail"] for issue in section["issues"])


@pytest.mark.parametrize("lane", ["writer", "qc"])
@pytest.mark.parametrize(
    "formula",
    [
        "OFFSET('Data'!$B$1,2,0,2,1)",
        "INDEX('Data'!$B:$B,3):INDEX('Data'!$B:$B,4)",
        'INDIRECT("Data!B3:B4")',
    ],
)
def test_dynamic_chart_extents_are_not_inferred_from_literal_base(tmp_path, engines, lane, formula):
    wb = _book()
    chart = _bar(wb["Data"])
    chart.ser[0].val.numRef.f = formula
    wb["Other"].add_chart(chart, "E1")
    template, output = tmp_path / "template.xlsx", tmp_path / "result.xlsx"
    wb.save(template)
    wb.close()
    plan = {"phases": [_insert()]}
    if lane == "writer":
        with pytest.raises(engines[0].PlanError, match="图表"):
            _write(engines[0], template, output, plan)
        assert not output.exists()
    else:
        broken = load_workbook(template)
        broken["Data"].insert_rows(3)
        broken.save(output)
        broken.close()
        section = engines[1].run_qc(output, plan, template_path=template)["sections"]["conformance"]
        assert section["status"] == "fail"
        assert any("图表" in issue["detail"] for issue in section["issues"])
