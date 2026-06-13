from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_ROW_CAP = 500
MAX_COL_CAP = 100


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


def _sheet_to_dict(ws, formula_ws=None) -> Dict[str, Any]:
    max_row = int(ws.max_row or 0)
    max_col = int(ws.max_column or 0)
    cap_row = min(max_row, MAX_ROW_CAP)
    cap_col = min(max_col, MAX_COL_CAP)
    truncated = max_row > cap_row or max_col > cap_col

    cells: List[Dict[str, Any]] = []
    for r in range(1, cap_row + 1):
        for c in range(1, cap_col + 1):
            cell = ws.cell(r, c)
            if cell.value is None and (formula_ws is None or formula_ws.cell(r, c).value is None):
                continue
            cells.append(_cell_payload(ws, r, c, formula_ws=formula_ws))

    headers: List[Dict[str, Any]] = []
    if cap_row >= 1:
        for c in range(1, cap_col + 1):
            v = ws.cell(1, c).value
            if v is not None and str(v).strip():
                headers.append(_cell_payload(ws, 1, c, formula_ws=formula_ws))

    header_names = [str(h.get("display") or h.get("value") or "").strip() for h in headers]
    header_names = [n for n in header_names if n]

    rows_out: List[Dict[str, Any]] = []
    for r in range(2, cap_row + 1):
        row_cells: Dict[str, Any] = {}
        has_data = False
        for c in range(1, cap_col + 1):
            v = ws.cell(r, c).value
            if v is not None and str(v).strip() != "":
                has_data = True
            key = header_names[c - 1] if c - 1 < len(header_names) else f"col_{c}"
            row_cells[key] = v
        if has_data:
            rows_out.append({"row_index": r, "cells": row_cells})

    return {
        "name": ws.title,
        "max_row": max_row,
        "max_column": max_col,
        "truncated": truncated,
        "headers": headers,
        "rows": rows_out,
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
            sheets.append(_sheet_to_dict(ws, fws))
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
            "max_row_cap": MAX_ROW_CAP,
            "max_col_cap": MAX_COL_CAP,
        },
    }
    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    total_cells = sum(int(s.get("cell_count") or 0) for s in sheets)
    return {
        "output_path": str(json_path),
        "sheet_count": len(sheets),
        "cell_count": total_cells,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }