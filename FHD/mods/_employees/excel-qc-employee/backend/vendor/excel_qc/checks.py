"""独立读取 Excel 产物并核对计划、保护区、规则和原模板。

质检不依赖写入员或映射员实现，缺少输入的检查应说明原因。
报告章节和问责路由见员工包 README。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from itertools import chain
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl.cell.cell import MergedCell, get_time_format
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils.cell import column_index_from_string, range_boundaries

from app.mod_sdk.workbook_controls import (
    WORKBOOK_BANDED_TABLE_STYLE,
    WORKBOOK_STRUCTURAL_PHASES,
)
from app.mod_sdk.workbook_row_references import shift_formula_rows, shift_row_reference

_MAX_SAMPLES = 8
_NUM_TOL = 1e-6

_REF_ERR_RE = re.compile(r"#REF!")
_SHEET_REF_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9\u4e00-\u9fff_]+))!")
_RANGE_RE = re.compile(r"^(?:'?([^'!]+)'?!)?([A-Z]{1,3})?(\d+)?(?::([A-Z]{1,3})?(\d+)?)?$")
_CellTarget = tuple[str, int, int]
_CellExpectations = dict[_CellTarget, tuple[str, Any]]
_ClearedArea = tuple[str, int, int, int, int]
_FORMULA_EXPECTATIONS = {"formula_writes", "table_formula"}


def _ref_to_tuple(ref: str) -> Tuple[int, int]:
    m = re.match(r"^([A-Z]{1,3})(\d+)$", ref.strip().upper())
    if not m:
        raise ValueError(f"非法单元格引用：{ref!r}")
    return int(m.group(2)), column_index_from_string(m.group(1))


def canonical_rules_sha256(rules: Dict[str, Any]) -> str:
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _Finding:
    """一节检查的累积器。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "pass"
        self.issues: List[Dict[str, Any]] = []
        self.stats: Dict[str, Any] = {}
        self.skipped_reason = ""

    def fail(self, detail: str, **extra: Any) -> None:
        self.status = "fail"
        if len(self.issues) < _MAX_SAMPLES * 4:
            self.issues.append({"severity": "fail", "detail": detail, **extra})

    def warn(self, detail: str, **extra: Any) -> None:
        if self.status == "pass":
            self.status = "warn"
        if len(self.issues) < _MAX_SAMPLES * 4:
            self.issues.append({"severity": "warn", "detail": detail, **extra})

    def skip(self, reason: str) -> None:
        self.status = "skipped"
        self.skipped_reason = reason

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "issues": self.issues, "stats": self.stats}
        if self.skipped_reason:
            out["skipped_reason"] = self.skipped_reason
        return out


