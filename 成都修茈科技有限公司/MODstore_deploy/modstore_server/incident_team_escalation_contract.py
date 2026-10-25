"""Identity, lifecycle and receipt rules for an incident's review escalation."""

from __future__ import annotations

import json
import os
from typing import Any

from modstore_server.customer_issue_delivery_contract import para_task_succeeded
from modstore_server.dot_ticket_dispatch import redact_ticket_text
from modstore_server.incident_team_handoff import format_role_handoff
from modstore_server.models_cs import CustomerServiceTicket

ULTIMATE_TOOLS = frozenset({"grok_bot", "dolt"})


def safe_text(value: Any, limit: int = 500) -> str:
    return redact_ticket_text(str(value or ""))[:limit]


def object_json(value: Any) -> dict:
    decoded = json.loads(value or "{}")
    return decoded if isinstance(decoded, dict) else {}


def active_context(db, event, *, receipt: dict | None = None) -> tuple[dict, str]:
    """Fence the old event after close, reopen, owner change or a newer revision."""
    if event is None:
        return {}, "incident_missing"
    payload = object_json(event.payload_json)
    ticket_id = int(payload.get("ticket_id") or 0)
    if ticket_id:
        ticket = db.get(CustomerServiceTicket, ticket_id, with_for_update=True)
        if ticket is None:
            return payload, "ticket_missing"
        owner = int(payload.get("user_id") or 0)
        if owner != ticket.user_id or int(payload.get("tenant_id") or owner) != owner:
            return payload, "ticket_owner_mismatch"
        resolution = object_json(ticket.evidence_json).get("resolution") or {}
        original = payload.get("resolution") or {}
        if ticket.closed_at or ticket.status in {"closed", "resolved", "expired"}:
            return payload, "ticket_closed"
        if resolution.get("reopened_at") != original.get("reopened_at"):
            return payload, "ticket_reopened"
        if int(resolution.get("incident_event_id") or 0) > event.id:
            return payload, "incident_superseded"
        if resolution.get("owner_user_id") not in (None, owner):
            return payload, "ticket_owner_mismatch"
        if resolution.get("source_ref") and resolution.get("source_ref") != payload.get(
            "source_ref"
        ):
            return payload, "ticket_source_mismatch"
        from modstore_server.customer_issue_shared_repairs import active_shared_repair

        if active_shared_repair(db, ticket):
            return payload, "shared_repair_reused"
    elif event.event_type == "ops.intake.customer_ticket":
        return payload, "ticket_identity_missing"
    if receipt is not None:
        rows = (payload.get("_team_claim") or {}).get("team") or []
        current: dict[str, Any] = next(
            (r for r in rows if r.get("role") == receipt["role"]), {}
        )
        if current.get("attempt_id") != receipt["attempt_id"]:
            return payload, "attempt_superseded"
        if current.get("ok") is True:
            return payload, "attempt_recovered"
    return payload, ""


def review_input(event_id: int, payload: dict, receipt: dict) -> dict:
    """Reuse the configured ultimate route, pinned to a read-only review."""
    from modstore_server.para_delegate_handler import _normalize_tool_name

    if os.environ.get("MODSTORE_MAC_CONTROL_EMPLOYEE_DISPATCH") == "1":
        raise ValueError("ultimate_review_requires_para_dispatch")
    route = os.environ.get("MODSTORE_PARA_TICKET_ROUTE", "").strip()
    tool, device = "grok_bot", ""
    if route:
        for hop in route.split(","):
            name, separator, target = hop.strip().partition("@")
            candidate = _normalize_tool_name(name)
            if separator and target.strip() and candidate in ULTIMATE_TOOLS:
                tool, device = candidate, target.strip()
                break
        else:
            raise ValueError("ultimate_review_route_unavailable")
    else:
        tool = _normalize_tool_name(os.environ.get("MODSTORE_PARA_TICKET_TOOL") or tool)
        device = os.environ.get("MODSTORE_PARA_TICKET_DEVICE_ID", "").strip()
        if tool not in ULTIMATE_TOOLS:
            raise ValueError("ultimate_review_route_unavailable")
    summary = safe_text(payload.get("summary") or payload.get("title"), 1200)
    rows = (payload.get("_team_claim") or {}).get("team") or []
    failed: dict[str, Any] = next(
        (row for row in rows if row.get("role") == receipt["role"]), {}
    )
    handoff = format_role_handoff(failed, receipt["role"], max_chars=4000)
    references = json.loads(handoff).get("references") or []
    original_tasks = sorted(
        {
            str(ref[key])
            for ref in references
            for key in ("task_id", "para_task_id")
            if ref.get(key)
        }
    )
    actions = json.dumps(receipt.get("attempted_actions") or {}, ensure_ascii=False)
    # Dot's existing privacy adapter caps its summary. Put original task IDs and
    # already-attempted actions first so that its compact report keeps provenance.
    compact = (
        f"Original Para tasks: {json.dumps(original_tasks)}\nAttempted actions: {actions}\n"
        f"Failure: {receipt['reason']}\nIssue: {summary[:500]}"
    )
    prompt = (
        "Review the failed incident attempt and propose the next safe action. "
        "This is a read-only escalation: do not run another repair, change files, "
        "merge, deploy, close the ticket, or contact the customer. "
        "An uncertain original task must be inspected by its existing task ID.\n"
        f"Role: {receipt['role']}\n{compact}\nFailed role handoff: {handoff}"
    )
    scout: dict[str, Any] = next(
        (row for row in rows if row.get("role") == "scout"), {}
    )
    if scout and receipt["role"] != "scout":
        prompt += "\nScout handoff: " + format_role_handoff(
            scout, "scout", max_chars=1600
        )
    return {
        "event_id": event_id,
        "event_type": "ops.intake.customer_ticket"
        if payload.get("ticket_id")
        else "on_error",
        "user_id": payload.get("user_id"),
        "tenant_id": payload.get("tenant_id") or payload.get("user_id"),
        "request_id": receipt["key"],
        "attempt_id": receipt["key"],
        "revision": receipt["attempt_id"],
        "role": "escalation_review",
        "_incident_handoff": {
            "schema": "incident-team-runtime/v1",
            "event_id": event_id,
            "role": "escalation_review",
            "attempt_id": receipt["key"],
        },
        "tool_name": tool,
        "device_id": device,
        "allow_tool_fallback": "0",
        "mode": "review",
        "report_only": True,
        "allow_code_fix": False,
        "allow_auto_merge": False,
        "wait_for_para": False,
        "title": "Incident escalation review",
        "prompt": prompt,
        "incident": {
            "summary": compact,
            "issue_domain": safe_text(payload.get("issue_domain")),
        },
    }


