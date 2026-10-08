"""incident-bus：去重发布、yuangon 绑定同步。"""

from __future__ import annotations

import json

import pytest

import modstore_server.models as models
from modstore_server.incident_bus import (
    _incident_employee_input,
    publish,
    sync_employee_trigger_bindings_from_yuangon,
)
from modstore_server.sync_employee_triggers import sync_duty_contract_event_bindings


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "incident.sqlite"))
    # 单测断言派发副作用时保持同步，避免线程竞态。
    monkeypatch.setenv("MODSTORE_INCIDENT_SYNC_DISPATCH", "1")
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


@pytest.fixture
def admin_user(fresh_db):
    with models.get_session_factory()() as db:
        db.add(
            models.User(
                username="incident_admin", password_hash="x", email="inc@example.com", is_admin=True
            )
        )
        db.commit()


@pytest.mark.parametrize("gate", ["", "gate-secret"])
def test_incident_employee_input_allows_high_risk_shell(monkeypatch, gate):
    monkeypatch.setenv("MODSTORE_RISK_HIGH_GATE_TOKEN", gate)
    inp = _incident_employee_input(
        incident_payload={"summary": "pytest lastfailed 非空"},
        event_type="on_quality_fail",
        source="pytest",
    )
    assert inp["allow_high_risk_real_run"] is True
    assert inp["incident"]["summary"] == "pytest lastfailed 非空"
    assert inp.get("high_risk_gate_token", "") == gate


@pytest.mark.parametrize("support_chars", [0, 8000, 60540, 100000])
@pytest.mark.parametrize("prior", [None, '{"ticket_id":', '{"_team_claim": {}}'])
def test_publish_dedupes_within_window(fresh_db, monkeypatch, support_chars, prior):
    from modstore_server.unified_autonomy_orchestrator import orchestrate_incident

    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)
    monkeypatch.setattr("modstore_server.incident_bus._dispatch_incident", lambda *a, **k: None)
    payload = {
        "support_bundle_base64": "A" * support_chars,
        "ticket_id": 1,
        "ticket_no": "CI-regression",
        "user_id": 1,
        "work_order_id": "WO-regression",
    }
    kwargs = {
        "source": "customer-issue-intake",
        "fingerprint": "original-outbox",
        "dedupe_minutes": 24 * 60,
    }
    if prior is not None:
        with models.get_session_factory()() as db:
            db.add(
                models.IncidentEvent(
                    event_type="ops.intake.customer_ticket",
                    source=kwargs["source"],
                    fingerprint=kwargs["fingerprint"],
                    payload_json=prior,
                )
            )
            db.commit()
    assert publish("ops.intake.customer_ticket", payload, **kwargs) is True
    assert publish("ops.intake.customer_ticket", payload, **kwargs) is False
    sf = models.get_session_factory()
    with sf() as db:
        events = db.query(models.IncidentEvent).order_by(models.IncidentEvent.id).all()
        event = events[-1]
        restored = json.loads(event.payload_json)
        assert all(restored[key] == value for key, value in payload.items())
        if prior is not None:
            assert len(events) == 2 and events[0].payload_json == prior
            assert restored["_incident_replay"]["original_event_id"] == events[0].id
        eid = event.id
    assert orchestrate_incident(eid)["should_dispatch"]
    from modstore_server import employee_task_market as market

    monkeypatch.setattr(
        market,
        "rank_market_candidates",
        lambda _: {
            "ok": True,
            "candidates": [{"employee_id": "fixture-worker", "score": 1}],
        },
    )
    monkeypatch.setattr(market, "execute_employee_task", lambda *a, **k: {"ok": True})
    assert market.dispatch_incident_via_market(eid)["claimed"]
    with sf() as db:
        restored = json.loads(db.get(models.IncidentEvent, eid).payload_json)
        assert all(restored[key] == value for key, value in payload.items())


@pytest.mark.parametrize("damaged", ['{"ticket_id": 1, "support": "', "[]"])
def test_damaged_incident_cannot_dispatch_or_replace_evidence(fresh_db, monkeypatch, damaged):
    from modstore_server.incident_dispatch import _dispatch_incident_body
    from modstore_server.unified_autonomy_orchestrator import orchestrate_incident

    with models.get_session_factory()() as db:
        event = models.IncidentEvent(
            event_type="ops.intake.customer_ticket", source="unit", payload_json=damaged
        )
        db.add(event)
        db.commit()
        eid = event.id
    from modstore_server.employee_task_market import rank_market_candidates

    for dispatch in (orchestrate_incident, _dispatch_incident_body, rank_market_candidates):
        with pytest.raises(ValueError):
            dispatch(eid)
        with models.get_session_factory()() as db:
            event = db.get(models.IncidentEvent, eid)
            assert event.payload_json == damaged and event.dispatched_count == 0


