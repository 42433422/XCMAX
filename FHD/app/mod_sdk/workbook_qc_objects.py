"""Independent plan readback for native Excel tables and charts.

These checks read the output workbook and never import a writer implementation.
"""

from __future__ import annotations

from typing import Any, Dict


def check_native_table(ws, phase: Dict[str, Any], f: Any, targets: set) -> None:
    from openpyxl.utils.cell import get_column_letter, range_boundaries

    left, top, right, bottom = range_boundaries(phase["range"].upper())
    columns = [ws.cell(top, col).value for col in range(left, right + 1)]
    heading, formula = phase["sum_column"], phase["calculated_formula"]
    table = ws.tables.get(phase["name"])
    if table is None or heading not in columns:
        f.fail("输出缺少计划的原生 Excel 表格或合计列", sheet=ws.title)
        return
    start, end = f"{get_column_letter(left)}{top}", get_column_letter(right)
    if (
        table.ref != f"{start}:{end}{bottom + 1}"
        or table.totalsRowCount != 1
        or table.totalsRowShown is False
        or table.autoFilter is None
        or table.autoFilter.ref != f"{start}:{end}{bottom}"
        or [column.name for column in table.tableColumns] != columns
    ):
        f.fail("原生表格范围、合计行、筛选范围或列标题与计划不符", sheet=ws.title)
        return
    idx = columns.index(heading)
    amount, label = table.tableColumns[idx], 0 if idx else 1
    if (
        amount.calculatedColumnFormula is None
        or amount.calculatedColumnFormula.attr_text != formula[1:]
        or amount.totalsRowFunction != "sum"
        or table.tableColumns[label].totalsRowLabel != "合计"
        or ws.cell(bottom + 1, left + label).value != "合计"
    ):
        f.fail("原生表格计算列或合计行元数据与计划不符", sheet=ws.title)
    targets.add((ws.title, bottom + 1, left + label))
    for row in range(top + 1, bottom + 2):
        targets.add((ws.title, row, left + idx))
        cell = ws.cell(row, left + idx)
        expected = formula if row <= bottom else f"=SUBTOTAL(109,{table.displayName}[{heading}])"
        if cell.data_type != "f" or cell.value != expected:
            f.fail("表格计算列或合计公式与计划不符", sheet=ws.title, ref=cell.coordinate)


def _chart_title_text(title) -> str:
    rich = title.tx.rich if title and title.tx else None
    return "" if rich is None else "".join(run.t for para in rich.p for run in para.r)


def check_native_chart(wb, ws, phase: Dict[str, Any], f: Any) -> None:
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.utils.cell import range_boundaries

    source = phase["source_sheet"]
    if source not in wb.sheetnames or wb[source] not in wb.worksheets:
        f.fail("图表源工作表不存在", sheet=source)
        return

    def expected_ref(key):
        left, top, right, bottom = range_boundaries(phase[key].upper())
        if any(wb[source].cell(row, left).value is None for row in range(top, bottom + 1)):
            raise ValueError("图表源存在空值")
        return str(Reference(wb[source], min_col=left, min_row=top, max_col=right, max_row=bottom))

    categories, bar_values, line_values = map(
        expected_ref, ("categories", "bar_values", "line_values")
    )
    for chart in ws._charts:
        parts = chart._charts
        if (
            len(parts) != 2
            or not isinstance(parts[0], BarChart)
            or not isinstance(parts[1], LineChart)
            or any(len(part.series) != 1 for part in parts)
        ):
            continue
        bar, line = parts
        if (
            bar.type != "col"
            or chart.legend is None
            or chart.legend.position != "b"
            or _chart_title_text(chart.title) != phase["title"]
            or bar.y_axis.axId == line.y_axis.axId
            or bar.y_axis.axPos != "l"
            or line.y_axis.axPos != "r"
            or line.y_axis.crosses != "max"
            or line.y_axis.crossAx != bar.x_axis.axId
            or line.y_axis.numFmt.formatCode != "0.00%"
            or line.dLbls is None
            or not line.dLbls.showVal
            or line.dLbls.numFmt != "0.00%"
        ):
            continue
        for part, values, title in (
            (bar, bar_values, phase["bar_title"]),
            (line, line_values, phase["line_title"]),
        ):
            series = part.series[0]
            if (
                series.cat is None
                or series.cat.strRef is None
                or series.cat.strRef.f != categories
                or series.val is None
                or series.val.numRef is None
                or series.val.numRef.f != values
                or series.title is None
                or series.title.v != title
                or _chart_title_text(part.y_axis.title) != title
            ):
                break
        else:
            return
    f.fail("输出缺少符合计划的原生双轴柱线组合图", sheet=ws.title)
