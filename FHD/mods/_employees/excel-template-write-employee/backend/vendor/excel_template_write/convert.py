"""按 WORKBOOK_WRITE_INPUT 声明的顺序写入既有 Excel 模板。

上游负责选定写入目标和值。写入员保护未指定的内容，只保存公式文本，
并把 expected 原样带给独立质检。员工包 README 记载直接调用方式。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.mod_sdk.errors import RECOVERABLE_ERRORS
from app.mod_sdk.workbook_chart_references import ChartReferenceError, validate_chart_insert
from app.mod_sdk.workbook_conditional_formats import (
    ConditionalFormatError,
    validate_conditional_insert,
)
from app.mod_sdk.workbook_controls import (
    WORKBOOK_CONTROL_PHASES,
    WORKBOOK_STRUCTURAL_PHASES,
    write_control,
)
from app.mod_sdk.workbook_native_objects import (
    XLSX_MAX_COL as XLSX_MAX_COL,
)
from app.mod_sdk.workbook_native_objects import (
    XLSX_MAX_ROW as XLSX_MAX_ROW,
)
from app.mod_sdk.workbook_native_objects import (
    PlanError as PlanError,
)
from app.mod_sdk.workbook_native_objects import (
    _bounded_range as _bounded_range,
)
from app.mod_sdk.workbook_native_objects import (
    _native_sheet as _native_sheet,
)
from app.mod_sdk.workbook_native_objects import (
    _overlaps as _overlaps,
)
from app.mod_sdk.workbook_native_objects import (
    _run_create_combo_chart as _run_create_combo_chart,
)
from app.mod_sdk.workbook_native_objects import (
    _run_create_table as _run_create_table,
)
from app.mod_sdk.workbook_reference_relocation import (
    DefinedNameError,
    ReferenceOverflowError,
    shifted_defined_names,
    validate_named_control_order,
)
from app.mod_sdk.workbook_reference_relocation import shift_formula_rows as _shift_formula_rows
from app.mod_sdk.workbook_table_ranges import (
    TableRangeError,
    apply_table_ranges,
    shifted_table_ranges,
)
from app.mod_sdk.workbook_three_dimensional import (
    ThreeDimensionalReferenceError,
    validate_three_dimensional_references,
)

PLAN_VERSION = 1

# xlsx 规格上限；无界范围（如 ``BR:CC``）在保护区语义下必须覆盖全部行/列。

KNOWN_PHASES = (
    {
        "clear_ranges",
        "cell_writes",
        "formula_writes",
        "retain_sheets",
        "remove_sheets",
        "create_table",
        "create_combo_chart",
        "cell_styles",
    }
    | WORKBOOK_CONTROL_PHASES
    | WORKBOOK_STRUCTURAL_PHASES
)

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M",
)


def _load_plan(src_path: Optional[Path], payload: Dict[str, Any]) -> Dict[str, Any]:
    inline = (payload or {}).get("plan")
    if isinstance(inline, dict):
        return inline
    if src_path is None or not src_path.is_file():
        raise PlanError("缺少写入计划：请上传 plan.json 或在 payload.plan 传入计划对象。")
    if src_path.suffix.lower() != ".json":
        raise PlanError(f"写入计划必须是 .json：{src_path.name}")
    try:
        data = json.loads(src_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan.json 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan.json 根节点必须是对象。")
    return data


def _normalize_phases(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = plan.get("phases")
    if phases is None and isinstance(plan.get("writes"), list):
        phases = [{"phase": "cell_writes", "writes": plan["writes"]}]
    if not isinstance(phases, list) or not phases:
        raise PlanError("plan.phases 必须是非空数组（或顶层提供 writes）。")
    out: List[Dict[str, Any]] = []
    for i, ph in enumerate(phases):
        if not isinstance(ph, dict):
            raise PlanError(f"phases[{i}] 必须是对象。")
        kind = str(ph.get("phase") or "").strip()
        if kind not in KNOWN_PHASES:
            raise PlanError(f"phases[{i}] 未知阶段：{kind or '(空)'}；支持 {sorted(KNOWN_PHASES)}")
        out.append(ph)
    try:
        validate_named_control_order(out)
    except DefinedNameError as exc:
        raise PlanError(str(exc)) from exc
    return out


def _split_sheet_token(token: str) -> Tuple[Optional[str], str]:
    text = str(token or "").strip()
    if "!" in text:
        sheet, _, rng = text.partition("!")
        return sheet.strip().strip("'"), rng.strip()
    return None, text


def _range_bounds(
    ws, rng: str, *, unbounded_row: Optional[int] = None, unbounded_col: Optional[int] = None
) -> Tuple[int, int, int, int]:
    """``A1:B2`` / ``BR:CC`` / ``A1`` → (min_row, min_col, max_row, max_col)，1-based 闭区间。

    整列/整行写法缺行（列）界时，用 ``unbounded_row/col`` 兜底（缺省取 sheet 已用范围）。
    """
    from openpyxl.utils.cell import range_boundaries

    try:
        min_col, min_row, max_col, max_row = range_boundaries(rng)
    except RECOVERABLE_ERRORS as exc:
        raise PlanError(f"非法范围：{rng!r}（{exc}）") from exc
    return (
        int(min_row or 1),
        int(min_col or 1),
        int(max_row or unbounded_row or ws.max_row or 1),
        int(max_col or unbounded_col or ws.max_column or 1),
    )


class _ProtectedZones:
    """保护区索引：sheet → [(min_row, min_col, max_row, max_col), ...]。"""

    def __init__(self, wb, tokens: List[str]) -> None:
        self.zones: Dict[str, List[Tuple[int, int, int, int]]] = {}
        for token in tokens:
            sheet, rng = _split_sheet_token(token)
            if not sheet:
                raise PlanError(f"protected_ranges 必须带 sheet 名：{token!r}")
            if sheet not in wb.sheetnames:
                raise PlanError(f"protected_ranges 引用不存在的 sheet：{sheet!r}")
            self.zones.setdefault(sheet, []).append(
                _range_bounds(
                    wb[sheet], rng, unbounded_row=XLSX_MAX_ROW, unbounded_col=XLSX_MAX_COL
                )
            )

    def hit(self, sheet: str, row: int, col: int) -> Optional[Tuple[int, int, int, int]]:
        for zone in self.zones.get(sheet, ()):  # 保护区通常个位数，逐一判断足够
            min_row, min_col, max_row, max_col = zone
            if min_row <= row <= max_row and min_col <= col <= max_col:
                return zone
        return None

    def shift_rows(self, sheet: str, insert_row: int, count: int) -> None:
        """插入行后同步移动保护区坐标，避免后续写入落入已下移的受保护数据。"""
        shifted: List[Tuple[int, int, int, int]] = []
        for min_row, min_col, max_row, max_col in self.zones.get(sheet, ()):
            if min_row >= insert_row:
                min_row += count
                max_row += count
            elif max_row >= insert_row:
                max_row += count
            shifted.append((min_row, min_col, max_row, max_col))
        if sheet in self.zones:
            self.zones[sheet] = shifted


def _resolve_target(
    ws_names: List[str], item: Dict[str, Any], idx: int, phase: str
) -> Tuple[str, int, int]:
    from openpyxl.utils.cell import coordinate_to_tuple

    sheet = str(item.get("sheet") or "").strip().strip("'")
    if not sheet:
        raise PlanError(f"{phase}[{idx}] 缺少 sheet 字段。")
    if sheet not in ws_names:
        raise PlanError(f"{phase}[{idx}] sheet 不存在：{sheet!r}；模板可用 {ws_names}")
    ref = str(item.get("ref") or "").strip()
    if ref:
        try:
            row, col = coordinate_to_tuple(ref.upper())
        except RECOVERABLE_ERRORS as exc:
            raise PlanError(f"{phase}[{idx}] 非法单元格引用：{ref!r}") from exc
        return sheet, int(row), int(col)
    try:
        row = int(item.get("row"))
        col = int(item.get("col"))
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{phase}[{idx}] 需要 ref 或 row+col。") from exc
    if row < 1 or col < 1:
        raise PlanError(f"{phase}[{idx}] row/col 必须 ≥ 1：row={row}, col={col}")
    return sheet, row, col


def _coerce_value(item: Dict[str, Any], idx: int, warnings: List[str]) -> Any:
    value = item.get("value")
    vtype = str(item.get("value_type") or "").strip().lower()
    if not vtype or vtype in ("auto", "string", "str"):
        return value
    text = str(value or "").strip()
    if vtype == "number":
        try:
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            warnings.append(f"cell_writes[{idx}] value_type=number 解析失败，按原样写入：{value!r}")
            return value
    if vtype == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        warnings.append(f"cell_writes[{idx}] value_type=date 解析失败，按原样写入：{value!r}")
        return value
    if vtype == "datetime":
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        warnings.append(f"cell_writes[{idx}] value_type=datetime 解析失败，按原样写入：{value!r}")
        return value
    warnings.append(f"cell_writes[{idx}] 未知 value_type={vtype!r}，按原样写入。")
    return value


def _apply_number_format(ws, row: int, col: int, number_format: Any) -> None:
    if number_format:
        ws.cell(row, col).number_format = str(number_format)


def _run_clear_ranges(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    ranges = phase.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise PlanError("clear_ranges 阶段缺少 ranges 数组。")
    for token in ranges:
        sheet, rng = _split_sheet_token(str(token))
        if not sheet:
            raise PlanError(f"clear_ranges 范围必须带 sheet 名：{token!r}")
        if sheet not in wb.sheetnames:
            raise PlanError(f"clear_ranges 引用不存在的 sheet：{sheet!r}；模板可用 {wb.sheetnames}")
        ws = wb[sheet]
        min_row, min_col, max_row, max_col = _range_bounds(ws, rng)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                zone = protected.hit(sheet, r, c)
                if zone is not None:
                    stats["violations"].append(
                        {
                            "phase": "clear_ranges",
                            "sheet": sheet,
                            "row": r,
                            "col": c,
                            "zone": list(zone),
                        }
                    )
                    continue
                cell = ws.cell(r, c)
                if cell.value is not None:
                    cell.value = None
                    stats["cells_cleared"] += 1


def _run_cell_writes(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
    warnings: List[str],
) -> None:
    writes = phase.get("writes")
    if not isinstance(writes, list) or not writes:
        raise PlanError("cell_writes 阶段缺少 writes 数组。")
    for idx, item in enumerate(writes):
        if not isinstance(item, dict):
            raise PlanError(f"cell_writes[{idx}] 必须是对象。")
        sheet, row, col = _resolve_target(wb.sheetnames, item, idx, "cell_writes")
        zone = protected.hit(sheet, row, col)
        if zone is not None:
            stats["violations"].append(
                {"phase": "cell_writes", "sheet": sheet, "row": row, "col": col, "zone": list(zone)}
            )
            continue
        ws = wb[sheet]
        ws.cell(row, col).value = _coerce_value(item, idx, warnings)
        _apply_number_format(ws, row, col, item.get("number_format"))
        stats["cells_written"] += 1


def _run_formula_writes(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    writes = phase.get("writes")
    if not isinstance(writes, list) or not writes:
        raise PlanError("formula_writes 阶段缺少 writes 数组。")
    for idx, item in enumerate(writes):
        if not isinstance(item, dict):
            raise PlanError(f"formula_writes[{idx}] 必须是对象。")
        formula = str(item.get("formula") or "").strip()
        if not formula.startswith("="):
            raise PlanError(f"formula_writes[{idx}] 公式必须以 = 开头：{formula!r}")
        sheet, row, col = _resolve_target(wb.sheetnames, item, idx, "formula_writes")
        zone = protected.hit(sheet, row, col)
        if zone is not None:
            stats["violations"].append(
                {
                    "phase": "formula_writes",
                    "sheet": sheet,
                    "row": row,
                    "col": col,
                    "zone": list(zone),
                }
            )
            continue
        ws = wb[sheet]
        ws.cell(row, col).value = formula
        _apply_number_format(ws, row, col, item.get("number_format"))
        stats["formulas_written"] += 1


def _sheet_of(phase: Dict[str, Any], kind: str) -> str:
    sheet = str(phase.get("sheet") or "").strip().strip("'")
    if not sheet:
        raise PlanError(f"{kind} 阶段缺少 sheet 字段。")
    return sheet


def _run_insert_rows(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    from copy import copy

    sheet = _sheet_of(phase, "insert_rows")
    if sheet not in wb.sheetnames:
        raise PlanError(f"insert_rows 引用不存在的 sheet：{sheet!r}；模板可用 {wb.sheetnames}")
    try:
        row, count = int(phase.get("row")), int(phase.get("count"))
    except (TypeError, ValueError) as exc:
        raise PlanError("insert_rows 需要整数 row 与 count。") from exc
    if not 1 <= row <= XLSX_MAX_ROW:
        raise PlanError(f"insert_rows 的 row 越界：{row}")
    if not 1 <= count <= 10000:
        raise PlanError(f"insert_rows 的 count 必须在 1..10000：{count}")
    ws = wb[sheet]
    last_row = max(ws.max_row, max(ws.row_dimensions, default=0))
    if last_row >= row and last_row + count > XLSX_MAX_ROW:
        raise PlanError("insert_rows 会使现有单元格超出工作表行数上限。")
    # openpyxl 只移动单元格，不迁移合并区、行高与公式引用，这里逐项补齐。
    try:
        validate_three_dimensional_references(wb, row, count, sheet)
        validate_chart_insert(wb, sheet, row, count)
        validate_conditional_insert(wb, sheet, row, count)
        tables = shifted_table_ranges(wb, row, count, sheet)
        defined_names = shifted_defined_names(wb, row, count, sheet)
        formulas = [
            (
                source,
                cell.row + (count if source is ws and cell.row >= row else 0),
                cell.column,
                _shift_formula_rows(
                    cell.value, row, count, formula_sheet=source.title, target_sheet=sheet
                ),
            )
            for source in wb.worksheets
            for cell in source._cells.values()
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
    except (
        ReferenceOverflowError,
        DefinedNameError,
        TableRangeError,
        ConditionalFormatError,
        ThreeDimensionalReferenceError,
        ChartReferenceError,
    ) as exc:
        raise PlanError(str(exc)) from exc
    merges = [
        (rng.min_row, rng.min_col, rng.max_row, rng.max_col)
        for rng in ws.merged_cells.ranges
        if rng.max_row >= row
    ]
    merge_styles = {
        (r + (count if r >= row else 0), c): copy(ws.cell(r, c)._style)
        for top, left, bottom, right in merges
        for r in range(top, bottom + 1)
        for c in range(left, right + 1)
        if ws.cell(r, c).has_style
    }
    dimensions = {idx: copy(dim) for idx, dim in ws.row_dimensions.items() if idx >= row}
    # 必须先解除原坐标的合并，否则 unmerge 会删除已经移动到该坐标的原始数据。
    for rng in list(ws.merged_cells.ranges):
        if rng.max_row >= row:
            ws.unmerge_cells(str(rng))
    ws.insert_rows(row, count)
    for min_row, min_col, max_row, max_col in merges:
        if min_row >= row:
            min_row += count
            max_row += count
        elif max_row >= row:
            max_row += count
        ws.merge_cells(start_row=min_row, start_column=min_col, end_row=max_row, end_column=max_col)
    for (r, col), style in merge_styles.items():
        ws.cell(r, col)._style = style
    for idx in dimensions:
        del ws.row_dimensions[idx]
    for idx, dimension in dimensions.items():
        dimension.index = idx + count
        ws.row_dimensions[idx + count] = dimension
    for source, r, col, formula in formulas:
        source.cell(r, col).value = formula
    for definition, text in defined_names:
        definition.attr_text = text
    apply_table_ranges(tables)

    protected.shift_rows(sheet, row, count)
    stats["rows_inserted"] += count


def _run_merge_cells(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    sheet = _sheet_of(phase, "merge_cells")
    if sheet not in wb.sheetnames:
        raise PlanError(f"merge_cells 引用不存在的 sheet：{sheet!r}")
    token = str(phase.get("range") or "").strip()
    if not token:
        raise PlanError("merge_cells 阶段缺少 range。")
    top, left, bottom, right = _bounded_range(token)
    target = (top, left, bottom, right)
    if top == bottom and left == right:
        raise PlanError("merge_cells 至少需要两个单元格。")
    if (bottom - top + 1) * (right - left + 1) > 100_000:
        raise PlanError("merge_cells 区域过大（最多 100000 格）。")
    if any(_overlaps(target, zone) for zone in protected.zones.get(sheet, ())):
        raise PlanError("合并区域与保护区重叠。")
    ws = wb[sheet]
    for rng in ws.merged_cells.ranges:
        bounds = _bounded_range(str(rng))
        if bounds == target:
            return
        if _overlaps(target, bounds):
            raise PlanError("合并区域与现有合并单元格重叠。")
    if any(
        ws.cell(r, c).value is not None
        for r in range(top, bottom + 1)
        for c in range(left, right + 1)
        if (r, c) != (top, left)
    ):
        raise PlanError("合并区域包含非左上角数据，合并会丢失内容。")
    ws.merge_cells(start_row=top, start_column=left, end_row=bottom, end_column=right)
    stats["merged_ranges"] += 1


def _run_set_row_height(wb, phase: Dict[str, Any], stats: Dict[str, Any]) -> None:
    sheet = _sheet_of(phase, "set_row_height")
    if sheet not in wb.sheetnames:
        raise PlanError(f"set_row_height 引用不存在的 sheet：{sheet!r}")
    try:
        row, height = int(phase.get("row")), float(phase.get("height"))
    except (TypeError, ValueError) as exc:
        raise PlanError("set_row_height 需要整数 row 与数值 height。") from exc
    if not 1 <= row <= XLSX_MAX_ROW:
        raise PlanError(f"set_row_height 的 row 越界：{row}")
    if not 0.25 <= height <= 409:
        raise PlanError(f"set_row_height 的 height 必须在 0.25..409：{height}")
    wb[sheet].row_dimensions[row].height = height
    stats["row_heights_set"] += 1


def _run_set_column_width(wb, phase: Dict[str, Any]) -> None:
    from copy import copy

    from openpyxl.utils.cell import column_index_from_string, get_column_letter

    ws = _native_sheet(wb, _sheet_of(phase, "set_column_width"))
    column = str(phase.get("column") or "").strip().upper()
    try:
        index = column_index_from_string(column)
        width = float(phase.get("width"))
    except (TypeError, ValueError) as exc:
        raise PlanError("set_column_width 需要 Excel 列名和数值宽度。") from exc
    if index > XLSX_MAX_COL or not 0 < width <= 255:
        raise PlanError("set_column_width 的列名或宽度超出 Excel 边界。")

    dimensions = ws.column_dimensions
    for dimension in dimensions.values():
        dimension.reindex()
        if dimension.min <= index <= dimension.max:
            break
    else:
        dimension = dimensions[column]
        dimension.reindex()

    # An existing grouped dimension can span this column. Preserve its other columns.
    for start, end in ((dimension.min, index - 1), (index + 1, dimension.max)):
        if start <= end:
            sibling = copy(dimension)
            sibling.index = get_column_letter(start)
            sibling.min, sibling.max = start, end
            dimensions[sibling.index] = sibling
    dimension.index = column
    dimension.min = dimension.max = index
    dimension.width, dimension.bestFit = width, False
    dimensions[column] = dimension


def _run_freeze_panes(wb, phase: Dict[str, Any], stats: Dict[str, Any]) -> None:
    from openpyxl.utils.cell import coordinate_to_tuple

    sheet = _sheet_of(phase, "freeze_panes")
    if sheet not in wb.sheetnames:
        raise PlanError(f"freeze_panes 引用不存在的 sheet：{sheet!r}")
    ref = str(phase.get("ref") or "").strip().upper()
    try:
        coordinate_to_tuple(ref)
    except RECOVERABLE_ERRORS as exc:
        raise PlanError(f"freeze_panes 的 ref 非法：{ref!r}") from exc
    wb[sheet].freeze_panes = ref
    stats["frozen_sheets"] += 1


def _run_cell_styles(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    from copy import copy

    from openpyxl.styles import PatternFill, Side

    sheet = str(phase.get("sheet") or "").strip().strip("'")
    if sheet not in wb.sheetnames:
        raise PlanError(f"cell_styles 引用不存在的 sheet：{sheet!r}")
    token = str(phase.get("range") or "").strip()
    if not token:
        raise PlanError("cell_styles 阶段缺少 range。")
    min_row, min_col, max_row, max_col = _bounded_range(token)
    bold = phase.get("bold")
    font_size = phase.get("font_size")
    horizontal = phase.get("horizontal")
    vertical = phase.get("vertical")
    fill_color = str(phase.get("fill_color") or "").strip().upper()
    border = str(phase.get("border") or "").strip()
    number_format = phase.get("number_format")
    if "number_format" in phase and (not isinstance(number_format, str) or not number_format):
        raise PlanError("cell_styles 的 number_format 需要非空格式字符串。")
    if not any(
        (
            bold is not None,
            font_size is not None,
            horizontal,
            vertical,
            fill_color,
            border,
            number_format,
        )
    ):
        raise PlanError("cell_styles 阶段至少需要一个样式字段。")
    if font_size is not None:
        try:
            font_size = float(font_size)
        except (TypeError, ValueError) as exc:
            raise PlanError(f"font_size 必须是数值：{phase.get('font_size')!r}") from exc
        if not 1 <= font_size <= 409:
            raise PlanError(f"font_size 必须在 1..409：{font_size}")
    if fill_color and not re.fullmatch(r"[0-9A-F]{6}", fill_color):
        raise PlanError(f"fill_color 必须是 6 位十六进制：{fill_color!r}")
    if border and border != "thin":
        raise PlanError(f"不支持的 border：{border!r}")
    fill = (
        PatternFill(start_color=f"FF{fill_color}", end_color=f"FF{fill_color}", fill_type="solid")
        if fill_color
        else None
    )
    thin = Side(style="thin") if border else None
    ws = wb[sheet]
    styled = 0
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            zone = protected.hit(sheet, row, col)
            if zone is not None:
                stats["violations"].append(
                    {
                        "phase": "cell_styles",
                        "sheet": sheet,
                        "row": row,
                        "col": col,
                        "zone": list(zone),
                    }
                )
                continue
            cell = ws.cell(row, col)
            if number_format is not None:
                cell.number_format = number_format
            if bold is not None or font_size is not None:
                font = copy(cell.font)
                if bold is not None:
                    font.bold = bool(bold)
                if font_size is not None:
                    font.sz = font_size
                cell.font = font
            if horizontal or vertical:
                alignment = copy(cell.alignment)
                if horizontal:
                    alignment.horizontal = str(horizontal)
                if vertical:
                    alignment.vertical = str(vertical)
                cell.alignment = alignment
            if fill is not None:
                cell.fill = copy(fill)
            if thin is not None:
                from openpyxl.styles import Border

                cell.border = Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin,
                    diagonal=cell.border.diagonal,
                    diagonal_direction=cell.border.diagonal_direction,
                    outline=cell.border.outline,
                    vertical=cell.border.vertical,
                    horizontal=cell.border.horizontal,
                )
            styled += 1
    stats["styled_cells"] = int(stats.get("styled_cells") or 0) + styled


def _run_create_sheet(wb, phase: Dict[str, Any], stats: dict) -> None:
    name = phase["sheet"]
    if (
        not name.strip()
        or len(name) > 31
        or re.search(r"[\\/*?:\[\]\x00-\x1f]", name)
        or name.startswith("'")
        or name.endswith("'")
        or name.casefold() in {item.casefold() for item in wb.sheetnames}
    ):
        raise PlanError(f"需要合法且未占用的新工作表名称：{name!r}")
    wb.create_sheet(name)
    stats["sheets_created"].append(name)


def _run_sheet_prune(wb, phase: Dict[str, Any], stats: Dict[str, Any]) -> None:
    kind = str(phase.get("phase"))
    names = phase.get("names")
    if not isinstance(names, list) or not names:
        raise PlanError(f"{kind} 阶段缺少 names 数组。")
    wanted = [str(n).strip() for n in names if str(n).strip()]
    if kind == "retain_sheets":
        keep = [n for n in wanted if n in wb.sheetnames]
        if not keep:
            raise PlanError(f"retain_sheets 与模板无交集：{wanted}；模板可用 {wb.sheetnames}")
        for name in list(wb.sheetnames):
            if name not in keep:
                del wb[name]
                stats["sheets_removed"].append(name)
    else:
        for name in wanted:
            if name in wb.sheetnames:
                if len(wb.sheetnames) == 1:
                    raise PlanError(f"remove_sheets 不能删除最后一个 sheet：{name!r}")
                del wb[name]
                stats["sheets_removed"].append(name)


def _resolve_template_path(
    template_path: Optional[Path],
    plan: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Path:
    if template_path is not None and Path(template_path).is_file():
        return Path(template_path)
    hint = plan.get("template")
    raw = str((hint or {}).get("path") or "").strip() if isinstance(hint, dict) else ""
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path(str((ctx or {}).get("workspace_root") or Path.cwd())) / raw
        if p.is_file():
            return p
    raise PlanError(
        "模板缺失：请在 payload.template_path/template_relpath 指定模板 xlsx，"
        "或在员工包 templates/ 目录内置模板，或在 plan.template.path 声明。"
    )


def _check_template_contract(wb, plan: Dict[str, Any]) -> None:
    hint = plan.get("template")
    if not isinstance(hint, dict):
        return
    wanted = [str(n).strip() for n in (hint.get("sheet_names") or []) if str(n).strip()]
    missing = [n for n in wanted if n not in wb.sheetnames]
    if missing:
        raise PlanError(f"模板缺少计划声明的 sheet：{missing}；模板实际 {wb.sheetnames}")


def _apply_plan(wb, plan: dict, warnings: list[str], *, strict_protected: bool) -> dict:
    _check_template_contract(wb, plan)
    tokens = [str(t) for t in (plan.get("protected_ranges") or [])]
    protected = _ProtectedZones(wb, tokens)

    stats: Dict[str, Any] = {
        "cells_written": 0,
        "formulas_written": 0,
        "cells_cleared": 0,
        "styled_cells": 0,
        "rows_inserted": 0,
        "merged_ranges": 0,
        "row_heights_set": 0,
        "frozen_sheets": 0,
        "sheets_removed": [],
        "sheets_created": [],
        "violations": [],
    }
    written: Dict[Tuple[str, int, int], Tuple[str, Any]] = {}
    for ph in _normalize_phases(plan):
        kind = str(ph.get("phase"))
        if kind == "insert_rows":
            # Row insertion changes later addresses; only compare writes in one stable layout.
            written.clear()
        if kind in {"cell_writes", "formula_writes"}:
            for index, item in enumerate(ph.get("writes") or []):
                if not isinstance(item, dict):
                    raise PlanError(f"{kind}[{index}] 必须是对象。")
                sheet, row, col = _resolve_target(wb.sheetnames, item, index, kind)
                key = (sheet, row, col)
                value = (
                    kind,
                    item.get("formula") if kind == "formula_writes" else item.get("value"),
                )
                if key in written and written[key] != value:
                    raise PlanError(
                        f"同一单元格被不同写入项覆盖：{sheet}!{wb[sheet].cell(row, col).coordinate}"
                    )
                written[key] = value
        if kind == "clear_ranges":
            _run_clear_ranges(wb, ph, protected, stats)
        elif kind == "cell_writes":
            _run_cell_writes(wb, ph, protected, stats, warnings)
        elif kind == "formula_writes":
            _run_formula_writes(wb, ph, protected, stats)
        elif kind == "cell_styles":
            _run_cell_styles(wb, ph, protected, stats)
        elif kind == "create_table":
            _run_create_table(wb, ph, protected, stats)
        elif kind == "create_combo_chart":
            _run_create_combo_chart(wb, ph)
        elif kind == "create_sheet":
            _run_create_sheet(wb, ph, stats)
        elif kind == "insert_rows":
            _run_insert_rows(wb, ph, protected, stats)
        elif kind == "merge_cells":
            _run_merge_cells(wb, ph, protected, stats)
        elif kind == "set_row_height":
            _run_set_row_height(wb, ph, stats)
        elif kind == "set_column_width":
            _run_set_column_width(wb, ph)
        elif kind == "freeze_panes":
            _run_freeze_panes(wb, ph, stats)
        elif kind in WORKBOOK_CONTROL_PHASES:
            try:
                write_control(wb, ph)
            except (KeyError, TypeError, ValueError) as exc:
                raise PlanError(f"{kind}：{exc}") from exc
        else:
            _run_sheet_prune(wb, ph, stats)

    if stats["violations"]:
        msg = f"{len(stats['violations'])} 条写入落在保护区"
        if strict_protected:
            raise PlanError(
                f"{msg}，strict_protected 模式下拒绝写出。示例：{stats['violations'][:3]}"
            )
        warnings.append(f"{msg}，已跳过（详见 write_report.json violations）。")
    return stats


def _stored_values(wb) -> dict:
    # Use the loaded cells so distant formatting cannot expand the scan to a rectangle.
    return {
        (ws.title, row, col): (cell.data_type, cell.value)
        for ws in wb.worksheets
        for (row, col), cell in ws._cells.items()
        if cell.value is not None
    }


def _semantically_equal(left: tuple, right: tuple) -> bool:
    if left == right:
        return True
    if right[0] != "d":
        return False
    if left[0] == "s":
        value_type = "datetime" if isinstance(right[1], datetime) else "date"
        return _coerce_value({"value": left[1], "value_type": value_type}, 0, []) == right[1]
    return (
        isinstance(left[1], datetime)
        and type(right[1]) is date
        and left[1] == datetime.combine(right[1], datetime.min.time())
    )


def review_literal_changes(template: Path, plan: dict) -> list[dict]:
    """Apply the actual phases in memory and isolate proposed business-value changes."""
    from openpyxl import load_workbook
    from openpyxl.utils.cell import get_column_letter

    phases = _normalize_phases(plan)
    value_phases = {
        "cell_writes",
        "formula_writes",
        "clear_ranges",
        "insert_rows",
        "retain_sheets",
        "remove_sheets",
        "create_table",
        "create_sheet",
    }
    if not value_phases.intersection(phase["phase"] for phase in phases):
        return []
    wb = load_workbook(template, data_only=False, keep_links=False)
    try:
        original = _stored_values(wb)
        source_tables = {
            (ws.title, table.name) for ws in wb.worksheets for table in ws.tables.values()
        }
        _apply_plan(wb, plan, [], strict_protected=True)
        result = _stored_values(wb)
        moves = [phase for phase in phases if phase["phase"] == "insert_rows"]

        def source_row(sheet: str, row: int) -> int | None:
            for phase in reversed(moves):
                if sheet != _sheet_of(phase, "insert_rows") or row < phase["row"]:
                    continue
                if row < phase["row"] + phase["count"]:
                    return None
                row -= phase["count"]
            return row

        structural_text = {
            (ws.title, region.min_row, region.min_col)
            for ws in wb.worksheets
            for region in ws.merged_cells.ranges
            if source_row(ws.title, region.min_row) is None
        }
        for ws in wb.worksheets:
            for table in ws.tables.values():
                if (ws.title, table.name) in source_tables:
                    continue
                top, left, bottom, _ = _bounded_range(table.ref)
                for col, column in enumerate(table.tableColumns, start=left):
                    if (
                        column.calculatedColumnFormula is not None
                        or source_row(ws.title, top) is None
                    ):
                        structural_text.add((ws.title, top, col))
                    if column.totalsRowLabel is not None:
                        structural_text.add((ws.title, bottom, col))

        changes = []
        blank = ("blank", None)
        for (sheet, row, col), new in result.items():
            key = (sheet, source_row(sheet, row), col)
            old = original.pop(key, blank)
            if (
                _semantically_equal(old, new)
                or (new[0] == "f" and old[0] in {"blank", "f"})
                or (old == blank and new[0] == "s" and (sheet, row, col) in structural_text)
            ):
                continue
            changes.append(
                {
                    "sheet": sheet,
                    "ref": f"{get_column_letter(col)}{row}",
                    "source_ref": f"{get_column_letter(col)}{key[1]}" if key[1] else None,
                    "kind": "fill_blank" if old == blank else "replace",
                    "before": old,
                    "after": new,
                }
            )
        changes.extend(
            {
                "sheet": sheet,
                "ref": f"{get_column_letter(col)}{row}",
                "source_ref": f"{get_column_letter(col)}{row}",
                "kind": "clear",
                "before": old,
                "after": blank,
            }
            for (sheet, row, col), old in original.items()
        )
        return changes
    finally:
        wb.close()


def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from openpyxl import load_workbook

    payload = payload or {}
    plan = _load_plan(src_path if isinstance(src_path, Path) else None, payload)
    version = plan.get("plan_version", PLAN_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = -1
    if version != PLAN_VERSION:
        raise PlanError(
            f"不支持的 plan_version：{plan.get('plan_version')!r}（当前支持 {PLAN_VERSION}）"
        )
    phases = _normalize_phases(plan)

    template = _resolve_template_path(template_path, plan, ctx or {})
    if template.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise PlanError(f"模板必须是 .xlsx/.xlsm：{template.name}")
    keep_vba = template.suffix.lower() == ".xlsm"

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_path
    if xlsx_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        default_name = Path(
            str(rule_spec.get("default_output_relpath") or "outputs/filled.xlsx")
        ).name
        xlsx_path = output_dir / default_name
    warnings: List[str] = []
    if keep_vba and xlsx_path.suffix.lower() != ".xlsm":
        xlsx_path = xlsx_path.with_suffix(".xlsm")
        warnings.append("模板为 .xlsm，输出扩展名已改为 .xlsm 以保留宏。")

    wb = load_workbook(template, data_only=False, keep_vba=keep_vba)
    try:
        stats = _apply_plan(
            wb, plan, warnings, strict_protected=bool(payload.get("strict_protected"))
        )
        wb.save(xlsx_path)
        output_sheet_names = list(wb.sheetnames)
    finally:
        wb.close()

    report = {
        "plan_version": PLAN_VERSION,
        "template": str(template),
        "output": str(xlsx_path),
        "phases_executed": [str(p.get("phase")) for p in phases],
        "output_sheet_names": output_sheet_names,
        **stats,
        "warnings": warnings,
        "expected": plan.get("expected"),
    }
    report_path = xlsx_path.parent / "write_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "output_path": str(xlsx_path),
        "report_path": str(report_path),
        "cells_written": stats["cells_written"],
        "formulas_written": stats["formulas_written"],
        "cells_cleared": stats["cells_cleared"],
        "violations": stats["violations"],
        "sheets_removed": stats["sheets_removed"],
        "output_sheet_names": output_sheet_names,
        "warnings": warnings,
        "expected": plan.get("expected"),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
