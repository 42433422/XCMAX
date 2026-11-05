"""Escalation intent, actual acceptance, same-task readback and lifecycle fences."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import modstore_server.models as models
from modstore_server import incident_team_escalation as escalation
from modstore_server import incident_team_failure_loop as failure_loop
from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket


@pytest.fixture
def incident(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "escalation.sqlite"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", "grok_bot@review-node")
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_EMPLOYEE_DISPATCH", "0")
    models.init_db()
    with models.get_session_factory()() as db:
        user = models.User(
            username="escalation-owner", email="owner@example.test", password_hash="x"
        )
        db.add(user)
        db.flush()
        session = CustomerServiceSession(user_id=user.id)
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=user.id,
            session_id=session.id,
            ticket_no="CS-ESCALATION",
            status="processing",
            evidence_json=json.dumps({"resolution": {"owner_user_id": user.id}}),
        )
        db.add(ticket)
        db.flush()
        event = models.IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="customer_ticket",
            payload_json=json.dumps(
                {
                    "ticket_id": ticket.id,
                    "user_id": user.id,
                    "tenant_id": user.id,
                    "summary": "Failure contact user@example.test token=secret-value",
                    "resolution": {"owner_user_id": user.id},
                    "_team_claim": {
                        "ok": False,
                        "preserve_me": "audit",
                        "team": [
                            {
                                "role": "fix",
                                "attempt_id": "attempt-one",
                                "status": "failed",
                                "ok": False,
                            }
                        ],
                    },
                }
            ),
        )
        db.add(event)
        db.commit()
        ids = event.id, ticket.id
    yield ids
    models._engine = None
    models._SessionFactory = None


def _payload(event_id):
    with models.get_session_factory()() as db:
        return json.loads(db.get(models.IncidentEvent, event_id).payload_json)


def _stored(event_id):
    return next(iter(_payload(event_id)["_team_claim"]["escalations"].values()))


def _request(event_id):
    return escalation.request_incident_escalation(
        event_id=event_id,
        role="fix",
        category="quota",
        reason="token=private-value quota exceeded",
    )


def _mutate_event(event_id, update):
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, event_id)
        payload = json.loads(event.payload_json)
        update(payload)
        event.payload_json = json.dumps(payload)
        db.commit()


def _close_or_reopen(ticket_id, mode):
    with models.get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        if mode == "closed":
            ticket.status = "resolved"
            ticket.closed_at = datetime.now(UTC)
        else:
            evidence = json.loads(ticket.evidence_json)
            evidence["resolution"].update(state="reopened", reopened_at="2026-10-21T10:00:00Z")
            ticket.evidence_json = json.dumps(evidence)
        db.commit()


def test_dispatch_intent_is_durable_and_accepted_review_never_repairs(incident, monkeypatch):
    event_id, ticket_id = incident
    calls = []

    def dispatch(data):
        saved = _stored(event_id)
        assert saved["state"] == "dispatching" and saved["requested_at"]
        assert saved["accepted"] is False
        assert data["request_id"] == saved["key"]
        assert data["mode"] == "review" and data["report_only"] is True
        assert data["allow_tool_fallback"] == "0" and data["tool_name"] == "grok_bot"
        assert data["wait_for_para"] is False and data["allow_code_fix"] is False
        assert "user@example.test" not in data["prompt"] and "secret-value" not in data["prompt"]
        assert "private-value" not in data["prompt"]
        calls.append(data)
        return {"accepted": True, "task_id": "review-1", "status": "para_task_accepted"}

    monkeypatch.setattr(escalation, "_dispatch_review", dispatch)
    receipt = _request(event_id)
    repeated = _request(event_id)
    assert receipt["state"] == "accepted" and receipt["accepted"] is True
    assert receipt["task_id"] == "review-1" and repeated["key"] == receipt["key"]
    assert len(calls) == 1
    claim = _payload(event_id)["_team_claim"]
    assert claim["ok"] is False and claim["team"][0]["ok"] is False
    assert claim["preserve_me"] == "audit"
    with models.get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        assert ticket.status == "processing" and not ticket.closed_at


@pytest.mark.parametrize(
    "result,state",
    [
        ({"ok": True}, "failed"),
        ({"ok": True, "accepted": True}, "unknown"),
        ({"task_id": "p1", "accepted": False}, "unknown"),
        ({"queued": True, "status": "awaiting_para_dispatcher"}, "unknown"),
        ({"accepted": True, "task_id": "p1", "partial": True}, "unknown"),
        (
            {"accepted": True, "task_id": "p1", "requires_reconciliation": True},
            "unknown",
        ),
        (
            {"ok": False, "accepted": False, "status": "blocked_no_online_para_device"},
            "failed",
        ),
    ],
)
def test_unconfirmed_response_never_claims_accepted(incident, monkeypatch, result, state):
    monkeypatch.setattr(escalation, "_dispatch_review", lambda data: result)
    receipt = _request(incident[0])
    assert receipt["state"] == state and receipt["accepted"] is False


def test_unknown_reads_original_task_without_reposting(incident, monkeypatch):
    event_id, _ = incident
    calls = []
    monkeypatch.setattr(
        escalation,
        "_dispatch_review",
        lambda data: (
            calls.append(data)
            or {
                "accepted": True,
                "task_id": "original",
                "outcome": "unknown",
                "planned_devices": ["review-node"],
            }
        ),
    )
    assert _request(event_id)["state"] == "unknown"
    assert _request(event_id)["state"] == "unknown"
    reads = []

    def fetch(base, task_id):
        reads.append(task_id)
        return {
            "id": task_id,
            "status": "completed",
            "subTasks": [{"id": "child-1", "device_id": "review-node", "status": "completed"}],
        }

    escalation.reconcile_incident_escalations(event_id=event_id, fetcher=fetch)
    receipt = _stored(event_id)
    assert receipt["state"] == "completed" and receipt["accepted"] is True
    assert receipt["completed"] is True and reads == ["original"] and len(calls) == 1
    assert _payload(event_id)["_team_claim"]["ok"] is False


@pytest.mark.parametrize("mode", ["timeout", "dispatching"])
def test_interrupted_submission_without_task_id_never_reposts(incident, monkeypatch, mode):
    calls = []

    def dispatch(data):
        calls.append(data)
        raise TimeoutError("response lost")

    monkeypatch.setattr(escalation, "_dispatch_review", dispatch)
    event_id = incident[0]
    receipt = _request(event_id)
    if mode == "dispatching":
        _mutate_event(
            event_id,
            lambda p: p["_team_claim"]["escalations"][receipt["key"]].update(state="dispatching"),
        )
    assert _request(event_id)["state"] == "unknown"
    escalation.reconcile_incident_escalations(
        event_id=event_id, fetcher=lambda *args: pytest.fail("no original ID, no GET")
    )
    assert len(calls) == 1 and _stored(event_id)["accepted"] is False
    assert _stored(event_id)["error"] == "original_task_id_missing_manual_review"


def test_requested_intent_recovers_before_first_post(incident, monkeypatch):
    event_id = incident[0]
    original = escalation._dispatch_requested
    monkeypatch.setattr(escalation, "_dispatch_requested", lambda eid, receipt: receipt)
    receipt = _request(event_id)
    assert receipt["state"] == "requested"
    monkeypatch.setattr(escalation, "_dispatch_requested", original)
    calls = []
    monkeypatch.setattr(
        escalation,
        "_dispatch_review",
        lambda data: calls.append(data) or {"accepted": True, "task_id": "restored"},
    )
    escalation.reconcile_incident_escalations(event_id=event_id, fetcher=lambda *a: {})
    assert len(calls) == 1 and _stored(event_id)["state"] == "accepted"
    assert _stored(event_id)["key"] == receipt["key"]


@pytest.mark.parametrize("mode", ["closed", "reopened"])
def test_old_event_is_blocked_before_and_after_acceptance(incident, monkeypatch, mode):
    event_id, ticket_id = incident
    _close_or_reopen(ticket_id, mode)
    monkeypatch.setattr(
        escalation, "_dispatch_review", lambda data: pytest.fail("stale event POST")
    )
    assert _request(event_id)["state"] == "cancelled"
    assert "escalations" not in _payload(event_id)["_team_claim"]


@pytest.mark.parametrize("mode", ["closed", "reopened"])
def test_late_acceptance_is_audit_only_after_close_or_reopen(incident, monkeypatch, mode):
    event_id, ticket_id = incident

    def dispatch(data):
        _close_or_reopen(ticket_id, mode)
        return {"accepted": True, "task_id": "late-review"}

    monkeypatch.setattr(escalation, "_dispatch_review", dispatch)
    receipt = _request(event_id)
    assert receipt["state"] == "cancelled"
    assert receipt["task_id"] == "late-review" and receipt["accepted"] is True
    escalation.reconcile_incident_escalations(
        event_id=event_id,
        fetcher=lambda *a: pytest.fail("cancelled review must not advance ticket"),
    )
    assert _payload(event_id)["_team_claim"]["ok"] is False


@pytest.mark.parametrize(
    "task",
    [
        {"id": "different", "status": "completed"},
        {"id": "original", "status": "completed", "subTasks": []},
        {
            "id": "original",
            "status": "completed",
            "subTasks": [
                {
                    "id": "other-child",
                    "device_id": "other-device",
                    "status": "completed",
                }
            ],
        },
    ],
)
def test_incomplete_or_wrong_original_receipt_stays_unconfirmed(incident, monkeypatch, task):
    event_id = incident[0]
    monkeypatch.setattr(
        escalation,
        "_dispatch_review",
        lambda data: {
            "accepted": False,
            "task_id": "original",
            "requires_reconciliation": True,
            "planned_devices": ["review-node"],
            "required_subtask_ids": ["expected-child"],
        },
    )
    _request(event_id)
    escalation.reconcile_incident_escalations(event_id=event_id, fetcher=lambda *a: task)
    receipt = _stored(event_id)
    assert receipt["state"] == "unknown" and receipt["accepted"] is False
    assert receipt["completed"] is False


def test_shared_repair_blocks_new_escalation(incident, monkeypatch):
    monkeypatch.setattr(
        "modstore_server.customer_issue_shared_repairs.active_shared_repair",
        lambda db, ticket: {"action_id": 1},
    )
    monkeypatch.setattr(
        escalation, "_dispatch_review", lambda data: pytest.fail("shared repair POST")
    )
    receipt = _request(incident[0])
    assert receipt["state"] == "cancelled" and receipt["error"] == "shared_repair_reused"


@pytest.mark.parametrize("tool", ["grok_bot", "dolt"])
def test_review_keeps_original_task_and_attempted_actions(incident, monkeypatch, tool):
    from modstore_server.dot_ticket_dispatch import prepare_dolt_ticket_payload

    event_id = incident[0]
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", f"{tool}@review-node")

    def evidence(payload):
        payload["_team_claim"]["team"][0]["handler_outputs"] = {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "task_id": "original-fix-task",
                    "accepted": True,
                    "ok": False,
                    "status": "para_task_failed",
                    "error": "CI failed",
                    "summary": "bounded failed result " * 400,
                }
            ]
        }
        payload["_team_claim"]["team"].append(
            {
                "role": "scout",
                "status": "completed",
                "ok": True,
                "attempt_id": "original-scout",
                "summary": "Known source/version inspected",
            }
        )

    _mutate_event(event_id, evidence)
    prompts = []

    def dispatch(data):
        assert _stored(event_id)["attempted_actions"]["attempts"] == 3
        assert '"schema": "incident-role-handoff/v1"' in data["prompt"]
        assert "Scout handoff:" in data["prompt"]
        final = prepare_dolt_ticket_payload(
            {"raw_input": data, "report_only": True}, {"prompt": data["prompt"]}, tool
        )
        prompts.append(final["prompt"])
        return {"accepted": True, "task_id": "review-original"}

    monkeypatch.setattr(escalation, "_dispatch_review", dispatch)
    receipt = escalation.request_incident_escalation(
        event_id=event_id,
        role="fix",
        category="code",
        reason="CI still fails",
        attempted_actions={
            "action": "code_retry_with_feedback",
            "attempts": 3,
            "max_rounds": 3,
        },
    )
    assert receipt["state"] == "accepted"
    assert "original-fix-task" in prompts[0]
    assert "code_retry_with_feedback" in prompts[0]
    assert '"schema": "incident-role-handoff/v1"' in prompts[0]
    if tool == "dolt":
        handoffs = json.loads(
            next(
                line.removeprefix("structured_handoffs: ")
                for line in prompts[0].splitlines()
                if line.startswith("structured_handoffs: ")
            )
        )
        assert [item["role"] for item in handoffs] == ["fix", "scout"]
        assert handoffs[0]["succeeded"] is False
        assert "review_context:" in prompts[0]
    assert '"attempts": 3' in prompts[0]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda p: p.update(user_id=999), "ticket_owner_mismatch"),
        (lambda p: p.update(tenant_id=999), "ticket_owner_mismatch"),
        (lambda p: p["_team_claim"]["team"][0].update(ok=True), "attempt_recovered"),
    ],
)
def test_owner_and_recovered_attempt_guards(incident, monkeypatch, mutation, reason):
    _mutate_event(incident[0], mutation)
    monkeypatch.setattr(
        escalation, "_dispatch_review", lambda data: pytest.fail("invalid attempt POST")
    )
    receipt = _request(incident[0])
    assert receipt["state"] == "cancelled" and receipt["error"] == reason


def test_same_claim_reentrant_but_competing_claim_never_posts(incident, monkeypatch):
    from modstore_server.node_coordinator import (
        claim_incident_for_node,
        incident_claim_scope,
        release_incident_claim,
    )

    event_id = incident[0]
    calls = []
    monkeypatch.setattr(
        escalation,
        "_dispatch_review",
        lambda data: (
            calls.append(data)
            or {
                "accepted": True,
                "task_id": "claimed-review",
            }
        ),
    )
    competing = claim_incident_for_node(event_id)
    assert competing["claimed"] is True
    try:
        assert _request(event_id)["state"] == "unknown"
        assert calls == []
    finally:
        release_incident_claim(event_id, owner_token=competing["owner_token"])
    with incident_claim_scope(event_id):
        assert _request(event_id)["state"] == "accepted"
    assert len(calls) == 1


def test_rejected_dispatch_is_not_automatically_replayed(incident, monkeypatch):
    calls = []
    monkeypatch.setattr(
        escalation,
        "_dispatch_review",
        lambda data: (
            calls.append(data)
            or {
                "accepted": False,
                "status": "blocked_no_online_para_device",
            }
        ),
    )
    first = _request(incident[0])
    assert first["state"] == "failed"
    assert _request(incident[0])["key"] == first["key"]
    escalation.reconcile_incident_escalations(event_id=incident[0], fetcher=lambda *a: {})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "state,accepted,task_id,expected",
    [
        ("requested", False, "", False),
        ("unknown", True, "p1", False),
        ("accepted", True, "", False),
        ("accepted", True, "p1", True),
        ("cancelled", True, "p1", False),
    ],
)
def test_failure_loop_labels_only_confirmed_active_acceptance(
    monkeypatch, state, accepted, task_id, expected
):
    monkeypatch.setattr(
        failure_loop,
        "request_incident_escalation",
        lambda **kw: {
            "key": "stable-key",
            "state": state,
            "accepted": accepted,
            "task_id": task_id,
            "updated_at": "receipt-time",
        },
    )
    results = [
        {
            "role": "fix",
            "ok": False,
            "result": {"status": "handler_failed", "error": "quota exceeded"},
        }
    ]
    followup = failure_loop.run_failure_loop(
        retry_member=lambda **kw: pytest.fail("quota must not retry"),
        event_id=1,
        results=results,
        team_plan={},
        payload={},
        event_type="on_error",
        source="test",
        uid=1,
    )[0]
    assert followup["escalation_accepted"] is expected
    assert bool(followup["escalated_to"]) is expected
    assert followup["ok"] is False and results[0]["ok"] is False
    summary = failure_loop.loop_summary([followup])[0]
    assert summary["escalation_key"] == "stable-key"
    assert summary["escalation_updated_at"] == "receipt-time"
