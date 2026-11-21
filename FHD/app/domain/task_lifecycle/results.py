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
_UNKNOWN_STATES = {
    "unknown",
    "interrupted",
    "partial",
    "partial_success",
    "timeout",
    "timed_out",
}
_ACTIVE_STATES = _UNKNOWN_STATES | {
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

_EXECUTION_ENVELOPE_KEYS = frozenset(
    {
        "success",
        "ok",
        "error",
        "outcome",
        "execution_state",
        "execution_status",
        "execution_outcome",
        "exit_status",
        "outcome_unknown",
        "reconciliation_required",
        "requires_reconciliation",
        "requires_token",
        "pending_approval",
        "needs_user_input",
        "task_id",
        "execution_id",
    }
)


def execution_result_envelopes(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Walk only result envelopes; business rows in items/sheets are not run states."""
    pending: list[tuple[dict[str, Any], dict[str, Any] | None]] = [(data, None)]
    seen: set[int] = set()
    while pending:
        current, data_parent = pending.pop()
        if id(current) in seen:
            continue
        if len(seen) >= 256:
            yield {"error": "任务结果层级超限，需核对原结果", "requires_reconciliation": True}
            return
        seen.add(id(current))
        # A tool can return an order/customer row in data. Its generic status
        # describes that entity, not whether the tool ran (e.g. cancelled order).
        # Keep business evidence visible, but classify only explicit execution
        # envelopes. Nested output/result wrappers retain their ordinary meaning.
        # Trace adapters copy their own run ID onto business data; only an
        # independent child-run identity denotes an execution envelope.
        if data_parent is not None and not (
            _EXECUTION_ENVELOPE_KEYS.intersection(current)
            or any(
                current.get(key)
                and current[key] not in (data_parent.get("run_id"), data_parent.get("agent_run_id"))
                for key in ("run_id", "agent_run_id")
            )
        ):
            yield {key: value for key, value in current.items() if key not in {"state", "status"}}
        else:
            yield current
        children = [
            (current.get(key), current if key == "data" else None)
            for key in (
                "result",
                "output",
                "data",
                "payload",
                "final_output",
                "business_result",
                "chat_payload",
            )
        ]
        for key in ("outputs", "node_outputs"):
            outputs = current.get(key)
            if isinstance(outputs, dict):
                children.extend((value, None) for value in outputs.values())
            elif isinstance(outputs, list):
                children.extend((value, None) for value in outputs)
        for key in ("tool_records", "legacy_tool_records", "_tool_records"):
            records = current.get(key)
            if isinstance(records, list):
                children.extend(
                    (record.get("output"), None) for record in records if isinstance(record, dict)
                )
        pending.extend((item, flag) for item, flag in reversed(children) if isinstance(item, dict))


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
            "agent_status",
            "run_status",
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
            or result.get("outcome_unknown") is True
            or result.get("pending_approval")
            or result.get("requires_token")
            or result.get("needs_user_input")
            or (
                (result.get("execution_accepted") is True or result.get("accepted") is True)
                and "completed" not in execution_result_states(result)
            )
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


def execution_result_outcome_unknown(data: dict[str, Any]) -> bool:
    """Distinguish uncertain effects from ordinary pending or approval states."""
    return any(
        execution_result_states(result) & _UNKNOWN_STATES
        or result.get("reconciliation_required") is True
        or result.get("requires_reconciliation") is True
        or result.get("outcome_unknown") is True
        for result in execution_result_envelopes(data)
    )


def execution_result_pending_state(data: dict[str, Any]) -> str:
    """Project an unfinished receipt without treating acceptance as completion."""
    if execution_result_outcome_unknown(data):
        return "unknown"
    waiting = execution_result_wait_reason(data)
    if waiting:
        return {
            "authorization": "waiting_auth",
            "approval": "waiting_approval",
            "input": "waiting_input",
            "paused": "paused",
        }[waiting]
    states = set().union(
        *(execution_result_states(row) for row in execution_result_envelopes(data))
    )
    pending = next(
        (
            state
            for state in (
                "blocked",
                "retrying",
                "running",
                "processing",
                "planning",
                "queued",
                "pending",
                "accepted",
            )
            if state in states
        ),
        "",
    )
    if not pending and any(
        (row.get("execution_accepted") is True or row.get("accepted") is True)
        and "completed" not in execution_result_states(row)
        for row in execution_result_envelopes(data)
    ):
        return "queued"
    return pending



def execution_result_requires_reconciliation(data: dict[str, Any]) -> bool:
    """Preserve unresolved execution through the same envelopes used by verification."""
    return any(
        execution_result_states(result) & _ACTIVE_STATES
        or result.get("reconciliation_required")
        or result.get("requires_reconciliation")
        or result.get("outcome_unknown") is True
        or (
            (result.get("execution_accepted") is True or result.get("accepted") is True)
            and "completed" not in execution_result_states(result)
        )
        for result in execution_result_envelopes(data)
    )


def normalize_execution_result(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the first receipt and durable replay on the same result contract.

    A transport success cannot override an unfinished or failed child execution.
    Retain its original identity/evidence while making the outer status usable
    by execution, billing and graph consumers. Business status is not run state.
    """
    error = execution_result_error(data)
    requires_reconciliation = execution_result_requires_reconciliation(data)
    if not (error or requires_reconciliation):
        return data
    result = dict(data)
    if error:
        result.update(success=False, message=error)
    if requires_reconciliation:
        result.update(
            success=False,
            outcome="unknown",
            retryable=False,
            reconciliation_required=True,
        )
    return result


def execution_result_awaits_approval(data: dict[str, Any]) -> bool:
    """Keep known approval/credential waits distinct from successful execution."""
    return execution_result_wait_reason(data) in {"approval", "authorization"}


def agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", False) and not output.get("message"):
        output["message"] = getattr(run, "error", False)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output
