"""Start one owner-bound workbench delivery generation."""

from datetime import UTC, datetime
from typing import Any

from modstore_server.customer_service_delivery_models import (
    custom_delivery_brief as _custom_delivery_brief,
)


async def _start_custom_delivery_run(
    *,
    user_id: int,
    evidence: dict[str, Any],
    attempt: int,
    rework_note: str = "",
    ticket_id: int = 0,
) -> dict[str, Any]:
    from modstore_server.workbench_api import start_workbench_session_for_user

    kind = str(evidence.get("kind") or "").strip()
    payload: dict[str, Any] = {
        "intent": "employee" if kind == "employee" else "mod",
        "brief": _custom_delivery_brief(evidence, rework_note),
        "suggested_mod_id": str(evidence.get("suggested_id") or "").strip() or None,
        "replace": False,
        "generate_full_suite": kind == "bundle",
        "generate_frontend": kind in {"module", "bundle"},
        "employee_target": "pack_plus_workflow",
        "embed_script_workflow": kind == "employee",
    }
    started = await start_workbench_session_for_user(
        int(user_id),
        payload,
        delivery_context={"ticket_id": ticket_id, "evidence": evidence} if ticket_id else None,
    )
    return {
        "kind": kind,
        "attempt": int(attempt),
        "session_id": str(started.get("session_id") or ""),
        "status": str(started.get("status") or "running"),
        "created_at": datetime.now(UTC).isoformat(),
    }
