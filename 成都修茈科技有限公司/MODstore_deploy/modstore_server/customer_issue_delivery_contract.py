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


def team_succeeded(rows: list[dict[str, Any]]) -> bool:
    by_role = {str(row.get("role") or ""): row for row in rows if isinstance(row, dict)}
    successful = all(by_role.get(role, {}).get("ok") is True for role in ("scout", "fix", "verify"))
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
    ticket: Any, evidence: dict[str, Any], *, event_id: int, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    resolution = issue_resolution(ticket, evidence)
    successful = team_succeeded(rows)
    # An employee run cannot establish release or customer-runtime postconditions.
    resolution.update(
        state=(
            "awaiting_manual_review"
            if any(row.get("status") == "manual_review" for row in rows)
            else (
                "awaiting_delivery"
                if successful
                else (
                    "processing"
                    if rows
                    and all(
                        row.get("ok")
                        or row.get("status")
                        in {
                            "planned",
                            "dispatching",
                            "pending",
                            "skipped_fix_unfinished",
                            "verification_invalidated",
                        }
                        for row in rows
                    )
                    else "repair_failed"
                )
            )
        ),
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
