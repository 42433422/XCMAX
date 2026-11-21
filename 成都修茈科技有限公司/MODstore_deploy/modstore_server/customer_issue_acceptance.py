"""Decision eligibility shared by original-customer read and write entry points."""

from __future__ import annotations

from typing import Any

from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_ticket_disposition import read_disposition


def customer_issue_decision_permissions(ticket: Any) -> dict[str, bool]:
    from modstore_server.customer_service_orchestrator import CLOSED_CUSTOMER_ISSUE_STATES

    evidence = json_loads(ticket.evidence_json, {})
    if (
        ticket.intent != "product_issue"
        or not isinstance(evidence, dict)
        or read_disposition(evidence)
    ):
        return {"can_resolve": False, "can_reopen": False}
    resolution = issue_resolution(ticket, evidence)
    state = resolution.get("state")
    closed = ticket.status in CLOSED_CUSTOMER_ISSUE_STATES
    fault = evidence.get("fault_remains") is True
    site_action = evidence.get("corp_download_repair_action_id")
    target = resolution.get("release_target")
    site_ready = not evidence.get("corp_download_case") or (
        type(site_action) is int
        and site_action > 0
        and isinstance(target, dict)
        and target.get("surface") == "corp_download"
        and target.get("repair_action_id") == site_action
        and site_action > int(resolution.get("reopen_after_action_id") or 0)
    )
    return {
        "can_resolve": bool(
            ticket.status == "awaiting_customer"
            and not ticket.closed_at
            and not fault
            and site_ready
            and (
                state in {"awaiting_customer_verification", "awaiting_delivery", "repair_verified"}
                or resolution.get("repair_verified") is True
            )
        ),
        "can_reopen": closed or (not fault and state not in {"received", "reopened", "processing"}),
    }
