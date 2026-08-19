from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.mod_sdk.host_services import (
        resolve_table_spec as _shared_resolve_table_spec,
    )
except Exception:  # noqa: BLE001 - employee packs must remain self-contained outside MODstore.
    _shared_resolve_table_spec = None


def _load_json_file(src_path: Path) -> Dict[str, Any]:
    data = json.loads(src_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须是对象")
    return data


def _stringify_cell_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _row_to_flat_dict(row: Any) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    cells = row.get("cells")
    if isinstance(cells, dict):
        return dict(cells)
    return dict(row)


def _header_to_name(header: Any, idx: int) -> str:
    if isinstance(header, dict):
        raw = header.get("display") or header.get("value") or header.get("letter")
    else:
        raw = header
    text = str(raw or "").strip()
    return text or f"col_{idx}"


def _dedupe_columns(columns: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for idx, raw in enumerate(columns, start=1):
        base = str(raw or "").strip() or f"col_{idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out


def _coerce_sheet(sheet: Dict[str, Any], idx: int) -> Dict[str, Any]:
    name = str(
        sheet.get("name") or sheet.get("sheet") or sheet.get("sheet_name") or f"Sheet{idx + 1}"
    )
    raw_rows = sheet.get("rows")
    if not isinstance(raw_rows, list):
        raw_rows = sheet.get("row_records") if isinstance(sheet.get("row_records"), list) else []
    rows = [_row_to_flat_dict(row) for row in raw_rows]
    rows = [row for row in rows if row]

    columns = [str(c) for c in (sheet.get("columns") or []) if str(c).strip()]
    if not columns:
        headers = sheet.get("headers")
        if isinstance(headers, list) and headers:
            columns = [_header_to_name(h, i) for i, h in enumerate(headers, start=1)]
    if not columns and rows:
        ordered: List[str] = []
        seen = set()
        for row in rows:
            for key in row.keys():
                text = str(key)
                if text not in seen:
                    ordered.append(text)
                    seen.add(text)
        columns = ordered
    columns = _dedupe_columns(columns)
    return {"name": name, "columns": columns, "rows": rows}


def _is_table_structured(data: Dict[str, Any]) -> bool:
    if isinstance(data.get("sheets"), list) and data["sheets"]:
        return True
    return isinstance(data.get("columns"), list) and isinstance(data.get("rows"), list)


def _coerce_json_to_table(data: Dict[str, Any]) -> Dict[str, Any]:
    nested = data.get("table_json") or data.get("workbook") or data.get("document_full")
    if isinstance(nested, dict) and _is_table_structured(nested):
        data = nested

    sheets = data.get("sheets")
    if isinstance(sheets, list) and sheets:
        return {
            "sheets": [_coerce_sheet(sh, i) for i, sh in enumerate(sheets) if isinstance(sh, dict)]
        }

    columns = [str(c) for c in (data.get("columns") or []) if str(c).strip()]
    rows_in = data.get("rows")
    rows = [_row_to_flat_dict(row) for row in rows_in] if isinstance(rows_in, list) else []
    if not columns and rows:
        columns = list(rows[0].keys())
    return {
        "columns": _dedupe_columns(columns),
        "rows": rows,
        "sheets": [
            {
                "name": str(data.get("sheet") or data.get("sheet_name") or "Sheet1"),
                "columns": _dedupe_columns(columns),
                "rows": rows,
            }
        ],
    }


def _table_from_text(text: str) -> Dict[str, Any]:
    import csv
    import io

    lines = [ln for ln in str(text or "").splitlines() if ln.strip()]
    if not lines:
        return {
            "columns": ["内容"],
            "rows": [],
            "sheets": [{"name": "Sheet1", "columns": ["内容"], "rows": []}],
        }
    sample = lines[0]
    if "," in sample:
        rows_raw = list(csv.reader(io.StringIO("\n".join(lines))))
        columns = _dedupe_columns(
            [str(c).strip() or f"列{i + 1}" for i, c in enumerate(rows_raw[0])]
        )
        rows = [
            {columns[i]: (raw[i] if i < len(raw) else "") for i in range(len(columns))}
            for raw in rows_raw[1:]
        ]
        return {
            "columns": columns,
            "rows": rows,
            "sheets": [{"name": "Sheet1", "columns": columns, "rows": rows}],
        }
    if "\t" in sample:
        rows_raw = [ln.split("\t") for ln in lines]
        columns = [f"列{i + 1}" for i in range(len(rows_raw[0]))]
        rows = [
            {columns[i]: (raw[i] if i < len(raw) else "") for i in range(len(columns))}
            for raw in rows_raw
        ]
        return {
            "columns": columns,
            "rows": rows,
            "sheets": [{"name": "Sheet1", "columns": columns, "rows": rows}],
        }
    rows = [{"内容": ln.strip()} for ln in lines]
    return {
        "columns": ["内容"],
        "rows": rows,
        "sheets": [{"name": "Sheet1", "columns": ["内容"], "rows": rows}],
    }


async def _resolve_table_spec(
    src_path: Path,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    if isinstance((payload or {}).get("table_json"), dict):
        return _coerce_json_to_table(payload["table_json"]), []

    suffix = src_path.suffix.lower()
    if suffix == ".json" and src_path.is_file():
        return _coerce_json_to_table(_load_json_file(src_path)), []

    if _shared_resolve_table_spec is not None:
        return await _shared_resolve_table_spec(
            src_path,
            payload or {},
            ctx or {},
            rule_spec or {},
            fmt="excel",
        )

    if suffix == ".txt" and src_path.is_file():
        return _table_from_text(src_path.read_text(encoding="utf-8", errors="replace")), []

    text = str((payload or {}).get("user_query") or (payload or {}).get("plain_text") or "").strip()
    if text:
        return _table_from_text(text), []

    raise ValueError("缺少可生成内容：请上传规范 JSON/TXT，或在 payload.table_json 中提供表格结构")


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
    return [
        {
            "name": str(table.get("sheet") or table.get("sheet_name") or "Sheet1"),
            "columns": columns,
            "rows": rows_in,
        }
    ]


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

    table, _warnings = await _resolve_table_spec(
        src_path, payload or {}, ctx or {}, rule_spec or {}
    )
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
                ws.cell(row_idx, col_idx, _stringify_cell_value(row.get(header, "")))
            total_rows += 1
    wb.save(xlsx_path)
    wb.close()

    return {
        "output_path": str(xlsx_path),
        "sheet_count": len(sheets),
        "row_count": total_rows,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
