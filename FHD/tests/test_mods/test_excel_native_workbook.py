"""Native Excel layout, table, chart and control conformance scenarios."""

from __future__ import annotations

from copy import copy
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from tests.test_mods._excel_template_cases import (
    _sales_border_phase,
    _sales_chart_phase,
    _sales_header_style_phase,
    _sales_table_phase,
)
from tests.test_mods._excel_template_cases import (
    native_workbook as native_workbook,
)


def test_writer_applies_header_style_and_data_borders(native_workbook):
    run, template, qc, _ = native_workbook
    out, plan = run([_sales_header_style_phase(), _sales_border_phase()])
    wb = load_workbook(out)
    try:
        header = wb["销售明细"]["A1"]
        assert header.font.bold is True
        assert header.alignment.horizontal == "center"
        assert header.alignment.vertical == "center"
        assert header.fill.fgColor.rgb.upper().endswith("FFF2CC")
        for ref in ("A1", "D3"):
            cell = wb["销售明细"][ref]
            assert cell.border.left.style == "thin"
            assert cell.border.right.style == "thin"
            assert cell.border.top.style == "thin"
            assert cell.border.bottom.style == "thin"
    finally:
        wb.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    assert qc.run_qc(template, plan, template_path=template)["verdict"] == "FAIL"


def test_range_number_format_preserves_values_and_types(native_workbook):
    run, template, _, _ = native_workbook
    with_template = load_workbook(template)
    sheet = with_template.active
    sheet["A2"] = "0007"
    with_template.save(template)
    with_template.close()
    phase = {
        "phase": "cell_styles",
        "sheet": sheet.title,
        "range": "A2:E2",
        "number_format": "0000",
    }
    out, _ = run([phase])
    original, result = load_workbook(template), load_workbook(out)
    try:
        for before, after in zip(original.active["A2:E2"][0], result.active["A2:E2"][0]):
            assert (after.value, after.data_type) == (before.value, before.data_type)
            assert after.number_format == "0000"
    finally:
        original.close()
        result.close()
    with pytest.raises(ValueError, match="strict_protected"):
        run([phase], [f"{sheet.title}!C2"])


def test_writer_inserts_title_row_without_losing_existing_data_or_formulas(native_workbook):
    run, template, qc, _ = native_workbook
    sheet = "销售明细"
    title = "2026 年 9 月销售明细表"
    out, plan = run(
        [
            {"phase": "insert_rows", "sheet": sheet, "row": 1, "count": 1},
            {"phase": "merge_cells", "sheet": sheet, "range": "A1:F1"},
            {"phase": "cell_writes", "writes": [{"sheet": sheet, "ref": "A1", "value": title}]},
            {
                "phase": "cell_styles",
                "sheet": sheet,
                "range": "A1",
                "font_size": 18,
                "bold": True,
                "horizontal": "center",
            },
            {"phase": "set_row_height", "sheet": sheet, "row": 1, "height": 30},
            {"phase": "freeze_panes", "sheet": sheet, "ref": "A3"},
        ]
    )
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    wb = load_workbook(out)
    try:
        sales = wb[sheet]
        assert sales["A1"].value == title
        assert [cell.value for cell in sales[2][:4]] == ["产品", "数量", "单价", "金额"]
        assert [cell.value for cell in sales[3][:4]] == ["样品甲", 2, 20, "=ROUND(B3*C3,2)"]
        assert [cell.value for cell in sales[4][:4]] == ["样品乙", 1, 10, "=ROUND(B4*C4,2)"]
        assert {str(region) for region in sales.merged_cells.ranges} == {"A1:F1"}
        assert sales["A1"].font.sz == 18
        assert sales["A1"].font.bold is True
        assert sales["A1"].alignment.horizontal == "center"
        assert sales.row_dimensions[1].height == 30
        assert sales.freeze_panes == "A3"
        sales["D3"] = "=ROUND(B2*C2,2)"
        wb.save(out)
    finally:
        wb.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "FAIL"


def test_writer_relocates_native_table_and_workbook_references(native_workbook):
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.filters import AutoFilter
    from openpyxl.worksheet.table import Table, TableColumn, TableFormula

    run, template, qc, writer = native_workbook
    data_name, summary_name = "销售明细", "产品汇总"
    with template.open("rb") as stream:
        source = load_workbook(stream)
    data, summary = source[data_name], source[summary_name]
    data["A1"] = "Q1"
    table = Table(
        displayName="SampleItems",
        ref="A1:D3",
        autoFilter=AutoFilter(ref="A1:D3"),
        tableColumns=[
            TableColumn(id=index, name=cell.value) for index, cell in enumerate(data[1], start=1)
        ],
    )
    table.autoFilter.add_sort_condition("B2:B3")
    table.tableColumns[3].calculatedColumnFormula = TableFormula(attr_text="$B2*$C2")
    data.add_table(table)
    data.auto_filter.ref = "F1:G3"
    data["D2"] = f"=SUM($B2,'{summary_name}'!$D$2,SampleItems[Q1])"
    data["F1"] = "=SUM(C3:C3)"
    data["A5"] = "Original block"
    data.merge_cells("A5:A6")
    data.row_dimensions[2].height = 24
    summary["D2"] = f"='{data_name}'!$B$2"
    summary["D3"] = "=SUM(B$2:B3)"
    source.defined_names.add(DefinedName("SampleCells", attr_text=f"'{data_name}'!$B$2:$B$3"))
    source.save(template)
    source.close()

    phases = [
        {
            "phase": "formula_writes",
            "writes": [{"sheet": summary_name, "ref": "D4", "formula": f"='{data_name}'!$B$3"}],
        },
        {"phase": "insert_rows", "sheet": data_name, "row": 1, "count": 1},
        {"phase": "insert_rows", "sheet": data_name, "row": 4, "count": 1},
    ]
    protected = [f"{summary_name}!D2:D3"]
    # Complex table metadata remains unsupported: reject it before creating an
    # output, then exercise relocation with the supported native-table contract.
    for reason, field in (
        ("元数据公式", "calculated"),
        ("工作表级筛选/排序", "worksheet_filter"),
        ("筛选范围或排序", "table_sort"),
    ):
        with pytest.raises(writer.PlanError, match=reason):
            run(phases, protected)
        assert not template.with_name("filled.xlsx").exists()
        source = load_workbook(template)
        data = source[data_name]
        table = data.tables["SampleItems"]
        if field == "calculated":
            table.tableColumns[3].calculatedColumnFormula = None
        elif field == "worksheet_filter":
            data.auto_filter.ref = None
        else:
            table.autoFilter.sortState = None
        source.save(template)
        source.close()

    out, plan = run(phases, protected)
    with out.open("rb") as stream:
        saved = load_workbook(stream)
    try:
        data, summary = saved[data_name], saved[summary_name]
        table = data.tables["SampleItems"]
        assert (table.ref, table.autoFilter.ref) == ("A2:D5", "A2:D5")
        assert table.autoFilter.sortState is None
        assert table.tableColumns[3].calculatedColumnFormula is None
        assert data.auto_filter.ref is None
        assert data["D3"].value == f"=SUM($B3,'{summary_name}'!$D$2,SampleItems[Q1])"
        assert data["F2"].value == "=SUM(C5:C5)"
        assert summary["D2"].value == f"='{data_name}'!$B$3"
        assert summary["D3"].value == "=SUM(B$2:B3)"
        assert summary["D4"].value == f"='{data_name}'!$B$5"
        assert saved.defined_names["SampleCells"].attr_text == f"'{data_name}'!$B$3:$B$5"
        assert str(next(iter(data.merged_cells.ranges))) == "A7:A8"
        assert data["A7"].value == "Original block"
        assert data.row_dimensions[3].height == 24
        sections = qc.run_qc(out, plan, template_path=template)["sections"]
        assert sections["conformance"]["status"] == sections["protection"]["status"] == "pass"
        summary["D2"] = f"='{data_name}'!$B$2"
        table.autoFilter.ref = "A1:D3"
        saved.save(out)
    finally:
        saved.close()
    sections = qc.run_qc(out, plan, template_path=template)["sections"]
    assert sections["conformance"]["status"] == sections["protection"]["status"] == "fail"
    assert any(
        issue.get("sheet") == data_name and issue.get("table") == "SampleItems"
        for issue in sections["conformance"]["issues"]
    )


