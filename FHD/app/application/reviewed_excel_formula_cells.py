"""Formula text and cached values for reviewed workbook inspection."""

from __future__ import annotations

import warnings
from io import BytesIO
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string

from app.utils.operational_errors import BOUNDARY_ERRORS

FormulaFacts = dict[tuple[str, str], dict[str, Any]]


def formula_text(value: object) -> str:
    """Formula body, never an ArrayFormula object repr."""
    if value is None:
        return ""
    text = getattr(value, "text", None)
    raw = text.strip() if isinstance(text, str) and text.strip() else str(value).strip()
    if raw.startswith("<") and " object at " in raw:
        return ""
    if raw.startswith("{=") and raw.endswith("}"):
        raw = "=" + raw[2:-1]
    elif raw and not raw.startswith("="):
        raw = "=" + raw
    return raw


def same_cell_value(left: object, right: object) -> bool:
    """Array formulas compare by ref and text. openpyxl does not equate those objects."""
    if left == right:
        return True
    left_ref = getattr(left, "ref", None)
    right_ref = getattr(right, "ref", None)
    if left_ref is None and right_ref is None:
        return False
    text = formula_text(left)
    return (
        str(left_ref or "") == str(right_ref or "")
        and text.startswith("=")
        and text == formula_text(right)
    )


def formula_facts(body: bytes) -> FormulaFacts:
    """XML formula text and cached `<v>`, including cells openpyxl drops."""
    from defusedxml import ElementTree as SafeET

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    facts: FormulaFacts = {}
    try:
        with ZipFile(BytesIO(body)) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
                return facts
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = SafeET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.iter(ns + "t"))
                    for item in root.iter(ns + "si")
                ]
            targets: dict[str, str] = {}
            for rel in SafeET.fromstring(archive.read("xl/_rels/workbook.xml.rels")):
                target = rel.attrib.get("Target", "")
                rel_id = rel.attrib.get("Id")
                if not rel_id or not target or "://" in target:
                    continue
                path = target.split("#", 1)[0].lstrip("/")
                if path.startswith("../"):
                    path = path[3:]
                if not path.startswith("xl/"):
                    path = "xl/" + path
                targets[rel_id] = path
            book = SafeET.fromstring(archive.read("xl/workbook.xml"))
            for sheet in book.iter(ns + "sheet"):
                sheet_path = targets.get(sheet.attrib.get(rid_attr, ""))
                title = sheet.attrib.get("name")
                if not title or not sheet_path or sheet_path not in names:
                    continue
                for cell in SafeET.fromstring(archive.read(sheet_path)).iter(ns + "c"):
                    formula = next((child for child in cell if child.tag == ns + "f"), None)
                    if formula is None or not cell.attrib.get("r"):
                        continue
                    cached = next((child for child in cell if child.tag == ns + "v"), None)
                    raw = None if cached is None else cached.text
                    kind = cell.attrib.get("t") or ""
                    if kind == "s" and raw and raw.isdigit() and int(raw) < len(shared):
                        raw = shared[int(raw)]
                    missing = raw is None or raw == ""
                    facts[(title, cell.attrib["r"])] = {
                        "formula": formula_text(formula.text or ""),
                        "cached": None if missing else raw,
                        "cache_missing": missing,
                    }
    except BOUNDARY_ERRORS:
        return {}
    return facts


def content_bounds(sheet: object, facts: FormulaFacts) -> tuple[int, int]:
    """Bounds of valued cells. Empty styled cells must not inflate the used range."""
    title = str(getattr(sheet, "title", ""))
    max_row = max_col = 0
    for cell in getattr(sheet, "_cells", {}).values():
        coordinate = getattr(cell, "coordinate", "")
        if getattr(cell, "value", None) is None and (title, coordinate) not in facts:
            continue
        row, col = getattr(cell, "row", None), getattr(cell, "column", None)
        if isinstance(row, int):
            max_row = max(max_row, row)
        if isinstance(col, int):
            max_col = max(max_col, col)
    for sheet_name, coord in facts:
        if sheet_name != title:
            continue
        try:
            letters, row = coordinate_from_string(coord)
        except ValueError:
            continue
        max_row = max(max_row, row)
        max_col = max(max_col, column_index_from_string(letters))
    return max_row, max_col


def load_cached_workbook(body: bytes):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return load_workbook(BytesIO(body), data_only=True, keep_links=False)
        except BOUNDARY_ERRORS:
            return None
