"""Keep one template block together, and reuse a template with the same layout.

Document cuts may arrive as adjacent pieces of a single form, or as repeated
copies of one layout. This module joins the pieces and recognizes the copy.
It does not call the model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.print_settings import PrintArea

from app.application.elt.parser_structure import semantic_key
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_structural_index import _is_document_heading_text
from app.utils.operational_errors import RECOVERABLE_ERRORS

_MAX_TEMPLATE_BYTES = 8_000_000


def join_split_template_blocks(
    body: bytes, groups: list[tuple[list[dict], str, str]]
) -> list[tuple[list[dict], str, str]]:
    """Join adjacent pieces of one form. A new document heading stays separate."""
    if len(groups) < 2 or not body:
        return groups
    try:
        workbook = load_workbook(BytesIO(body), data_only=False)
    except RECOVERABLE_ERRORS:
        return groups
    try:
        items = [_piece(workbook, index, group) for index, group in enumerate(groups)]
    except RECOVERABLE_ERRORS:
        return groups
    finally:
        workbook.close()
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left == right:
            return
        if items[left]["order"] <= items[right]["order"]:
            parent[right] = left
        else:
            parent[left] = right

    for left, right in _touching_pairs(items):
        upper, lower = (left, right) if _above(items[left], items[right]) else (right, left)
        if items[lower]["heading"] or not _same_print_unit(items[upper], items[lower]):
            continue
        union(upper, lower)
    ordered: dict[int, list[int]] = {}
    for index in range(len(items)):
        ordered.setdefault(find(index), []).append(index)
    joined = []
    for root in sorted(ordered, key=lambda index: items[index]["order"]):
        members = sorted(ordered[root], key=lambda index: items[index]["order"])
        fragments = [dict(fragment) for index in members for fragment in items[index]["fragments"]]
        basis, reason = items[members[0]]["basis"], items[members[0]]["reason"]
        joined.append((fragments, basis, reason))
    return joined


def header_layout_key(cells: list[dict]) -> str:
    """Identity of a header row. Fewer than three labels is not a shared layout."""
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in cells:
        value = str(cell.get("value") or "").strip()
        if not value or len(value) > 24 or _mostly_digits(value):
            continue
        try:
            row, column = int(cell["row"]), int(cell["column"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.setdefault(row, []).append((column, value))
    best: list[str] = []
    for items in rows.values():
        labels = [value for _column, value in sorted(items)]
        if len(labels) > len(best):
            best = labels
    if len(best) < 3:
        return ""
    return "|".join(semantic_key(value) for value in best)


def merge_same_layout_families(groups: list[dict], evidence: list[dict]) -> list[dict]:
    """Fold families that share one header layout into a single template family."""
    keys = []
    for item in evidence:
        if item.get("truncated") or not item.get("cells"):
            keys.append("")
        else:
            keys.append(header_layout_key(item.get("cells") or []))
    merged: list[dict] = []
    seen: dict[str, dict] = {}
    for group in groups:
        member_keys = {keys[index] for index in group["members"] if index < len(keys)}
        key = next(iter(member_keys)) if len(member_keys) == 1 else ""
        if key and key in seen:
            seen[key]["members"].extend(group["members"])
            continue
        item = {"members": list(group["members"]), "reason": group["reason"]}
        merged.append(item)
        if key:
            seen[key] = item
    return merged


def workbook_template_fingerprint(body: bytes) -> str:
    """Stable identity of a cleaned template. Zip timestamps are ignored."""
    if not body or len(body) > _MAX_TEMPLATE_BYTES:
        return ""
    try:
        workbook = load_workbook(BytesIO(body), data_only=False, read_only=False)
    except RECOVERABLE_ERRORS:
        return ""
    try:
        sheets = []
        for worksheet in workbook.worksheets:
            cells = []
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value is None or cell.value == "":
                        continue
                    cells.append([cell.coordinate, _token(cell.value)])
            merges = sorted(str(item) for item in worksheet.merged_cells.ranges)
            sheets.append(
                {
                    "title": worksheet.title,
                    "state": worksheet.sheet_state,
                    "cells": cells,
                    "merges": merges,
                }
            )
    except RECOVERABLE_ERRORS:
        return ""
    finally:
        workbook.close()
    raw = json.dumps(sheets, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def collapse_listed_templates(templates: list[dict]) -> list[dict]:
    """Show one library card for each reviewed-excel layout."""
    fingerprints = [_listed_fingerprint(item) for item in templates]
    chosen: dict[str, int] = {}
    for index, fingerprint in enumerate(fingerprints):
        if not fingerprint:
            continue
        previous = chosen.get(fingerprint)
        if previous is None or _listed_id(templates[index]) < _listed_id(templates[previous]):
            chosen[fingerprint] = index
    return [
        item
        for index, item in enumerate(templates)
        if not fingerprints[index] or chosen[fingerprints[index]] == index
    ]


def _piece(workbook, index: int, group: tuple[list[dict], str, str]) -> dict:
    fragments, basis, reason = group
    sheets = {fragment["sheet"] for fragment in fragments}
    boxes = [bounded_range(fragment["range"]) for fragment in fragments]
    box = (
        min(item[0] for item in boxes),
        min(item[1] for item in boxes),
        max(item[2] for item in boxes),
        max(item[3] for item in boxes),
    )
    heading = False
    print_fit = "multi"
    if len(sheets) == 1:
        worksheet = workbook[next(iter(sheets))]
        heading = _is_document_heading_text(_row_text(worksheet, box[0], box[1], box[2]))
        print_fit = _print_fit(worksheet, box)
    return {
        "order": index,
        "fragments": fragments,
        "basis": basis,
        "reason": reason,
        "box": box,
        "sheet": next(iter(sheets)) if len(sheets) == 1 else "",
        "heading": heading,
        "print_fit": print_fit,
        "multi": len(sheets) != 1,
    }


def _row_text(worksheet, c1: int, row: int, c2: int) -> str:
    bits = []
    for column in range(c1, c2 + 1):
        value = worksheet.cell(row, column).value
        if value is None:
            continue
        text = str(value).strip()
        if text:
            bits.append(text)
    return " | ".join(bits)


def _above(left: dict, right: dict) -> bool:
    left_box, right_box = left["box"], right["box"]
    if int(left_box[1]) != int(right_box[1]):
        return int(left_box[1]) < int(right_box[1])
    return int(left_box[0]) <= int(right_box[0])


def _same_print_unit(left: dict, right: dict) -> bool:
    """A slice inside the print area stays apart from one that leaves it."""
    left_fit, right_fit = str(left.get("print_fit") or ""), str(right.get("print_fit") or "")
    return left_fit == right_fit and left_fit in {"unset", "inside", "outside"}


def _print_fit(worksheet, box: tuple[int, int, int, int]) -> str:
    area = worksheet.print_area
    if not area:
        return "unset"
    try:
        ranges = PrintArea.from_string(str(area)).ranges
    except RECOVERABLE_ERRORS:
        return "unset"
    boxes = [bounded_range(str(item)) for item in ranges]

    def covers(outer: tuple[int, int, int, int]) -> bool:
        return (
            outer[0] <= box[0] and outer[1] <= box[1] and box[2] <= outer[2] and box[3] <= outer[3]
        )

    def hits(outer: tuple[int, int, int, int]) -> bool:
        return (
            outer[0] <= box[2] and box[0] <= outer[2] and outer[1] <= box[3] and box[1] <= outer[3]
        )

    if any(covers(item) for item in boxes):
        return "inside"
    if any(hits(item) for item in boxes):
        return "cross"
    return "outside"


def _touching_pairs(items: list[dict]) -> list[tuple[int, int]]:
    pairs = []
    for left in range(len(items)):
        if items[left]["multi"]:
            continue
        for right in range(left + 1, len(items)):
            if items[right]["multi"] or items[left]["sheet"] != items[right]["sheet"]:
                continue
            if _touches(items[left]["box"], items[right]["box"]):
                pairs.append((left, right))
    return pairs


def _touches(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    """Pieces of one form stacked with at most one blank row between them."""
    cols_overlap = left[0] <= right[2] and right[0] <= left[2]
    return cols_overlap and 0 <= _gap(left[1], left[3], right[1], right[3]) <= 1


def _gap(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    if start_b > end_a:
        return start_b - end_a - 1
    if start_a > end_b:
        return start_a - end_b - 1
    return -1


def _mostly_digits(value: str) -> bool:
    digits = sum(character.isdigit() for character in value)
    return digits > 0 and digits * 2 >= len(value)


def _token(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _listed_fingerprint(template: dict) -> str:
    preview = template.get("preview_data")
    if not isinstance(preview, dict) or preview.get("reviewed_excel") is not True:
        return ""
    stored = str(preview.get("content_fingerprint") or "").strip()
    if stored:
        return stored
    path = str(template.get("path") or template.get("file_path") or "")
    if not path:
        return ""
    try:
        body = Path(path).read_bytes()
    except RECOVERABLE_ERRORS:
        return ""
    return workbook_template_fingerprint(body)


def _listed_id(template: dict) -> int:
    raw = template.get("db_id")
    if isinstance(raw, int):
        return raw
    text = str(template.get("id") or "")
    if text.startswith("db:") and text[3:].isdigit():
        return int(text[3:])
    return 2**31
