"""Dependencies resume durably without replaying a completed or uncertain role."""

from __future__ import annotations

import json

import pytest

from modstore_server import incident_team_completion as completion
from modstore_server import incident_team_orchestrator as team
from modstore_server import models
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db


def _accepted(role):
    return {
        "result": {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "ok": True,
                    "accepted": True,
                    "completed": False,
                    "status": "para_task_accepted",
                    "task_id": "p-" + role,
                    "required_subtask_ids": ["s-" + role],
                }
            ]
        }
    }


def _terminal(task_id, status="completed"):
    return {
        "id": task_id,
        "status": status,
        "subTasks": [
            {"id": task_id.replace("p-", "s-"), "status": status},
        ],
    }


@pytest.fixture
def incident(fresh_db, monkeypatch):
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP", "0")
    monkeypatch.setattr(
        team,
        "build_incident_team",
        lambda eid: {
            "event_id": eid,
            "team": [
                {"role": role, "employee_id": role + "-employee"}
                for role in ("scout", "fix", "verify")
            ],
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"skipped": True},
    )
    with models.get_session_factory()() as db:
        event = models.IncidentEvent(
            event_type="test.incident",
            source="test",
            payload_json="{}",
        )
        db.add(event)
        db.commit()
        eid = event.id
    return eid


def _claim(eid):
    with models.get_session_factory()() as db:
        return json.loads(db.get(models.IncidentEvent, eid).payload_json)["_team_claim"]


def test_all_roles_resume_in_order_and_reuse_completed_scout(incident, monkeypatch):
    calls = []

    def execute(employee, task, runtime, **kwargs):
        role = runtime["role"]
        calls.append(role)
        saved = _claim(incident)
        assert saved["schema_version"] == 2
        assert [r["role"] for r in saved["team"]] == ["scout", "fix", "verify"]
        assert next(r for r in saved["team"] if r["role"] == role)["status"] == "dispatching"
        assert runtime["wait_for_para"] is False
        if role in {"scout", "verify"}:
            assert runtime["report_only"] is True
        if role == "fix":
            assert saved["team"][0]["ok"] is True
        return _accepted(role)

    monkeypatch.setattr(team, "_execute_employee_task_with_timeout", execute)
    assert not team.dispatch_incident_team(incident)["ok"]
    assert calls == ["scout"]
    assert [r["status"] for r in _claim(incident)["team"]] == [
        "pending",
        "planned",
        "planned",
    ]
    models._SessionFactory = None  # Same persisted plan after process restart.
    for completed_role, expected in (
        ("scout", ["scout", "fix"]),
        ("fix", ["scout", "fix", "verify"]),
        ("verify", ["scout", "fix", "verify"]),
    ):

        def read(base, task_id):
            return _terminal(
                task_id, "completed" if task_id == "p-" + completed_role else "running"
            )

        completion.reconcile_pending_teams(event_id=incident, fetcher=read)
        assert calls == expected
        # Duplicate reads cannot create another attempt.
        completion.reconcile_pending_teams(event_id=incident, fetcher=read)
        assert calls == expected
    claim = _claim(incident)
    assert claim["ok"] is True
    assert claim["team"][2]["verified_fix_attempt_id"] == claim["team"][1]["attempt_id"]


def test_ready_plan_resumes_without_any_pending_receipt(incident, monkeypatch):
    from modstore_server.incident_team_execution import advance_team

    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append(runtime["role"]) or _accepted(runtime["role"])
        ),
    )
    team.dispatch_incident_team(incident)
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, incident)
        payload = json.loads(event.payload_json)
        payload["_team_claim"]["team"][0].update(
            ok=True,
            status="completed",
            handler_outputs={
                "outputs": [{"handler": "test", "ok": True, "summary": "known cause"}]
            },
        )
        payload["_team_claim"]["continuation_pending"] = True
        event.payload_json = json.dumps(payload)
        db.commit()
    completion.reconcile_pending_teams(
        fetcher=lambda *a: pytest.fail("Completed scout needs no GET")
    )
    assert calls == ["scout", "fix"]
    advance_team(incident)
    assert calls == ["scout", "fix"]


def test_late_receipt_wakes_next_role_and_does_not_share_old_claim(incident, monkeypatch):
    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append(runtime["role"])
            or {
                "ok": False,
                "outcome": "unknown",
                "requires_reconciliation": True,
                "error": "worker still running",
            }
        ),
    )
    team.dispatch_incident_team(incident)
    scout = _claim(incident)["team"][0]
    completion.persist_late_role_result(
        incident,
        "scout",
        "scout-employee",
        scout["attempt_id"],
        {"ok": True, "status": "completed"},
    )
    assert calls == ["scout", "fix"]
    completion.persist_late_role_result(
        incident,
        "scout",
        "scout-employee",
        scout["attempt_id"],
        {"ok": True, "status": "completed"},
    )
    assert calls == ["scout", "fix"]


