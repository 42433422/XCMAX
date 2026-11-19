"""Employee dispatch uses the same durable acceptance as management commands."""

import time
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import begin_immediate_write, json_loads
from modstore_server.db.db_base import get_session_factory
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, accept, digest, request_cancellation, view
from modstore_server.models_cs import CustomerServiceTicket


def stop_ticket_employee_tasks(db: Session, ticket: CustomerServiceTicket) -> list[dict[str, Any]]:
    rows = (
        db.query(MacControlTask)
        .filter(
            MacControlTask.actor.startswith("employee:"),
            MacControlTask.request_json.contains(f'"ticket_id":{ticket.id}'),
            MacControlTask.state.notin_(TERMINAL),
        )
        .all()
    )
    for_task = []
    for task in rows:
        request = json_loads(task.request_json, {})
        if not isinstance(request, dict) or (
            request.get("source"),
            request.get("ticket_id"),
            request.get("customer_id"),
        ) != ("employee", ticket.id, ticket.user_id):
            continue
        db.refresh(task, with_for_update=True)
        state = (
            "stop_pending_lease"
            if task.lease_until > time.time() and task.state not in TERMINAL
            else request_cancellation(db, task, commit=False)
        )
        for_task.append({"id": task.id, "para_task_id": task.para_task_id, "state": state})
    return for_task


def accept_employee(task: str, input_data: dict, employee_id: str) -> dict:
    source_id = next(
        (
            str(input_data[k])
            for k in (
                "request_id",
                "incident_event_id",
                "run_id",
                "action_item_id",
                "record_id",
            )
            if input_data.get(k)
        ),
        "",
    )
    if not source_id:
        return {
            "handler": "para_delegate",
            "ok": False,
            "queued": False,
            "status": "blocked_missing_request_identity",
        }
    request: dict[str, Any] = {
        "message": task,
        "target": "mac",
        "mode": "review",
        "tool": "codex",
        "source": "employee",
        "employee_id": employee_id,
        "source_id": source_id,
    }
    with get_session_factory()() as db:
        if input_data.get("ticket_id"):
            from modstore_server.customer_ticket_intake_review import intake_dispatch_block_reason

            begin_immediate_write(db)
            try:
                ticket_id = int(input_data["ticket_id"])
            except (ValueError, TypeError):
                ticket_id = 0
            ticket = db.get(CustomerServiceTicket, ticket_id, with_for_update=True)
            if ticket is None or (
                input_data.get("customer_id")
                and str(input_data["customer_id"]) != str(ticket.user_id)
            ):
                return {
                    "handler": "para_delegate",
                    "ok": False,
                    "queued": False,
                    "status": "blocked_invalid_ticket_identity",
                }
            if reason := intake_dispatch_block_reason(ticket):
                return {"handler": "para_delegate", "ok": False, "queued": False, "status": reason}
            request.update(ticket_id=ticket.id, customer_id=ticket.user_id)
        row = accept(
            db,
            actor="employee:" + employee_id,
            key=digest([employee_id, source_id]),
            request=request,
        )
        return {
            "handler": "para_delegate",
            "ok": row.state == "execution_completed",
            "queued": row.state not in {"execution_completed", "failed", "cancelled"},
            "status": row.state,
            "task_id": row.para_task_id,
            "correlation_id": row.id,
            "execution": view(row)["execution"],
        }
