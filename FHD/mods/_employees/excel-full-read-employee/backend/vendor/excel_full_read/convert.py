from __future__ import annotations

import json
import os
from collections.abc import ItemsView, Iterator
from datetime import date, datetime, time, timedelta
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional

DEFAULT_MAX_ROW_CAP = 0
DEFAULT_MAX_COL_CAP = 0
HEADER_SCAN_ROWS = 30


HEADER_KEYWORDS = {
    "姓名",
    "员工",
    "日期",
    "考勤",
    "部门",
    "工号",
    "打卡",
    "时间",
    "金额",
    "数量",
    "单价",
    "规格",
    "型号",
}


def _int_payload(payload: Dict[str, Any], key: str, default: int) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _apply_cap(total: int, cap: int) -> int:
    return min(total, cap) if cap > 0 else total


def _display(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _dedupe_columns(names: List[str]) -> List[str]:
    from app.mod_sdk.host_services import tabular_column_keys

    return tabular_column_keys(
        [name.strip() for name in names], len(names), empty_prefix="col_", duplicate_separator="_"
    )


def _legacy_value(cell: Dict[str, Any]) -> Any:
    formula = cell.get("formula_attributes") is not None
    value = cell["cached_value"] if formula else cell["value"]
    kind = cell["cached_value_type"] if formula else cell["value_type"]
    # Preserve historical default=str rendering while canonical values retain
    # their explicit type and ISO representation.
    if value is not None and kind in {"datetime", "date", "time"}:
        return {"datetime": datetime, "date": date, "time": time}[kind].fromisoformat(value)
    if value is not None and kind == "duration_seconds":
        return timedelta(seconds=value)
    return value


def _detect_header_row(rows, cap_row: int, cap_col: int, *, payload: Dict[str, Any]) -> int:
    explicit = _int_payload(payload, "header_row", 0)
    if explicit > 0:
        return min(explicit, cap_row or explicit)
    scan_rows = min(cap_row, _int_payload(payload, "header_scan_rows", HEADER_SCAN_ROWS))
    best_row, best_score = 1, -1
    for row in sorted(number for number in rows if number <= scan_rows):
        values = [_display(_legacy_value(cell)) for cell in rows[row] if cell["column"] <= cap_col]
        filled = sum(bool(value) for value in values)
        if not filled:
            continue
        next_filled = sum(
            bool(_display(_legacy_value(cell)))
            for cell in rows.get(row + 1, ())
            if cell["column"] <= cap_col
        )
        keyword_hits = sum(any(keyword in value for keyword in HEADER_KEYWORDS) for value in values)
        title_penalty = 8 if filled <= 1 and next_filled > filled else 0
        score = filled * 3 + keyword_hits * 6 + min(next_filled, filled) - title_penalty
        if score > best_score:
            best_row, best_score = row, score
    return best_row


def _cell_payload(cell: Dict[str, Any]) -> Dict[str, Any]:
    from openpyxl.utils import get_column_letter

    raw = _legacy_value(cell)
    out = {
        "row": cell["row"],
        "col": cell["column"],
        "letter": get_column_letter(cell["column"]),
        "value": raw,
        "display": "" if raw is None else str(raw),
        "formula": cell.get("formula"),
        "data_type": cell.get("cached_data_type")
        if cell.get("formula_attributes") is not None
        else cell.get("data_type"),
        "source_ref": cell["source_ref"],
        "cache_state": cell["cache_state"],
    }
    number_format = cell.get("number_format")
    if number_format and number_format != "General":
        out["number_format"] = number_format
    return out


def _sheet_to_dict(sheet: Dict[str, Any], *, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Project records lazily; full native facts never inherit legacy caps."""
    max_row, max_col = int(sheet.get("max_row", 0)), int(sheet.get("max_column", 0))
    cap_row = _apply_cap(max_row, _int_payload(payload, "max_row_cap", DEFAULT_MAX_ROW_CAP))
    cap_col = _apply_cap(max_col, _int_payload(payload, "max_col_cap", DEFAULT_MAX_COL_CAP))
    rows = {}
    for cell in sheet["cells"]:
        if cell["row"] > cap_row or cell["column"] > cap_col:
            continue
        if cell["value_state"] == "blank" and not cell.get("formula"):
            continue
        rows.setdefault(cell["row"], []).append(cell)
    header_row = _detect_header_row(rows, cap_row, cap_col, payload=payload)
    data_start_row = min(header_row + 1, cap_row + 1)
    header_cells = {cell["column"]: cell for cell in rows.get(header_row, ())}
    columns = _dedupe_columns(
        [
            _display(_legacy_value(header_cells[col])) if col in header_cells else ""
            for col in range(1, cap_col + 1)
        ]
    )
    active_rows = [row for row in sorted(rows) if row >= data_start_row]
    # Only the compatibility projection may become sparse. This avoids a wide
    # sheet multiplying 100k actual records by 16k absent cells in JSON.
    sparse = len(active_rows) * cap_col > 250_000

    def row_values(row):
        flat = {} if sparse else dict.fromkeys(columns)
        for cell in rows[row]:
            flat[columns[cell["column"] - 1]] = _legacy_value(cell)
        return flat

    return {
        "name": sheet["sheet"],
        "sheet_state": sheet["sheet_state"],
        "max_row": max_row,
        "max_column": max_col,
        "truncated": max_row > cap_row or max_col > cap_col,
        "header_row": header_row,
        "header_source": "legacy_compatibility_fallback",
        "data_start_row": data_start_row,
        "columns": columns,
        "headers": [
            _cell_payload(cell)
            for cell in rows.get(header_row, ())
            if _display(_legacy_value(cell))
        ],
        "rows": (row_values(row) for row in active_rows),
        "row_records": ({"row_index": row, "cells": row_values(row)} for row in active_rows),
        "rows_representation": "sparse" if sparse else "dense_active_rows",
        "cells": (_cell_payload(cell) for cell in chain.from_iterable(rows.values())),
        "cell_count": sum(map(len, rows.values())),
        "row_count": len(active_rows),
        "merged_ranges": sheet.get("merges", []),
        "facts_sheet_id": sheet["sheet_id"],
    }


def _write_json(handle, value, encoder):
    """Stream explicit container views; stdlib C encoding handles each record.

    Only outer objects/arrays use views and iterators. Ordinary cell/row dicts
    retain JSONEncoder's escaping, type handling and non-finite-value checks.
    """
    if isinstance(value, ItemsView):
        handle.write("{")
        for index, (key, item) in enumerate(value):
            handle.write(("," if index else "") + encoder.encode(key) + ":")
            _write_json(handle, item, encoder)
        handle.write("}")
    elif isinstance(value, Iterator):
        handle.write("[")
        for index, item in enumerate(value):
            if index:
                handle.write(",")
            _write_json(handle, item, encoder)
        handle.write("]")
    else:
        handle.write(encoder.encode(value))


def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    suffix = src_path.suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .xlsx / .xlsm")

    from app.mod_sdk.host_services import read_workbook_facts

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "workbook.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".json"):
        json_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    scope_values = [str(ctx.get(key) or "") for key in ("tenant_id", "user_id", "mod_id")]
    scope = json.dumps(scope_values, separators=(",", ":")) if any(scope_values) else ""
    document = read_workbook_facts(src_path, authorization_scope=scope)
    summaries = []

    def legacy_sheets():
        for source_sheet in document["sheets"]:
            sheet = _sheet_to_dict(source_sheet, payload=payload or {})
            summaries.append((sheet["cell_count"], sheet["truncated"]))
            yield sheet.items()

    native_sheets = (
        {**sheet, "cells": iter(sheet["cells"])}.items() for sheet in document["sheets"]
    )

    payload_data: Dict[str, Any] = {
        "source": src_path.name,
        "document": {
            **document,
            "sheets": native_sheets,
            "styles": document["styles"].items(),
        }.items(),
        "sheet_count": len(document["sheets"]),
        "sheets": legacy_sheets(),
        "meta": {
            "source": src_path.name,
            "byte_size": document["byte_size"],
            "max_row_cap": _int_payload(payload or {}, "max_row_cap", DEFAULT_MAX_ROW_CAP),
            "max_col_cap": _int_payload(payload or {}, "max_col_cap", DEFAULT_MAX_COL_CAP),
            "cap_semantics": "0 means unlimited; caps apply only to legacy projection",
            "source_sha256": document["source_ref"]["source_sha256"],
            "facts_status": document["status"],
        },
    }
    # Follow the existing staged artifact publication pattern. Streaming avoids
    # another full-document string; errors leave the old verified file intact.
    with NamedTemporaryFile(
        dir=json_path.parent, prefix=".workbook-", suffix=".json", delete=False
    ) as staging:
        staged = Path(staging.name)
    try:
        with staged.open("w", encoding="utf-8") as handle:
            _write_json(
                handle,
                payload_data.items(),
                json.JSONEncoder(
                    ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False
                ),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, json_path)
    finally:
        staged.unlink(missing_ok=True)

    return {
        "output_path": str(json_path),
        "sheet_count": len(document["sheets"]),
        "cell_count": sum(count for count, _ in summaries),
        "document_id": document["document_id"],
        "source_sha256": document["source_ref"]["source_sha256"],
        "facts_status": document["status"],
        "legacy_projection_truncated": any(truncated for _, truncated in summaries),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