def test_employee_lifecycle_events_do_not_dispatch_back_to_employees(admin_user, monkeypatch):
    calls = {"n": 0}

    def fake_execute(*_args, **_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr("modstore_server.incident_bus.execute_employee_task", fake_execute)
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)
    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.ingest_suggestion_event_payload",
        lambda *a, **k: None,
    )

    assert publish(
        "employee.evolution.suggested",
        {"employee_id": "x", "summary": "loop"},
        source="evolution-engine",
    )
    assert calls["n"] == 0


def test_successful_task_event_skips_deterministic_duty_without_real_input(admin_user, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.CatalogItem(
                pkg_id="employee-planner",
                version="1.0.0",
                name="Planner",
                artifact="employee_pack",
            )
        )
        s.add(
            models.EmployeeTriggerBinding(
                employee_id="employee-planner",
                event_type="employee.task.done:intent-analyst",
                is_active=True,
                priority=1,
            )
        )
        s.commit()

    generic_calls = {"orchestrator": 0, "team": 0, "market": 0}
    employee_calls: list[str] = []

    def fail_generic(kind):
        def _fail(*_args, **_kwargs):
            generic_calls[kind] += 1
            raise AssertionError(f"successful lifecycle event reached {kind}")

        return _fail

    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        fail_generic("orchestrator"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        fail_generic("team"),
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        fail_generic("market"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        lambda employee_id, *_args, **_kwargs: (employee_calls.append(employee_id) or {"ok": True}),
    )
    monkeypatch.setattr(
        "modstore_server.node_coordinator.claim_incident_for_node",
        lambda _event_id: {"claimed": True},
    )
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)

    assert publish(
        "employee.task.done",
        {"summary": "intent analysis completed", "execution_status": "success"},
        source="intent-analyst",
    )

    assert generic_calls == {"orchestrator": 0, "team": 0, "market": 0}
    assert employee_calls == []


def test_successful_task_event_without_subscription_is_record_only(admin_user, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        lambda employee_id, *_args, **_kwargs: (calls.append(employee_id) or {"ok": True}),
    )
    monkeypatch.setattr(
        "modstore_server.node_coordinator.claim_incident_for_node",
        lambda _event_id: {"claimed": True},
    )
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)

    assert publish(
        "employee.task.done",
        {"summary": "quality validation completed", "execution_status": "success"},
        source="quality-validator",
    )
    assert calls == []


def test_change_request_submission_only_dispatches_explicit_auditor(admin_user, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.CatalogItem(
                pkg_id="change-request-auditor",
                version="1.0.0",
                name="Change Request Auditor",
                artifact="employee_pack",
            )
        )
        s.add(
            models.EmployeeTriggerBinding(
                employee_id="change-request-auditor",
                event_type="ops.change_request.submitted",
                is_active=True,
                priority=1,
            )
        )
        s.commit()

    generic_calls = {"orchestrator": 0, "team": 0, "market": 0}
    employee_calls: list[str] = []

    def fail_generic(kind):
        def _fail(*_args, **_kwargs):
            generic_calls[kind] += 1
            raise AssertionError(f"change-request workflow signal reached {kind}")

        return _fail

    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        fail_generic("orchestrator"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        fail_generic("team"),
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        fail_generic("market"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        lambda employee_id, *_args, **_kwargs: (employee_calls.append(employee_id) or {"ok": True}),
    )
    monkeypatch.setattr(
        "modstore_server.node_coordinator.claim_incident_for_node",
        lambda _event_id: {"claimed": True},
    )
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)

    assert publish(
        "ops.change_request.submitted",
        {"change_request_id": 47, "risk_level": "low"},
        source="deploy-release-officer",
    )

    assert generic_calls == {"orchestrator": 0, "team": 0, "market": 0}
    assert employee_calls == ["change-request-auditor"]


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("schedule.tick", {"kind": "digest_prewarm"}),
        ("backup.completed", {"trigger": "scheduled", "ok": True}),
        ("backup.ondemand_completed", {"trigger": "manual", "ok": True}),
        ("backup.dr_guard.cleared", {"reason": "probe_recovered"}),
        (
            "ops.change_request.submitted",
            {"change_request_id": 47, "risk_level": "low"},
        ),
    ],
)
def test_binding_only_workflow_signal_skips_generic_incident_fanout(
    admin_user,
    monkeypatch,
    event_type,
    payload,
):
    generic_calls = {"orchestrator": 0, "team": 0, "market": 0}
    employee_calls: list[str] = []

    def fail_generic(kind):
        def _fail(*_args, **_kwargs):
            generic_calls[kind] += 1
            raise AssertionError(f"binding-only workflow signal reached {kind}")

        return _fail

    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        fail_generic("orchestrator"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        fail_generic("team"),
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        fail_generic("market"),
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        lambda employee_id, *_args, **_kwargs: (employee_calls.append(employee_id) or {"ok": True}),
    )
    monkeypatch.setattr(
        "modstore_server.node_coordinator.claim_incident_for_node",
        lambda _event_id: {"claimed": True},
    )
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)

    assert publish(event_type, payload, source="workflow-signal-test")
    assert generic_calls == {"orchestrator": 0, "team": 0, "market": 0}
    assert employee_calls == []


