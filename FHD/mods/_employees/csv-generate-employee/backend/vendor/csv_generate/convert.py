from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.office_plaintext_generate import resolve_table_spec


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    table, _warnings = await resolve_table_spec(src_path, payload or {}, ctx or {}, rule_spec or {}, fmt="csv")
    columns = [str(c) for c in (table.get("columns") or []) if str(c).strip()]
    rows_in = table.get("rows")
    if not isinstance(rows_in, list):
        raise ValueError("JSON 缺少 rows 数组")
    if not columns and rows_in and isinstance(rows_in[0], dict):
        columns = [str(k) for k in rows_in[0].keys()]

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "output.csv"
    if output_path.suffix.lower() == ".csv":
        csv_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".csv"):
        csv_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    delimiter = str((table.get("meta") or {}).get("delimiter") or payload.get("delimiter") or ",")
    encoding = "utf-8-sig"
    with csv_path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=delimiter)
        writer.writeheader()
        for row in rows_in:
            if isinstance(row, dict):
                writer.writerow({k: row.get(k, "") for k in columns})

    return {
        "output_path": str(csv_path),
        "row_count": len(rows_in),
        "column_count": len(columns),
        "delimiter": delimiter,
        "encoding": encoding,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }