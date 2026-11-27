"""Native openpyxl visual facts, not a renderer or a semantic classifier.

The caller owns the authorized workbook snapshot and loading/resource limits.
Only the materialized sparse cell store of a normal Worksheet is supported.
Openpyxl normalizes merged cells; this is not raw OOXML cell fidelity.
"""

from collections import defaultdict
from copy import copy

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils import column_index_from_string
from openpyxl.xml.functions import tostring


def _xml(value):
    return tostring(copy(value).to_tree()).decode("utf-8") if value is not None else None


def _color(value):
    if value is None:
        return None
    return {"type": value.type, "value": value.value, "tint": value.tint}


def _style_key(obj):
    # Native XF identity, scoped to this workbook; unlike style_id, no registration.
    return ":".join(map(str, obj._style or (0,) * 9))


def _style(obj, styles):
    key = _style_key(obj)
    if key not in styles:
        font, fill, border, alignment = obj.font, obj.fill, obj.border, obj.alignment
        styles[key] = {
            "font": {
                "name": font.name,
                "size_pt": font.sz,
                "family": font.family,
                "bold": font.bold,
                "italic": font.italic,
                "color": _color(font.color),
                "xml": _xml(font),
            },
            "fill": {
                "pattern": fill.patternType if hasattr(fill, "patternType") else None,
                "foreground": _color(getattr(fill, "fgColor", None)),
                "xml": _xml(fill),
            },
            "border": {
                "sides": {
                    name: getattr(border, name).style if getattr(border, name) else None
                    for name in ("left", "right", "top", "bottom")
                },
                "xml": _xml(border),
            },
            "alignment": {"horizontal": alignment.horizontal, "xml": _xml(alignment)},
            "number_format": obj.number_format,
            "protection_xml": _xml(obj.protection),
        }
    return key


def workbook_visual_context(workbook):
    """Palette/theme evidence once per workbook; no guessed RGB or font substitution."""
    theme = workbook.loaded_theme
    return {
        "theme_xml": theme.decode("utf-8") if theme else None,
        "indexed_colors": list(workbook._colors),
        "rendered": False,
    }


def _dimensions(sheet, styles):
    def dimension(dim):
        return {
            "hidden": bool(dim.hidden),
            "outline_level": dim.outlineLevel,
            "collapsed": bool(dim.collapsed),
            "style": _style(dim, styles),
        }

    fmt = sheet.sheet_format
    return {
        "default_row_height_pt": fmt.defaultRowHeight,
        "default_column_width_chars": fmt.defaultColWidth,
        "base_column_width_chars": fmt.baseColWidth,
        "default_rows_hidden": bool(fmt.zeroHeight),
        "rows": [
            {"row": key, "height_pt": dim.height, **dimension(dim)}
            for key, dim in sorted(sheet.row_dimensions.items())
        ],
        "columns": sorted(
            [
                {
                    "start": dim.min or column_index_from_string(key),
                    "end": dim.max or dim.min or column_index_from_string(key),
                    "width_chars": dim.width,
                    **dimension(dim),
                }
                for key, dim in sheet.column_dimensions.items()
            ],
            key=lambda item: (item["start"], item["end"]),
        ),
    }


def _neighbors(cells, styles):
    """Consecutive materialized cells per axis; sparse graph edges, not table labels."""
    for axis, fixed, varying in (("horizontal", "row", "column"), ("vertical", "column", "row")):
        groups = defaultdict(list)
        for cell in cells:
            groups[cell[fixed]].append(cell)
        facing, parallel = (
            (("right", "left"), ("top", "bottom"))
            if axis == "horizontal"
            else (("bottom", "top"), ("left", "right"))
        )
        for group in groups.values():
            group.sort(key=lambda cell: cell[varying])
            for left, right in zip(group, group[1:]):
                gap = right[varying] - left[varying] - 1
                a, b = (styles[cell["style"]]["border"]["sides"] for cell in (left, right))
                yield {
                    "axis": axis,
                    "from": left["address"],
                    "to": right["address"],
                    "gap": gap,
                    "same_style": left["style"] == right["style"],
                    "facing_borders": [a[facing[0]], b[facing[1]]] if gap == 0 else None,
                    "continuous_sides": [
                        side for side in parallel if gap == 0 and a[side] and a[side] == b[side]
                    ],
                }


