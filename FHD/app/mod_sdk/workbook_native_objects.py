"""Native Excel tables and charts with the existing declared range guards.

The writer's file-path entrypoint and package entrypoint share these operations;
neither requires a second loader or imports back into the employee converter.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Protocol, Tuple

from app.mod_sdk.workbook_controls import WORKBOOK_BANDED_TABLE_STYLE

XLSX_MAX_ROW = 1_048_576
XLSX_MAX_COL = 16_384


class _ProtectedZones(Protocol):
    zones: Dict[str, List[Tuple[int, int, int, int]]]


class PlanError(ValueError):
    """plan.json 结构或与模板不匹配的错误（fail-fast）。"""


def _bounded_range(token: str) -> Tuple[int, int, int, int]:
    from openpyxl.utils.cell import range_boundaries

    try:
        left, top, right, bottom = range_boundaries(token.upper())
    except ValueError as exc:
        raise PlanError(f"非法范围：{token!r}") from exc
    if (
        left is None
        or top is None
        or right is None
        or bottom is None
        or not (1 <= left <= right <= XLSX_MAX_COL and 1 <= top <= bottom <= XLSX_MAX_ROW)
    ):
        raise PlanError(f"需要工作表内的有限范围：{token!r}")
    return top, left, bottom, right


def _overlaps(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _native_sheet(wb, name: str):
    if name not in wb.sheetnames or wb[name] not in wb.worksheets:
        raise PlanError(f"工作表不存在：{name!r}")
    return wb[name]


def _run_create_table(wb, phase: Dict[str, Any], protected: _ProtectedZones, stats) -> None:
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    from openpyxl.utils.cell import column_index_from_string, get_column_letter
    from openpyxl.worksheet.filters import AutoFilter
    from openpyxl.worksheet.table import Table, TableColumn, TableFormula, TableStyleInfo

    sheet, name = phase["sheet"], phase["name"]
    ws = _native_sheet(wb, sheet)
    top, left, bottom, right = _bounded_range(phase["range"])
    sum_heading = phase.get("sum_column")
    formula = phase.get("calculated_formula")
    calc_heading = phase.get("calculated_column", sum_heading if formula is not None else None)
    table_bottom = bottom + int(sum_heading is not None)
    if (
        top == bottom
        or table_bottom > XLSX_MAX_ROW
        or ((table_bottom - top + 1) * (right - left + 1) > 100_000)
    ):
        raise PlanError("表格需要标题和数据行，范围最多 100000 格且不能越界。")
    if sum_heading is not None and left == right:
        raise PlanError("合计行需要分别容纳标签和合计值的两列。")
    target = (top, left, table_bottom, right)
    if any(_overlaps(target, zone) for zone in protected.zones.get(sheet, ())):
        raise PlanError("表格范围与保护区重叠。")
    if any(_overlaps(target, _bounded_range(str(rng))) for rng in ws.merged_cells.ranges):
        raise PlanError("表格范围与合并单元格重叠。")
    if any(_overlaps(target, _bounded_range(table.ref)) for table in ws.tables.values()):
        raise PlanError("表格范围与现有表格重叠。")

    # Excel identifiers allow Unicode letters. Only cell-reference notation is ASCII.
    if not isinstance(name, str) or not (
        1 <= len(name) <= 255
        and (name[0].isalpha() or name[0] in "_\\")
        and all(char.isalnum() or char in "_." for char in name[1:])
    ):
        raise PlanError(f"非法 Excel 表格名称：{name!r}")
    cell_ref = re.fullmatch(r"([A-Z]{1,3})([0-9]+)", name, re.ASCII | re.IGNORECASE)
    if re.fullmatch(r"[RC]|R[0-9]*C[0-9]*", name, re.ASCII | re.IGNORECASE) or (
        cell_ref
        and column_index_from_string(cell_ref[1]) <= XLSX_MAX_COL
        and 1 <= int(cell_ref[2]) <= XLSX_MAX_ROW
    ):
        raise PlanError(f"非法 Excel 表格名称：{name!r}")
    existing_names = list(wb.defined_names)
    for worksheet in wb.worksheets:
        existing_names.extend(worksheet.tables)
        existing_names.extend(worksheet.defined_names)
    if name.casefold() in {item.casefold() for item in existing_names}:
        raise PlanError(f"Excel 表格名称已存在：{name!r}")

    headers = [ws.cell(top, col) for col in range(left, right + 1)]
    if any(
        cell.data_type != "s"
        or not isinstance(cell.value, str)
        or not cell.value.strip()
        or len(cell.value) > 255
        for cell in headers
    ):
        raise PlanError("表格标题必须是非空文本，最长 255 个字符。")
    headings = [cell.value for cell in headers]
    if len({value.casefold() for value in headings}) != len(headings):
        raise PlanError("表格标题不能重复。")
    if sum_heading is not None and (
        sum_heading not in headings or re.search(r"[\[\]#'@\r\n]", sum_heading)
    ):
        raise PlanError("合计列必须是存在的表格标题，且不含结构化引用转义字符。")
    if formula is not None or calc_heading is not None:
        if (
            calc_heading not in headings
            or not isinstance(formula, str)
            or (not formula.startswith("=") or not formula[1:].strip())
        ):
            raise PlanError("计算列需要存在的标题和以 = 开头的非空公式。")
        try:
            Tokenizer(formula)
        except TokenizerError as exc:
            raise PlanError("计算列公式无法解析。") from exc
    if sum_heading is not None and any(
        ws.cell(table_bottom, col).value is not None for col in range(left, right + 1)
    ):
        raise PlanError("表格下方的合计行必须为空。")

    start = f"{get_column_letter(left)}{top}"
    end = get_column_letter(right)
    table = Table(
        displayName=name,
        ref=f"{start}:{end}{table_bottom}",
        totalsRowCount=1 if sum_heading is not None else None,
        totalsRowShown=sum_heading is not None,
        autoFilter=AutoFilter(ref=f"{start}:{end}{bottom}"),
    )
    if phase.get("banded_rows") is True:
        table.tableStyleInfo = TableStyleInfo(name=WORKBOOK_BANDED_TABLE_STYLE, showRowStripes=True)
    summed = headings.index(sum_heading) if sum_heading is not None else None
    calculated = headings.index(calc_heading) if calc_heading is not None else None
    label = 1 if summed == 0 else 0
    for idx, value in enumerate(headings):
        column = TableColumn(id=idx + 1, name=value)
        if idx == calculated:
            assert isinstance(formula, str)  # The calculation-pair validation above is binding.
            column.calculatedColumnFormula = TableFormula(attr_text=formula[1:])
        if idx == summed:
            column.totalsRowFunction = "sum"
        elif summed is not None and idx == label:
            column.totalsRowLabel = "合计"
        table.tableColumns.append(column)
    ws.add_table(table)
    if calculated is not None:
        for row in range(top + 1, bottom + 1):
            ws.cell(row, left + calculated).value = formula
        stats["formulas_written"] += bottom - top
    if summed is not None:
        total = ws.cell(table_bottom, left + summed)
        total.value = f"=SUBTOTAL(109,{name}[{sum_heading}])"
        if total.number_format == "General":
            total.number_format = ws.cell(bottom, left + summed).number_format
        ws.cell(table_bottom, left + label).value = "合计"
        stats["formulas_written"] += 1


def _run_create_combo_chart(wb, phase: Dict[str, Any]) -> None:
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.chart.data_source import AxDataSource, StrRef
    from openpyxl.chart.label import DataLabelList
    from openpyxl.chart.series import SeriesLabel

    source = _native_sheet(wb, phase["source_sheet"])
    name = phase["sheet"]
    if (
        not name.strip()
        or len(name) > 31
        or re.search(r"[\\/*?:\[\]]", name)
        or name.startswith("'")
        or name.endswith("'")
        or name.casefold() in {item.casefold() for item in wb.sheetnames}
    ):
        raise PlanError(f"图表需要合法且未占用的新工作表名称：{name!r}")
    ranges = [_bounded_range(phase[key]) for key in ("categories", "bar_values", "line_values")]
    first, _, last, _ = ranges[0]
    if (
        last - first >= 10_000
        or any(
            (top, bottom) != (first, last) or left != right for top, left, bottom, right in ranges
        )
        or len({bounds[1] for bounds in ranges}) != 3
    ):
        raise PlanError("图表源需要三个同行对齐的独立单列范围（每列最多 10000 格）。")
    for idx, (_, col, _, _) in enumerate(ranges):
        for row in range(first, last + 1):
            cell = source.cell(row, col)
            if cell.value is None or cell.data_type not in (
                {"s", "n", "f"} if idx == 0 else {"n", "f"}
            ):
                raise PlanError(f"图表源包含空单元格或不兼容值：{cell.coordinate}")
    categories, bars, lines = [
        Reference(source, min_row=top, min_col=left, max_row=bottom, max_col=right)
        for top, left, bottom, right in ranges
    ]
    bar, line = BarChart(), LineChart()
    bar.type = "col"
    bar.title = phase["title"]
    bar.y_axis.title = phase["bar_title"]
    bar.y_axis.axPos = "l"
    bar.y_axis.crosses = "autoZero"
    bar.x_axis.axPos = "b"
    bar.legend.position = "b"
    line.y_axis.title = phase["line_title"]
    line.y_axis.axId = 200
    line.y_axis.crosses = "max"
    line.y_axis.axPos = "r"
    line.y_axis.numFmt = "0.00%"
    line.y_axis.majorGridlines = None
    line.x_axis = bar.x_axis
    line.y_axis.crossAx = bar.x_axis.axId
    line.dLbls = DataLabelList(showVal=True, numFmt="0.00%", dLblPos="t")
    for chart, data, label in ((bar, bars, phase["bar_title"]), (line, lines, phase["line_title"])):
        chart.add_data(data)
        chart.series[0].cat = AxDataSource(strRef=StrRef(f=str(categories)))
        chart.series[0].title = SeriesLabel(v=label)
    bar += line
    wb.create_sheet(name).add_chart(bar, "A1")
