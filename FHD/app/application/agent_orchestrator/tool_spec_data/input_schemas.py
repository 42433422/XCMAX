"""Input schemas for special tool/domain/action combinations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]
_SCHEMA_PATH = Path(__file__).with_name("input_schemas.json")


def _load_special_input_schemas() -> dict[tuple[str, str], dict[str, Any]]:
    """Load special input schemas from JSON and convert key strings to tuple keys."""
    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, schema in payload.items():
        domain, _, action = key.partition("|")
        if not action:
            raise ValueError(f"invalid schema key in input_schemas.json: {key!r}")
        result[(domain, action)] = schema
    return result


_SPECIAL_INPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = _load_special_input_schemas()