def _plan_phases(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = plan.get("phases")
    if isinstance(phases, list):
        return [p for p in phases if isinstance(p, dict)]
    if isinstance(plan.get("writes"), list):
        return [{"phase": "cell_writes", "writes": plan["writes"]}]
    return []


def _iter_writes(plan: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ph in _plan_phases(plan):
        if str(ph.get("phase")) == kind:
            out.extend(w for w in (ph.get("writes") or []) if isinstance(w, dict))
    return out


def _target(write: Dict[str, Any]) -> Tuple[str, int, int]:
    sheet = str(write.get("sheet") or "").strip().strip("'")
    ref = str(write.get("ref") or "").strip()
    if ref:
        row, col = _ref_to_tuple(ref)
    else:
        row, col = int(write.get("row")), int(write.get("col"))
    return sheet, row, col


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M",
)


def _coerce_planned(value: Any, value_type: str) -> Any:
    """还原写入员的 value_type 语义（独立实现，不 import 写入员）。"""
    vtype = (value_type or "").strip().lower()
    if not vtype or vtype in ("auto", "string", "str"):
        return value
    text = str(value or "").strip()
    if vtype == "number":
        try:
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            return value
    if vtype == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return value
    if vtype == "datetime":
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return value
    return value


def _values_match(planned: Any, actual: Any) -> bool:
    if planned is None and actual is None:
        return True
    if isinstance(planned, (int, float)) and not isinstance(planned, bool):
        if isinstance(actual, (int, float)) and not isinstance(actual, bool):
            return abs(float(planned) - float(actual)) <= _NUM_TOL
        return False
    if isinstance(planned, date) and not isinstance(planned, datetime):
        if isinstance(actual, datetime):
            return actual.date() == planned and actual.time() == datetime.min.time()
        return actual == planned
    return str(planned) == str(actual) if planned is not None else actual is None


def _range_bounds(ws, token: str) -> Tuple[str, int, int, int, int]:
    """``Sheet!A1:B2`` → (sheet, min_row, min_col, max_row, max_col)；无界用已用范围兜底。"""
    text = str(token).strip()
    sheet = ""
    if "!" in text:
        sheet, _, text = text.partition("!")
        sheet = sheet.strip().strip("'")
    m = _RANGE_RE.match(text.upper().replace("$", ""))
    if not m:
        raise ValueError(f"非法范围：{token!r}")
    _, c1, r1, c2, r2 = m.groups()
    min_col = column_index_from_string(c1) if c1 else 1
    max_col = column_index_from_string(c2) if c2 else (min_col if c1 else ws.max_column or 1)
    min_row = int(r1) if r1 else 1
    max_row = int(r2) if r2 else (int(r1) if r1 else ws.max_row or 1)
    return sheet, min_row, min_col, max_row, max_col


# ---------------------------------------------------------------------------
# 六节检查
# ---------------------------------------------------------------------------


def _check_native_table(
    ws, phase: Dict[str, Any], f: _Finding, cells: _CellExpectations, formats: dict[_CellTarget, str]
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
    if (table.ref != f"{start}:{end}{bottom + int(has_total)}"
            or (table.totalsRowCount or 0) != int(has_total)
            or (table.totalsRowShown is False if has_total else table.totalsRowShown is True)
            or table.autoFilter is None
            or table.autoFilter.ref != f"{start}:{end}{bottom}"
            or [column.name for column in table.tableColumns] != columns):
        f.fail("原生表格范围、合计行、筛选范围或列标题与计划不符", sheet=ws.title)
        return
    if "banded_rows" in phase:
        style = table.tableStyleInfo
        striped = style is not None and style.showRowStripes is True
        if striped != phase["banded_rows"] or (striped and style.name != WORKBOOK_BANDED_TABLE_STYLE):
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


def _chart_title_text(title) -> str:
    rich = title.tx.rich if title and title.tx else None
    return "" if rich is None else "".join(run.t for para in rich.p for run in para.r)


def _check_native_chart(wb, ws, phase: Dict[str, Any], f: _Finding) -> None:
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

    categories, bar_values, line_values = map(expected_ref, ("categories", "bar_values", "line_values"))
    for chart in ws._charts:
        parts = chart._charts
        if (len(parts) != 2 or not isinstance(parts[0], BarChart)
                or not isinstance(parts[1], LineChart) or any(len(part.series) != 1 for part in parts)):
            continue
        bar, line = parts
        if (bar.type != "col" or chart.legend is None or chart.legend.position != "b"
                or _chart_title_text(chart.title) != phase["title"]
                or bar.y_axis.axId == line.y_axis.axId or bar.y_axis.axPos != "l"
                or line.y_axis.axPos != "r" or line.y_axis.crosses != "max"
                or line.y_axis.crossAx != bar.x_axis.axId or line.y_axis.numFmt.formatCode != "0.00%"
                or line.dLbls is None or not line.dLbls.showVal or line.dLbls.numFmt != "0.00%"):
            continue
        for part, values, title in ((bar, bar_values, phase["bar_title"]),
                                    (line, line_values, phase["line_title"])):
            series = part.series[0]
            if (series.cat is None or series.cat.strRef is None or series.cat.strRef.f != categories
                    or series.val is None or series.val.numRef is None or series.val.numRef.f != values
                    or series.title is None or series.title.v != title
                    or _chart_title_text(part.y_axis.title) != title):
                break
        else:
            return
    f.fail("输出缺少符合计划的原生双轴柱线组合图", sheet=ws.title)


def _check_cell_styles(wb, ph: Dict[str, Any], formats: dict[_CellTarget, str], f: _Finding) -> int:
    sheet = str(ph.get("sheet") or "").strip("'")
    if sheet not in wb.sheetnames:
        f.fail(f"cell_styles 的 sheet 不在输出中：{sheet!r}")
        return 0
    ws = wb[sheet]
    try:
        _, min_row, min_col, max_row, max_col = _range_bounds(ws, str(ph.get("range") or ""))
    except (TypeError, ValueError) as exc:
        f.fail(f"cell_styles range 非法：{exc}", sheet=sheet)
        return 0
    fill_color = str(ph.get("fill_color") or "").strip().upper()
    border = str(ph.get("border") or "").strip()
    number_format = ph.get("number_format")
    checked = set()
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            cell = ws.cell(row, col)
            # Excel stores a merged area's visible style on its top-left cell.
            if isinstance(cell, MergedCell):
                area = next(area for area in ws.merged_cells.ranges if cell.coordinate in area)
                cell = ws.cell(area.min_row, area.min_col)
            position = (sheet, cell.row, cell.column)
            if position in checked:
                continue
            checked.add(position)
            if number_format:
                formats[position] = str(number_format)
            if "bold" in ph and bool(cell.font.bold) != bool(ph.get("bold")):
                f.fail("bold 与计划不符", sheet=sheet, row=row, col=col,
                       planned=str(ph.get("bold")), actual=str(cell.font.bold))
            if "horizontal" in ph and (cell.alignment.horizontal or "") != str(ph.get("horizontal")):
                f.fail("horizontal 对齐与计划不符", sheet=sheet, row=row, col=col,
                       planned=str(ph.get("horizontal")), actual=str(cell.alignment.horizontal))
            if "vertical" in ph and (cell.alignment.vertical or "") != str(ph.get("vertical")):
                f.fail("vertical 对齐与计划不符", sheet=sheet, row=row, col=col,
                       planned=str(ph.get("vertical")), actual=str(cell.alignment.vertical))
            if "font_size" in ph and abs(float(cell.font.sz or 0) - float(ph.get("font_size"))) > _NUM_TOL:
                f.fail("font_size 与计划不符", sheet=sheet, row=row, col=col,
                       planned=str(ph.get("font_size")), actual=str(cell.font.sz))
            if fill_color:
                actual_color = str(cell.fill.fgColor.rgb or "").upper()
                if cell.fill.patternType != "solid" or not actual_color.endswith(fill_color):
                    f.fail("填充色与计划不符", sheet=sheet, row=row, col=col,
                           planned=fill_color, actual=f"{cell.fill.patternType}:{actual_color}")
            if border:
                sides = (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)
                styles = [side.style if side is not None else None for side in sides]
                if any(style != border for style in styles):
                    f.fail("边框与计划不符", sheet=sheet, row=row, col=col,
                           planned=border,
                           actual=",".join(str(style) for style in styles))
    return len(checked)


def _row_insertion(phase: dict) -> tuple[str, int, int]:
    sheet, row, count = str(phase["sheet"]).strip().strip("'"), int(phase["row"]), int(phase["count"])
    if not (1 <= row <= 1_048_576 and 1 <= count <= min(10000, 1_048_577 - row)):
        raise ValueError("插入行的范围超出 Excel 行上限")
    return sheet, row, count


def _declared_ranges(plan: Dict[str, Any], kind: str) -> List[Tuple[str, int, int, int, int]]:
    from openpyxl.utils.cell import range_boundaries

    out: List[Tuple[str, int, int, int, int]] = []
    for ph in _plan_phases(plan):
        if str(ph.get("phase")) != kind:
            continue
        tokens = ph.get("ranges") if kind == "clear_ranges" else [ph.get("range")]
        for token in tokens or []:
            text = str(token).strip()
            sheet = ""
            if "!" in text:
                sheet, _, text = text.partition("!")
                sheet = sheet.strip().strip("'")
            try:
                left, top, right, bottom = range_boundaries(text.upper())
            except (TypeError, ValueError):
                continue
            if left and top and right and bottom:
                out.append((sheet, top, left, bottom, right))
    return out


def _in_ranges(ranges, sheet: str, row: int, col: int) -> bool:
    return any(
        (not name or name == sheet) and top <= row <= bottom and left <= col <= right
        for name, top, left, bottom, right in ranges
    )


def _style_signature(cell) -> Tuple[Any, ...]:
    return (
        cell.number_format,
        cell.font.sz,
        bool(cell.font.bold),
        cell.fill.patternType,
        str(cell.fill.fgColor.rgb or ""),
        cell.alignment.horizontal,
        cell.alignment.vertical,
    )


def _filter_references(target) -> tuple:
    sorting = getattr(target, "sortState", None)
    return (
        getattr(target, "ref", None),
        getattr(sorting, "ref", None),
        *(rule.ref for rule in getattr(sorting, "sortCondition", ())),
    )


def _project_formula_rows(formula: str, sheet: str, insertions) -> str:
    for name, row, count in insertions:
        formula = shift_formula_rows(formula, sheet, name, row, count)
    return formula


def _check_insert_rows(wb, insertions, plan, template_wb, planned_targets, cleared, f) -> None:
    if template_wb is None:
        f.warn("未提供原模板，插入行后的数据与公式迁移无法独立核验")
        return
    for sheet in {sheet for sheet, _, _ in insertions} - set(template_wb.sheetnames):
        f.fail("插入行的 sheet 不在原模板中", sheet=sheet)
    style_ranges = _declared_ranges(plan, "cell_styles")
    for tpl in template_wb.worksheets:
        sheet = tpl.title
        if sheet not in wb.sheetnames:
            continue
        out = wb[sheet]
        local = [(row, count) for name, row, count in insertions if name == sheet]
        coords = set(tpl._cells)
        # Verify relocated blanks as well as saved source values without inflating
        # the workbook to the rectangular extent of a distant styled cell.
        if local:
            max_row, max_col = tpl.max_row, tpl.max_column
            for actual_row, col in out._cells:
                source_row = actual_row
                for row, count in reversed(local):
                    if row <= source_row < row + count:
                        break
                    if source_row >= row + count:
                        source_row -= count
                else:
                    if source_row <= max_row and col <= max_col:
                        coords.add((source_row, col))
        _check_relocated_tables(tpl, out, local, insertions, f)
        for row, col in sorted(coords):
            actual_row = row
            for start, count in local:
                if actual_row >= start:
                    actual_row += count
            before = tpl.cell(row, col)
            if actual_row == row and before.data_type != "f":
                continue
            target = (sheet, actual_row, col)
            if target in planned_targets or _in_ranges(cleared, *target):
                continue
            expected = before.value
            if before.data_type == "f" and isinstance(expected, str):
                expected = _project_formula_rows(expected, sheet, insertions)
            after = out.cell(actual_row, col)
            if not _values_match(expected, after.value) or (before.data_type == "f" and after.data_type != "f"):
                f.fail(
                    "插入行后原数据或公式引用未按行迁移",
                    sheet=sheet,
                    template_ref=before.coordinate,
                    actual_ref=after.coordinate,
                    planned=str(expected)[:80],
                    actual=str(after.value)[:80],
                )
            elif not _in_ranges(style_ranges, *target) and (
                _style_signature(before) != _style_signature(after)
            ):
                f.fail(
                    "插入行后原样式未保留",
                    sheet=sheet,
                    template_ref=before.coordinate,
                    actual_ref=after.coordinate,
                )


def _check_relocated_tables(tpl, out, local, insertions, f) -> None:
    def expected(target) -> tuple:
        refs = _filter_references(target)
        for row, count in local:
            refs = tuple(shift_row_reference(ref, row, count) if ref else ref for ref in refs)
        return refs

    def columns(table, steps=()) -> list[tuple]:
        def formula_text(node):
            return _project_formula_rows(node.attr_text, tpl.title, steps) if node and node.attr_text else None

        return [
            (col.name, formula_text(col.calculatedColumnFormula), formula_text(col.totalsRowFormula))
            for col in table.tableColumns
        ]

    if expected(tpl.auto_filter) != _filter_references(out.auto_filter):
        f.fail("插入行后工作表筛选范围未同步迁移", sheet=tpl.title)
    for name in tpl.tables:
        table = tpl.tables[name]
        saved = out.tables.get(name)
        if saved is None or expected(table) != _filter_references(saved) or (
            expected(table.autoFilter) != _filter_references(saved.autoFilter)
            or columns(table, insertions) != columns(saved)
        ):
            f.fail("插入行后原生表格的范围、筛选或公式未同步迁移", sheet=tpl.title, table=name)


def _check_structural(wb, plan, template_wb, planned_targets, cleared, f) -> int:
    from openpyxl.utils.cell import column_index_from_string, range_boundaries

    checked = 0
    insertions: list[tuple[str, int, int]] = []
    for ph in _plan_phases(plan):
        kind = str(ph.get("phase"))
        if kind not in WORKBOOK_STRUCTURAL_PHASES:
            continue
        checked += 1
        sheet = str(ph.get("sheet") or "").strip().strip("'")
        if sheet not in wb.sheetnames:
            f.fail(f"{kind} 的 sheet 不在输出中：{sheet!r}")
            continue
        ws = wb[sheet]
        try:
            if kind == "create_sheet":
                if template_wb is None:
                    f.fail("缺少原模板，无法核验新增工作表", sheet=sheet)
                elif sheet.casefold() in {name.casefold() for name in template_wb.sheetnames}:
                    f.fail("计划新增的工作表已存在于原模板", sheet=sheet)
            elif kind == "insert_rows":
                insertions.append(_row_insertion(ph))
            elif kind == "merge_cells":
                left, top, right, bottom = range_boundaries(str(ph.get("range")).upper())
                merged = {(r.min_row, r.min_col, r.max_row, r.max_col) for r in ws.merged_cells.ranges}
                if (top, left, bottom, right) not in merged:
                    f.fail("计划合并区域在输出中不存在", sheet=sheet, range=str(ph.get("range")))
            elif kind == "set_row_height":
                row = int(ph.get("row"))
                height = ws.row_dimensions[row].height
                if height is None or abs(float(height) - float(ph.get("height"))) > _NUM_TOL:
                    f.fail("行高与计划不符", sheet=sheet, row=row,
                           planned=str(ph.get("height")), actual=str(height))
            elif kind == "set_column_width":
                column = column_index_from_string(ph["column"].upper())
                dimensions = [d for d in ws.column_dimensions.values() if d.min <= column <= d.max]
                if len(dimensions) != 1 or dimensions[0].bestFit or (
                    abs(dimensions[0].width - float(ph["width"])) > _NUM_TOL
                ):
                    f.fail("列宽与计划不符", sheet=sheet, column=ph["column"], planned=ph["width"])
            else:
                ref = str(ph.get("ref") or "").strip().upper()
                if str(ws.freeze_panes or "").upper() != ref:
                    f.fail("冻结窗格与计划不符", sheet=sheet,
                           planned=ref, actual=str(ws.freeze_panes))
        except (TypeError, ValueError, KeyError) as exc:
            f.fail(f"{kind} 计划无法核验：{exc}", sheet=sheet)
    if insertions:
        try:
            _check_insert_rows(wb, insertions, plan, template_wb, planned_targets, cleared, f)
        except (TypeError, ValueError, KeyError) as exc:
            f.fail(f"insert_rows 计划无法核验：{exc}")
    return checked


def _move_expected_rows(
    cells: _CellExpectations,
    formats: dict[_CellTarget, str],
    cleared: list[_ClearedArea],
    sheet: str,
    row: int,
    count: int,
) -> None:
    # A formula can refer to the inserted sheet from an unmoved or protected cell.
    for target, (kind, value) in cells.items():
        if kind != "s" and isinstance(value, str) and value.startswith("="):
            cells[target] = kind, shift_formula_rows(value, target[0], sheet, row, count)
    moved = [target for target in set(cells) | set(formats) if target[0] == sheet and target[1] >= row]
    for target in sorted(moved, reverse=True):
        dest = (sheet, target[1] + count, target[2])
        if target in cells:
            cells[dest] = cells.pop(target)
        if target in formats:
            formats[dest] = formats.pop(target)
    for index, (name, top, left, bottom, right) in enumerate(cleared):
        if name == sheet and bottom >= row:
            cleared[index] = (sheet, top + count if top >= row else top, left, bottom + count, right)


def _check_final_cells(
    wb, cells: _CellExpectations, formats: dict[_CellTarget, str], f: _Finding
) -> int:
    checked = 0
    for (sheet, row, col), (kind, expected) in cells.items():
        if sheet not in wb.sheetnames:
            f.fail(f"计划写入的 sheet 不在输出中：{sheet!r}", row=row, col=col)
            continue
        cell = wb[sheet].cell(row, col)
        checked += 1
        if kind in _FORMULA_EXPECTATIONS:
            if cell.data_type != "f" or cell.value != expected:
                detail = "表格计算列或合计公式与计划不符" if kind == "table_formula" else "公式与计划不符"
                f.fail(detail, sheet=sheet, row=row, col=col, planned=str(expected)[:80], actual=str(cell.value)[:80])
        elif not _values_match(expected, cell.value):
            f.fail("格值与计划不符", sheet=sheet, row=row, col=col, planned=str(expected), actual=str(cell.value))
    for (sheet, row, col), expected in formats.items():
        if sheet in wb.sheetnames:
            actual = wb[sheet].cell(row, col).number_format
            if actual != expected:
                f.warn("number_format 与计划不符", sheet=sheet, row=row, col=col, planned=expected, actual=actual)
    return checked


def _check_conformance(
    wb, plan: Dict[str, Any], write_report: Optional[Dict[str, Any]], template_wb=None
) -> _Finding:
    from app.mod_sdk.workbook_controls import (
        WORKBOOK_CONTROL_PHASES,
        WORKBOOK_NATIVE_PHASES,
        control_matches,
    )

    f = _Finding("conformance")
    # Sheet operations can replace a value without replacing its number format.
    # Track both obligations until the ordered plan reaches the saved workbook.
    cells: _CellExpectations = {}
    formats: dict[_CellTarget, str] = {}
    cleared: list[_ClearedArea] = []
    planned = {"cell_writes": 0, "formula_writes": 0}
    native_checked = styled_checked = 0

    for phase in _plan_phases(plan):
        kind = str(phase.get("phase"))
        if kind in planned:
            for write in phase.get("writes") or []:
                if not isinstance(write, dict):
                    continue
                planned[kind] += 1
                try:
                    target = _target(write)
                except (TypeError, ValueError, KeyError) as exc:
                    f.fail(f"计划 {kind} 条目非法：{exc}", write=write)
                    continue
                value = (
                    str(write.get("formula") or "").strip()
                    if kind == "formula_writes"
                    else _coerce_planned(write.get("value"), str(write.get("value_type") or ""))
                )
                cells[target] = kind, value
                if number_format := write.get("number_format"):
                    formats[target] = str(number_format)
                elif isinstance(value, date) and target in formats and not is_date_format(formats[target]):
                    formats[target] = get_time_format(type(value))
        elif kind == "clear_ranges":
            for token in phase.get("ranges") or []:
                text = str(token)
                sheet = text.split("!", maxsplit=1)[0].strip("'") if "!" in text else ""
                if sheet and sheet not in wb.sheetnames:
                    f.warn(f"clear 范围 sheet 不在输出中：{sheet!r}")
                    continue
                ws = wb[sheet] if sheet else wb.active
                try:
                    _, top, left, bottom, right = _range_bounds(ws, token)
                except ValueError:
                    f.warn(f"clear 范围无法解析：{token!r}")
                    continue
                area = (ws.title, top, left, bottom, right)
                cleared.append(area)
                for target in list(cells):
                    if _in_ranges((area,), *target):
                        del cells[target]
        elif kind == "cell_styles":
            styled_checked += _check_cell_styles(wb, phase, formats, f)
        elif kind == "insert_rows":
            try:
                _move_expected_rows(cells, formats, cleared, *_row_insertion(phase))
            except (TypeError, ValueError, KeyError) as exc:
                f.fail(f"插入行后的计划引用无法核验：{exc}", sheet=phase.get("sheet"))
        elif kind == "retain_sheets":
            wanted = [str(name) for name in (phase.get("names") or [])]
            extra = [name for name in wb.sheetnames if name not in wanted]
            if extra:
                f.fail(f"retain_sheets 后仍存在多余 sheet：{extra}")
        elif kind in WORKBOOK_NATIVE_PHASES:
            native_checked += 1
            try:
                ws = wb[phase["sheet"]]
                if ws not in wb.worksheets:
                    raise ValueError("目标不是工作表")
                if kind in WORKBOOK_CONTROL_PHASES:
                    if not control_matches(wb, phase):
                        f.fail("工作表控制规则与计划不符", phase=kind, sheet=ws.title)
                elif kind == "create_table":
                    _check_native_table(ws, phase, f, cells, formats)
                elif template_wb is not None and ws.title.casefold() in {
                    name.casefold() for name in template_wb.sheetnames
                }:
                    f.fail("图表未放在新工作表", sheet=ws.title)
                else:
                    _check_native_chart(wb, ws, phase, f)
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                f.fail("工作簿原生对象缺失或无法核验", phase=kind, sheet=phase.get("sheet"))

    checked = _check_final_cells(wb, cells, formats, f)
    residues = 0
    for sheet, top, left, bottom, right in cleared:
        ws = wb[sheet]
        for row in range(top, min(bottom, ws.max_row or bottom) + 1):
            for col in range(left, right + 1):
                cell = ws.cell(row, col)
                if (sheet, row, col) not in cells and cell.value is not None:
                    residues += 1
                    if residues <= _MAX_SAMPLES:
                        f.fail("clear 范围内存在计划外残值", sheet=sheet, row=row,
                               col=col, actual=str(cell.value)[:40])

    structural_checked = _check_structural(wb, plan, template_wb, cells, cleared, f)
    f.stats = {
        "cell_writes_planned": planned["cell_writes"],
        "formula_writes_planned": planned["formula_writes"],
        "cells_checked": checked,
        "style_cells_checked": styled_checked,
        "clear_residues": residues,
    }
    if native_checked:
        f.stats["native_phases_checked"] = native_checked
    if structural_checked:
        f.stats["structural_phases_checked"] = structural_checked
    if write_report:
        rep_cells = write_report.get("cells_written")
        if rep_cells is not None and int(rep_cells) != planned["cell_writes"]:
            f.warn(
                f"write_report 自述 cells_written={rep_cells} 与计划条数 {planned['cell_writes']} 不符"
            )
        if write_report.get("violations"):
            f.warn(
                f"写入员报告 {len(write_report['violations'])} 条保护区 violation（计划与保护区冲突）",
                samples=write_report["violations"][:3],
            )
    return f


def _check_protection(wb, plan: Dict[str, Any], template_wb) -> _Finding:
    f = _Finding("protection")
    tokens = [str(t) for t in (plan.get("protected_ranges") or [])]
    if not tokens:
        f.skip("计划未声明 protected_ranges")
        return f
    if template_wb is None:
        f.skip("未提供原模板，无法对照保护区（建议 payload.template_path 传入）")
        return f
    try:
        insertions = [
            _row_insertion(phase) for phase in _plan_phases(plan)
            if phase.get("phase") == "insert_rows"
        ]
    except (TypeError, ValueError, KeyError) as exc:
        f.fail(f"插入行后的保护区无法核验：{exc}")
        return f
    diffs = 0
    for token in tokens:
        name, _, bounds = token.strip().partition("!")
        sheet = name.strip().strip("'")
        if not sheet or sheet not in wb.sheetnames or sheet not in template_wb.sheetnames:
            f.warn(f"保护区 sheet 无法对照：{token!r}")
            continue
        ws_out, ws_tpl = wb[sheet], template_wb[sheet]
        try:
            c1, r1, c2, r2 = range_boundaries(bounds.strip())
        except ValueError:
            f.warn(f"保护区范围无法解析：{token!r}")
            continue
        ranges = [(sheet, r1 or 1, c1 or 1, r2 or 1_048_576, c2 or 16_384)]

        def values(ws) -> _CellExpectations:
            _, top, left, bottom, right = ranges[0]
            return {
                (sheet, row, col): (cell.data_type, cell.value)
                for (row, col), cell in ws._cells.items()
                if top <= row <= bottom and left <= col <= right and cell.value is not None
            }

        # Reuse ordered coordinate translation for protected values and the full
        # zone, so new cells inserted inside a protected range remain blank.
        expected = values(ws_tpl)
        try:
            for insertion in insertions:
                _move_expected_rows(expected, {}, ranges, *insertion)
        except ValueError as exc:
            f.fail(f"插入行后的保护区无法核验：{exc}", sheet=sheet)
            continue
        actual = values(ws_out)
        for target in sorted(set(expected) | set(actual)):
            old_type, old = expected.get(target, ("blank", None))
            new_type, new = actual.get(target, ("blank", None))
            if old_type == new_type and old_type == "f" and type(old) is type(new) and not isinstance(old, str):
                old, new = vars(old), vars(new)
            if old_type == new_type and old == new:
                continue
            diffs += 1
            if diffs <= _MAX_SAMPLES:
                f.fail("保护区格与原模板不一致", sheet=sheet, row=target[1], col=target[2])
    f.stats = {"protected_ranges": len(tokens), "diffs": diffs}
    return f


def _block_of_row(row: int, blocks: List[Dict[str, Any]], rows: int) -> Optional[str]:
    for b in blocks:
        top = int(b.get("top") or 0)
        if top <= row < top + rows:
            return str(b.get("key") or "").strip()
    return None


def _check_expected(wb, plan: Dict[str, Any], rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("expected")
    expected = plan.get("expected")
    if not isinstance(expected, dict):
        f.skip("计划无 expected 块（映射员未产出对账基准）")
        return f

    cell_writes = _iter_writes(plan, "cell_writes")
    formula_writes = _iter_writes(plan, "formula_writes")

    exp_cells = expected.get("cells_planned")
    if exp_cells is not None and int(exp_cells) != len(cell_writes):
        f.fail(
            f"expected.cells_planned={exp_cells} 与计划实际 {len(cell_writes)} 不符（映射员自述失真）"
        )
    exp_formulas = expected.get("formulas_planned")
    if exp_formulas is not None and int(exp_formulas) != len(formula_writes):
        f.fail(f"expected.formulas_planned={exp_formulas} 与计划实际 {len(formula_writes)} 不符")

    exp_sum = expected.get("per_key_numeric_sum")
    tm = (rules or {}).get("template_map") if isinstance(rules, dict) else None
    if isinstance(exp_sum, dict) and isinstance(tm, dict):
        blocks = [b for b in (tm.get("blocks") or []) if isinstance(b, dict)]
        rows = int((tm.get("block") or {}).get("rows") or 1)
        sheet_name = str(tm.get("sheet") or "")
        plan_sum: Dict[str, float] = {}
        file_sum: Dict[str, float] = {}
        for w in cell_writes:
            try:
                sheet, row, col = _target(w)
            except (TypeError, ValueError, KeyError):
                continue
            if sheet != sheet_name:
                continue
            key = _block_of_row(row, blocks, rows)
            if not key:
                continue
            planned = _coerce_planned(w.get("value"), str(w.get("value_type") or ""))
            if isinstance(planned, (int, float)) and not isinstance(planned, bool):
                plan_sum[key] = round(plan_sum.get(key, 0.0) + float(planned), 4)
            if sheet in wb.sheetnames:
                actual = wb[sheet].cell(row, col).value
                if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                    file_sum[key] = round(file_sum.get(key, 0.0) + float(actual), 4)
        for key, exp_v in exp_sum.items():
            pv = plan_sum.get(str(key), 0.0)
            fv = file_sum.get(str(key), 0.0)
            if abs(float(exp_v) - pv) > _NUM_TOL:
                f.fail(f"键 {key!r} expected 数值合计 {exp_v} ≠ 计划重算 {pv}（映射员统计失真）")
            if abs(pv - fv) > _NUM_TOL:
                f.fail(f"键 {key!r} 计划数值合计 {pv} ≠ 输出文件重算 {fv}（写入丢失/篡改）")
        f.stats = {"keys_checked": len(exp_sum), "plan_sum": plan_sum, "file_sum": file_sum}
    elif isinstance(exp_sum, dict):
        f.warn("expected 含 per_key_numeric_sum 但未提供 rules.json，无法按块重算（建议传入）")

    dropped = expected.get("records_dropped")
    if isinstance(dropped, list) and dropped:
        f.warn(
            f"映射员丢弃了 {len(dropped)} 条记录（携带原因，需人工确认是否合理）",
            samples=dropped[:_MAX_SAMPLES],
        )
    return f


def _check_formulas(wb) -> _Finding:
    f = _Finding("formulas")
    total = 0
    ref_errors = 0
    dangling: set[str] = set()
    names = set(wb.sheetnames)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                total += 1
                if _REF_ERR_RE.search(v):
                    ref_errors += 1
                    if ref_errors <= _MAX_SAMPLES:
                        f.fail("公式含 #REF!", sheet=ws.title, ref=cell.coordinate, formula=v[:80])
                for m in _SHEET_REF_RE.finditer(v):
                    target = (m.group(1) or m.group(2) or "").strip()
                    if target and target not in names and not target.isdigit():
                        dangling.add(target)
    for target in sorted(dangling):
        f.fail(f"公式引用了不存在的 sheet：{target!r}")
    f.stats = {"formulas_total": total, "ref_errors": ref_errors}
    return f


def _check_traceability(plan: Dict[str, Any], rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("traceability")
    ref = (
        ((plan.get("meta") or {}).get("rules_ref") or {})
        if isinstance(plan.get("meta"), dict)
        else {}
    )
    declared = str(ref.get("sha256") or "")
    if not declared:
        f.skip("计划未携带 meta.rules_ref（无法追溯规则版本）")
        return f
    if rules is None:
        f.warn("计划声明了 rules_ref 但未提供 rules.json，无法验证哈希")
        f.stats = {"declared": declared[:16]}
        return f
    actual = canonical_rules_sha256(rules)
    if actual != declared:
        f.fail(
            f"rules.json 哈希 {actual[:16]}… ≠ 计划声明 {declared[:16]}…（规则版本不一致，产物不可追溯）"
        )
    f.stats = {"declared": declared[:16], "actual": actual[:16]}
    return f


def _check_structure(wb, rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("structure")
    tm = (rules or {}).get("template_map") if isinstance(rules, dict) else None
    if not isinstance(tm, dict):
        f.skip("未提供 rules.json，跳过结构漂移检查")
        return f
    sheet_name = str(tm.get("sheet") or "")
    key_col = tm.get("key_col")
    blocks = [b for b in (tm.get("blocks") or []) if isinstance(b, dict)]
    if not sheet_name or not key_col or not blocks:
        f.skip("rules.template_map 缺 sheet/key_col/blocks，无法比对结构")
        return f
    if sheet_name not in wb.sheetnames:
        f.fail(f"规则声明的 sheet 不在输出中：{sheet_name!r}")
        return f
    ws = wb[sheet_name]
    drift = 0
    for b in blocks:
        expected_key = str(b.get("key") or "").strip()
        if not expected_key:
            continue
        top = int(b.get("top") or 0)
        actual = str(ws.cell(top, int(key_col)).value or "").strip()
        if actual != expected_key:
            drift += 1
            if drift <= _MAX_SAMPLES:
                f.fail(
                    "块键与规则不符（模板重排/规则过期）",
                    row=top,
                    expected=expected_key,
                    actual=actual,
                )
    f.stats = {
        "keyed_blocks": sum(1 for b in blocks if str(b.get("key") or "").strip()),
        "drift": drift,
    }
    return f


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

_BLAME = {
    "conformance": "writer_or_plan",
    "protection": "writer",
    "expected": "mapper",
    "formulas": "template_or_plan",
    "traceability": "pipeline",
    "structure": "rules_stale",
    "semantic": "semantic_llm",
}


def merge_semantic_section(report: Dict[str, Any], semantic: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 语义审查节并入报告并重算 verdict/blame（确定性节结论不受影响）。"""
    report["sections"]["semantic"] = semantic
    statuses = {name: s.get("status") for name, s in report["sections"].items()}
    if any(s == "fail" for s in statuses.values()):
        report["verdict"] = "FAIL"
    elif any(s == "warn" for s in statuses.values()):
        report["verdict"] = "WARN"
    else:
        report["verdict"] = "PASS"
    report["blame"] = sorted(
        {_BLAME[name] for name, s in statuses.items() if s == "fail" and name in _BLAME}
    )
    if semantic.get("human_summary"):
        report["human_summary"] = semantic["human_summary"]
    summary_bits = [f"{name}:{status}" for name, status in statuses.items()]
    report["summary"] = f"QC {report['verdict']}（" + "，".join(summary_bits) + "）"
    return report


def _cell_changes(before, after, limit: int = 100_000) -> dict:
    """Compare saved values at the same address without copying business values into receipts."""
    sheets = {ws.title: ws for ws in before.worksheets}
    output = {ws.title: ws for ws in after.worksheets}
    changes: dict[tuple[str, str], dict] = {}
    observed = 0
    complete = True
    for sheet in dict.fromkeys((*sheets, *output)):
        # openpyxl's loaded-cell indexes allow sparse sheets without materializing a rectangle.
        source = sheets[sheet]._cells if sheet in sheets else {}
        result = output[sheet]._cells if sheet in output else {}
        for key in chain(source, (key for key in result if key not in source)):
            if observed == limit:
                complete = False
                break
            observed += 1
            left, right = source.get(key), result.get(key)
            old, new = getattr(left, "value", None), getattr(right, "value", None)
            kinds = (
                left.data_type if old is not None else "blank",
                right.data_type if new is not None else "blank",
            )
            # Array and data-table formulas are OOXML objects, including their formula text.
            if kinds == ("f", "f") and not isinstance(old, str) and type(old) is type(new):
                old, new = vars(old), vars(new)
            if kinds[0] == kinds[1] and old == new:
                continue
            group = changes.setdefault(
                kinds, {"from": kinds[0], "to": kinds[1], "count": 0, "examples": []}
            )
            group["count"] += 1
            if len(group["examples"]) < _MAX_SAMPLES:
                cell = right if right is not None else left
                group["examples"].append({"sheet": sheet, "ref": cell.coordinate})
        if not complete:
            break
    return {
        "scope": "worksheet_values_at_matching_addresses",
        "scan_complete": complete,
        "scanned_addresses": observed,
        "groups": list(changes.values()),
    }


def run_qc(
    filled_path: Path,
    plan: Dict[str, Any],
    *,
    template_path: Optional[Path] = None,
    rules: Optional[Dict[str, Any]] = None,
    write_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from openpyxl import load_workbook

    keep_vba = filled_path.suffix.lower() == ".xlsm"
    wb = load_workbook(filled_path, data_only=False, keep_vba=keep_vba)
    template_wb = None
    try:
        if template_path is not None and Path(template_path).is_file():
            template_wb = load_workbook(template_path, data_only=False)
        changes = _cell_changes(template_wb, wb) if template_wb is not None else None
        sections = {
            "conformance": _check_conformance(wb, plan, write_report, template_wb),
            "protection": _check_protection(wb, plan, template_wb),
            "expected": _check_expected(wb, plan, rules),
            "formulas": _check_formulas(wb),
            "traceability": _check_traceability(plan, rules),
            "structure": _check_structure(wb, rules),
        }
    finally:
        wb.close()
        if template_wb is not None:
            template_wb.close()

    statuses = {name: s.status for name, s in sections.items()}
    if any(s == "fail" for s in statuses.values()):
        verdict = "FAIL"
    elif any(s == "warn" for s in statuses.values()):
        verdict = "WARN"
    else:
        verdict = "PASS"
    blame = sorted({_BLAME[name] for name, s in statuses.items() if s == "fail"})

    summary_bits = [f"{name}:{status}" for name, status in statuses.items()]
    return {
        "verdict": verdict,
        "cell_changes": changes,
        "blame": blame,
        "sections": {name: s.as_dict() for name, s in sections.items()},
        "summary": f"QC {verdict}（" + "，".join(summary_bits) + "）",
        "inputs": {
            "filled": str(filled_path),
            "template": str(template_path or ""),
            "rules_provided": rules is not None,
            "write_report_provided": write_report is not None,
        },
    }
