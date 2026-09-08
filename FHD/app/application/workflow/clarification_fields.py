"""Validate one missing scalar field before resuming a clarified operation."""

from __future__ import annotations

import json
import math
from typing import Any

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call

from .types import WorkflowNode


def resolve_missing_field(
    node: WorkflowNode, item: dict[str, Any], text: str
) -> dict[str, Any] | None:
    if item.get("reason") != "missing_required" or node.tool_id == "business_db":
        return None
    missing = item.get("missing_fields")
    if not isinstance(missing, list) or len(missing) != 1 or missing[0] != item.get("field"):
        return None
    field = missing[0]
    spec = get_tool_action_spec(node.tool_id, node.action)
    if spec is None or field not in spec.required_params:
        return None
    schema = spec.input_schema.get("properties", {}).get(field, {})
    kind = schema.get("type")
    value: Any = str(text or "").strip()
    if not value:
        return None
    if kind in ("integer", "number", "boolean"):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
    elif kind != "string":
        return None
    params = {**node.params, field: value}
    if not validate_tool_call(node.tool_id, node.action, params).ok:
        return None
    return {field: value}
