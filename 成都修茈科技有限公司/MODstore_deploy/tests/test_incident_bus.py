"""incident-bus：去重发布、yuangon 绑定同步。"""

from __future__ import annotations

import pytest

import modstore_server.models as models
from modstore_server.incident_bus import (
    _incident_employee_input,
    publish,
    sync_employee_trigger_bindings_from_yuangon,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "incident.sqlite"))
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def test_incident_employee_input_allows_high_risk_shell(monkeypatch):
    monkeypatch.delenv("MODSTORE_RISK_HIGH_GATE_TOKEN", raising=False)
    inp = _incident_employee_input(
        incident_payload={"summary": "pytest lastfailed 非空"},
        event_type="on_quality_fail",
        source="pytest",
    )
    assert inp["allow_high_risk_real_run"] is True
    assert inp["incident"]["summary"] == "pytest lastfailed 非空"
    assert "high_risk_gate_token" not in inp

    monkeypatch.setenv("MODSTORE_RISK_HIGH_GATE_TOKEN", "gate-secret")
    inp2 = _incident_employee_input(
        incident_payload={},
        event_type="on_error",
        source="nginx",
    )
    assert inp2["high_risk_gate_token"] == "gate-secret"


def test_publish_dedupes_within_window(fresh_db, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.User(
                username="incident_admin",
                password_hash="x",
                email="inc@example.com",
                is_admin=True,
            )
        )
        s.commit()

    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        lambda *a, **k: {"ok": True},
    )

    assert publish("on_error", {"summary": "dup-test"}, source="unit") is True
    assert publish("on_error", {"summary": "dup-test"}, source="unit") is False


def test_employee_lifecycle_events_do_not_dispatch_back_to_employees(fresh_db, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.User(
                username="incident_admin",
                password_hash="x",
                email="inc2@example.com",
                is_admin=True,
            )
        )
        s.commit()

    calls = {"n": 0}

    def fake_execute(*_args, **_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr("modstore_server.incident_bus.execute_employee_task", fake_execute)
    monkeypatch.setattr(
        "modstore_server.incident_bus._publish_stream_shadow", lambda *a, **k: None
    )
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
