"""Native openpyxl visual facts, not a renderer or a semantic classifier.

The caller owns the authorized workbook snapshot and loading/resource limits.
Only the materialized sparse cell store of a normal Worksheet is supported.
Openpyxl normalizes merged cells; this is not raw OOXML cell fidelity.
"""

from collections import defaultdict
from copy import copy
from itertools import groupby

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


def _style(obj, styles, style_keys=None):
    if style_keys is None:
        key = _style_key(obj)
    else:
        native = tuple(obj._style or (0,) * 9)
        key = style_keys.get(native)
        if key is None:
            key = style_keys[native] = ":".join(map(str, native))
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


def _dimensions(sheet, styles, style_keys=None):
    def dimension(dim):
        return {
            "hidden": bool(dim.hidden),
            "outline_level": dim.outlineLevel,
            "collapsed": bool(dim.collapsed),
            "style": _style(dim, styles, style_keys),
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


def _border_spans(cells, merged_anchors):
    """Keep native outline styles separate from thinner internal grid strokes."""
    starts = {}
    for column, cell in cells:
        if not cell.has_style:
            continue
        border = cell.border
        end_row, end_column = merged_anchors.get((cell.row, column), (cell.row, column))
        if border.left and border.left.style:
            starts[border.left.style] = [column, 0, 0]
        # openpyxl's finite border-style enum bounds active outline kinds.
        for style, counts in starts.items():
            counts[1] += bool(border.top and border.top.style == style)
            counts[2] += bool(
                cell.row == end_row and border.bottom and border.bottom.style == style
            )
        if column == end_column and border.right and border.right.style:
            counts = starts.pop(border.right.style, None)
            if counts is None:
                continue
            start, top, bottom = counts
            width = column - start + 1
            if width > 1:
                yield start, column, border.right.style, top == width, bottom == width


def _fill_spans(cells):
    start = end = fill = 0
    for column, cell in cells:
        current = cell._style.fillId if cell.has_style and cell.fill.patternType else 0
        if current != fill or column != end + 1:
            if fill:
                yield start, end, fill
            start = column
        end, fill = column, current
    if fill:
        yield start, end, fill


def worksheet_geometry_regions(sheet):
    """Offer source-border enclosures and fill runs, without deciding table semantics.

    This is a sparse projection of pinned openpyxl border/fill objects, not a
    general graph partitioner. Missing side edges or missing native rows break
    an enclosure. Filled runs merge only over consecutive, identical spans.
    Unclosed and unstyled content remains in the caller's original cell facts.
    """
    store = getattr(sheet, "_cells", {})
    if not any(cell.has_style for cell in store.values()):
        return ()
    regions = []
    outlines = {}
    fills = {}
    # openpyxl copies the final right/bottom borders to a merged anchor; those
    # strokes belong at the merge edge, not inside the span at the anchor.
    merged_anchors = {
        (merge.min_row, merge.min_col): (merge.max_row, merge.max_col)
        for merge in sheet.merged_cells.ranges
    }

    def finish_fill(key, rows):
        left, right, fill = key
        top, bottom = rows
        if top != bottom or left != right:
            regions.append(((top, left, bottom, right), "style_continuity", f"fill:{fill}"))

    for row, entries in groupby(sorted(store.items()), key=lambda item: item[0][0]):
        cells = [(position[1], cell) for position, cell in entries]
        current_outlines = {}
        for left, right, style, top, bottom in _border_spans(cells, merged_anchors):
            previous = outlines.get((left, right, style))
            start = row if top else previous[0] if previous and previous[1] == row - 1 else None
            if start is None:
                continue
            if bottom:
                if start < row:
                    regions.append(((start, left, row, right), "border_enclosure", ""))
            else:
                current_outlines[(left, right, style)] = (start, row)
        outlines = current_outlines
        current_fills = {}
        for left, right, fill in _fill_spans(cells):
            key = (left, right, fill)
            previous = fills.pop(key, None)
            if previous and previous[1] == row - 1:
                current_fills[key] = (previous[0], row)
            else:
                if previous:
                    finish_fill(key, previous)
                current_fills[key] = (row, row)
        for key, rows in fills.items():
            finish_fill(key, rows)
        fills = current_fills
    for key, rows in fills.items():
        finish_fill(key, rows)
    return tuple(sorted(regions))


def worksheet_visual_facts(
    sheet, *, include_neighbors=True, include_cells=True, styles=None, style_keys=None
):
    """Sparse native geometry and style facts; no rectangular iteration or cell creation."""
    styles = {} if styles is None else styles
    style_keys = {} if style_keys is None else style_keys
    cells = []
    entries = sorted(sheet._cells.items()) if include_cells else sheet._cells.items()
    for (row, column), cell in entries:
        if cell.value is None and not cell.has_style:
            continue
        style = _style(cell, styles, style_keys)
        if include_cells:
            cells.append(
                {
                    "row": row,
                    "column": column,
                    "address": cell.coordinate,
                    "style": style,
                    "blank": cell.value is None,
                    "merge_placeholder": isinstance(cell, MergedCell),
                }
            )
    dimensions = _dimensions(sheet, styles, style_keys)
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
        "neighbor_candidates_status": "included"
        if include_neighbors and include_cells
        else "not_requested",
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
