"""The operational view joins existing facts without claiming delivery or acceptance."""

import json
import uuid

import pytest

from modstore_server.customer_service_tools import json_dumps


@pytest.fixture
def execution_case(client):
    from modstore_server.models import IncidentEvent, get_session_factory
    from tests.test_customer_service_api import _make_ticket, _make_user

    user = _make_user("overview_owner")
    with get_session_factory()() as db:
        ticket = _make_ticket(
            db,
            user,
            ticket_no=uuid.uuid4().hex,
            title="客户原问题",
            intent="product_issue",
            status="processing",
        )
        payload = {
            "ticket_id": ticket.id,
            "user_id": user.id,
            "_team_claim": {
                "team": [
                    {
                        "role": "fix",
                        "employee_id": "fixer",
                        "attempt_id": "attempt-current",
                        "status": "failed",
                        "ok": False,
                    }
                ],
                "escalations": {
                    "key": {
                        "role": "fix",
                        "attempt_id": "attempt-current",
                        "state": "requested",
                        "accepted": False,
                        "task_id": "",
                        "completed": False,
                        "target_tool": "grok_bot",
                        "updated_at": "2026-10-21T10:00:00+00:00",
                        "reason": "password=PRIVATE_CANARY",
                    }
                },
            },
        }
        event = IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="test",
            payload_json=json_dumps(payload),
            fingerprint=uuid.uuid4().hex,
        )
        db.add(event)
        db.flush()
        ticket.evidence_json = json_dumps(
            {
                "resolution": {
                    "state": "repair_failed",
                    "incident_event_id": event.id,
                    "updated_at": "2026-10-21T09:00:00+00:00",
                }
            }
        )
        db.commit()
        return user, ticket.id, event.id, payload


def test_requested_review_is_not_acceptance_and_fresh_receipt_updates_overview(execution_case):
    from modstore_server.customer_ticket_execution import ticket_execution_overview
    from modstore_server.models import IncidentEvent, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user, tid, event_id, payload = execution_case
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        before = ticket_execution_overview(db, ticket)
        assert before["receipts"][0]["accepted"] is False
        assert before["blocker"] == "execution_failed"
        assert before["responsible"]["label"] == "fixer"
        receipt = payload["_team_claim"]["escalations"]["key"]
        receipt.update(
            state="accepted",
            accepted=True,
            task_id="real-task-17",
            updated_at="2026-10-21T11:00:00+00:00",
        )
        db.get(IncidentEvent, event_id).payload_json = json_dumps(payload)
        db.commit()
        after = ticket_execution_overview(db, ticket)
        assert after["receipts"][0]["accepted"] is True
        assert after["receipts"][0]["task_id"] == "real-task-17"
        assert after["responsible"]["label"] == "grok_bot"
        assert after["next_step"]["code"] == "await_review"
        assert after["last_progress"]["at"] == "2026-10-21T11:00:00+00:00"
        assert "PRIVATE_CANARY" not in json.dumps(after)
        assert ticket.status == "processing"


@pytest.mark.parametrize("change", ["owner", "reopen", "attempt", "unknown", "missing_task"])
def test_stale_or_unconfirmed_review_never_becomes_real_acceptance(execution_case, change):
    from modstore_server.customer_ticket_execution import ticket_execution_overview
    from modstore_server.models import IncidentEvent, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user, tid, event_id, payload = execution_case
    receipt = payload["_team_claim"]["escalations"]["key"]
    receipt.update(state="accepted", accepted=True, task_id="real-task-17")
    if change == "owner":
        payload["user_id"] = user.id + 9999
    elif change == "reopen":
        payload["resolution"] = {"reopened_at": "previous-reopen"}
    elif change == "attempt":
        receipt["attempt_id"] = "previous-attempt"
    elif change == "unknown":
        receipt.update(state="unknown", requires_reconciliation=True)
    else:
        receipt["task_id"] = ""
    with get_session_factory()() as db:
        db.get(IncidentEvent, event_id).payload_json = json_dumps(payload)
        db.commit()
        overview = ticket_execution_overview(db, db.get(CustomerServiceTicket, tid))
        assert not any(row["accepted"] for row in overview["receipts"])
        if change == "unknown":
            assert overview["next_step"]["code"] == "reconcile_task"


