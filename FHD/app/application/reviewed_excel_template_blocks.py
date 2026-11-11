"""Keep one template block together, and reuse a template with the same layout.

Document cuts may arrive as adjacent pieces of a single form, or as repeated
copies of one layout. This module joins the pieces and recognizes the copy.
It does not call the model.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import cast
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.print_settings import PrintArea

from app.application.elt.parser_structure import semantic_key
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_structural_index import _is_document_heading_text
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

_MAX_TEMPLATE_BYTES = 8_000_000
_FINGERPRINT_ERRORS: tuple[type[Exception], ...] = (
    BadZipFile,
    ParseError,
    DefusedXmlException,
) + RECOVERABLE_ERRORS


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
        if items[lower]["heading"]:
            continue
        print_areas = items[upper]["print_areas"]
        if print_areas is not None and (
            not print_areas or print_areas != items[lower]["print_areas"]
        ):
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
    """Only reconcile model splits when complete text and layout evidence agree."""
    keys = []
    for item in evidence:
        fragments = item.get("fragments") or []
        cells = item.get("cells") or []
        if (
            item.get("truncated")
            or not item.get("layout_available")
            or len(fragments) != 1
            or not header_layout_key(cells)
        ):
            keys.append("")
        else:
            c1, r1, c2, r2 = bounded_range(fragments[0]["range"])
            keys.append(
                json.dumps(
                    {
                        "type": item.get("type"),
                        "shape": [r2 - r1, c2 - c1],
                        "merged": sorted(item.get("merged") or []),
                        "layout": item.get("layout"),
                        "cells": sorted(
                            (
                                cell["row"],
                                cell["column"],
                                str(cell.get("value") or ""),
                                cell.get("kind"),
                                cell.get("style"),
                            )
                            for cell in cells
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
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
    """Hash the bounded package, preserving every layout part, without expanding cells."""
    from app.application.reviewed_excel_template import MAX_CELLS, MAX_UNPACKED

    if not body or len(body) > _MAX_TEMPLATE_BYTES:
        return ""
    try:
        with ZipFile(BytesIO(body)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if (
                len(entries) > 5000
                or len(names) != len(entries)
                or sum(entry.file_size for entry in entries) > MAX_UNPACKED
                or not {"xl/workbook.xml", "[Content_Types].xml"} <= names
            ):
                return ""
            digest = hashlib.sha256()
            cell_count = 0
            for entry in sorted(entries, key=lambda entry: entry.filename):
                if entry.is_dir():
                    continue
                part = archive.read(entry)
                if entry.filename == "docProps/core.xml":
                    core = ElementTree.fromstring(part)
                    for child in list(core):
                        if child.tag in {
                            "{http://purl.org/dc/terms/}created",
                            "{http://purl.org/dc/terms/}modified",
                        }:
                            core.remove(child)
                    part = ElementTree.tostring(core)
                if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                    root = ElementTree.fromstring(part)
                    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                    dimension = root.find(f"{namespace}dimension")
                    if dimension is not None:
                        bounds = range_boundaries(dimension.get("ref", ""))
                        if not all(isinstance(axis, int) and axis > 0 for axis in bounds):
                            return ""
                        c1, r1, c2, r2 = cast(tuple[int, int, int, int], bounds)
                        if (c2 - c1 + 1) * (r2 - r1 + 1) > MAX_CELLS:
                            return ""
                    cell_count += sum(1 for _ in root.iter(f"{namespace}c"))
                    if cell_count > MAX_CELLS:
                        return ""
                name = entry.filename.encode()
                digest.update(len(name).to_bytes(8, "big") + name)
                digest.update(len(part).to_bytes(8, "big") + part)
            return digest.hexdigest()
    except _FINGERPRINT_ERRORS:
        return ""


def template_file_fingerprint(path: str, *, tenant_id: int | None = None) -> str:
    """Only read bounded regular files inside this tenant's template directories."""
    from app.application.shipment_excel_etl_security import (
        _open_directory_under_root,
        _windows_open_relative,
    )

    if tenant_id is None:
        from app.infrastructure.tenant_scope import current_tenant_id

        tenant_id = current_tenant_id()
    if not path or type(tenant_id) is not int or tenant_id <= 0:
        return ""
    try:
        runtime = Path(get_app_data_dir()).resolve()
        roots = [runtime / "templates" / "reviewed_excel" / str(tenant_id)]
        roots.extend(
            runtime / "tenants" / str(tenant_id) / name
            for name in ("templates", "document_templates")
        )
        resolved = Path(path).resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in roots):
            return ""
        parent = _open_directory_under_root(runtime, resolved.parent, create=False)
        try:
            descriptor = (
                _windows_open_relative(
                    parent, resolved.name, directory=False, create=False, for_input=True
                )
                if os.name == "nt"
                else os.open(
                    resolved.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=parent,
                )
            )
        finally:
            os.close(parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 0 < info.st_size <= _MAX_TEMPLATE_BYTES
            ):
                return ""
            return workbook_template_fingerprint(stream.read(_MAX_TEMPLATE_BYTES + 1))
    except RECOVERABLE_ERRORS:
        return ""


def collapse_listed_templates(templates: list[dict]) -> list[dict]:
    """Show one library card for each reviewed-excel layout."""
    identities = [_listed_identity(item) for item in templates]
    chosen: dict[str, int] = {}
    for index, (fingerprint, usable) in enumerate(identities):
        if not fingerprint:
            continue
        previous = chosen.get(fingerprint)
        if previous is None or (not usable, _listed_id(templates[index])) < (
            not identities[previous][1],
            _listed_id(templates[previous]),
        ):
            chosen[fingerprint] = index
    return [
        item
        for index, item in enumerate(templates)
        if not identities[index][0] or chosen[identities[index][0]] == index
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
    print_areas = None
    if len(sheets) == 1:
        worksheet = workbook[next(iter(sheets))]
        text = _row_text(worksheet, box[0], box[1], box[2])
        primary = text.split("|", 1)[0].strip()
        heading = primary in {
            "送货单",
            "退货单",
            "发货单",
            "出货单",
            "入库单",
            "出库单",
        } or _is_document_heading_text(text)
        if worksheet.print_area:
            print_areas = tuple(
                str(area)
                for area in PrintArea.from_string(worksheet.print_area).ranges
                if area.min_col <= box[0] <= box[2] <= area.max_col
                and area.min_row <= box[1] <= box[3] <= area.max_row
            )
    return {
        "order": index,
        "fragments": fragments,
        "basis": basis,
        "reason": reason,
        "box": box,
        "sheet": next(iter(sheets)) if len(sheets) == 1 else "",
        "heading": heading,
        "print_areas": print_areas,
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
    if left["box"][1] != right["box"][1]:
        return bool(left["box"][1] < right["box"][1])
    return bool(left["box"][0] <= right["box"][0])


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


def _listed_identity(template: dict) -> tuple[str, bool]:
    preview = template.get("preview_data")
    if not isinstance(preview, dict) or preview.get("reviewed_excel") is not True:
        return "", False
    # A saved revision keeps its own card even when its workbook is unchanged.
    if preview.get("revision_parent"):
        return "", False
    stored = str(preview.get("content_fingerprint") or "").strip()
    path = str(template.get("path") or template.get("file_path") or "")
    actual = template_file_fingerprint(path)
    # Only an unavailable card may use its old identity; it must never hide a usable file.
    if actual:
        return actual, True
    return (stored, False) if template.get("exists") is False else ("", False)


def _listed_id(template: dict) -> int:
    raw = template.get("db_id")
    if isinstance(raw, int):
        return raw
    text = str(template.get("id") or "")
    if text.startswith("db:") and text[3:].isdigit():
        return int(text[3:])
    return 2**31
