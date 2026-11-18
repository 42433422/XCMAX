"""Tool-schema inputs shared by clarification discovery and durable answers."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, ValidationError, validators
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012


def _required_values(validator, required, instance, schema):
    if isinstance(instance, dict):
        for key in required:
            value = instance.get(key)
            if value is None or isinstance(value, str) and not value.strip():
                yield ValidationError(f"Missing input: {key}", path=[key])


def _dependent_inputs(validator, dependencies, instance, schema):
    if isinstance(instance, dict):
        for key, required in dependencies.items():
            if key in instance:
                yield from validator.descend(instance, {"required": required})


_INPUT_VALIDATOR = validators.extend(
    Draft202012Validator,
    {"required": _required_values, "dependentRequired": _dependent_inputs},
)


def action_input_metadata(
    tool_id: str, action: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.services.tools_execution.registry import get_workflow_tool_registry

    spec = get_tool_action_spec(tool_id, action)
    registered = (
        get_workflow_tool_registry().get(tool_id, {}).get("actions", {}).get(action, {})
        if metadata is None
        else {}
    )
    return {**(spec.to_dict() if spec is not None else {}), **registered, **(metadata or {})}


def input_field_schema(schema: dict[str, Any], field: str) -> dict[str, Any]:
    """Resolve an object/array field with the same local refs as JSON Schema."""
    resolver = Registry().resolver_with_root(DRAFT202012.create_resource(schema))
    current: Any = schema
    for part in [*field.split("."), None]:
        seen: set[str] = set()
        while isinstance(current, dict) and "$ref" in current:
            reference = current["$ref"]
            if not isinstance(reference, str) or reference in seen:
                return {}
            seen.add(reference)
            try:
                resolved = resolver.lookup(reference)
            except Unresolvable:
                return {}
            current, resolver = resolved.contents, resolved.resolver
        if not isinstance(current, dict):
            return {}
        if part is None:
            return current
        properties = current.get("properties") or {}
        current = properties.get(part, current.get("items", {}) if part.isdigit() else {})
    return {}


def _missing_errors(error):
    if error.validator == "required":
        yield ".".join(str(part) for part in error.absolute_path)
    for child in error.context:
        yield from _missing_errors(child)


def missing_tool_fields(
    tool_id: str,
    action: str,
    params: dict[str, Any],
    action_meta: dict[str, Any] | None = None,
) -> list[str]:
    """Use registered schemas; retain domain checks for accepted input aliases."""
    if (tool_id, action) == ("inventory", "stock_in"):
        from app.domain.app_pure.inventory_inputs import missing_stock_in_fields

        return missing_stock_in_fields(params)
    if tool_id == "sales" and action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import missing_quote_fields

        return missing_quote_fields(params)
    from app.application.shipment_inputs import missing_shipment_call_fields, shipment_call_payload

    if shipment_call_payload(tool_id, action, params) is not None:
        return missing_shipment_call_fields(tool_id, action, params)
    action_meta = action_input_metadata(tool_id, action, action_meta)
    schema = action_meta.get("input_schema") or {}
    required = action_meta.get("required_params") or []
    missing = [
        key
        for key in required
        if params.get(key) in (None, "", [])
        or isinstance(params.get(key), str)
        and not params[key].strip()
    ]
    try:
        for error in _INPUT_VALIDATOR(schema, registry=Registry()).iter_errors(params):
            missing.extend(_missing_errors(error))
    except Unresolvable as exc:
        raise ValueError("工具输入契约包含不可解析的引用") from exc
    for group in action_meta.get("required_any") or []:
        if all(
            params.get(key) in (None, "", [])
            or isinstance(params.get(key), str)
            and not params[key].strip()
            for key in group
        ):
            missing.extend(group)
    # These roots are supplied by the execution context, never by user answers.
    return list(dict.fromkeys(key for key in missing if key not in {"user_id", "tenant_id"}))


def apply_input_fields(params: dict[str, Any], answers: dict[str, Any]) -> None:
    """Patch allowlisted fields only inside existing object/array containers."""
    for field, value in answers.items():
        path = field.split(".")
        parent: Any = params
        for part in path[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if not isinstance(parent, dict):
            raise ValueError("澄清字段的对象结构已变化")
        parent[path[-1]] = value