def test_native_qc_rejects_tampered_header_style(native_workbook):
    run, template, qc, _ = native_workbook
    out, plan = run([_sales_header_style_phase(), _sales_border_phase()])
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    wb = load_workbook(out)
    try:
        from copy import copy

        font = copy(wb["销售明细"]["A1"].font)
        font.bold = False
        wb["销售明细"]["A1"].font = font
        wb.save(out)
    finally:
        wb.close()
    report = qc.run_qc(out, plan, template_path=template)
    assert report["verdict"] == "FAIL"
    assert report["sections"]["conformance"]["status"] == "fail"


def test_writer_sets_column_width_without_changing_group_neighbors(native_workbook):
    run, template, qc, _ = native_workbook
    book = load_workbook(template)
    columns = book["销售明细"].column_dimensions
    columns["B"].width = 16
    columns.group("B", "D", outline_level=1, hidden=True)
    book.save(template)
    book.close()

    out, plan = run(
        [
            {
                "phase": "set_column_width",
                "sheet": "销售明细",
                "column": "C",
                "width": 20,
            }
        ]
    )
    book = load_workbook(out)
    columns = book["销售明细"].column_dimensions
    assert [
        (columns[col].width, columns[col].outlineLevel, columns[col].hidden) for col in "BCD"
    ] == [
        (16, 1, True),
        (20, 1, True),
        (16, 1, True),
    ]
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    columns["C"].width = 19
    book.save(out)
    book.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "FAIL"


@pytest.mark.parametrize("banded", [False, True])
def test_writer_creates_native_table_with_calculation_and_total(native_workbook, banded):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    run, template, qc, _ = native_workbook
    phase = _sales_table_phase()
    if banded:
        phase["banded_rows"] = True
    out, plan = run([phase], ["销售明细!E:E"])
    with ZipFile(out) as archive:
        root = ET.fromstring(archive.read("xl/tables/table1.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert root.attrib["displayName"] == "tblSales"
    assert root.attrib["ref"] == "A1:D4"
    assert root.attrib["totalsRowCount"] == "1"
    assert root.find("x:autoFilter", ns).attrib["ref"] == "A1:D3"
    style = root.find("x:tableStyleInfo", ns)
    if banded:
        assert style.attrib == {"name": "TableStyleMedium2", "showRowStripes": "1"}
    else:
        assert style is None
    amount = root.find("x:tableColumns/x:tableColumn[@name='金额']", ns)
    assert amount.attrib["totalsRowFunction"] == "sum"
    assert (
        amount.findtext("x:calculatedColumnFormula", namespaces=ns)
        == phase["calculated_formula"][1:]
    )
    wb = load_workbook(out)
    try:
        assert wb["销售明细"]["D4"].value == "=SUBTOTAL(109,tblSales[金额])"
    finally:
        wb.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    assert qc.run_qc(template, plan, template_path=template)["verdict"] == "FAIL"
    if banded:
        book = load_workbook(out)
        book["销售明细"].tables["tblSales"].tableStyleInfo.showRowStripes = False
        book.save(out)
        book.close()
        assert qc.run_qc(out, plan, template_path=template)["verdict"] == "FAIL"


def test_writer_rejects_table_overlap_with_protected_range(native_workbook):
    run, _, _, writer = native_workbook
    with pytest.raises(writer.PlanError, match="保护区"):
        run([_sales_table_phase()], ["销售明细!D4"])


@pytest.mark.parametrize("name", ["部品_台帳2", r"\Änderung.1"])
def test_native_table_name_round_trips_unicode(native_workbook, name):
    run, template, qc, _ = native_workbook
    out, plan = run([{**_sales_table_phase(), "name": name}])
    book = load_workbook(out)
    try:
        sheet = book["销售明细"]
        assert sheet.tables[name].displayName == name
        assert sheet["D4"].value == f"=SUBTOTAL(109,{name}[金额])"
    finally:
        book.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"


def test_unicode_table_name_remains_unique_across_workbook_names(native_workbook):
    from openpyxl.workbook.defined_name import DefinedName

    run, template, _, writer = native_workbook
    book = load_workbook(template)
    try:
        book.defined_names.add(DefinedName("Änderung_2", attr_text="'销售明细'!$A$1"))
        book.save(template)
    finally:
        book.close()
    with pytest.raises(writer.PlanError, match="表格名称已存在"):
        run([{**_sales_table_phase(), "name": "ÄNDERUNG_2"}])


@pytest.mark.parametrize("calculated", [False, True])
def test_native_table_without_total_preserves_the_next_row(native_workbook, calculated):
    run, template, qc, _ = native_workbook
    phase = _sales_table_phase()
    heading, formula = phase.pop("sum_column"), phase.pop("calculated_formula")
    if calculated:
        phase.update(calculated_column=heading, calculated_formula=formula)
    book = load_workbook(template)
    book[phase["sheet"]]["D4"] = "keep original footer"
    book.save(template)
    book.close()

    out, plan = run([phase], [f"{phase['sheet']}!D4"])
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    book = load_workbook(out)
    sheet = book[phase["sheet"]]
    table = sheet.tables[phase["name"]]
    assert table.ref == table.autoFilter.ref == "A1:D3"
    assert table.totalsRowCount in (None, 0) and table.totalsRowShown is False
    assert sheet["D4"].value == "keep original footer"
    assert sheet["D2"].value == (formula if calculated else "=ROUND(B2*C2,2)")
    assert all(column.totalsRowFunction is None for column in table.tableColumns)
    table.totalsRowShown = True
    book.save(out)
    book.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "FAIL"


@pytest.mark.parametrize("calculated", [False, True])
def test_native_table_can_sum_existing_data_without_assigning_its_calculation(
    native_workbook, calculated
):
    run, template, qc, _ = native_workbook
    phase = _sales_table_phase()
    phase.pop("calculated_formula")
    if calculated:
        phase.update(calculated_column="单价", calculated_formula="=5*2")
    out, plan = run([phase])
    book = load_workbook(out)
    sheet = book[phase["sheet"]]
    table = sheet.tables[phase["name"]]
    assert table.ref == "A1:D4" and table.autoFilter.ref == "A1:D3"
    assert table.tableColumns[3].calculatedColumnFormula is None
    assert table.tableColumns[3].totalsRowFunction == "sum"
    assert sheet["D2"].value == "=ROUND(B2*C2,2)"
    assert sheet["D4"].value == "=SUBTOTAL(109,tblSales[金额])"
    assert sheet["C2"].value == ("=5*2" if calculated else 20)
    book.close()
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"


@pytest.mark.parametrize("fields", [{"calculated_column": "金额"}, {"calculated_formula": "=1"}])
def test_native_table_schema_requires_complete_calculation_pairs(native_workbook, fields):
    from jsonschema import ValidationError

    phase = _sales_table_phase()
    phase.pop("sum_column")
    phase.pop("calculated_formula")
    phase.update(fields)
    run, _, _, _ = native_workbook
    with pytest.raises(ValidationError):
        run([phase])


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        *(
            ("name", name, "非法 Excel 表格名称")
            for name in ("a01", "XFD1048576", "R1C1", "RC", "r", "1合計", "税 目", r"Bad\Name")
        ),
        ("range", "A1:XFE2", "有限范围"),
    ],
)
def test_plain_table_keeps_native_name_and_range_guards(native_workbook, field, value, error):
    run, _, _, writer = native_workbook
    phase = _sales_table_phase()
    phase.pop("sum_column")
    phase.pop("calculated_formula")
    with pytest.raises(writer.PlanError, match=error):
        run([{**phase, field: value}])