def worksheet_visual_facts(sheet, *, include_neighbors=True):
    """Sparse native geometry and style facts; no rectangular iteration or cell creation."""
    styles, cells = {}, []
    for (row, column), cell in sorted(sheet._cells.items()):
        if cell.value is None and not cell.has_style:
            continue
        cells.append(
            {
                "row": row,
                "column": column,
                "address": cell.coordinate,
                "style": _style(cell, styles),
                "blank": cell.value is None,
                "merge_placeholder": isinstance(cell, MergedCell),
            }
        )
    dimensions = _dimensions(sheet, styles)
    conditional = []
    for scope in sheet.conditional_formatting:
        for rule in sheet.conditional_formatting[scope]:
            conditional.append(
                {
                    "range": str(scope.sqref),
                    "rule_xml": _xml(rule),
                    "differential_style_id": rule.dxfId,
                    "differential_style_xml": _xml(rule.dxf),
                }
            )
    return {
        "version": 1,
        "sheet": sheet.title,
        "sheet_state": sheet.sheet_state,
        "representation": "openpyxl_normalized",
        "rendered": False,
        "dimensions": dimensions,
        "styles": styles,
        "cells": cells,
        "merges": [
            str(region)
            for region in sorted(sheet.merged_cells.ranges, key=lambda region: region.bounds)
        ],
        "conditional_formatting": conditional,
        "neighbor_candidates": list(_neighbors(cells, styles)) if include_neighbors else [],
        "neighbor_candidates_status": "included" if include_neighbors else "not_requested",
    }


def preview_style(cell, styles):
    """Project the old preview fields from the same native style extraction."""
    style = styles[_style(cell, styles)]
    font, fill = style["font"], style["fill"]

    def rgb(color):
        return color["value"][-6:] if color and color["type"] == "rgb" else ""

    return {
        "bold": bool(font["bold"]),
        "italic": bool(font["italic"]),
        "font_size": font["size_pt"] or 11,
        "font_color": rgb(font["color"]),
        "fill": rgb(fill["foreground"]) if fill["pattern"] == "solid" else "",
        "align": style["alignment"]["horizontal"] or "",
    }


def preview_layout(sheet, facts_by_cell, formula_text, max_row, max_col):
    """Compatibility projection only. Spans clipped to viewport; dimensions are estimates."""
    merged, covered, styles = {}, set(), {}
    for region in sheet.merged_cells.ranges:
        if region.min_row > max_row or region.min_col > max_col:
            continue
        end_row, end_col = min(region.max_row, max_row), min(region.max_col, max_col)
        anchor = (region.min_row, region.min_col)
        merged[anchor] = (end_row - anchor[0] + 1, end_col - anchor[1] + 1)
        covered.update(
            (r, c)
            for r in range(anchor[0], end_row + 1)
            for c in range(anchor[1], end_col + 1)
            if (r, c) != anchor
        )
    geometry = _dimensions(sheet, styles)
    rows, heights = [], {item["row"]: item["height_pt"] for item in geometry["rows"]}
    for r in range(1, max_row + 1):
        row_cells = []
        for c in range(1, max_col + 1):
            if (r, c) in covered:
                continue
            cell = sheet._cells.get((r, c)) or Cell(sheet, row=r, column=c)
            fact = facts_by_cell.get((sheet.title, cell.coordinate))
            formula = cell.data_type == "f" or fact is not None
            span = merged.get((r, c), (1, 1))
            value = (
                (formula_text(cell.value) or (fact or {}).get("formula") or "")
                if formula
                else ("" if cell.value is None else str(cell.value))
            )
            row_cells.append(
                {
                    "cell": cell.coordinate,
                    "value": value,
                    "formula": formula,
                    "rowspan": span[0],
                    "colspan": span[1],
                    **preview_style(cell, styles),
                }
            )
        height = heights.get(r)
        rows.append(
            {
                "height": height
                if height is not None
                else (geometry["default_row_height_pt"] or 15),
                "cells": row_cells,
            }
        )
    widths = [
        next(
            (
                item["width_chars"]
                for item in geometry["columns"]
                if item["start"] <= c <= item["end"] and item["width_chars"] is not None
            ),
            geometry["default_column_width_chars"] or 8.43,
        )
        for c in range(1, max_col + 1)
    ]
    return {
        "sheet": sheet.title,
        "rows": rows,
        "widths": widths,
        "total_rows": sheet.max_row,
        "total_columns": sheet.max_column,
        "truncated": sheet.max_row > max_row or sheet.max_column > max_col,
    }
