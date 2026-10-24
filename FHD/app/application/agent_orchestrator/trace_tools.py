"""Normalize observed tool records and admit only validated, idempotent reads."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .trace_payloads import _iter_payload_dicts

_LEGACY_EXECUTE_READ_DEFAULTS = {
    "business_db": ("read",),
    "customers": ("query",),
    "materials": ("query",),
    "products": ("query",),
    "shipment_records": ("query",),
}


def _iter_tool_call_payloads(
    payload: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("toolCall", "tool_call", "tool_call_payload"):
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate
        auto_action = item.get("autoAction") or item.get("auto_action")
        if isinstance(auto_action, dict) and auto_action.get("type") == "tool_call":
            yield auto_action
        if item.get("action") == "tool_call" and (item.get("tool_key") or item.get("tool_id")):
            yield item


def _candidate_tool_actions(tool_id: str, raw_action: Any, params: dict[str, Any]) -> list[str]:
    actions: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in actions:
            actions.append(text)

    add(raw_action)
    nested_action = params.get("action")
    if nested_action:
        add(nested_action)
        return actions
    raw = str(raw_action or "").strip().lower()
    if not raw or raw in {"执行", "execute", "exec", "run", "view"}:
        for fallback in _LEGACY_EXECUTE_READ_DEFAULTS.get(tool_id, ()):
            add(fallback)
    return actions


def _extract_low_risk_tool_call(
    payload: dict[str, Any],
) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    for tool_call in _iter_tool_call_payloads(payload):
        tool_id = str(
            tool_call.get("tool_id") or tool_call.get("tool_key") or tool_call.get("name") or ""
        ).strip()
        if not tool_id:
            continue
        params = tool_call.get("params")
        if not isinstance(params, dict):
            params = {}
        for action in _candidate_tool_actions(tool_id, tool_call.get("action"), params):
            validation = validate_tool_call(tool_id, action, params)
            spec = validation.spec
            if not validation.ok or spec is None:
                continue
            if spec.risk != "low" or not spec.idempotent:
                continue
            return (spec.tool_id, spec.action, dict(params), dict(tool_call))
    return None


def _normalized_record_payload(
    record: dict[str, Any],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    tool_id = str(
        record.get("tool_id") or record.get("tool_name") or record.get("tool_key") or ""
    ).strip()
    action = str(record.get("action") or "").strip() or "execute"
    params = record.get("params")
    output = record.get("output")
    return (
        tool_id,
        action,
        dict(params) if isinstance(params, dict) else {},
        dict(output)
        if isinstance(output, dict)
        else {"success": False, "message": str(output or "")},
    )
