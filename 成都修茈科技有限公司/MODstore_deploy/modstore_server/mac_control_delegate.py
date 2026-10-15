"""Employee dispatch uses the same durable acceptance as management commands."""

from typing import Any

from modstore_server.db.base import get_session_factory
from modstore_server.mac_control_store import accept, digest, view
from modstore_server.models_cs import CustomerServiceTicket


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
            try:
                ticket_id = int(input_data["ticket_id"])
            except (ValueError, TypeError):
                ticket_id = 0
            ticket = db.get(CustomerServiceTicket, ticket_id)
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
