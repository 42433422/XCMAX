"""Shared customer issue routing and evidence gates; employee progress is not delivery."""

from __future__ import annotations

import hashlib
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
        or status
        in {
            "failed",
            "error",
            "handler_failed",
            "orchestrator_failed",
            "skipped",
            "pending",
            "running",
            "queued",
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


def execution_pending(result: dict[str, Any]) -> bool:
    """Accepted Para work remains pending; a failed companion handler cannot be hidden."""
    if (
        result.get("ok") is False
        or result.get("success") is False
        or result.get("status") in {"failed", "error", "handler_failed", "blocked_by_risk_gate"}
        or any(result.get(k) for k in ("error", "handler_failed", "blocked_by_risk_gate"))
    ):
        return False
    nested = result.get("result")
    outputs = nested.get("outputs") if isinstance(nested, dict) else None
    decisive = [row for row in outputs or [result] if not _is_informational_row(row)]

    def pending(row):
        return (
            isinstance(row, dict)
            and row.get("handler") == "para_delegate"
            and row.get("ok") is True
            and row.get("accepted") is True
            and row.get("completed") is False
            and not row.get("error")
            and row.get("status") in {"para_task_accepted", "pending", "running", "queued"}
            and bool(_para_task_id(row))
        )

    return any(pending(row) for row in decisive) and all(
        pending(row) or execution_succeeded(row) for row in decisive
    )


_REVISION_KEYS = ("merge_commit_sha", "branch", "task_id", "change_request_id", "revision")


def artifact_revision(digest: Any, *, attempt: int = 0) -> str:
    """fix 产物身份：优先 merge SHA/任务号，缺产物时退化为轮次；新 fix 必得新 revision。"""
    rows = digest.get("outputs") if isinstance(digest, dict) else None
    parts = [
        f"{key}={row[key]}"
        for row in rows or []
        if isinstance(row, dict)
        for key in _REVISION_KEYS
        if row.get(key)
    ]
    parts.append(f"attempt={int(attempt)}")
    return "rev:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def verification_bound(fix_row: dict[str, Any], verify_row: dict[str, Any]) -> bool:
    """verify 只对它验过的那一版 fix 有效；revision 不匹配即视为未验证。"""
    expected = str(fix_row.get("fix_revision") or "")
    if not expected:
        return True
    return str(verify_row.get("verified_revision") or "") == expected


def team_succeeded(rows: list[dict[str, Any]]) -> bool:
    by_role = {str(row.get("role") or ""): row for row in rows if isinstance(row, dict)}
    if not all(by_role.get(role, {}).get("ok") is True for role in ("scout", "fix", "verify")):
        return False
    return verification_bound(by_role["fix"], by_role["verify"])


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
    return {"repair_verified": bool(source), "repair_verified_by": source, "repair_verified_at": at}


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
                    if rows and all(row.get("ok") or row.get("status") == "pending" for row in rows)
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