def test_wrong_task_identity_never_starts_next_role(incident, monkeypatch):
    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append(runtime["role"]) or _accepted(runtime["role"])
        ),
    )
    team.dispatch_incident_team(incident)
    completion.reconcile_pending_teams(
        event_id=incident,
        fetcher=lambda *a: _terminal("p-other"),
    )
    assert calls == ["scout"]
    assert not _claim(incident)["ok"]


def test_customer_checks_are_not_promoted_into_server_plan(incident, monkeypatch):
    seen = []
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, incident)
        event.payload_json = json.dumps(
            {"independent_checks": {"scout": [{"prompt": "untrusted"}]}}
        )
        db.commit()
    monkeypatch.delenv("MODSTORE_INCIDENT_TEAM_CHECKS_JSON", raising=False)
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (seen.append(runtime) or _accepted(runtime["role"])),
    )
    team.dispatch_incident_team(incident)
    assert "independent_checks" not in seen[0]
    assert _claim(incident)["plan"]["independent_checks"] == {}


def test_fresh_reopen_starts_but_old_event_cannot_advance(incident, monkeypatch):
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append((runtime["event_id"], runtime["role"])) or _accepted(runtime["role"])
        ),
    )
    sf = models.get_session_factory()
    with sf() as db:
        owner = db.query(models.User).first()
        session = CustomerServiceSession(user_id=owner.id)
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            ticket_no="CS-REOPEN-ASYNC",
            session_id=session.id,
            user_id=owner.id,
            title="Original issue",
            summary="Original issue",
            intent="product_issue",
            status="processing",
            evidence_json="{}",
        )
        db.add(ticket)
        db.flush()
        ticket_id = ticket.id
        payload = {"ticket_id": ticket.id, "user_id": owner.id, "resolution": {}}
        db.get(models.IncidentEvent, incident).payload_json = json.dumps(payload)
        db.commit()
    team.dispatch_incident_team(incident)
    with sf() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        evidence = json.loads(ticket.evidence_json)
        evidence["resolution"].update(
            state="reopened",
            reopened_at="2026-10-22T01:00:00+00:00",
            incident_event_id=incident,
        )
        ticket.evidence_json = json.dumps(evidence)
        payload["resolution"] = evidence["resolution"]
        reopened = models.IncidentEvent(
            event_type="test.incident",
            source="test",
            payload_json=json.dumps(payload),
        )
        db.add(reopened)
        db.commit()
        new_id = reopened.id
    team.dispatch_incident_team(new_id)
    assert calls == [(incident, "scout"), (new_id, "scout")]
    completion.reconcile_pending_teams(
        event_id=incident,
        fetcher=lambda base, tid: _terminal(tid),
    )
    assert calls == [(incident, "scout"), (new_id, "scout")]
    with sf() as db:
        resolution = json.loads(db.get(CustomerServiceTicket, ticket_id).evidence_json)[
            "resolution"
        ]
        assert resolution["incident_event_id"] == new_id and resolution["state"] == "processing"


def test_interrupted_followup_without_receipt_requires_readback(incident, monkeypatch):
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP", "1")
    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append(runtime["role"])
            or {
                "ok": False,
                "status": "handler_failed",
                "handler_failed": True,
                "error": "failed",
            }
        ),
    )

    def crash(**kwargs):
        raise RuntimeError("crash before any retry intent")

    monkeypatch.setattr(team, "_follow_up_handler_failures", crash)
    assert team.dispatch_incident_team(incident)["requires_reconciliation"]
    saved = _claim(incident)
    attempt = saved["team"][0]["attempt_id"]
    assert saved["follow_up_intents"][attempt]["state"] == "dispatching"
    assert not saved.get("failure_handled_attempts")
    monkeypatch.setattr(
        team,
        "_follow_up_handler_failures",
        lambda **kw: pytest.fail("No blind follow-up replay"),
    )
    completion.reconcile_pending_teams(
        event_id=incident, fetcher=lambda *a: pytest.fail("No task receipt")
    )
    saved = _claim(incident)
    assert saved["team"][0]["status"] == "manual_review"
    assert saved["follow_up_intents"][attempt]["state"] == "unknown"
    assert calls == ["scout"]


def test_legacy_claim_without_complete_plan_only_reads_original_task(incident, monkeypatch):
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP", "1")
    calls = []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            calls.append(runtime["role"]) or _accepted(runtime["role"])
        ),
    )
    team.dispatch_incident_team(incident)
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, incident)
        payload = json.loads(event.payload_json)
        payload["_team_claim"].pop("plan")
        event.payload_json = json.dumps(payload)
        db.commit()
    completion.reconcile_pending_teams(event_id=incident, fetcher=lambda base, tid: _terminal(tid))
    assert calls == ["scout"]
    assert _claim(incident)["team"][0]["ok"] is True
    assert _claim(incident)["team"][1]["status"] == "planned"