@pytest.mark.parametrize("table_last", [True, False])
def test_native_qc_checks_last_formula_when_table_and_explicit_writes_overlap(
    native_workbook, table_last
):
    run, template, qc, _ = native_workbook
    table = _sales_table_phase()
    formula = "=B2*C2"
    write = {
        "phase": "formula_writes",
        "writes": [{"sheet": table["sheet"], "ref": "D2", "formula": formula}],
    }
    out, plan = run([write, table] if table_last else [table, write])
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    with out.open("rb") as handle:
        book = load_workbook(handle)
        sheet = book[table["sheet"]]
        assert sheet["D2"].value == (table["calculated_formula"] if table_last else formula)
        sheet["D2"] = formula if table_last else table["calculated_formula"]
    book.save(out)
    book.close()
    report = qc.run_qc(out, plan, template_path=template)
    assert report["verdict"] == "FAIL"
    assert [
        (issue["row"], issue["col"]) for issue in report["sections"]["conformance"]["issues"]
    ] == [(2, 4)]


def test_qc_checks_visible_styles_on_merged_and_unmerged_cells(native_workbook):
    run, template, qc, _ = native_workbook
    sheet = "产品汇总"
    out, plan = run(
        [
            {"phase": "merge_cells", "sheet": sheet, "range": "A5:C5"},
            {
                "phase": "cell_styles",
                "sheet": sheet,
                "range": "A5:D5",
                "bold": True,
                "horizontal": "center",
                "font_size": 16,
            },
        ]
    )
    section = qc.run_qc(out, plan, template_path=template)["sections"]["conformance"]
    assert section["status"] == "pass" and section["stats"]["style_cells_checked"] == 2
    book = load_workbook(out)
    book[sheet]["A5"].font = copy(book[sheet]["D6"].font)
    book[sheet]["D5"].alignment = copy(book[sheet]["D6"].alignment)
    book.save(out)
    book.close()
    failed = qc.run_qc(out, plan, template_path=template)["sections"]["conformance"]
    assert failed["status"] == "fail"
    assert {issue["col"] for issue in failed["issues"]} == {1, 4}


