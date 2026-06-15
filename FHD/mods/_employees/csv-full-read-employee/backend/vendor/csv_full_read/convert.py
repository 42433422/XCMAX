from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


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
    if suffix != ".csv":
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .csv")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".json"):
        json_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    raw_bytes = src_path.read_bytes()
    text, encoding = _decode_bytes(raw_bytes)
    delimiter = _sniff_delimiter(text)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows: List[Dict[str, Any]] = [dict(r) for r in reader]
    columns = list(reader.fieldnames or [])
    if not columns and rows:
        columns = list(rows[0].keys())

    payload_data: Dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "meta": {
            "source": src_path.name,
            "delimiter": delimiter,
            "encoding": encoding,
            "byte_size": len(raw_bytes),
        },
    }
    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(json_path),
        "row_count": len(rows),
        "column_count": len(columns),
        "delimiter": delimiter,
        "encoding": encoding,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }