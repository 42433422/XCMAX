"""Validate one missing schema-defined field before resuming a clarified operation."""

from __future__ import annotations

import json
from typing import Any

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call

from .types import WorkflowNode


def resolve_missing_field(
    node: WorkflowNode, item: dict[str, Any], text: str
) -> dict[str, Any] | None:
    if item.get("reason") != "missing_required" or node.tool_id == "business_db":
        return None
    missing = item.get("missing_fields")
    if not isinstance(missing, list) or not missing or missing[0] != item.get("field"):
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
    if kind == "string" and isinstance(schema.get("enum"), list):
        from .clarification_options import field_options

        value = field_options(node.tool_id, node.action, field).get(value, value)
    if kind in ("integer", "number", "boolean", "array", "object"):
        try:
            value = json.loads(value)
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError):
            return None
    elif kind != "string":
        return None
    params = {**node.params, field: value}
    if len(missing) == 1:
        if not validate_tool_call(node.tool_id, node.action, params).ok:
            return None
    else:
        from app.application.agent_orchestrator.tool_schema_validation import (
            _validate_schema_payload,
        )

        valid, _ = _validate_schema_payload(
            {"type": "object", "required": [field], "properties": {field: schema}},
            {field: value},
            subject="澄清回答",
        )
        if not valid:
            return None
    return {field: value}
