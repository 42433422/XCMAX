"""Output schemas for special tool/domain/action combinations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).with_name("output_schemas.json")

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
    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, schema in payload.items():
        domain, _, action = key.partition("|")
        if not action:
            raise ValueError(f"invalid schema key in output_schemas.json: {key!r}")
        result[(domain, action)] = schema
    return result


_SPECIAL_OUTPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = _load_special_output_schemas()
