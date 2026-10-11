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
def para_ready(monkeypatch, fresh_db):
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
    monkeypatch.setattr(ee, "load_employee_pack_resolved", lambda _s, _e: _pack(["agent"]))
    monkeypatch.setattr(ee, "chat_dispatch_via_session", _llm_must_not_run)
    monkeypatch.setattr(ee, "_cognition_sync", _llm_must_not_run)
    monkeypatch.setattr(ee, "_cognition_real", _llm_must_not_run)
    monkeypatch.setattr(
        "modstore_server.services.llm.chat_dispatch_via_platform_only",
        _llm_must_not_run,
    )
    return calls


def _metrics():
    sf = models.get_session_factory()
    with sf() as session:
        return session.query(models.EmployeeExecutionMetric).all()


def test_para_first_fix_skips_planning_llm_and_records_zero_tokens(para_ready):
    out = ee.execute_employee_task(
        "vibe-coding-maintainer",
        "你是事故处理小组的 fix。只删除一行。",
        {
            "role": "fix",
            "allow_high_risk_real_run": True,
            "suppress_lifecycle_events": True,
        },
        0,
        bench_llm_override=("deepseek", "deepseek-chat"),
    )
    assert out["llm_tokens"] == 0
    assert not out.get("handler_failed")
    assert para_ready["para"] == 1
    metrics = _metrics()
    assert metrics and all(int(m.llm_tokens or 0) == 0 for m in metrics)


def test_incident_team_fix_does_not_fall_back_to_local_llm_when_para_fails(para_ready, monkeypatch):
    def failed_para(*, task, input_data, employee_id):
        para_ready["para"] += 1
        return {"handler": "para_delegate", "ok": False, "error": "no code change"}

    monkeypatch.setattr("modstore_server.para_delegate_handler.dispatch_para_delegate", failed_para)
    out = ee.execute_employee_task(
        "vibe-coding-maintainer",
        "你是事故处理小组的 fix。",
        {
            "role": "fix",
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
        },
        0,
    )
    assert out["llm_tokens"] == 0
    assert out.get("handler_failed") is True
    assert para_ready["agent"] == 0


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


def test_para_first_scout_outputs_only_para_row(para_ready, monkeypatch):
    """工单 37/38 scout 配置 llm_md,echo,agent：Para 优先后只留 Para 一行，不再出现 llm_md 回退行。"""
    monkeypatch.setattr(
        ee,
        "load_employee_pack_resolved",
        lambda _s, _e: {**_pack(["llm_md", "echo", "agent"]), "pack_id": "change-request-auditor"},
    )
    out = ee.execute_employee_task(
        "change-request-auditor",
        "你是事故处理小组的 scout。",
        {
            "role": "scout",
            "_trusted_incident_team_execution": True,
            "suppress_lifecycle_events": True,
        },
        0,
    )
    assert out["llm_tokens"] == 0
    assert [o.get("handler") for o in out["result"]["outputs"]] == ["para_delegate"]