def dispatch_receipt(result: dict) -> dict:
    """A queued outbox, parent-only POST or unknown response is never acceptance."""
    task_id = str(result.get("task_id") or result.get("para_task_id") or "").strip()
    accepted = result.get("accepted") is True and bool(task_id)
    uncertain = (
        result.get("requires_reconciliation") is True
        or result.get("outcome") == "unknown"
        or result.get("partial") is True
        or result.get("queued") is True
        or bool(result.get("outbox_path"))
        or (result.get("accepted") is True and not task_id)
    )
    state = "unknown" if uncertain else "accepted" if accepted else "failed"
    if not accepted and (task_id or result.get("submission_started")):
        state = "unknown"
    if (
        result.get("status") in {"failed", "para_task_failed", "merge_conflict"}
        and not uncertain
    ):
        state = "failed"
    return {
        "state": state,
        "accepted": accepted and not uncertain,
        "task_id": task_id,
        "completed": False,
        "requires_reconciliation": state in {"accepted", "unknown"},
        "required_subtask_ids": result.get("required_subtask_ids") or [],
        "planned_devices": result.get("planned_devices") or [],
        "error": safe_text(
            result.get("error") or ("acceptance_not_confirmed" if not accepted else "")
        ),
        "dispatch_status": safe_text(result.get("status"), 100),
    }


def task_receipt(receipt: dict, task: dict) -> dict:
    task_id = receipt["task_id"]
    if str(task.get("id") or "") != task_id:
        raise ValueError("escalation_task_id_mismatch")
    children = task.get("subTasks", task.get("subtasks", []))
    children = children if isinstance(children, list) else []
    required = set(receipt.get("required_subtask_ids") or [])
    returned = {
        str(child.get("id") or "") for child in children if isinstance(child, dict)
    }
    planned = set(receipt.get("planned_devices") or [])
    devices = {
        str(child.get("device_id") or child.get("deviceId") or "")
        for child in children
        if isinstance(child, dict)
    }
    worker_receipt = bool(returned - {""}) and required.issubset(returned)
    if planned and len(required) < len(planned):
        worker_receipt = worker_receipt and planned.issubset(devices)
    accepted = receipt.get("accepted") is True or worker_receipt
    status = str(task.get("status") or "")
    completed = (
        accepted
        and worker_receipt
        and para_task_succeeded(task, task_id, list(required), list(planned))
    )
    state = "completed" if completed else "accepted" if accepted else "unknown"
    if status in {"failed", "merge_conflict", "cancelled"}:
        state = "failed"
    elif status in {"completed", "merged"} and not completed:
        state = "unknown"
    return {
        "state": state,
        "accepted": accepted,
        "completed": completed,
        "requires_reconciliation": state in {"accepted", "unknown"},
        "task_status": safe_text(status, 100),
        "error": safe_text(
            task.get("error")
            or ("worker_receipt_incomplete" if state == "unknown" else "")
        ),
    }
