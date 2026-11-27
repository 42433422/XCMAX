"""Preflight native worksheet table ranges before moving their cells."""

from __future__ import annotations

from openpyxl.utils.cell import get_column_letter, range_boundaries

from .workbook_reference_relocation import shift_formula_rows


class TableRangeError(ValueError):
    """An insertion cannot preserve a native table's meaning."""


def _bounds(ref):
    try:
        left, top, right, bottom = range_boundaries(ref)
        valid = 1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise TableRangeError(f"表格范围非法或越界：{ref!r}")
    return left, top, right, bottom


def _ref(left, top, right, bottom):
    return f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"


def shifted_table_ranges(wb, insert_row, count, target_sheet):
    """Return updates without mutation; unsupported metadata fails before insertion."""
    updates = []
    for source in wb.worksheets:
        for table in source.tables.values():
            for column in table.tableColumns:
                for definition in (column.calculatedColumnFormula, column.totalsRowFormula):
                    if definition is None:
                        continue
                    formula = "=" + str(definition.attr_text).lstrip("=")
                    shifted = shift_formula_rows(
                        formula,
                        insert_row,
                        count,
                        formula_sheet=source.title,
                        target_sheet=target_sheet,
                    )
                    if shifted != formula:
                        raise TableRangeError(
                            f"表格 {source.title}!{table.displayName} 的元数据公式受插行影响，无法安全迁移。"
                        )
    worksheet_filter = wb[target_sheet].auto_filter
    for ref in (
        worksheet_filter.ref,
        worksheet_filter.sortState.ref if worksheet_filter.sortState is not None else None,
    ):
        if ref and insert_row <= _bounds(ref)[3]:
            raise TableRangeError(
                f"表格插行会影响 {target_sheet} 的工作表级筛选/排序，无法安全迁移。"
            )
    for table in wb[target_sheet].tables.values():
        left, top, right, bottom = _bounds(table.ref)
        if insert_row > bottom:
            continue
        label = f"表格 {target_sheet}!{table.displayName}"
        header, totals = table.headerRowCount, table.totalsRowCount or 0
        if header not in (0, 1) or totals not in (0, 1) or bottom - top + 1 < header + totals:
            raise TableRangeError(f"{label} 的表头/汇总行元数据不受支持。")
        if len(table.tableColumns) != right - left + 1:
            raise TableRangeError(f"{label} 的列定义与范围不一致。")
        if (
            table.tableType not in (None, "worksheet")
            or table.connectionId is not None
            or table.sortState is not None
            or any(
                col.calculatedColumnFormula is not None
                or col.totalsRowFormula is not None
                or col.queryTableFieldId is not None
                or col.xmlColumnPr is not None
                for col in table.tableColumns
            )
        ):
            raise TableRangeError(f"{label} 含计算列、外部连接、自定义汇总或排序，无法安全插行。")
        auto_filter = table.autoFilter
        if auto_filter is not None and (
            auto_filter.sortState is not None
            or _bounds(auto_filter.ref) != (left, top, right, bottom - totals)
        ):
            raise TableRangeError(f"{label} 的筛选范围或排序无法安全迁移。")
        if bottom + count > 1048576:
            raise TableRangeError(f"{label} 插行后超出工作表行数上限。")
        new_top, new_bottom = top + (count if insert_row <= top else 0), bottom + count
        new_ref = _ref(left, new_top, right, new_bottom)
        # Inserting immediately above totals creates data rows, so the filter must
        # grow even though its old endpoint precedes the insertion boundary.
        new_filter = (
            _ref(left, new_top, right, new_bottom - totals) if auto_filter is not None else None
        )
        updates.append((table, new_ref, new_filter))
    return updates


def apply_table_ranges(updates):
    for table, ref, filter_ref in updates:
        table.ref = ref
        if table.autoFilter is not None:
            table.autoFilter.ref = filter_ref
