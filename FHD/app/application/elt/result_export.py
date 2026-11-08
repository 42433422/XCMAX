"""Excel result built from committed row values, never from the upload bytes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_NUMERIC_TYPES = {"money", "number", "integer"}


def infer_column_type(label: str) -> str:
    text = str(label or "")
    if any(word in text for word in ("金额", "单价", "价格", "amount", "price")):
        return "money"
    if any(word in text for word in ("数量", "桶数", "quantity")):
        return "number"
    if "日期" in text or text.casefold().endswith("date"):
        return "date"
    return "text"


def export_context(
    draft: dict[str, Any], adapter: Any, features: dict[str, Any], sheet_name: str
) -> dict[str, Any]:
    """Column order follows the confirmed mapping; labels follow the business template."""
    fields = {field.key: field for field in getattr(adapter, "fields", ()) or ()}
    columns: list[dict[str, str]] = []
    for item in draft.get("field_mappings") or []:
        key = str(item.get("target") or "")
        if not key:
            continue
        field = fields.get(key)
        label = str(item.get("label") or item.get("source") or getattr(field, "label", "") or key)
        kind = infer_column_type(label)
        field_type = str(getattr(field, "type", "") or "")
        if field_type == "date":
            kind = "date"
        elif field_type == "integer":
            kind = "integer"
        elif field_type == "number" and kind == "text":
            kind = "number"
        columns.append({"key": key, "label": label, "type": kind})
    name = str(features.get("sheet_name") or "")
    sheets = features.get("sheets") or []
    if not name and sheets:
        name = str((sheets[0] or {}).get("name") or "")
    notes = [str(item) for item in features.get("business_notes") or [] if str(item)]
    return {
        "export_template": {"sheet_name": name or sheet_name or "业务结果", "columns": columns},
        "export_notes": notes,
    }


def columns_for_export(
    context: dict[str, Any], sample: dict[str, Any] | None
) -> list[dict[str, str]]:
    template = context.get("export_template") or {}
    supplied = template.get("columns") or []
    if supplied:
        return [
            {
                "key": str(item.get("key") or ""),
                "label": str(item.get("label") or item.get("key") or ""),
                "type": str(item.get("type") or infer_column_type(str(item.get("label") or ""))),
            }
            for item in supplied
            if str(item.get("key") or "")
        ]
    headers = list(context.get("output_headers") or (list(sample or {})))
    return [
        {"key": str(key), "label": str(key), "type": infer_column_type(str(key))} for key in headers
    ]


def snapshot_sha256(columns: list[dict[str, str]], rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = {column["key"]: row.get(column["key"]) for column in columns}
        digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _sheet_title(name: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", str(name or "").strip())[:31]
    return cleaned or "业务结果"


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        match = _DATE_PREFIX.match(text)
        if match and (len(text) == 10 or "T" in text):
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, str):
        # Normalized JSON stores decimal transforms as strings, not JSON floats.
        text = value.strip()
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text):
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        value = float(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _put_text(cell: Any, value: Any) -> None:
    text = "" if value is None else str(value)
    if text[:1] in _FORMULA_PREFIXES:
        text = "'" + text
    cell.value = text
    if text[:1] in {"'", *_FORMULA_PREFIXES}:
        cell.data_type = "s"


def _put_value(cell: Any, value: Any, kind: str) -> None:
    if kind == "date":
        parsed = _as_date(value)
        if parsed is not None:
            cell.value = parsed
            cell.number_format = "YYYY-MM-DD"
            return
    if kind in _NUMERIC_TYPES:
        number = _as_number(value)
        if number is not None:
            if kind == "integer" or (kind == "number" and float(number).is_integer()):
                cell.value = int(number)
                cell.number_format = "#,##0"
            else:
                cell.value = float(number)
                cell.number_format = "#,##0.00"
            return
    _put_text(cell, value)


def write_xlsx_result(
    path: Path,
    *,
    columns: list[dict[str, str]],
    rows: list[dict[str, Any]],
    sheet_name: str,
    notes: list[str],
    progress: Any = None,
    total: int = 0,
) -> dict[str, Any]:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None  # A new Workbook always creates its default sheet.
    worksheet.title = _sheet_title(sheet_name)
    for index, column in enumerate(columns, start=1):
        cell = worksheet.cell(1, index, column["label"])
        cell.font = Font(bold=True)
    for executed, row in enumerate(rows, start=1):
        for index, column in enumerate(columns, start=1):
            _put_value(worksheet.cell(executed + 1, index), row.get(column["key"]), column["type"])
        if executed % 500 == 0 and callable(progress):
            progress(executed, total)
    executed = len(rows)
    numeric = [
        index for index, column in enumerate(columns, start=1) if column["type"] in _NUMERIC_TYPES
    ]
    note_row = executed + 3
    if executed and numeric:
        total_row = executed + 2
        labeled = False
        for index, column in enumerate(columns, start=1):
            if column["type"] in _NUMERIC_TYPES:
                letter = get_column_letter(index)
                cell = worksheet.cell(total_row, index, f"=SUM({letter}2:{letter}{executed + 1})")
                cell.number_format = "#,##0.00" if column["type"] == "money" else "#,##0"
            elif not labeled:
                worksheet.cell(total_row, index, "合计")
                labeled = True
        note_row = total_row + 2
    for note in notes:
        cell = worksheet.cell(note_row, 1, note)
        cell.data_type = "s"
        note_row += 1
    title = worksheet.title
    workbook.save(path)
    workbook.close()
    if callable(progress):
        progress(executed, total)
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "file_name": path.name,
        "download_url": "",
        "sha256": file_hash,
        "snapshot_sha256": snapshot_sha256(columns, rows),
        "sheet_name": title,
        "headers": [column["label"] for column in columns],
        "data_rows": executed,
        "reversible": False,
    }
