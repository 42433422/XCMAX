"""Para 优先岗：Para 可派单时不调服务端规划 LLM，工单修复不绕开 Para（llm_tokens=0）。"""

from __future__ import annotations

import pytest

import modstore_server.models as models
from modstore_server import employee_executor as ee


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "para_first.sqlite"))
    models.init_db()
    from tests.test_customer_service_api import _make_user

    _make_user("para-first-admin", admin=True)
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def _pack(handlers):
    return {
        "pack_id": "vibe-coding-maintainer",
        "version": "1.0.0",
        "manifest": {
            "id": "vibe-coding-maintainer",
            "employee_config_v2": {
                "cognition": {"agent": {"system_prompt": "x", "model": {"provider": "auto"}}},
                "actions": {"handlers": list(handlers)},
            },
        },
    }


def _llm_must_not_run(*_args, **_kwargs):
    raise AssertionError("Para 优先岗不应调用服务端规划 LLM")


@pytest.fixture
def guarded_executor(monkeypatch, fresh_db):
    import socket

    monkeypatch.setattr(socket.socket, "connect", _llm_must_not_run)
    monkeypatch.setattr(ee, "load_employee_pack_resolved", lambda _s, _e: _pack(["agent"]))
    for name in (
        "chat_dispatch_via_session",
        "_cognition_sync",
        "_cognition_real",
        "_action_agent_runner",
    ):
        monkeypatch.setattr(ee, name, _llm_must_not_run)
    monkeypatch.setattr(
        "modstore_server.services.llm.chat_dispatch_via_platform_only", _llm_must_not_run
    )


@pytest.fixture
def para_ready(monkeypatch, guarded_executor):
    calls = {"para": 0, "agent": 0}
    monkeypatch.setattr("modstore_server.para_delegate_handler.para_delegate_enabled", lambda: True)
    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.para_delegate_ready_for_dispatch",
        lambda: True,
    )

    def fake_para(*, task, input_data, employee_id):
        calls["para"] += 1
        return {"handler": "para_delegate", "ok": True, "status": "completed"}

    def fake_agent(*_args, **_kwargs):
        calls["agent"] += 1
        return {"handler": "agent", "ok": False, "error": "local llm fallback"}

    monkeypatch.setattr("modstore_server.para_delegate_handler.dispatch_para_delegate", fake_para)
    monkeypatch.setattr(ee, "_action_agent_runner", fake_agent)
    return calls


def _metrics():
    sf = models.get_session_factory()
    with sf() as session:
        return session.query(models.EmployeeExecutionMetric).all()


@pytest.mark.parametrize(
    "employee,handlers",
    [
        ("vibe-coding-maintainer", ["agent"]),
        ("change-request-auditor", ["llm_md", "echo", "agent"]),
        ("test-qa-runner", ["llm_md", "echo"]),
    ],
)
def test_para_first_skips_llm_and_records_zero_tokens(para_ready, monkeypatch, employee, handlers):
    monkeypatch.setattr(ee, "load_employee_pack_resolved", lambda _s, _e: _pack(handlers))
    out = ee.execute_employee_task(
        employee,
        "处理原工单",
        {
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
            "allow_high_risk_real_run": True,
        },
        0,
        bench_llm_override=("deepseek", "deepseek-chat"),
    )
    assert out["llm_tokens"] == 0 and not out.get("handler_failed")
    assert para_ready == {"para": 1, "agent": 0}
    assert [o["handler"] for o in out["result"]["outputs"]] == ["para_delegate"]
    metrics = _metrics()
    assert metrics and all(int(m.llm_tokens or 0) == 0 for m in metrics)


