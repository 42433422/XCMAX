from __future__ import annotations

from datetime import datetime, timezone

import pytest

import modstore_server.models as models


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "employee_loop.sqlite"))
    monkeypatch.setenv("MODSTORE_HEALTH_SCAN_ENABLED", "1")
    models.init_db()
    yield
    models._engine = None
    models._SessionFactory = None


def _add_user(session) -> int:
    user = models.User(
        username="loop_admin",
        password_hash="x",
        email="loop@example.com",
        is_admin=True,
    )
    session.add(user)
    session.commit()
    return int(user.id)


def test_handler_failure_detail_preserves_para_error_for_classification():
    from modstore_server.employee_executor import _handler_failure_detail
    from modstore_server.llm_failure_classifier import FAILURE_KIND_TRANSIENT, classify_failure_kind

    error = _handler_failure_detail(
        {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "ok": False,
                    "status": "para_api_failed_outboxed",
                    "source": "para_api",
                    "error": "Para API 调用失败，已写入 outbox",
                }
            ]
        }
    )

    assert "para_delegate" in error
    assert "para_api_failed_outboxed" in error
    assert classify_failure_kind(error) == FAILURE_KIND_TRANSIENT


def test_vibe_employee_does_not_force_para_when_delegate_unconfigured(monkeypatch):
    from modstore_server.employee_executor import _actions_real

    monkeypatch.delenv("MODSTORE_PARA_API_BASE", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_ENABLED", raising=False)

    out = _actions_real(
        {"handlers": ["llm_md"]},
        {"reasoning": "已完成分析", "input": {}},
        "Incident team role=fix. Event=on_error.",
        "vibe-coding-maintainer",
        user_id=0,
    )

    assert out["handlers"] == ["llm_md"]
    assert out["outputs"] == [{"handler": "llm_md", "output": "已完成分析"}]


def test_incident_team_tasks_require_plain_chinese():
    from modstore_server.incident_team_orchestrator import _task_for_role

    task = _task_for_role(
        event_type="on_error",
        payload={"summary": "nginx error.log 尾部含 error"},
        role="verify",
        scout_result={"ok": True, "result": {"raw": "SCOUT_RESULT"}},
        fix_result={"ok": False, "error": "handler_failed"},
    )

    assert "回复必须说人话" in task
    assert "不要直接倾倒 JSON" in task
    assert "用 PASS/FAIL 开头" in task
    assert "Incident team role=" not in task


def test_health_scan_excludes_infra_and_lifecycle_failures(fresh_db, monkeypatch):
    from modstore_server.employee_health_scan import run_health_scan
    from modstore_server.llm_failure_classifier import FAILURE_KIND_TRANSIENT

    monkeypatch.setattr(
        "modstore_server.employee_health_scan._record_runtime_policy", lambda **_kw: None
    )
    monkeypatch.setattr("modstore_server.employee_health_scan._notify_admins", lambda *a, **k: None)

    sf = models.get_session_factory()
    now = datetime.now(timezone.utc)
    with sf() as session:
        uid = _add_user(session)
        session.add_all(
            [
                models.EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="para-worker",
                    task="Incident team role=fix. Event=on_error.",
                    status="handler_failed",
                    error="handler para_delegate failed status=para_api_failed_outboxed",
                    failure_kind=FAILURE_KIND_TRANSIENT,
                    created_at=now,
                ),
                models.EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="lifecycle-worker",
                    task="Incident team role=verify. Event=employee.evolution.suggested.",
                    status="handler_failed",
                    error="one or more handlers returned ok=False",
                    failure_kind="prompt",
                    created_at=now,
                ),
                models.EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="vibe-coding-maintainer",
                    task="Incident team role=fix. Event=on_error.",
                    status="handler_failed",
                    error="one or more handlers returned ok=False",
                    failure_kind="prompt",
                    created_at=now,
                ),
                models.EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="real-worker",
                    task="Incident team role=verify. Event=on_error.",
                    status="handler_failed",
                    error="tool call returned invalid json",
                    failure_kind="prompt",
                    created_at=now,
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(
        "modstore_server.employee_health_scan._deactivate_catalog_employee",
        lambda _employee_id: True,
    )
    out = run_health_scan(lookback_hours=24, warn_threshold=1, deactivate_threshold=2, notify=False)

    assert len(out["warned"]) == 1
    assert out["warned"][0]["employee_id"] == "real-worker"
    assert out["warned"][0]["fail_count"] == 1
    assert out["warned"][0]["last_failure_at"]
    assert out["deactivated"] == []


def test_health_scan_evolution_records_are_cooled_down(fresh_db, monkeypatch):
    from modstore_server.employee_health_scan import run_health_scan

    monkeypatch.setattr(
        "modstore_server.employee_health_scan._record_runtime_policy", lambda **_kw: None
    )
    monkeypatch.setattr(
        "modstore_server.employee_health_scan._deactivate_catalog_employee",
        lambda _employee_id: True,
    )

    sf = models.get_session_factory()
    now = datetime.now(timezone.utc)
    with sf() as session:
        uid = _add_user(session)
        session.add_all(
            [
                models.EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="real-worker",
                    task="Incident team role=fix. Event=on_error.",
                    status="handler_failed",
                    error="tool call returned invalid json",
                    failure_kind="prompt",
                    created_at=now,
                )
                for _ in range(3)
            ]
        )
        session.commit()

    out1 = run_health_scan(lookback_hours=24, warn_threshold=1, deactivate_threshold=2, notify=False)
    out2 = run_health_scan(lookback_hours=24, warn_threshold=1, deactivate_threshold=2, notify=False)
    assert out1["deactivated"][0]["employee_id"] == "real-worker"
    assert out2["deactivated"][0]["employee_id"] == "real-worker"

    with sf() as session:
        records = session.query(models.EmployeeEvolutionRecord).all()
    assert len(records) == 1
    assert records[0].employee_id == "real-worker"
    assert records[0].triggered_by == "employee_health_scan"


def test_llm_catalog_merge_accepts_dict_entries(monkeypatch):
    from modstore_server import llm_catalog

    monkeypatch.setattr(
        llm_catalog,
        "_load_fallback",
        lambda: {"openai": [{"id": "gpt-4.1"}, {"name": "gpt-4o"}, "gpt-4.1"]},
    )

    assert llm_catalog._merge_fallback("openai", [{"id": "gpt-5"}, "gpt-4o"]) == [
        "gpt-4.1",
        "gpt-4o",
        "gpt-5",
    ]