def test_reviewed_duty_binding_runs_after_generic_incident_team_claim(admin_user, monkeypatch):
    sf = models.get_session_factory()
    with sf() as session:
        session.add(
            models.EmployeeTriggerBinding(
                employee_id="log-monitor-incident",
                event_type="on_error",
                is_active=True,
            )
        )
        session.add(
            models.EmployeeTriggerBinding(
                employee_id="dbops-engineer",
                event_type="on_error",
                is_active=True,
            )
        )
        session.add(
            models.EmployeeTriggerBinding(
                employee_id="modstore-backend-api",
                event_type="on_error",
                is_active=True,
            )
        )
        session.commit()

    employee_calls = []
    monkeypatch.setattr(
        "modstore_server.unified_autonomy_orchestrator.orchestrate_incident",
        lambda _event_id: {"should_dispatch": True},
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.dispatch_incident_team",
        lambda _event_id: {"claimed": True, "ok": True},
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        lambda _event_id: (_ for _ in ()).throw(
            AssertionError("reviewed duty event reached generic task market")
        ),
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus._catalog_employee_ids",
        lambda _session: {
            "dbops-engineer",
            "log-monitor-incident",
            "modstore-backend-api",
        },
    )

    def execute(employee_id, task, input_data, **kwargs):
        employee_calls.append((employee_id, task, input_data, kwargs))
        return {"ok": True}

    monkeypatch.setattr("modstore_server.incident_bus.execute_employee_task", execute)
    monkeypatch.setattr(
        "modstore_server.node_coordinator.claim_incident_for_node",
        lambda _event_id: {"claimed": True},
    )
    monkeypatch.setattr("modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None)

    assert publish(
        "on_error",
        {"summary": "nginx upstream unavailable", "type": "upstream_error"},
        source="nginx_error_log",
    )
    assert [call[0] for call in employee_calls] == ["log-monitor-incident"]
    assert employee_calls[0][2]["events"][0]["message"] == "nginx upstream unavailable"
    assert employee_calls[0][3]["user_id"] == 0


def test_sync_employee_trigger_bindings_from_yuangon(fresh_db):
    y = fresh_db / "yuangon" / "g" / "e"
    y.mkdir(parents=True)
    (y / "employee.yaml").write_text(
        "id: incident-bind-1\n"
        "name: Bind\n"
        "version: '1.0.0'\n"
        "domain: test\n"
        "owner: admin\n"
        "area: test\n"
        "skills: []\n"
        "triggers:\n"
        "  on_error: true\n"
        "  on_quality_fail: false\n"
        "  on_coverage_miss: true\n",
        encoding="utf-8",
    )

    n = sync_employee_trigger_bindings_from_yuangon(fresh_db / "yuangon")
    assert n >= 2

    sf = models.get_session_factory()
    with sf() as s:
        rows = (
            s.query(models.EmployeeTriggerBinding)
            .filter(models.EmployeeTriggerBinding.employee_id == "incident-bind-1")
            .all()
        )
        types = {r.event_type for r in rows}
        assert "on_error" in types
        assert "on_coverage_miss" in types
        assert "on_quality_fail" not in types


def test_sync_employee_trigger_bindings_subscribes(fresh_db):
    y = fresh_db / "yuangon" / "quality-and-docs" / "test-qa-runner"
    y.mkdir(parents=True)
    (y / "employee.yaml").write_text(
        "id: test-qa-runner\n"
        "name: QA\n"
        "version: '2.0.3'\n"
        "domain: test\n"
        "owner: admin\n"
        "area: quality-and-docs\n"
        "skills: []\n"
        "triggers:\n"
        "  on_error: true\n"
        "  subscribes:\n"
        "    - employee.task.done:modstore-backend-api\n"
        "    - employee.task.done:market-frontend-dev\n",
        encoding="utf-8",
    )

    n = sync_employee_trigger_bindings_from_yuangon(fresh_db / "yuangon")
    assert n >= 3

    sf = models.get_session_factory()
    with sf() as s:
        rows = (
            s.query(models.EmployeeTriggerBinding)
            .filter(models.EmployeeTriggerBinding.employee_id == "test-qa-runner")
            .all()
        )
        types = {r.event_type for r in rows}
        assert "on_error" in types
        assert "employee.task.done:modstore-backend-api" in types
        assert "employee.task.done:market-frontend-dev" in types


def test_sync_duty_contract_event_bindings_excludes_high_risk(fresh_db):
    n = sync_duty_contract_event_bindings()

    assert n > 0
    sf = models.get_session_factory()
    with sf() as s:
        rows = s.query(models.EmployeeTriggerBinding).all()
        bindings = {(row.employee_id, row.event_type) for row in rows}
    assert ("fhd-core-maintainer", "on_error") in bindings
    assert ("employee-planner", "employee.task.done:intent-analyst") in bindings
    assert ("deploy-release-officer", "ci.passed") not in bindings
