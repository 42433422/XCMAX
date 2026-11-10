"""Bounded payload traversal, trusted actor resolution and response normalization."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_error,
    execution_result_states,
    execution_result_wait_reason,
)

from .run_models import RunStatus

_MAX_TRACE_STRING_CHARS = 4000
_MAX_TRACE_LIST_ITEMS = 20
_MAX_TRACE_DICT_ITEMS = 40


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


def _resolved_user_id(*, runtime_context: dict[str, Any] | None, user_id: str | None) -> str:
    context = runtime_context or {}
    candidates = (
        context.get("local_user_id"),
        context.get("actor_id"),
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
    envelopes = list(execution_result_envelopes(payload))
    states = set().union(*(execution_result_states(item) for item in envelopes))
    if states & {"unknown", "interrupted", "partial", "partial_success"} or any(
        item.get("requires_reconciliation") or item.get("reconciliation_required")
        for item in envelopes
    ):
        return "blocked"
    wait_reason = execution_result_wait_reason(payload)
    if wait_reason == "paused":
        return "paused"
    if wait_reason:
        return "waiting_user"
    if states & {"cancelled", "canceled"}:
        return "cancelled"
    if states & {"rejected", "expired"}:
        return "rejected"
    if "blocked" in states:
        return "blocked"
    if states & {"failed", "timeout", "timed_out"}:
        return "failed"
    if "queued" in states:
        return "queued"
    if "planning" in states:
        return "planning"
    if "retrying" in states:
        return "retrying"
    if states & {"pending", "accepted", "running", "processing"}:
        return "running"
    return "failed" if execution_result_error(payload) else "completed"


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


def _attach_run_id(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    payload["run_id"] = run_id
    payload["agent_run_id"] = run_id
    data = payload.get("data")
    if isinstance(data, dict):
        data["run_id"] = run_id
        data["agent_run_id"] = run_id
    else:
        payload["data"] = {"run_id": run_id, "agent_run_id": run_id}
    return payload
