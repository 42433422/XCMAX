"""Pure result-envelope classification shared by task execution adapters."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

_STATE_ALIASES = {
    "success": "completed",
    "succeeded": "completed",
    "done": "completed",
    "ok": "completed",
    "failure": "failed",
    "fail": "failed",
    "error": "failed",
    "denied": "rejected",
    "aborted": "cancelled",
    "outcome_unknown": "unknown",
    "in_progress": "running",
    "inflight": "running",
    "approval_required": "waiting_approval",
    "authorization_required": "waiting_auth",
    "needs_user_input": "waiting_user",
    "waiting": "waiting_user",
    "partial_failure": "partial",
}

_APPROVAL_STATES = {
    "waiting_approval",
    "awaiting_approval",
    "pending_approval",
}
_ACTIVE_STATES = {
    "unknown",
    "interrupted",
    "partial",
    "partial_success",
    "blocked",
    "pending",
    "accepted",
    "queued",
    "planning",
    "running",
    "processing",
    "retrying",
}
_UNFINISHED_STATES = (
    _APPROVAL_STATES
    | _ACTIVE_STATES
    | {
        "waiting_user",
        "waiting_input",
        "awaiting_input",
        "waiting_auth",
        "waiting_authorization",
        "awaiting_auth",
        "requires_token",
        "paused",
        "failed",
        "blocked",
        "cancelled",
        "canceled",
        "rejected",
        "expired",
        "timeout",
        "timed_out",
        "interrupted",
        "partial",
        "partial_success",
    }
)


def execution_result_envelopes(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Walk only result envelopes; business rows in items/sheets are not run states."""
    pending, seen = [data], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        if len(seen) >= 256:
            yield {"error": "任务结果层级超限，需核对原结果", "requires_reconciliation": True}
            return
        seen.add(id(current))
        yield current
        children = [
            current.get(key)
            for key in ("result", "output", "data", "payload", "final_output", "chat_payload")
        ]
        for key in ("outputs", "node_outputs"):
            outputs = current.get(key)
            if isinstance(outputs, dict):
                children.extend(outputs.values())
            elif isinstance(outputs, list):
                children.extend(outputs)
        for key in ("tool_records", "legacy_tool_records", "_tool_records"):
            records = current.get(key)
            if isinstance(records, list):
                children.extend(
                    record.get("output") for record in records if isinstance(record, dict)
                )
        pending.extend(item for item in reversed(children) if isinstance(item, dict))


def execution_result_states(data: dict[str, Any]) -> set[str]:
    """Normalize transport aliases once for the existing run, batch and verifier adapters."""
    return {
        _STATE_ALIASES.get(state, state)
        for key in (
            "state",
            "status",
            "outcome",
            "execution_state",
            "execution_status",
            "execution_outcome",
            "exit_status",
        )
        if (state := str(data.get(key) or "").strip().lower())
    }


def execution_result_wait_reason(data: dict[str, Any]) -> str:
    """Describe a known wait without merging user input into business approval."""
    reasons: set[str] = set()
    for result in execution_result_envelopes(data):
        states = execution_result_states(result)
        if result.get("requires_token") or states & {
            "waiting_auth",
            "waiting_authorization",
            "awaiting_auth",
            "requires_token",
        }:
            reasons.add("authorization")
        if result.get("pending_approval") or states & _APPROVAL_STATES:
            reasons.add("approval")
        if result.get("needs_user_input") or states & {
            "waiting_user",
            "waiting_input",
            "awaiting_input",
        }:
            reasons.add("input")
        if "paused" in states:
            reasons.add("paused")
    return next(
        (
            reason
            for reason in ("authorization", "approval", "input", "paused")
            if reason in reasons
        ),
        "",
    )


def execution_result_error(data: dict[str, Any]) -> str:
    """Inspect canonical result envelopes, never infer success from HTTP delivery."""
    for result in execution_result_envelopes(data):
        if result.get("error"):
            return str(result["error"])
        if (
            execution_result_states(result) & _UNFINISHED_STATES
            or result.get("reconciliation_required")
            or result.get("requires_reconciliation")
            or result.get("pending_approval")
            or result.get("requires_token")
            or result.get("needs_user_input")
        ):
            return str(result.get("message") or "任务尚未完成")
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            outputs = list(outputs.values())
        if isinstance(outputs, list) and any(not isinstance(item, dict) for item in outputs):
            return "任务结果无效"
    for result in execution_result_envelopes(data):
        if result.get("success") is False or result.get("ok") is False:
            return str(result.get("message") or result.get("summary") or "任务执行失败")
    return ""


def execution_result_requires_reconciliation(data: dict[str, Any]) -> bool:
    """Preserve unresolved execution through the same envelopes used by verification."""
    return any(
        execution_result_states(result) & _ACTIVE_STATES
        or result.get("reconciliation_required")
        or result.get("requires_reconciliation")
        for result in execution_result_envelopes(data)
    )


def execution_result_awaits_approval(data: dict[str, Any]) -> bool:
    """Keep known approval/credential waits distinct from successful execution."""
    return execution_result_wait_reason(data) in {"approval", "authorization"}
