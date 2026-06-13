from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.office_plaintext_generate import resolve_table_spec


def _normalize_sheets(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    sheets_in = table.get("sheets")
    if isinstance(sheets_in, list) and sheets_in:
        out: List[Dict[str, Any]] = []
        for idx, sh in enumerate(sheets_in):
            if not isinstance(sh, dict):
                continue
            name = str(sh.get("name") or f"Sheet{idx + 1}")
            columns = [str(c) for c in (sh.get("columns") or []) if str(c).strip()]
            rows_in = sh.get("rows")
            if not isinstance(rows_in, list):
                rows_in = []
            if not columns and rows_in and isinstance(rows_in[0], dict):
                columns = [str(k) for k in rows_in[0].keys()]
            out.append({"name": name, "columns": columns, "rows": rows_in})
        if out:
            return out
    columns = [str(c) for c in (table.get("columns") or []) if str(c).strip()]
    rows_in = table.get("rows")
    if not isinstance(rows_in, list):
        rows_in = []
    if not columns and rows_in and isinstance(rows_in[0], dict):
        columns = [str(k) for k in rows_in[0].keys()]
    return [{"name": str(table.get("sheet") or table.get("sheet_name") or "Sheet1"), "columns": columns, "rows": rows_in}]


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from openpyxl import Workbook

    table, _warnings = await resolve_table_spec(src_path, payload or {}, ctx or {}, rule_spec or {}, fmt="excel")
    sheets = _normalize_sheets(table)

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_dir / "output.xlsx"
    if output_path.suffix.lower() in {".xlsx", ".xlsm"}:
        xlsx_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".xlsx"):
        xlsx_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    wb = Workbook()
    first = True
    total_rows = 0
    for sh in sheets:
        name = str(sh.get("name") or "Sheet1")
        columns = list(sh.get("columns") or [])
        rows_in = sh.get("rows") if isinstance(sh.get("rows"), list) else []
        if first:
            ws = wb.active
            ws.title = name[:31]
            first = False
        else:
            ws = wb.create_sheet(title=name[:31])
        for col_idx, header in enumerate(columns, 1):
            ws.cell(1, col_idx, header)
        for row_idx, row in enumerate(rows_in, 2):
            if not isinstance(row, dict):
                continue
            for col_idx, header in enumerate(columns, 1):
                ws.cell(row_idx, col_idx, row.get(header, ""))
            total_rows += 1
    wb.save(xlsx_path)
    wb.close()

    return {
        "output_path": str(xlsx_path),
        "sheet_count": len(sheets),
        "row_count": total_rows,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }