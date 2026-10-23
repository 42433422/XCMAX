"""Receipt-based ticket progress; waiting is neither failure nor delivery."""

import uuid

import pytest

from modstore_server.customer_service_tools import json_loads
from tests.test_customer_issue_delivery_pipeline import make_ticket


@pytest.fixture
def progress_client(client, monkeypatch):
    """Keep parametrized intake requests out of other tests' rate-limit bucket."""
    monkeypatch.setitem(client.headers, "x-modstore-user", f"progress-{uuid.uuid4().hex}")
    return client


@pytest.mark.parametrize("team_ok", [False, True])
@pytest.mark.parametrize(
    "statuses,expected",
    [
        (("pending", "planned", "planned"), "pending"),
        (("success", "queued", "planned"), "pending"),
        (("success", "dispatching", "planned"), "pending"),
        (("success", "running", "planned"), "pending"),
        (("success", "success", "skipped_fix_unfinished"), "pending"),
        (("success", "success", "verification_invalidated"), "pending"),
        (("unknown", "planned", "planned"), "pending"),
        (("missing_receipt", "planned", "planned"), "manual_review"),
        (("failed_receipt", "planned", "planned"), "failed"),
        (("unknown_receipt", "planned", "planned"), "pending"),
        (("manual_review", "planned", "planned"), "manual_review"),
        (("pending", "handler_failed", "planned"), "failed"),
        (("manual_review", "refused", "planned"), "failed"),
        (("pending", "blocked_by_risk_gate", "planned"), "failed"),
        (("success", "skipped", "planned"), "failed"),
        (("success",), "partial"),
        (("success", "success", "stale_verify"), "partial"),
        (("success", "success", "success"), "completed"),
    ],
)
def test_planned_roles_wait_for_the_original_scout_without_reporting_failure(
    progress_client, monkeypatch, statuses, expected, team_ok
):
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

    _, tid = make_ticket(progress_client, monkeypatch)
    rows = [
        {"role": r, "ok": s == "success", "status": s}
        for r, s in zip(("scout", "fix", "verify"), statuses)
    ]
    if statuses[-1] == "stale_verify":
        rows[-1].update(ok=True, status="success", verified_fix_attempt_id="older-fix")
        rows[1]["attempt_id"] = "current-fix"
    if statuses[0] in {
        "pending",
        "unknown",
        "missing_receipt",
        "failed_receipt",
        "unknown_receipt",
    }:
        rows[0]["status"] = "pending" if statuses[0].endswith("receipt") else statuses[0]
        rows[0]["handler_outputs"] = {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "task_id": "original-scout",
                    "accepted": True,
                    "completed": False,
                }
            ]
        }
        receipt = rows[0]["handler_outputs"]["outputs"][0]
        if statuses[0] == "missing_receipt":
            receipt.pop("task_id")
        if statuses[0] == "failed_receipt":
            receipt.update(status="para_task_failed", ok=False, error="real execution failure")
        if statuses[0] == "unknown_receipt":
            receipt.update(outcome="unknown", error="lost response", requires_reconciliation=True)
    expected = "partial" if not team_ok and expected == "completed" else expected
    with get_session_factory()() as db:
        apply_customer_ticket_incident_progress(
            db, ticket_id=tid, event_id=45, team_ok=team_ok, team_rows=rows
        )
        action = db.query(CustomerServiceAction).filter_by(ticket_id=tid).one()
        ticket = db.get(CustomerServiceTicket, tid)
        assert action.status == expected
        failed_role = "scout" if statuses[0] == "failed_receipt" else "fix"
        assert action.error == (f"未成功角色：{failed_role}" if expected == "failed" else "")
        resolution = json_loads(ticket.evidence_json, {})["resolution"]
        assert resolution["state"] == {
            "failed": "repair_failed",
            "manual_review": "awaiting_manual_review",
            "completed": "awaiting_delivery",
        }.get(expected, "processing")
        assert resolution["repair_verified"] is (expected == "completed")
        assert ticket.status == "processing" and ticket.closed_at is None
