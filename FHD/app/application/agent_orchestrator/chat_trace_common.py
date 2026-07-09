"""
Shared chat trace helpers (payload parsing, tool extraction).

Split from ``chat_trace.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app.application.agent_orchestrator.run_models import RunStatus

logger = logging.getLogger(__name__)

_MAX_TRACE_STRING_CHARS = 4000
_MAX_TRACE_LIST_ITEMS = 20
_MAX_TRACE_DICT_ITEMS = 40
_LEGACY_EXECUTE_READ_DEFAULTS = {
    "business_db": ("read",),
    "customers": ("query",),
    "materials": ("query",),
    "products": ("query",),
    "shipment_records": ("query",),
}


def _trace_safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:_MAX_TRACE_STRING_CHARS]
    if isinstance(value, str):
        if len(value) <= _MAX_TRACE_STRING_CHARS:
            return value
        return value[:_MAX_TRACE_STRING_CHARS] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_trace_safe_value(item, depth=depth + 1) for item in value[:_MAX_TRACE_LIST_ITEMS]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= _MAX_TRACE_DICT_ITEMS:
                safe["_truncated"] = True
                break
            safe[str(key)] = _trace_safe_value(item, depth=depth + 1)
        return safe
    return str(value)[:_MAX_TRACE_STRING_CHARS]


def _resolved_user_id(
    *,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
) -> str:
    context = runtime_context or {}
    candidates = (
        user_id,
        context.get("user_id"),
        context.get("userId"),
        context.get("uid"),
        context.get("username"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return "anonymous"


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _payload_status(payload: dict[str, Any]) -> RunStatus:
    data = _payload_data(payload)
    if payload.get("requires_token") or data.get("requires_token"):
        return "waiting_user"
    if payload.get("success") is False:
        return "failed"
    return "completed"


def _payload_error_message(payload: dict[str, Any]) -> str:
    data = _payload_data(payload)
    return str(
        payload.get("message")
        or payload.get("error")
        or data.get("message")
        or data.get("error")
        or "Chat run failed"
    )


def _iter_payload_dicts(payload: dict[str, Any], *, max_depth: int = 3) -> Iterator[dict[str, Any]]:
    stack: list[tuple[dict[str, Any], int]] = [(payload, 0)]
    seen: set[int] = set()
    while stack:
        item, depth = stack.pop(0)
        item_id = id(item)
        if item_id in seen:
            continue
        seen.add(item_id)
        yield item
        if depth >= max_depth:
            continue
        for key in ("data", "payload", "result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                stack.append((nested, depth + 1))


def _iter_tool_call_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
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


def _candidate_tool_actions(
    tool_id: str,
    raw_action: Any,
    params: dict[str, Any],
) -> list[str]:
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
            return spec.tool_id, spec.action, dict(params), dict(tool_call)
    return None


def _extract_legacy_tool_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("legacy_tool_records", "_tool_records", "tool_records"):
            records = item.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
    return []


def _coerce_trace_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_trace_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
