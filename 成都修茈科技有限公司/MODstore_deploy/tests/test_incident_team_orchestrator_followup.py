"""tests/test_incident_team_orchestrator_followup.py

验证 handler_failed → 按 failure_kind 自动 follow-up 闭环：
  - quota：不重试，标 need_human
  - transient：自动重试 1 次
  - prompt：fallback 到 task market
  - MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP=0 关闭闭环（旧行为）
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

import modstore_server.models as models
from modstore_server.incident_team_orchestrator import (
    _follow_up_handler_failures,
    dispatch_incident_team,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "team.sqlite"))
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


@pytest.fixture
def admin_user(fresh_db):
    sf = models.get_session_factory()
    with sf() as s:
        s.add(
            models.User(
                username="admin",
                password_hash="x",
                email="admin@example.com",
                is_admin=True,
            )
        )
        s.commit()
    yield "admin"


def _make_results(handler_failed_role: str, error_text: str) -> list[Dict[str, Any]]:
    """构造 results 列表，指定 role 标记 handler_failed。"""
    base = [
        {
            "employee_id": "scout-1",
            "role": "scout",
            "ok": True,
            "result": {"status": "success"},
        },
        {
            "employee_id": "fix-1",
            "role": "fix",
            "ok": True,
            "result": {"status": "success"},
        },
        {
            "employee_id": "verify-1",
            "role": "verify",
            "ok": True,
            "result": {"status": "success"},
        },
    ]
    for row in base:
        if row["role"] == handler_failed_role:
            row["ok"] = False
            row["result"] = {
                "status": "handler_failed",
                "handler_failed": True,
                "error": error_text,
            }
    return base


def test_quota_failure_marks_need_human_no_retry(monkeypatch):
    """quota 类失败：不重试，标 quota_blocked_need_human。"""
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "should_not_be_called"},
    )
    market_calls = []
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        lambda *a, **k: market_calls.append(1) or {"ok": False, "claimed": False},
    )

    results = _make_results("fix", "403: 配额不足: llm_calls")
    follow_ups = _follow_up_handler_failures(
        event_id=1,
        results=results,
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={},
        event_type="on_error",
        source="unit",
        uid=1,
    )

    assert len(follow_ups) == 1
    fu = follow_ups[0]
    assert fu["failure_kind"] == "quota"
    assert fu["action"] == "quota_blocked_need_human"
    assert fu["ok"] is False
    # 关键：quota 不应触发 retry / market
    assert retry_calls == []
    assert market_calls == []


def test_transient_failure_triggers_one_retry(monkeypatch):
    """transient 类失败：调一次 _retry_member。"""
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "success"},
    )

    results = _make_results("verify", "timeout: connect_error 504")
    follow_ups = _follow_up_handler_failures(
        event_id=42,
        results=results,
        team_plan={"team": [{"employee_id": "verify-1", "role": "verify"}]},
        payload={"summary": "test"},
        event_type="on_quality_fail",
        source="pytest",
        uid=1,
    )

    assert len(follow_ups) == 1
    fu = follow_ups[0]
    assert fu["failure_kind"] == "transient"
    assert fu["action"] == "transient_retry"
    assert fu["ok"] is True
    assert fu["retry_result"] == {"status": "success"}
    assert len(retry_calls) == 1
    assert retry_calls[0]["event_id"] == 42
    assert retry_calls[0]["member"]["employee_id"] == "verify-1"


def test_transient_retry_limit_zero_disables_retry(monkeypatch):
    """MODSTORE_INCIDENT_TEAM_TRANSIENT_RETRY_LIMIT=0 时不重试。"""
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_TRANSIENT_RETRY_LIMIT", "0")
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "should_not_be_called"},
    )

    results = _make_results("fix", "503 service unavailable")
    follow_ups = _follow_up_handler_failures(
        event_id=1,
        results=results,
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={},
        event_type="on_error",
        source="unit",
        uid=1,
    )

    assert len(follow_ups) == 1
    fu = follow_ups[0]
    assert fu["failure_kind"] == "transient"
    # transient_retry_limit=0 → 落到 else 分支
    assert fu["action"] == "no_action_unknown_kind"
    assert retry_calls == []


def test_prompt_failure_falls_back_to_task_market(monkeypatch):
    """prompt 类失败：fallback 到 task market。"""
    market_calls = []
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        lambda *a, **k: (
            market_calls.append((a, k)) or {"ok": True, "claimed": True, "employee_id": "vibe-1"}
        ),
    )

    results = _make_results("scout", "unexpected token in response")
    follow_ups = _follow_up_handler_failures(
        event_id=99,
        results=results,
        team_plan={"team": [{"employee_id": "scout-1", "role": "scout"}]},
        payload={"summary": "prompt bug"},
        event_type="on_error",
        source="unit",
        uid=1,
    )

    assert len(follow_ups) == 1
    fu = follow_ups[0]
    assert fu["failure_kind"] == "prompt"
    assert fu["action"] == "fallback_task_market"
    assert fu["ok"] is True
    assert fu["retry_result"] == {"ok": True, "claimed": True, "employee_id": "vibe-1"}
    assert len(market_calls) == 1
    # dispatch_incident_via_market 接收 event_id
    assert market_calls[0][0][0] == 99


def test_no_handler_failures_returns_empty_followups(monkeypatch):
    """全部 success 时 follow_ups 为空。"""
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "should_not_be_called"},
    )
    results = [
        {
            "employee_id": "scout-1",
            "role": "scout",
            "ok": True,
            "result": {"status": "success"},
        },
        {
            "employee_id": "fix-1",
            "role": "fix",
            "ok": True,
            "result": {"status": "success"},
        },
    ]
    follow_ups = _follow_up_handler_failures(
        event_id=1,
        results=results,
        team_plan={"team": []},
        payload={},
        event_type="",
        source="",
        uid=1,
    )
    assert follow_ups == []
    assert retry_calls == []


def test_multiple_handler_failures_each_get_followup(monkeypatch):
    """多个 handler_failed 各自得到一个 follow_up。"""
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: {"status": "success"},
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        lambda *a, **k: {"ok": True, "claimed": True, "employee_id": "vibe-1"},
    )
    results = [
        {
            "employee_id": "scout-1",
            "role": "scout",
            "ok": False,
            "result": {
                "status": "handler_failed",
                "handler_failed": True,
                "error": "500 internal error",
            },
        },
        {
            "employee_id": "fix-1",
            "role": "fix",
            "ok": False,
            "result": {
                "status": "handler_failed",
                "handler_failed": True,
                "error": "timeout",
            },
        },
        {
            "employee_id": "verify-1",
            "role": "verify",
            "ok": False,
            "result": {
                "status": "handler_failed",
                "handler_failed": True,
                "error": "403 forbidden",
            },
        },
    ]
    follow_ups = _follow_up_handler_failures(
        event_id=1,
        results=results,
        team_plan={"team": [{"employee_id": "x", "role": "scout"}]},
        payload={},
        event_type="",
        source="",
        uid=1,
    )
    assert len(follow_ups) == 3
    # 各自按 failure_kind 分流
    assert follow_ups[0]["failure_kind"] == "prompt"  # 500 internal error 不匹配 quota/transient
    assert follow_ups[1]["failure_kind"] == "transient"
    assert follow_ups[2]["failure_kind"] == "quota"


def test_dispatch_incident_team_writes_followups_to_payload(fresh_db, admin_user, monkeypatch):
    """集成测试：dispatch_incident_team 把 follow_ups 写到 _team_claim.follow_ups。"""
    # 准备一个 incident event
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps({"summary": "integration test"}),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        event_id = ev.id

    # 关键：让 execute_employee_task 返回 handler_failed + transient error
    def fake_execute(employee_id, task, env=None, user_id=0, **kwargs):
        if employee_id == "verify-1":
            return {
                "status": "handler_failed",
                "handler_failed": True,
                "error": "connection reset by peer 504",
            }
        return {"status": "success"}

    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.execute_employee_task",
        fake_execute,
    )
    # 让 build_incident_team 返回预定义 team
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.build_incident_team",
        lambda eid: {
            "candidates": ["scout-1", "fix-1", "verify-1"],
            "code_owner": "",
            "code_owner_match": {},
            "event_id": eid,
            "team": [
                {"employee_id": "scout-1", "role": "scout"},
                {"employee_id": "fix-1", "role": "fix"},
                {"employee_id": "verify-1", "role": "verify"},
            ],
        },
    )
    # 让 maybe_execute_recovery 直接返回 ok
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )
    # 让 _retry_member 也失败（保持 handler_failed）
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: {"status": "handler_failed", "error": "still transient"},
    )

    result = dispatch_incident_team(event_id)
    assert result["claimed"] is True
    assert "follow_ups" in result
    assert len(result["follow_ups"]) == 1
    fu = result["follow_ups"][0]
    assert fu["role"] == "verify"
    assert fu["failure_kind"] == "transient"
    assert fu["action"] == "transient_retry"
    assert fu["ok"] is False  # retry 仍失败

    # 验证 _team_claim.follow_ups 落库
    with sf() as s:
        ev2 = s.get(models.IncidentEvent, event_id)
        payload = json.loads(ev2.payload_json or "{}")
        assert "_team_claim" in payload
        assert "follow_ups" in payload["_team_claim"]
        assert len(payload["_team_claim"]["follow_ups"]) == 1
        assert payload["_team_claim"]["follow_ups"][0]["failure_kind"] == "transient"


def test_followup_can_be_disabled_via_env(fresh_db, admin_user, monkeypatch):
    """MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP=0 关闭闭环（旧行为）。"""
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP", "0")
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps({"summary": "disabled test"}),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        event_id = ev.id

    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.execute_employee_task",
        lambda *a, **k: {
            "status": "handler_failed",
            "handler_failed": True,
            "error": "timeout",
        },
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "should_not_be_called"},
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.build_incident_team",
        lambda eid: {
            "candidates": ["scout-1", "fix-1"],
            "code_owner": "",
            "code_owner_match": {},
            "event_id": eid,
            "team": [
                {"employee_id": "scout-1", "role": "scout"},
                {"employee_id": "fix-1", "role": "fix"},
            ],
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )

    result = dispatch_incident_team(event_id)
    assert result["follow_ups"] == []
    assert retry_calls == []
