"""Independently verify native tables after planned worksheet row insertions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from app.mod_sdk.workbook_controls import WORKBOOK_BANDED_TABLE_STYLE

if TYPE_CHECKING:
    from .checks import _CellExpectations, _CellTarget, _Finding


from copy import deepcopy

from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.xml.functions import tostring

from .plan_coordinates import insertions, plan_phases, shift_formula_rows


def _rectangle(text):
    bounds = range_boundaries(text)
    left, first, right, last = bounds
    if not (1 <= left <= right <= 16384 and 1 <= first <= last <= 1048576):
        raise ValueError("非法表格范围")
    return bounds


def _expected_table(source, sheet, changes):
    expected = deepcopy(source)
    for column in source.tableColumns:
        for definition in (column.calculatedColumnFormula, column.totalsRowFormula):
            if definition is not None:
                formula = "=" + str(definition.attr_text).lstrip("=")
                if shift_formula_rows(formula, sheet, changes) != formula:
                    raise ValueError("表格元数据公式含受插行影响的引用")
    for changed_sheet, row, count in changes:
        if sheet.casefold() != changed_sheet.casefold():
            continue
        left, first, right, last = _rectangle(expected.ref)
        if row > last:
            continue
        header_count, total_count = expected.headerRowCount, expected.totalsRowCount or 0
        columns = expected.tableColumns
        if (
            header_count not in (0, 1)
            or total_count not in (0, 1)
            or last - first + 1 < header_count + total_count
            or len(columns) != right - left + 1
            or expected.tableType not in (None, "worksheet")
            or expected.connectionId is not None
            or expected.sortState is not None
            or any(
                c.calculatedColumnFormula is not None
                or c.totalsRowFormula is not None
                or c.queryTableFieldId is not None
                or c.xmlColumnPr is not None
                for c in columns
            )
        ):
            raise ValueError("计算列、连接、排序或表头/汇总定义无法独立核验")
        filtering = expected.autoFilter
        if filtering is not None and (
            filtering.sortState is not None
            or _rectangle(filtering.ref) != (left, first, right, last - total_count)
        ):
            raise ValueError("筛选范围或排序无法独立核验")
        first += count if row <= first else 0
        last += count
        if last > 1048576:
            raise ValueError("表格超出工作表行数上限")
        start = f"{get_column_letter(left)}{first}"
        expected.ref = f"{start}:{get_column_letter(right)}{last}"
        if filtering is not None:
            filtering.ref = f"{start}:{get_column_letter(right)}{last - total_count}"
    return expected


def _semantic_xml(table):
    root = table.to_tree()
    # openpyxl renumbers package table IDs when a sheet is removed or a new table
    # is saved. Display names, column IDs and every other semantic field remain.
    root.attrib.pop("id", None)
    return tostring(root)


def check_inserted_tables(wb, template_wb, plan, finding):
    changes = tuple(insertions(plan))
    for ws in template_wb.worksheets:
        if ws.title not in wb.sheetnames:
            continue
        filtering = ws.auto_filter
        try:
            refs = [filtering.ref]
            if filtering.sortState is not None:
                refs.append(filtering.sortState.ref)
            if any(
                sheet.casefold() == ws.title.casefold() and row <= _rectangle(ref)[3]
                for ref in refs
                if ref
                for sheet, row, _ in changes
            ):
                finding.fail("无法独立核验受插行影响的工作表级表格筛选/排序", sheet=ws.title)
            if tostring(filtering.to_tree()) != tostring(wb[ws.title].auto_filter.to_tree()):
                finding.fail("插行后工作表级表格筛选/排序元数据发生变化", sheet=ws.title)
        except (TypeError, ValueError) as exc:
            finding.fail("无法独立核验工作表级表格筛选范围", sheet=ws.title, error=str(exc))
    originals = {
        (ws.title, table.displayName): table
        for ws in template_wb.worksheets
        if ws.title in wb.sheetnames
        for table in ws.tables.values()
    }
    actual = {
        (ws.title, table.displayName): table for ws in wb.worksheets for table in ws.tables.values()
    }
    declared = {
        (str(phase.get("sheet") or "").strip().strip("'"), str(phase.get("name") or "").strip())
        for phase in plan_phases(plan)
        if phase.get("phase") == "create_table"
    }
    for sheet, name in sorted(originals.keys() - actual.keys()):
        finding.fail("插行后既有表格缺失或改名", sheet=sheet, table=name)
    for sheet, name in sorted(actual.keys() - originals.keys() - declared):
        finding.fail("插行后出现未声明的表格", sheet=sheet, table=name)
    for key in originals.keys() & actual.keys():
        sheet, name = key
        try:
            expected = _expected_table(originals[key], sheet, changes)
            if _semantic_xml(actual[key]) != _semantic_xml(expected):
                finding.fail(
                    "插行后表格范围、筛选或语义元数据不符合模板与计划",
                    sheet=sheet,
                    table=name,
                    expected=expected.ref,
                    actual=actual[key].ref,
                )
        except (TypeError, ValueError) as exc:
            finding.fail("无法独立核验插行后的表格", sheet=sheet, table=name, error=str(exc))


def _check_native_table(
    ws,
    phase: Dict[str, Any],
    f: _Finding,
    cells: _CellExpectations,
    formats: dict[_CellTarget, str],
) -> None:
    from openpyxl.utils.cell import get_column_letter, range_boundaries

    left, top, right, bottom = range_boundaries(phase["range"].upper())
    columns = [ws.cell(top, col).value for col in range(left, right + 1)]
    sum_heading = phase.get("sum_column")
    formula = phase.get("calculated_formula")
    calc_heading = phase.get("calculated_column", sum_heading if formula is not None else None)
    has_total = sum_heading is not None
    table = ws.tables.get(phase["name"])
    if (
        table is None
        or (has_total and (sum_heading not in columns or left == right))
        or (formula is not None and (calc_heading not in columns or not isinstance(formula, str)))
        or (calc_heading is not None and formula is None)
    ):
        f.fail("输出缺少计划的原生 Excel 表格或指定列", sheet=ws.title)
        return
    start, end = f"{get_column_letter(left)}{top}", get_column_letter(right)
    if (
        table.ref != f"{start}:{end}{bottom + int(has_total)}"
        or (table.totalsRowCount or 0) != int(has_total)
        or (table.totalsRowShown is False if has_total else table.totalsRowShown is True)
        or table.autoFilter is None
        or table.autoFilter.ref != f"{start}:{end}{bottom}"
        or [column.name for column in table.tableColumns] != columns
    ):
        f.fail("原生表格范围、合计行、筛选范围或列标题与计划不符", sheet=ws.title)
        return
    if "banded_rows" in phase:
        style = table.tableStyleInfo
        striped = style is not None and style.showRowStripes is True
        if striped != phase["banded_rows"] or (
            striped and style.name != WORKBOOK_BANDED_TABLE_STYLE
        ):
            f.fail("原生表格隔行底纹与计划不符", sheet=ws.title)
    summed = columns.index(sum_heading) if has_total else None
    calculated = columns.index(calc_heading) if calc_heading is not None else None
    label = 1 if summed == 0 else 0
    for idx, column in enumerate(table.tableColumns):
        actual_formula = getattr(column.calculatedColumnFormula, "attr_text", None)
        if (
            actual_formula != (formula[1:] if idx == calculated else None)
            or column.totalsRowFunction != ("sum" if idx == summed else None)
            or column.totalsRowLabel != ("合计" if has_total and idx == label else None)
            or column.totalsRowFormula is not None
        ):
            f.fail("原生表格计算列或合计行元数据与计划不符", sheet=ws.title)
    if calculated is not None:
        for row in range(top + 1, bottom + 1):
            cells[(ws.title, row, left + calculated)] = ("table_formula", formula)
    if summed is None:
        return
    cells[(ws.title, bottom + 1, left + label)] = ("cell_writes", "合计")
    total = (ws.title, bottom + 1, left + summed)
    cells[total] = ("table_formula", f"=SUBTOTAL(109,{phase['name']}[{sum_heading}])")
    if formats.get(total) == "General":
        # The writer gives a general-format total the last data row's format.
        inherited = formats.get((ws.title, bottom, left + summed))
        if inherited is None:
            formats.pop(total)
        else:
            formats[total] = inherited
