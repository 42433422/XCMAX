from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.mod_sdk.host_services import read_native_document
from app.mod_sdk.host_services import tabular_column_keys as column_keys


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
    if suffix not in {".csv", ".tsv"}:
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .csv/.tsv")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".json"):
        json_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    facts = read_native_document(src_path)
    if facts["status"] != "complete":
        raise ValueError(f"CSV 全量读取未完成：{facts['warnings']}")
    table = facts["tables"][0]
    records = {record["record"]: [] for record in table["records"]}
    for cell in table["cells"]:
        records[cell["source_ref"]["record"]].append(cell["value"])
    values = list(records.values())
    columns = values[0] if values else []
    keys = column_keys(columns, max((len(row) for row in values), default=0))
    rows = [
        {key: row[index] if index < len(row) else None for index, key in enumerate(keys)}
        for row in values[1:]
    ]
    delimiter, encoding = table["delimiter"], table["encoding"]

    payload_data: Dict[str, Any] = {
        "columns": columns,
        "column_keys": keys,
        "rows": rows,
        "document_facts": facts,
        "row_count": len(rows),
        "meta": {
            "source": src_path.name,
            "delimiter": delimiter,
            "encoding": encoding,
            "byte_size": src_path.stat().st_size,
            "source_ref": facts["source_ref"],
            "rows_are_compatibility_projection": True,
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
