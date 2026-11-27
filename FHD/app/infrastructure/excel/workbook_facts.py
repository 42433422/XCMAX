"""Sparse openpyxl facts plus original OOXML evidence, with no business inference.

The application supplies formula evidence and validates archive resource limits
before loading. XML is inspected only for native presence/raw-value distinctions
which openpyxl normalizes (empty strings, formula caches and merged cell content).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import openpyxl
from defusedxml import ElementTree as SafeET
from openpyxl.cell.cell import MergedCell
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from openpyxl.xml.functions import tostring

from app.domain.tabular_facts import location_id, make_source_ref, new_document
from app.infrastructure.excel.cell_visual_facts import (
    _style,
    workbook_visual_context,
    worksheet_visual_facts,
)
from app.infrastructure.excel.sparse_rows import iter_present_cells
from app.infrastructure.excel.workbook_parts import worksheet_parts

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(value: Any) -> str | None:
    return tostring(value.to_tree()).decode("utf-8") if value is not None else None


def _value(value: Any) -> tuple[Any, str]:
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        return value, "boolean"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(), type(value).__name__
    if isinstance(value, timedelta):
        return value.total_seconds(), "duration_seconds"
    if isinstance(value, (int, float)):
        return value, "number"
    if isinstance(value, (str, CellRichText)):
        return str(value), "rich_text" if isinstance(value, CellRichText) else "text"
    return None, "unknown"


def _raw_cells(archive: ZipFile, path: str):
    """Stream actual c elements: runtime depends on source cells, not far extents."""
    with archive.open(path) as handle:
        for _, node in SafeET.iterparse(handle, events=("end",)):
            if node.tag != _NS + "c":
                if node.tag == _NS + "row":
                    node.clear()
                continue
            address = node.attrib.get("r")
            if not address:
                raise ValueError("worksheet cell has no native address")
            cached = node.find(_NS + "v")
            formula = node.find(_NS + "f")
            inline = node.find(_NS + "is")
            yield (
                address,
                {
                    "data_type": node.attrib.get("t", "n"),
                    "raw_value": cached.text if cached is not None else None,
                    "value_node_present": cached is not None,
                    "inline_text": "".join(child.text or "" for child in inline.iter(_NS + "t"))
                    if inline is not None
                    else None,
                    "formula_attributes": dict(formula.attrib) if formula is not None else None,
                    "formula_text": formula.text if formula is not None else None,
                    # Consumed before advancing the iterator/clearing this element;
                    # ordinary cells do not allocate duplicate XML strings.
                    "xml_node": node,
                },
            )
            node.clear()


def _cell_fact(document_id, sheet, cached_cells, address, raw, formula_evidence, styles):
    row, column = coordinate_to_tuple(address)
    cell = sheet._cells.get((row, column))
    cached_value_raw, cached_data_type = cached_cells.get(address, (None, "n"))
    source = {"document_id": document_id, "sheet": sheet.title, "address": address}
    fact = formula_evidence.get((sheet.title, address), {})
    is_formula = raw["formula_attributes"] is not None or bool(fact)
    original = cell.value if cell is not None else None
    normalized_away = cell is None or isinstance(cell, MergedCell)
    value, value_type = _value(original)
    formula = None
    if is_formula:
        candidate = original if isinstance(original, str) else getattr(original, "text", None)
        candidate = candidate or fact.get("formula") or raw["formula_text"]
        formula = str(candidate) if candidate else None
        if formula and not formula.startswith("="):
            formula = "=" + formula
        value, value_type = formula, "formula"
    elif original is None and raw["data_type"] == "inlineStr" and not normalized_away:
        value, value_type = raw["inline_text"] or "", "text"
    if normalized_away and (raw["raw_value"] is not None or raw["inline_text"] is not None):
        # Preserve native content hidden under a merge; never invent a decoded
        # value when the library has intentionally discarded that cell.
        value, value_type = None, "unknown"
    state = (
        "unknown"
        if value_type == "unknown" or (is_formula and formula is None)
        else ("blank" if value is None else "empty_string" if value == "" else "present")
    )
    cached_value, cached_type = _value(cached_value_raw)
    cache_present = raw["value_node_present"] and (
        raw["raw_value"] not in (None, "") or raw["data_type"] == "str"
    )
    if is_formula and cache_present and raw["data_type"] == "str" and cached_value is None:
        cached_value, cached_type = raw["raw_value"] or "", "text"
    result = {
        "cell_id": location_id(document_id, "cell", sheet.title, address),
        "address": address,
        "row": row,
        "column": column,
        "value": value,
        "value_type": "error" if getattr(cell, "data_type", "") == "e" else value_type,
        "value_state": state,
        "data_type": str(getattr(cell, "data_type", raw["data_type"])),
        "formula": formula,
        "formula_attributes": raw["formula_attributes"],
        "cached_value": cached_value if is_formula else None,
        "cached_value_type": cached_type if is_formula else "not_applicable",
        "cached_data_type": cached_data_type if is_formula else None,
        "cache_state": ("present_validity_unknown" if cache_present else "missing")
        if is_formula
        else "not_applicable",
        "style_id": _style(cell, styles) if cell is not None else "",
        "number_format": getattr(cell, "number_format", None),
        "native_data_type": raw["data_type"],
        "native_value": raw["raw_value"],
        "source_ref": source,
        "display_state": "not_rendered",
    }
    if normalized_away:
        result["native_xml"] = SafeET.tostring(raw["xml_node"], encoding="unicode")
        result["normalization_state"] = "source_only"
    if isinstance(original, CellRichText):
        result["rich_text"] = [
            {"text": part.text, "font_xml": _xml(part.font)}
            if isinstance(part, TextBlock)
            else {"text": str(part)}
            for part in original
        ]
    if cell is not None and cell.comment is not None:
        result["comment"] = {"text": cell.comment.text, "author": cell.comment.author}
    if cell is not None and cell.hyperlink is not None:
        result["hyperlink"] = {
            "target": cell.hyperlink.target,
            "location": cell.hyperlink.location,
            "executed": False,
        }
    return result


def _native_objects(sheet) -> dict[str, Any]:
    return {
        "tables": [
            {"name": table.name, "range": table.ref, "xml": _xml(table)}
            for table in sheet.tables.values()
        ],
        "defined_names": [
            {"name": name.name, "xml": _xml(name)} for name in sheet.defined_names.values()
        ],
        "auto_filter_xml": _xml(sheet.auto_filter),
        "data_validations_xml": _xml(sheet.data_validations),
        "sheet_properties_xml": _xml(sheet.sheet_properties),
        "protection_xml": _xml(sheet.protection),
        "page_setup_xml": _xml(sheet.page_setup),
        "page_margins_xml": _xml(sheet.page_margins),
        "print_options_xml": _xml(sheet.print_options),
        "views_xml": _xml(sheet.views),
        "print_area": str(sheet.print_area),
        "print_title_rows": sheet.print_title_rows,
        "print_title_columns": sheet.print_title_cols,
        "freeze_panes": str(sheet.freeze_panes) if sheet.freeze_panes else None,
        "row_breaks_xml": _xml(sheet.row_breaks),
        "column_breaks_xml": _xml(sheet.col_breaks),
    }


def _formula_cache_cells(cached, name, addresses):
    if cached is None or not addresses:
        return {}
    return {
        cell.coordinate: (cell.value, cell.data_type)
        for cell in iter_present_cells(cached[name])
        if getattr(cell, "coordinate", None) in addresses
    }


def build_workbook_facts(
    body: bytes,
    *,
    source_name: str,
    authorization_scope: str,
    formula_evidence: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    document: dict[str, Any] = dict(
        new_document(
            make_source_ref(
                source_sha256=hashlib.sha256(body).hexdigest(),
                source_format="xlsm" if source_name.lower().endswith(".xlsm") else "xlsx",
                parser="openpyxl",
                parser_version=openpyxl.__version__,
                authorization_scope=authorization_scope,
            )
        )
    )
    document_id = document["document_id"]
    document["byte_size"] = len(body)
    workbook = openpyxl.load_workbook(
        BytesIO(body), data_only=False, keep_links=False, rich_text=True
    )
    cached = None
    try:
        formula_addresses: dict[str, set[str]] = {}
        for name, address in formula_evidence:
            formula_addresses.setdefault(name, set()).add(address)
        for sheet in workbook.worksheets:
            for cell in sheet._cells.values():
                if cell.data_type == "f":
                    formula_addresses.setdefault(sheet.title, set()).add(cell.coordinate)
        # No second materialized workbook. Read caches only when formulas exist,
        # using the same pinned native parser without rectangular gap filling.
        if formula_addresses:
            cached = openpyxl.load_workbook(
                BytesIO(body), read_only=True, data_only=True, keep_links=False, rich_text=True
            )
        document["native_objects"] = {
            "defined_names": [
                {"name": name.name, "xml": _xml(name)} for name in workbook.defined_names.values()
            ],
            "date_epoch": workbook.epoch.isoformat(),
            "calculation_xml": _xml(workbook.calculation),
            "visual_context": workbook_visual_context(workbook),
        }
        with ZipFile(BytesIO(body)) as archive:
            parts = worksheet_parts(archive)
            document["native_parts"] = [
                {"path": item.filename, "size": item.file_size} for item in archive.infolist()
            ]
            for name in workbook.sheetnames:
                sheet = workbook[name]
                part = parts.get(name)
                if not hasattr(sheet, "_cells") or part is None:
                    document["sheets"].append(
                        {
                            "sheet_id": location_id(document_id, "sheet", name),
                            "sheet": name,
                            "sheet_state": sheet.sheet_state,
                            "status": "unsupported",
                            "cells": [],
                            "native_part": part,
                        }
                    )
                    document["status"] = "partial"
                    document["warnings"].append(
                        {"code": "non_worksheet_source_only", "sheet": name}
                    )
                    continue
                # Geometry/style facts are complete without eagerly retaining a
                # second graph of inference candidates for every read-only page.
                visual = worksheet_visual_facts(sheet, include_neighbors=False)
                document["styles"].update(visual.pop("styles"))
                visual.pop("cells")
                cached_cells = _formula_cache_cells(
                    cached, name, formula_addresses.get(name, set())
                )
                cells = [
                    _cell_fact(
                        document_id,
                        sheet,
                        cached_cells,
                        address,
                        raw,
                        formula_evidence,
                        document["styles"],
                    )
                    for address, raw in _raw_cells(archive, part)
                ]
                cells.sort(key=lambda cell: (cell["row"], cell["column"]))
                if len({cell["address"] for cell in cells}) != len(cells):
                    raise ValueError("worksheet has duplicate native cell addresses")
                actual = [cell for cell in cells if cell["value_state"] != "blank"]
                content_range = None
                if actual:
                    content_range = f"{get_column_letter(min(cell['column'] for cell in actual))}{min(cell['row'] for cell in actual)}:{get_column_letter(max(cell['column'] for cell in actual))}{max(cell['row'] for cell in actual)}"
                visual.update(
                    {
                        "sheet_id": location_id(document_id, "sheet", name),
                        "cells": cells,
                        "native_part": part,
                        "native_objects": _native_objects(sheet),
                        "max_row": sheet.max_row,
                        "max_column": sheet.max_column,
                        "content_range": content_range,
                        "cell_count": len(cells),
                        "status": "partial"
                        if any(cell["value_state"] == "unknown" for cell in cells)
                        else "complete",
                    }
                )
                if visual["status"] == "partial":
                    document["status"] = "partial"
                    document["warnings"].append(
                        {"code": "native_values_require_source_readback", "sheet": name}
                    )
                document["sheets"].append(visual)
                for table in visual["native_objects"]["tables"]:
                    document["tables"].append(
                        {
                            "table_id": location_id(document_id, "table", name, table["name"]),
                            "source_ref": {
                                "document_id": document_id,
                                "sheet": name,
                                "range": table["range"],
                            },
                            "basis": "native_excel_table",
                            **table,
                        }
                    )
        document["capabilities"].update(
            {
                "raw_values": "supported",
                "native_styles": "supported",
                "rendered_values": "unsupported",
                "formula_cache_validity": "unknown",
                "formula_recalculation": "not_performed",
                "drawings_macros_external_links": "source_only_not_executed",
                "content_scope": "all_native_worksheet_cells",
            }
        )
        return document
    finally:
        workbook.close()
        if cached is not None:
            cached.close()