def test_native_qc_tracks_a_clear_and_prior_formula_through_row_insertion(native_workbook):
    run, template, qc, _ = native_workbook
    sheet = "销售明细"
    out, plan = run(
        [
            {"phase": "cell_writes", "writes": [{"sheet": sheet, "ref": "A2", "value": "临时值"}]},
            {"phase": "clear_ranges", "ranges": [f"{sheet}!A2"]},
            {
                "phase": "formula_writes",
                "writes": [{"sheet": sheet, "ref": "D2", "formula": "=B2*C2"}],
            },
            {"phase": "insert_rows", "sheet": sheet, "row": 2, "count": 1},
        ]
    )
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    book = load_workbook(out)
    assert book[sheet]["A3"].value is None
    assert book[sheet]["D3"].value == "=B3*C3"
    book[sheet]["A3"] = "非法残值"
    book.save(out)
    book.close()
    assert (
        qc.run_qc(out, plan, template_path=template)["sections"]["conformance"]["status"] == "fail"
    )


@pytest.mark.parametrize("range_last", [True, False])
def test_native_qc_checks_last_range_or_formula_number_format(native_workbook, range_last):
    run, template, qc, _ = native_workbook
    sheet = "销售明细"
    write = {
        "phase": "formula_writes",
        "writes": [{"sheet": sheet, "ref": "D2", "formula": "=B2*C2", "number_format": "0.000"}],
    }
    style = {"phase": "cell_styles", "sheet": sheet, "range": "D2:D3", "number_format": "#,##0.00"}
    out, plan = run([write, style] if range_last else [style, write])
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    book = load_workbook(out)
    cell = book[sheet]["D2"]
    assert cell.number_format == ("#,##0.00" if range_last else "0.000")
    cell.number_format = "0.000" if range_last else "#,##0.00"
    book.save(out)
    book.close()
    report = qc.run_qc(out, plan, template_path=template)
    assert report["verdict"] != "PASS"
    assert [
        (issue["row"], issue["col"]) for issue in report["sections"]["conformance"]["issues"]
    ] == [(2, 4)]


