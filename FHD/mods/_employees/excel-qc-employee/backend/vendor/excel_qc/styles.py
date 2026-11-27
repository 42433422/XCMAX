"""Validate declared cell styles and preserve undeclared style properties."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .plan_coordinates import insertions, moved_row, plan_phases, range_bounds

_NUM_TOL = 1e-6


def check_cell_styles(wb, plan: Dict[str, Any], f, projection=None) -> int:
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
                if projection is not None:
                    if style_signature(projection(sheet, row, col)) != style_signature(cell):
                        f.fail("单元格样式与批准阶段投影不符", **location)
                    continue
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
                    if any(side.style != border or side.color is not None for side in sides):
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
        bool(cell.quotePrefix),
        bool(cell.pivotButton),
    )
