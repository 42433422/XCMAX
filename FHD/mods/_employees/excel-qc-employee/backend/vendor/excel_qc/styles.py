"""Validate declared cell styles and preserve undeclared style properties."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from openpyxl.cell.cell import MergedCell

from .plan_coordinates import range_bounds as _range_bounds

if TYPE_CHECKING:
    from .checks import _CellTarget, _Finding


from typing import Tuple

from .plan_coordinates import insertions, moved_row, plan_phases, range_bounds
from .plan_coordinates import original_row as _original_row

_NUM_TOL = 1e-6


def check_cell_styles(wb, plan: Dict[str, Any], f) -> int:
    checked = 0
    for index, ph in enumerate(plan_phases(plan)):
        if str(ph.get("phase")) != "cell_styles":
            continue
        sheet = str(ph.get("sheet") or "").strip("'")
        if sheet not in wb.sheetnames:
            f.fail(f"cell_styles 的 sheet 不在输出中：{sheet!r}")
            continue
        ws = wb[sheet]
        try:
            _, min_row, min_col, max_row, max_col = range_bounds(ws, str(ph.get("range") or ""))
        except (TypeError, ValueError) as exc:
            f.fail(f"cell_styles range 非法：{exc}", sheet=sheet)
            continue
        fill_color = str(ph.get("fill_color") or "").strip().upper()
        border = str(ph.get("border") or "").strip()
        later = tuple(insertions(plan, index + 1))
        for original_row in range(min_row, max_row + 1):
            row = moved_row(sheet, original_row, later)
            for col in range(min_col, max_col + 1):
                cell = ws.cell(row, col)
                checked += 1
                location = {"sheet": sheet, "row": row, "col": col}
                for key, actual in (
                    ("bold", cell.font.bold),
                    ("horizontal", cell.alignment.horizontal),
                    ("vertical", cell.alignment.vertical),
                    ("font_size", cell.font.sz),
                ):
                    planned = ph.get(key)
                    if key in ("bold", "font_size"):
                        if planned is None:
                            continue
                        mismatch = (
                            bool(actual) != bool(planned)
                            if key == "bold"
                            else abs(float(actual or 0) - float(planned)) > _NUM_TOL
                        )
                        label = f"{key} 与计划不符"
                    else:
                        if not planned:
                            continue
                        mismatch, label = (actual or "") != str(planned), f"{key} 对齐与计划不符"
                    if mismatch:
                        f.fail(label, **location, planned=str(planned), actual=str(actual))
                if fill_color:
                    actual_color = str(cell.fill.fgColor.rgb or "").upper()
                    if cell.fill.patternType != "solid" or not actual_color.endswith(fill_color):
                        f.fail(
                            "填充色与计划不符",
                            **location,
                            planned=fill_color,
                            actual=f"{cell.fill.patternType}:{actual_color}",
                        )
                if border:
                    sides = (
                        cell.border.left,
                        cell.border.right,
                        cell.border.top,
                        cell.border.bottom,
                    )
                    if any(side.style != border for side in sides):
                        f.fail(
                            "边框与计划不符",
                            **location,
                            planned=border,
                            actual=",".join(str(side.style) for side in sides),
                        )
    return checked


def style_signature(cell, changed=()) -> Tuple[Any, ...]:
    from copy import copy

    font, alignment = copy(cell.font), copy(cell.alignment)
    for key, attr in (("bold", "bold"), ("font_size", "sz")):
        if key in changed:
            setattr(font, attr, None)
    for key in ("horizontal", "vertical"):
        if key in changed:
            setattr(alignment, key, None)
    return (
        None if "number_format" in changed else cell.number_format,
        font,
        alignment,
        None if "fill_color" in changed else copy(cell.fill),
        None if "border" in changed else copy(cell.border),
        copy(cell.protection),
    )


def _check_cell_styles(
    wb, ph: Dict[str, Any], formats: dict[_CellTarget, str], f: _Finding, later=()
) -> int:
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
    for original_row in range(min_row, max_row + 1):
        row = moved_row(sheet, original_row, later)
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
                source_row = _original_row(sheet, cell.row, later)
                if source_row is None:
                    f.fail("样式锚点不属于原计划阶段", sheet=sheet, row=cell.row, col=cell.column)
                else:
                    formats[(sheet, source_row, cell.column)] = str(number_format)
            if ph.get("bold") is not None and bool(cell.font.bold) != bool(ph.get("bold")):
                f.fail(
                    "bold 与计划不符",
                    sheet=sheet,
                    row=row,
                    col=col,
                    planned=str(ph.get("bold")),
                    actual=str(cell.font.bold),
                )
            if ph.get("horizontal") and (cell.alignment.horizontal or "") != str(
                ph.get("horizontal")
            ):
                f.fail(
                    "horizontal 对齐与计划不符",
                    sheet=sheet,
                    row=row,
                    col=col,
                    planned=str(ph.get("horizontal")),
                    actual=str(cell.alignment.horizontal),
                )
            if ph.get("vertical") and (cell.alignment.vertical or "") != str(ph.get("vertical")):
                f.fail(
                    "vertical 对齐与计划不符",
                    sheet=sheet,
                    row=row,
                    col=col,
                    planned=str(ph.get("vertical")),
                    actual=str(cell.alignment.vertical),
                )
            if (
                ph.get("font_size") is not None
                and abs(float(cell.font.sz or 0) - float(ph.get("font_size"))) > _NUM_TOL
            ):
                f.fail(
                    "font_size 与计划不符",
                    sheet=sheet,
                    row=row,
                    col=col,
                    planned=str(ph.get("font_size")),
                    actual=str(cell.font.sz),
                )
            if fill_color:
                actual_color = str(cell.fill.fgColor.rgb or "").upper()
                if cell.fill.patternType != "solid" or not actual_color.endswith(fill_color):
                    f.fail(
                        "填充色与计划不符",
                        sheet=sheet,
                        row=row,
                        col=col,
                        planned=fill_color,
                        actual=f"{cell.fill.patternType}:{actual_color}",
                    )
            if border:
                sides = (cell.border.left, cell.border.right, cell.border.top, cell.border.bottom)
                styles = [side.style if side is not None else None for side in sides]
                if any(style != border for style in styles):
                    f.fail(
                        "边框与计划不符",
                        sheet=sheet,
                        row=row,
                        col=col,
                        planned=border,
                        actual=",".join(str(style) for style in styles),
                    )
    return len(checked)