def test_writer_creates_native_dual_axis_chart(native_workbook):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    run, template, qc, _ = native_workbook
    out, plan = run([_sales_chart_phase()])
    with ZipFile(out) as archive:
        root = ET.fromstring(archive.read("xl/charts/chart1.xml"))
    ns = {
        "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    bar = root.find(".//c:barChart", ns)
    line = root.find(".//c:lineChart", ns)
    assert bar.find("c:barDir", ns).attrib["val"] == "col"
    assert bar.findtext("c:ser/c:cat/c:strRef/c:f", namespaces=ns) == "'产品汇总'!$A$2:$A$3"
    assert bar.findtext("c:ser/c:val/c:numRef/c:f", namespaces=ns) == "'产品汇总'!$B$2:$B$3"
    assert line.findtext("c:ser/c:val/c:numRef/c:f", namespaces=ns) == "'产品汇总'!$C$2:$C$3"
    axis_id = line.findall("c:axId", ns)[1].attrib["val"]
    assert axis_id != bar.findall("c:axId", ns)[1].attrib["val"]
    axis = root.find(f".//c:valAx/c:axId[@val='{axis_id}']/..", ns)
    assert axis.find("c:axPos", ns).attrib["val"] == "r"
    assert axis.find("c:numFmt", ns).attrib["formatCode"] == "0.00%"
    assert line.find("c:dLbls/c:showVal", ns).attrib["val"] == "1"
    assert root.find(".//c:legendPos", ns).attrib["val"] == "b"
    assert root.findtext(".//c:title//a:t", namespaces=ns) == "各产品销售额与累计占比"
    assert qc.run_qc(out, plan, template_path=template)["verdict"] == "PASS"
    assert qc.run_qc(template, plan, template_path=template)["verdict"] == "FAIL"


def test_native_qc_rejects_tampered_table_and_chart(native_workbook):
    run, template, qc, _ = native_workbook
    out, plan = run([_sales_table_phase(), _sales_chart_phase()], ["销售明细!E:E"])
    report = qc.run_qc(out, plan, template_path=template)
    assert report["verdict"] == "PASS"
    assert report["sections"]["conformance"]["stats"]["native_phases_checked"] == 2
    wb = load_workbook(out)
    try:
        wb["销售明细"].tables["tblSales"].tableColumns[3].calculatedColumnFormula = None
        wb["销售图表"]._charts[0]._charts[1].y_axis.axPos = "l"
        wb.save(out)
    finally:
        wb.close()
    for phase in plan["phases"]:
        readback = qc.run_qc(out, {**plan, "phases": [phase]}, template_path=template)
        assert readback["sections"]["conformance"]["status"] == "fail"


def test_native_table_formula_remains_subject_to_formula_qc(native_workbook):
    run, template, qc, _ = native_workbook
    out, plan = run([{**_sales_table_phase(), "calculated_formula": "=#REF!"}])
    assert qc.run_qc(out, plan, template_path=template)["sections"]["formulas"]["status"] == "fail"


def test_writer_rejects_misaligned_combo_sources(native_workbook):
    run, _, _, writer = native_workbook
    with pytest.raises(writer.PlanError, match="同行对齐"):
        run([{**_sales_chart_phase(), "line_values": "C3:C4"}])


@pytest.mark.parametrize("change", ["conditional", "validation", "defined_name", "print"])
def test_workbook_controls_survive_save_and_qc_rejects_tampering(native_workbook, change):
    run, template, qc, _ = native_workbook
    sheet = "销售明细"
    out, plan = run(
        [
            {
                "phase": "conditional_format",
                "sheet": sheet,
                "range": "D2:D3",
                "rule": "top_percent",
                "percent": 10,
                "color": "C6EFCE",
            },
            {
                "phase": "conditional_format",
                "sheet": sheet,
                "range": "D2:D3",
                "rule": "less_than",
                "threshold": 1000,
                "color": "9C0006",
            },
            {
                "phase": "conditional_format",
                "sheet": sheet,
                "range": "A2:D3",
                "rule": "duplicate_rows",
                "key_column": "A",
                "color": "FFC7CE",
            },
            {
                "phase": "data_validation",
                "sheet": sheet,
                "range": "A2:A3",
                "rule": "list",
                "source_sheet": "产品汇总",
                "source_range": "A2:A3",
                "name": "ProductNames",
                "error": "请选择有效产品",
            },
            {
                "phase": "data_validation",
                "sheet": sheet,
                "range": "B2:B3",
                "rule": "whole",
                "minimum": 1,
                "maximum": 999,
                "error": "数量必须为 1-999 的整数",
            },
            {
                "phase": "print_layout",
                "sheet": sheet,
                "range": "A1:H40",
                "orientation": "landscape",
                "paper": "A4",
                "margins": "narrow",
                "title_first_row": 1,
                "title_last_row": 2,
                "fit_width": 1,
                "footer": "第 &P 页，共 &N 页",
            },
        ]
    )
    report = qc.run_qc(out, plan, template_path=template)
    assert report["verdict"] == "PASS", report["sections"]
    assert report["sections"]["conformance"]["stats"]["native_phases_checked"] == 6

    wb = load_workbook(out)
    ws = wb[sheet]
    if change == "conditional":
        ws.conditional_formatting["D2:D3"][0].rank = 20
    elif change == "validation":
        ws.data_validations.dataValidation[-1].showErrorMessage = False
    elif change == "defined_name":
        wb.defined_names["ProductNames"].attr_text = "'产品汇总'!$A$2:$A$2"
    else:
        ws.page_setup.fitToWidth = 2
    wb.save(out)
    wb.close()
    assert (
        qc.run_qc(out, plan, template_path=template)["sections"]["conformance"]["status"] == "fail"
    )
