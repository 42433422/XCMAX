from __future__ import annotations

import json
from pathlib import Path
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


def _row_values(ws, row: int, cap_col: int) -> List[Any]:
    return [ws.cell(row, col).value for col in range(1, cap_col + 1)]


def _nonempty(values: List[Any]) -> int:
    return sum(1 for v in values if _display(v))


def _dedupe_columns(names: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for idx, raw in enumerate(names, start=1):
        base = raw.strip() if raw and raw.strip() else f"col_{idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out


def _detect_header_row(ws, cap_row: int, cap_col: int, *, payload: Dict[str, Any]) -> int:
    explicit = _int_payload(payload, "header_row", 0)
    if explicit > 0:
        return min(explicit, cap_row or explicit)
    if cap_row <= 0 or cap_col <= 0:
        return 1

    scan_rows = min(cap_row, _int_payload(payload, "header_scan_rows", HEADER_SCAN_ROWS))
    best_row = 1
    best_score = -1
    for row in range(1, scan_rows + 1):
        values = [_display(v) for v in _row_values(ws, row, cap_col)]
        filled = _nonempty(values)
        if filled <= 0:
            continue
        next_filled = (
            _nonempty([_display(v) for v in _row_values(ws, row + 1, cap_col)])
            if row < cap_row
            else 0
        )
        keyword_hits = sum(1 for v in values if any(k in v for k in HEADER_KEYWORDS))
        title_penalty = 8 if filled <= 1 and next_filled > filled else 0
        score = filled * 3 + keyword_hits * 6 + min(next_filled, filled) - title_penalty
        if score > best_score:
            best_row = row
            best_score = score
    return best_row


def _cell_payload(ws, row: int, col: int, *, formula_ws=None) -> Dict[str, Any]:
    from openpyxl.utils import get_column_letter

    cell = ws.cell(row, col)
    letter = get_column_letter(col)
    raw = cell.value
    display = "" if raw is None else str(raw)
    formula = None
    if formula_ws is not None:
        fcell = formula_ws.cell(row, col)
        if isinstance(fcell.value, str) and fcell.value.startswith("="):
            formula = fcell.value
    data_type = getattr(cell, "data_type", None)
    return {
        "row": row,
        "col": col,
        "letter": letter,
        "value": raw,
        "display": display,
        "formula": formula,
        "data_type": str(data_type) if data_type is not None else None,
    }


def _sheet_to_dict(ws, formula_ws=None, *, payload: Dict[str, Any]) -> Dict[str, Any]:
    max_row = int(ws.max_row or 0)
    max_col = int(ws.max_column or 0)
    row_cap = _int_payload(payload, "max_row_cap", DEFAULT_MAX_ROW_CAP)
    col_cap = _int_payload(payload, "max_col_cap", DEFAULT_MAX_COL_CAP)
    cap_row = _apply_cap(max_row, row_cap)
    cap_col = _apply_cap(max_col, col_cap)
    truncated = max_row > cap_row or max_col > cap_col

    cells: List[Dict[str, Any]] = []
    for r in range(1, cap_row + 1):
        for c in range(1, cap_col + 1):
            cell = ws.cell(r, c)
            if cell.value is None and (formula_ws is None or formula_ws.cell(r, c).value is None):
                continue
            cells.append(_cell_payload(ws, r, c, formula_ws=formula_ws))

    header_row = _detect_header_row(ws, cap_row, cap_col, payload=payload)
    data_start_row = min(header_row + 1, cap_row + 1)

    headers: List[Dict[str, Any]] = []
    if cap_row >= 1 and header_row <= cap_row:
        for c in range(1, cap_col + 1):
            v = ws.cell(header_row, c).value
            if v is not None and str(v).strip():
                headers.append(_cell_payload(ws, header_row, c, formula_ws=formula_ws))

    raw_columns = (
        [_display(v) for v in _row_values(ws, header_row, cap_col)] if header_row <= cap_row else []
    )
    columns = _dedupe_columns(raw_columns)

    rows_out: List[Dict[str, Any]] = []
    row_records: List[Dict[str, Any]] = []
    for r in range(data_start_row, cap_row + 1):
        flat_row: Dict[str, Any] = {}
        rich_cells: Dict[str, Any] = {}
        has_data = False
        for c in range(1, cap_col + 1):
            v = ws.cell(r, c).value
            if v is not None and str(v).strip() != "":
                has_data = True
            key = columns[c - 1] if c - 1 < len(columns) else f"col_{c}"
            flat_row[key] = v
            rich_cells[key] = v
        if has_data:
            rows_out.append(flat_row)
            row_records.append({"row_index": r, "cells": rich_cells})

    return {
        "name": ws.title,
        "max_row": max_row,
        "max_column": max_col,
        "truncated": truncated,
        "header_row": header_row,
        "data_start_row": data_start_row,
        "columns": columns,
        "headers": headers,
        "rows": rows_out,
        "row_records": row_records,
        "cells": cells,
        "cell_count": len(cells),
        "row_count": len(rows_out),
    }


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

    from openpyxl import load_workbook

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "workbook.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".json"):
        json_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    wb_val = load_workbook(src_path, read_only=False, data_only=True)
    wb_formula = load_workbook(src_path, read_only=False, data_only=False)
    sheets: List[Dict[str, Any]] = []
    try:
        for ws in wb_val.worksheets:
            fws = wb_formula[ws.title] if ws.title in wb_formula.sheetnames else None
            sheets.append(_sheet_to_dict(ws, fws, payload=payload or {}))
    finally:
        wb_val.close()
        wb_formula.close()

    payload_data: Dict[str, Any] = {
        "source": src_path.name,
        "sheet_count": len(sheets),
        "sheets": sheets,
        "meta": {
            "source": src_path.name,
            "byte_size": src_path.stat().st_size,
            "max_row_cap": _int_payload(payload or {}, "max_row_cap", DEFAULT_MAX_ROW_CAP),
            "max_col_cap": _int_payload(payload or {}, "max_col_cap", DEFAULT_MAX_COL_CAP),
            "cap_semantics": "0 means unlimited",
        },
    }
    json_path.write_text(
        json.dumps(payload_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    total_cells = sum(int(s.get("cell_count") or 0) for s in sheets)
    return {
        "output_path": str(json_path),
        "sheet_count": len(sheets),
        "cell_count": total_cells,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