def test_original_customer_decision_does_not_close_earlier_product_work_order(execution_case):
    from modstore_server.customer_ticket_execution import ticket_execution_overview
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from modstore_server.work_order_api import CandidateBody, _create_candidate

    owner, tid, _, _ = execution_case
    with get_session_factory()() as db:
        work = _create_candidate(
            db,
            CandidateBody(
                source="client_ai_product_issue",
                dedup_key=uuid.uuid4().hex,
                context={"customer_user_id": owner.id, "customer_reported": True},
            ),
        )
        ticket = db.get(CustomerServiceTicket, tid)
        ticket.status = "resolved"
        ticket.evidence_json = json_dumps(
            {
                "work_order_id": work["wo_id"],
                "resolution": {
                    "state": "resolved",
                    "repair_verified": True,
                    "repair_verified_by": "customer_decision",
                    "verification_mode": "customer_decision",
                },
            }
        )
        db.commit()
        view = ticket_execution_overview(db, ticket)
        assert view["customer_ticket"]["status"] == "resolved"
        assert view["work_order"] == {
            "binding": "verified",
            "id": work["wo_id"],
            "status": "candidate",
        }
        assert view["verification"] == {
            "repair_verified": True,
            "source": "customer_decision",
            "release_bound": False,
            "customer_confirmed": True,
        }
        assert view["next_step"]["code"] == "none"
        assert view["responsible"]["kind"] == "none"


def test_foreign_work_order_is_not_projected_to_scoped_reader(execution_case):
    from modstore_server.customer_ticket_reader import TicketReader, reader_detail
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from modstore_server.work_order_api import CandidateBody, _create_candidate

    owner, tid, _, _ = execution_case
    with get_session_factory()() as db:
        work = _create_candidate(
            db,
            CandidateBody(
                source="client_ai_product_issue",
                dedup_key=uuid.uuid4().hex,
                context={
                    "customer_user_id": owner.id + 9999,
                    "customer_reported": True,
                    "secret": "PRIVATE_CANARY",
                },
            ),
        )
        ticket = db.get(CustomerServiceTicket, tid)
        ticket.evidence_json = json_dumps(
            {"work_order_id": work["wo_id"], "secret": "PRIVATE_CANARY"}
        )
        db.commit()
        detail = reader_detail(
            db, ticket, TicketReader("grant", "dot", "company", "instance", (owner.id,))
        )
        assert detail["execution_overview"]["work_order"] == {
            "binding": "unavailable",
            "id": None,
            "status": None,
        }
        assert "PRIVATE_CANARY" not in json.dumps(detail)
        assert "evidence" not in detail["ticket"]


def test_admin_detail_serves_the_same_projection(execution_case, client):
    from tests.test_customer_service_api import _as_user, _make_user

    _, tid, _, _ = execution_case
    with _as_user(_make_user("overview_admin", admin=True)):
        response = client.get(f"/api/customer-service/tickets/{tid}")
    assert response.status_code == 200, response.text
    assert response.json()["execution_overview"]["next_step"]["code"] == "review_failure"


@pytest.mark.parametrize("missing", ["task_id", "accepted", "partial", "unknown"])
def test_incomplete_execution_receipt_cannot_claim_completion(missing):
    from modstore_server.customer_ticket_execution import _receipts

    output = {
        "handler": "para_delegate",
        "accepted": True,
        "completed": True,
        "task_id": "real-task",
        "ok": True,
        "status": "completed",
    }
    if missing in {"task_id", "accepted"}:
        output.pop(missing)
    elif missing == "partial":
        output["partial"] = True
    else:
        output["outcome"] = "unknown"
    receipts = _receipts(
        {"team": [{"role": "fix", "status": "completed", "handler_outputs": {"outputs": [output]}}]}
    )
    assert receipts[0]["completed"] is False
