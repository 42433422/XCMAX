"""Output schemas for special tool/domain/action combinations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).with_name("output_schemas.json")

# 去掉 JSON 尾随逗号（JSON5 风格兼容，标准 json.loads 不允许）
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["success"],
    "properties": {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {},
    },
}


def _load_special_output_schemas() -> dict[tuple[str, str], dict[str, Any]]:
    raw = _SCHEMA_PATH.read_text(encoding="utf-8")
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", raw)
    payload = json.loads(cleaned)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, schema in payload.items():
        domain, _, action = key.partition("|")
        if not action:
            raise ValueError(f"invalid schema key in output_schemas.json: {key!r}")
        result[(domain, action)] = schema
    return result


_SPECIAL_OUTPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = _load_special_output_schemas()
