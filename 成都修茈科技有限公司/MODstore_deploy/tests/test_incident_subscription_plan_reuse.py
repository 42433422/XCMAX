"""Customer follow-up reuses team assignment instead of launching another repair."""

import json

import pytest

import modstore_server.models as models
from modstore_server import incident_bus, incident_dispatch
from tests.test_incident_bus import admin_user, fresh_db  # noqa: F401


def test_intake_routing_suggestions_cannot_duplicate_persisted_team(monkeypatch):
    monkeypatch.setattr(
        incident_bus, "_extract_routing_plan", lambda result: [{"proposed_owner": "another-fixer"}]
    )
    calls = []
    monkeypatch.setattr(
        incident_bus, "execute_employee_task", lambda *a, **k: calls.append((a, k)) or {"ok": True}
    )
    count = incident_dispatch._dispatch_intake_routing_plan(
        {},
        incident_payload={"_team_claim": {"team": [{"employee_id": "owner", "role": "fix"}]}},
        event_type="ops.intake.customer_ticket",
        source="customer_ticket",
        admin_id=1,
        catalog_ids={"another-fixer"},
        skip_ids=set(),
        brief="customer issue",
    )
    assert count == 0
    assert calls == []


def test_customer_status_subscriber_keeps_original_team_context(admin_user, monkeypatch):
    members = {"intake-dispatcher", "code-owner", "user-customer-service-officer"}
    with models.get_session_factory()() as db:
        db.query(models.EmployeeTriggerBinding).delete()
        for employee in members:
            db.add(
                models.EmployeeTriggerBinding(
                    employee_id=employee, event_type="ops.intake.customer_ticket", is_active=True
                )
            )
        event = models.IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="customer_ticket",
            payload_json=json.dumps(
                {
                    "summary": "same original ticket",
                    "_team_claim": {"team": [{"role": "fix", "employee_id": "code-owner"}]},
                }
            ),
        )
        db.add(event)
        db.commit()
        event_id = event.id
    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        lambda _: {"should_dispatch": True},
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        lambda _: {"claimed": True, "ok": False},
    )
    monkeypatch.setattr(incident_dispatch, "_has_reviewed_duty_binding", lambda _: False)
    monkeypatch.setattr(incident_bus, "_catalog_employee_ids", lambda _: members)
    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.duty_event_execution_input", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.matching_duty_event_contract",
        lambda *a, **k: None,
    )
    calls = []
    monkeypatch.setattr(
        incident_bus,
        "execute_employee_task",
        lambda eid, task, data, **kwargs: calls.append((eid, task, data)) or {"ok": True},
    )
    incident_dispatch._dispatch_incident_body(event_id)
    assert [call[0] for call in calls] == ["user-customer-service-officer"]
    assert calls[0][2]["reuse_incident_team_plan"] is True
    assert calls[0][2]["incident"]["_team_claim"]["team"][0]["employee_id"] == "code-owner"


@pytest.mark.parametrize(
    "reason,saved_team",
    [
        ("shared_repair_reused", False),
        ("incident_scope_mismatch", True),
        ("incident_not_active", True),
        (None, False),
    ],
)
def test_terminal_or_unplanned_claim_never_launches_subscriber_repair(
    admin_user,
    monkeypatch,
    reason,
    saved_team,
):
    payload = {"summary": "previously queued ticket"}
    if saved_team:
        payload["_team_claim"] = {"team": [{"role": "fix", "employee_id": "code-owner"}]}
    with models.get_session_factory()() as db:
        db.query(models.EmployeeTriggerBinding).delete()
        db.add(
            models.EmployeeTriggerBinding(
                employee_id="intake-dispatcher",
                event_type="ops.intake.customer_ticket",
                is_active=True,
            )
        )
        event = models.IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="customer_ticket",
            payload_json=json.dumps(payload),
        )
        db.add(event)
        db.commit()
        event_id = event.id
    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        lambda _: {"should_dispatch": True},
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        lambda _: {"claimed": True, "ok": False, "reason": reason},
    )
    monkeypatch.setattr(incident_dispatch, "_has_reviewed_duty_binding", lambda _: False)
    monkeypatch.setattr(incident_bus, "_catalog_employee_ids", lambda _: {"intake-dispatcher"})
    calls = []
    monkeypatch.setattr(
        incident_bus, "execute_employee_task", lambda *a, **k: calls.append((a, k)) or {"ok": True}
    )
    incident_dispatch._dispatch_incident_body(event_id)
    assert calls == []
