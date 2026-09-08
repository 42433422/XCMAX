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
    nested = result.get("result")
    if isinstance(nested, dict) and nested:
        if any(
            key in nested for key in ("ok", "success", "status", "execution_status", "error")
        ) and not execution_succeeded(nested):
            return False
        outputs = nested.get("outputs")
        if isinstance(outputs, list) and outputs:
            return all(execution_succeeded(row) for row in outputs)
    rows = result.get("results")
    if isinstance(rows, list) and rows:
        return all(execution_succeeded(row) for row in rows)
    return (
        result.get("ok") is True
        or result.get("success") is True
        or status in {"success", "completed", "done", "executed", "ok"}
    )


def team_succeeded(rows: list[dict[str, Any]]) -> bool:
    by_role = {str(row.get("role") or ""): row for row in rows if isinstance(row, dict)}
    return all(by_role.get(role, {}).get("ok") is True for role in ("scout", "fix", "verify"))


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


def record_team_progress(
    ticket: Any, evidence: dict[str, Any], *, event_id: int, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    resolution = issue_resolution(ticket, evidence)
    successful = team_succeeded(rows)
    # An employee run cannot establish release or customer-runtime postconditions.
    resolution.update(
        state="awaiting_delivery" if successful else "repair_failed",
        incident_event_id=int(event_id),
        repair_verified=successful,
        team=[{k: row.get(k) for k in ("role", "employee_id", "ok", "status")} for row in rows],
        updated_at=datetime.now(UTC).isoformat(),
    )
    evidence["resolution"] = resolution
    return resolution
