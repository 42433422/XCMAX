"""Read editable metadata while tolerating older file-backed template rows."""

from __future__ import annotations

import json
from typing import Any


def _stored_json(raw: Any, expected_type: type, fallback: Any) -> Any:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return fallback
    return raw if isinstance(raw, expected_type) else fallback


def read_stored_template_metadata(row: Any) -> dict[str, Any]:
    analyzed = _stored_json(getattr(row, "analyzed_data", None), dict, {})
    rules = _stored_json(getattr(row, "business_rules", None), dict, {})
    fields = analyzed.get("fields")
    if not isinstance(fields, list):
        fields = _stored_json(getattr(row, "editable_config", None), list, [])
    preview = analyzed.get("preview_data")
    metadata = {"fields": fields, "preview_data": preview if isinstance(preview, dict) else {}}
    category = analyzed.get("category")
    if category in ("excel", "word", "pptx", "pdf", "label"):
        metadata["category"] = category
    scope = rules.get("business_scope") or analyzed.get("business_scope")
    if scope:
        metadata["business_scope"] = scope
    return metadata