def test_skip_can_be_disabled_and_ignores_non_para_roles(monkeypatch):
    monkeypatch.setattr("modstore_server.para_delegate_handler.para_delegate_enabled", lambda: True)
    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.para_delegate_ready_for_dispatch",
        lambda: True,
    )
    from modstore_server.employee_executor_part03_part01_part02 import (
        _para_first_skip_cognition,
    )

    assert _para_first_skip_cognition("vibe-coding-maintainer", ["agent"], {}) is True
    assert _para_first_skip_cognition("customer-service-agent", ["agent"], {}) is False
    assert (
        _para_first_skip_cognition(
            "test-qa-runner", ["direct_python"], {"handler": "direct_python"}
        )
        is False
    )
    assert _para_first_skip_cognition("test-qa-runner", ["llm_md"], {"burn_in": True}) is False
    monkeypatch.setenv("MODSTORE_PARA_FIRST_SKIP_COGNITION", "0")
    assert _para_first_skip_cognition("vibe-coding-maintainer", ["agent"], {}) is False


@pytest.mark.parametrize("role", ["scout", "fix", "verify"])
def test_dynamic_team_member_uses_the_existing_plan(para_ready, role):
    employee = "dynamic-code-owner"
    result = ee.execute_employee_task(
        employee,
        "沿用事故处理计划",
        {
            "role": role,
            "incident_team": {"team": [{"employee_id": employee, "role": role}]},
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
            "allow_high_risk_real_run": True,
        },
        0,
    )
    assert result["llm_tokens"] == 0
    assert para_ready == {"para": 1, "agent": 0}


@pytest.mark.parametrize(
    "plan", [None, {"team": None}, {"team": [{"employee_id": "other", "role": "fix"}]}]
)
def test_unselected_dynamic_employee_does_not_skip_cognition(plan):
    from modstore_server.employee_executor_part03_part01_part02 import _para_first_skip_cognition

    assert not _para_first_skip_cognition(
        "dynamic-code-owner",
        ["agent"],
        {"role": "fix", "_trusted_incident_team_execution": True, "incident_team": plan},
    )


@pytest.mark.parametrize("preflight", ["ready_failure", "not_ready", "exception", "disabled_flag"])
def test_trusted_incident_para_outage_never_plans_locally(para_ready, monkeypatch, preflight):
    def readiness():
        if preflight == "exception":
            raise RuntimeError("synthetic unavailable Para preflight")
        return preflight == "ready_failure"

    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.para_delegate_ready_for_dispatch", readiness
    )
    if preflight == "disabled_flag":
        monkeypatch.setenv("MODSTORE_PARA_FIRST_SKIP_COGNITION", "0")

    def failed_dispatch(*, task, input_data, employee_id):
        assert input_data["ticket_id"] == 1
        assert input_data["ticket_no"] == "TEST-OUTAGE-1"
        para_ready["para"] += 1
        return {"handler": "para_delegate", "ok": False, "error": "synthetic Para unavailable"}

    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.dispatch_para_delegate", failed_dispatch
    )
    out = ee.execute_employee_task(
        "vibe-coding-maintainer",
        "处理合成原工单 TEST-OUTAGE-1",
        {
            "role": "fix",
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
            "allow_high_risk_real_run": preflight != "ready_failure",
            "ticket_id": 1,
            "ticket_no": "TEST-OUTAGE-1",
        },
        0,
    )
    assert out["handler_failed"] is True
    assert out.get("llm_tokens", 0) == 0
    assert para_ready == {"para": 1, "agent": 0}


@pytest.mark.parametrize("skip_flag", ["0", "1"])
def test_trusted_incident_disabled_para_uses_real_failure_dispatch(
    guarded_executor, monkeypatch, skip_flag
):
    monkeypatch.setenv("MODSTORE_PARA_FIRST_SKIP_COGNITION", skip_flag)
    monkeypatch.setenv("MODSTORE_PARA_DELEGATE_ENABLED", "0")
    out = ee.execute_employee_task(
        "vibe-coding-maintainer",
        "Synthetic original incident TEST-DISABLED-1",
        {
            "role": "fix",
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
            "ticket_id": 1,
            "ticket_no": "TEST-DISABLED-1",
        },
        0,
    )
    assert out["handler_failed"] is True
    assert out["llm_tokens"] == 0
    assert out["result"]["handlers"] == ["para_delegate"]
    assert out["result"]["outputs"] == [
        {"handler": "para_delegate", "ok": False, "error": "MODSTORE_PARA_DELEGATE_ENABLED=0"}
    ]
