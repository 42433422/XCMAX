"""Shared customer issue routing and evidence gates; employee progress is not delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def execution_succeeded(result: Any) -> bool:
    """Require an explicit successful execution, including nested handler results."""
    if not isinstance(result, dict) or not result:
        return False
    status = str(result.get("status") or result.get("execution_status") or "").lower()
    if (
        result.get("ok") is False
        or result.get("success") is False
        or result.get("error")
        or result.get("handler_failed")
        or result.get("blocked_by_risk_gate")
        or result.get("partial")
        or result.get("outcome") == "unknown"
        or result.get("requires_reconciliation")
        or status
        in {
            "failed",
            "error",
            "handler_failed",
            "orchestrator_failed",
            "skipped",
            "pending",
            "planned",
            "running",
            "queued",
            "unknown",
            "partial",
            "reconciling",
            "dispatching",
            "blocked_by_risk_gate",
        }
    ):
        return False
    if result.get("handler") == "para_delegate":
        return (
            result.get("ok") is True
            and result.get("accepted") is True
            and result.get("completed") is True
            and bool(_para_task_id(result))
        )
    nested = result.get("result")
    if isinstance(nested, dict) and nested:
        if any(
            key in nested for key in ("ok", "success", "status", "execution_status", "error")
        ) and not execution_succeeded(nested):
            return False
        outputs = nested.get("outputs")
        if isinstance(outputs, list) and outputs:
            return _handler_outputs_succeeded(outputs)
    rows = result.get("results")
    if isinstance(rows, list) and rows:
        return all(execution_succeeded(row) for row in rows)
    return (
        result.get("ok") is True
        or result.get("success") is True
        or status in {"success", "completed", "done", "executed", "ok"}
    )


# 只回显服务端推理文本的 handler（无 ok/status、无 error）不是执行结果，不参与判定。
# 之前 Para 已 completed（ok=True）时，scout/verify 的 llm_md/echo 行因缺 ok 被判失败。
_INFORMATIONAL_HANDLERS = frozenset({"echo", "llm_md"})


def _is_informational_row(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and str(row.get("handler") or "") in _INFORMATIONAL_HANDLERS
        and not row.get("error")
        and not any(k in row for k in ("ok", "success", "status", "execution_status"))
    )


def _handler_outputs_succeeded(outputs: list[Any]) -> bool:
    decisive = [row for row in outputs if not _is_informational_row(row)]
    return bool(decisive) and all(execution_succeeded(row) for row in decisive)


def _para_task_id(row: dict[str, Any]) -> Any:
    snapshot = row.get("para_result")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    task = snapshot.get("task")
    return (
        row.get("para_task_id")
        or row.get("task_id")
        or snapshot.get("task_id")
        or snapshot.get("id")
        or (task.get("id") if isinstance(task, dict) else None)
    )


def execution_requires_reconciliation(result: Any) -> bool:
    """An error or lost response does not prove that accepted work stopped."""
    if not isinstance(result, dict):
        return False
    if result.get("outcome") == "unknown" or result.get("requires_reconciliation"):
        return True
    status = str(result.get("status") or result.get("execution_status") or "").lower()
    terminal = status in {
        "para_task_completed",
        "para_task_merged",
        "para_task_failed",
        "para_task_merge_conflict",
    }
    if result.get("completed") is True and not result.get("partial"):
        terminal = True
    if not terminal and (
        result.get("outcome") == "unknown"
        or result.get("requires_reconciliation")
        or result.get("ticket_route_requires_reconciliation")
        or result.get("accepted")
        or result.get("queued")
        or result.get("outbox_path")
        or status
        in {
            "unknown",
            "reconciling",
            "para_task_timeout",
            "para_task_poll_failed",
            "para_api_missing_task_id",
            "dispatching",
        }
    ):
        return True
    nested = result.get("result")
    if isinstance(nested, dict) and execution_requires_reconciliation(nested):
        return True
    return any(
        execution_requires_reconciliation(row)
        for key in ("outputs", "results")
        for row in (result[key] if isinstance(result.get(key), list) else [])
        if isinstance(row, dict)
    )


def para_task_succeeded(
    task: Any,
    expected_id: str,
    required_ids: list[str] | None = None,
    planned_devices: list[str] | None = None,
) -> bool:
    """Bind completion to the same task and all required/returned child receipts."""
    if not isinstance(task, dict) or str(task.get("id") or "") != str(expected_id):
        return False
    if task.get("status") not in {"completed", "merged"} or task.get("error"):
        return False
    children = task.get("subTasks", task.get("subtasks", []))
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        return False
    returned = {str(child.get("id") or "") for child in children}
    if planned_devices:
        if len(children) < len(planned_devices):
            return False
        if len(required_ids or []) < len(planned_devices):
            devices = {
                str(child.get("device_id") or child.get("deviceId") or "") for child in children
            }
            if not set(planned_devices).issubset(devices):
                return False  # Missing POST receipts need an explicit device/child readback.
    return set(required_ids or []).issubset(returned) and all(
        child.get("status") in {"completed", "merged", "done", "success"}
        and not (child.get("last_error") or child.get("error"))
        for child in children
    )


def execution_pending(result: dict[str, Any]) -> bool:
    """Unknown work remains pending despite transport errors, never eligible for replay."""
    nested = result.get("result")
    outputs = nested.get("outputs") if isinstance(nested, dict) else None
    decisive = [row for row in outputs or [result] if not _is_informational_row(row)]
    return any(execution_requires_reconciliation(row) for row in decisive) and all(
        execution_requires_reconciliation(row) or execution_succeeded(row) for row in decisive
    )


_WAITING_ROLE_STATES = frozenset(
    {
        "planned",
        "queued",
        "running",
        "dispatching",
        "pending",
        "skipped_fix_unfinished",
        "verification_invalidated",
    }
)


def role_progress_state(row: dict[str, Any]) -> str:
    """Project receipt state without executing, retrying or inventing completion."""
    status = row.get("status") or ""
    if not isinstance(status, str):
        return "manual_review"
    status = status.lower()
    terminal_failure = {
        "failed",
        "error",
        "handler_failed",
        "orchestrator_failed",
        "refused",
        "rejected",
        "blocked_by_risk_gate",
        "skipped",
        "partial",
        "para_task_failed",
        "para_task_merge_conflict",
    }
    if status in terminal_failure:
        return "failed"
    handler = row.get("handler_outputs")
    if handler is not None and not isinstance(handler, dict):
        return "manual_review"
    outputs = (handler or {}).get("outputs", [])
    if not isinstance(outputs, list) or not all(isinstance(o, dict) for o in outputs):
        return "manual_review"
    outputs = [o for o in outputs if not _is_informational_row(o)]
    if any(
        str(o.get("status") or o.get("execution_status") or "").lower() in terminal_failure
        or (
            (o.get("ok") is False or o.get("success") is False or o.get("error"))
            and not execution_requires_reconciliation(o)
        )
        for o in outputs
    ):
        return "failed"
    if status == "manual_review":
        return status
    receipt_rows = outputs or (
        [row]
        if status in {"unknown", "accepted", "reconciling"}
        or row.get("accepted")
        or row.get("requires_reconciliation")
        else []
    )
    receipts = [o for o in receipt_rows if execution_requires_reconciliation(o)]
    if receipts:
        return "pending" if all(_para_task_id(o) for o in receipts) else "manual_review"
    if status in _WAITING_ROLE_STATES:
        return "pending"
    if status in {"unknown", "accepted", "reconciling"}:
        return "manual_review"
    return "completed" if row.get("ok") is True else "failed"


def team_action_state(
    rows: list[dict[str, Any]], *, team_ok: bool | None = None
) -> tuple[str, list[str]]:
    states = {role_progress_state(row) for row in rows}
    failed = [str(row.get("role")) for row in rows if role_progress_state(row) == "failed"]
    if failed or not rows:
        return "failed", failed
    return (
        next(
            (s for s in ("manual_review", "pending") if s in states),
            "completed" if team_ok is not False and team_succeeded(rows) else "partial",
        ),
        [],
    )


def projected_dispatch_status(status: str, action_type: str, result: Any, error: str = "") -> str:
    """Correct only provable legacy waiting projections; retain the stored history."""
    rows = result.get("roles") if isinstance(result, dict) else None
    if status != "failed" or action_type != "employee.dispatch" or not isinstance(rows, list):
        return status
    if (
        len(rows) != 3
        or not all(
            isinstance(r, dict)
            and isinstance(r.get("role"), str)
            and isinstance(r.get("status"), str)
            and type(r.get("ok")) is bool
            for r in rows
        )
        or {r.get("role") for r in rows} != {"scout", "fix", "verify"}
    ):
        return status
    for row in rows:
        handler = row.get("handler_outputs", {})
        if (
            not isinstance(handler, dict)
            or not isinstance(handler.get("outputs", []), list)
            or not all(isinstance(o, dict) for o in handler.get("outputs", []))
        ):
            return status
    old_failed = [
        str(r.get("role"))
        for r in rows
        if not r.get("ok") and r.get("status") not in {"pending", "manual_review"}
    ]
    if not old_failed or error != "未成功角色：" + "、".join(old_failed):
        return status
    projected, _ = team_action_state(rows)
    return (
        projected
        if projected in {"pending", "manual_review"}
        and any(r.get("status") in _WAITING_ROLE_STATES for r in rows)
        else status
    )


def team_succeeded(rows: list[dict[str, Any]]) -> bool:
    by_role = {str(row.get("role") or ""): row for row in rows if isinstance(row, dict)}
    successful = all(
        role_progress_state(by_role.get(role, {})) == "completed"
        for role in ("scout", "fix", "verify")
    )
    fix_attempt = by_role.get("fix", {}).get("attempt_id")
    return successful and (
        not fix_attempt or by_role.get("verify", {}).get("verified_fix_attempt_id") == fix_attempt
    )


def issue_resolution(ticket: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    """Bind routing and original request to the authenticated ticket owner."""
    existing = evidence.get("resolution")
    resolution = dict(existing) if isinstance(existing, dict) else {}
    custom = (
        str(evidence.get("issue_domain") or "") == "custom"
        or str(getattr(ticket, "intent", "")) == "custom_delivery"
        or str(evidence.get("source") or "") == "private_mod_rework"
    )
    resolution.update(
        schema_version=1,
        ticket_id=int(ticket.id),
        owner_user_id=int(ticket.user_id),
        route="private_mod" if custom else "shared_core",
    )
    resolution.setdefault("state", "received")
    resolution.setdefault("source_ref", str(evidence.get("source_ref") or ticket.ticket_no))
    resolution.setdefault("original_title", str(ticket.title or ""))
    resolution.setdefault("original_request", str(ticket.summary or ""))
    if evidence.get("target_mod_id"):
        resolution["entitlement_mod_id"] = str(evidence["target_mod_id"])
        resolution["target_mod_id"] = str(
            evidence.get("runtime_mod_id") or evidence["target_mod_id"]
        )
    if evidence.get("installed_version"):
        resolution["reported_version"] = str(evidence["installed_version"])
    if evidence.get("shared_core_prerequisite"):
        resolution["shared_core_prerequisite"] = str(evidence["shared_core_prerequisite"])
    return resolution


def repair_verification(source: str | None) -> dict[str, Any]:
    """repair_verified 只随实际核验来源置真：incident_team / customer_decision / *_runtime_receipt。"""
    at = datetime.now(UTC).isoformat() if source else None
    return {
        "repair_verified": bool(source),
        "repair_verified_by": source,
        "repair_verified_at": at,
    }


def record_team_progress(
    ticket: Any,
    evidence: dict[str, Any],
    *,
    event_id: int,
    rows: list[dict[str, Any]],
    team_ok: bool | None = None,
) -> dict[str, Any]:
    resolution = issue_resolution(ticket, evidence)
    successful = team_ok is not False and team_succeeded(rows)
    action_state, _ = team_action_state(rows, team_ok=team_ok)
    # An employee run cannot establish release or customer-runtime postconditions.
    resolution.update(
        state={
            "failed": "repair_failed",
            "manual_review": "awaiting_manual_review",
            "completed": "awaiting_delivery",
        }.get(action_state, "processing"),
        incident_event_id=int(event_id),
        **repair_verification("incident_team" if successful else None),
        team=[{k: row.get(k) for k in ("role", "employee_id", "ok", "status")} for row in rows],
        updated_at=datetime.now(UTC).isoformat(),
    )
    from modstore_server.incident_team_handler_digest import handler_output_digest

    resolution["processing"] = [
        {
            "role": row.get("role"),
            **handler_output_digest({**row["handler_outputs"], "result": row["handler_outputs"]}),
        }
        for row in rows
        if isinstance(row.get("handler_outputs"), dict)
    ]
    evidence["resolution"] = resolution
    return resolution
