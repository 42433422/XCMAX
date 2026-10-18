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


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_RETRY_BACKOFF_SEC", "0")


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
    from tests.test_customer_service_api import _make_user

    return _make_user("team-admin", admin=True)


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
    # transient_retry_limit=0 → 不重试，直接升级终极员工（不静默停摆）
    assert fu["action"] == "retry_disabled_escalated"
    assert fu["escalated_to"] == "ultimate_employee"
    assert retry_calls == []


def test_code_failure_retries_with_feedback_until_limit_then_escalates(monkeypatch):
    """代码问题：失败日志回喂再修，默认 3 轮，到上限升级终极员工；全程串行不并行。"""
    calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: calls.append(kw)
        or {
            "status": "handler_failed",
            "handler_failed": True,
            "error": "CI 失败：pytest 2 failed",
        },
    )
    follow_ups = _follow_up_handler_failures(
        event_id=99,
        results=_make_results("fix", "AssertionError in test_admin_ticket"),
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={"summary": "code bug"},
        event_type="on_error",
        source="unit",
        uid=1,
    )
    fu = follow_ups[0]
    assert fu["category"] == "code"
    assert fu["action"] == "code_retry_with_feedback"
    assert fu["attempts"] == 3 and len(calls) == 3
    assert calls[0]["feedback"].startswith("AssertionError")
    assert "CI 失败" in calls[1]["feedback"]
    assert fu["escalated_to"] == "ultimate_employee" and fu["need_human"] is True
    assert "3/3" in fu["reason"]


def test_code_retry_success_reruns_verify(monkeypatch):
    calls = []

    def retry(**kw):
        calls.append(kw["member"]["role"])
        return {"status": "success"}

    monkeypatch.setattr("modstore_server.incident_team_orchestrator._retry_member", retry)
    results = _make_results("fix", "SyntaxError: invalid syntax")
    results[2].update(ok=False, status="failed")
    follow_ups = _follow_up_handler_failures(
        event_id=7,
        results=results,
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={},
        event_type="on_error",
        source="unit",
        uid=1,
    )
    assert follow_ups[0]["ok"] is True and follow_ups[0]["escalated_to"] == ""
    assert calls == ["fix", "verify"]
    assert results[1]["ok"] is True and results[2]["ok"] is True


def test_environment_failure_backs_off(monkeypatch):
    from modstore_server import incident_team_failure_loop as loop

    sleeps = []
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_RETRY_BACKOFF_SEC", "5")
    monkeypatch.setattr(loop, "_sleep", sleeps.append)
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: {
            "status": "handler_failed",
            "handler_failed": True,
            "error": "401 Unauthorized",
        },
    )
    follow_ups = _follow_up_handler_failures(
        event_id=8,
        results=_make_results("fix", "para auth 401"),
        team_plan={"team": []},
        payload={},
        event_type="on_error",
        source="unit",
        uid=1,
    )
    assert follow_ups[0]["category"] == "environment"
    assert sleeps == [5, 10, 20]
    assert follow_ups[0]["escalated_to"] == "ultimate_employee"


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
    assert follow_ups[0]["category"] == "code"  # 500 internal error 不匹配 quota/transient
    assert follow_ups[1]["failure_kind"] == "transient"
    assert follow_ups[2]["failure_kind"] == "quota"


def test_dispatch_incident_team_writes_followups_to_payload(fresh_db, admin_user, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps(
                {
                    "summary": "integration test",
                    "support_bundle_base64": "A" * 60540,
                    "work_order_id": "WO-regression",
                }
            ),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        event_id = ev.id

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
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )
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
    assert fu["category"] == "environment"
    # 重试后的报错重新分类为代码问题 → 改走回喂再修；到上限升级终极员工
    assert fu["last_category"] == "code"
    assert fu["action"] == "code_retry_with_feedback"
    assert fu["ok"] is False  # retry 仍失败
    assert fu["attempts"] == 3 and fu["escalated_to"] == "ultimate_employee"

    with sf() as s:
        ev2 = s.get(models.IncidentEvent, event_id)
        payload = json.loads(ev2.payload_json or "{}")
        assert payload["support_bundle_base64"] == "A" * 60540
        assert payload["work_order_id"] == "WO-regression"
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


def test_fix_role_timeout_not_shorter_than_para_wait(monkeypatch):
    """工单40：修复岗外层超时不得早于 Para 等待窗口，其他岗位不变。"""
    from modstore_server.incident_team_orchestrator import _role_timeout_seconds

    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_ROLE_TIMEOUT_SECONDS", "480")
    monkeypatch.setenv("MODSTORE_PARA_WAIT_TIMEOUT_SEC", "1800")
    assert _role_timeout_seconds("scout") == 480
    assert _role_timeout_seconds("verify") == 480
    assert _role_timeout_seconds("fix") == 1920
    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_ROLE_TIMEOUT_SECONDS", "3600")
    assert _role_timeout_seconds("fix") == 3600


def test_role_timeout_is_not_retried(monkeypatch):
    """超时的岗位可能仍在跑：不得 transient 重派第二个 fix，交人工闭环。"""
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "success"},
    )
    follow_ups = _follow_up_handler_failures(
        event_id=40,
        results=_make_results("fix", "incident_team_role_timeout:480s"),
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={"summary": "test"},
        event_type="ops.intake.customer_ticket",
        source="pytest",
        uid=1,
    )
    assert [fu["action"] for fu in follow_ups] == ["role_timeout_no_retry_need_human"]
    assert follow_ups[0]["ok"] is False
    assert retry_calls == []


def test_fix_timeout_skips_verify_and_fails_closed(fresh_db, admin_user, monkeypatch):
    """修复岗超时：不跑 verify（避免假 FAIL），不重派 fix，整单失败闭环。"""
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps({"summary": "fix timeout"}),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        event_id = ev.id

    calls = []

    def fake_timeout(employee_id, task, runtime_input, **kwargs):
        calls.append((employee_id, kwargs["timeout_seconds"]))
        if employee_id == "fix-1":
            return {
                "ok": False,
                "handler_failed": True,
                "status": "handler_failed",
                "error": "incident_team_role_timeout:1920s",
                "failure_kind": "transient",
            }
        return {"status": "success"}

    monkeypatch.setenv("MODSTORE_INCIDENT_TEAM_ROLE_TIMEOUT_SECONDS", "480")
    monkeypatch.setenv("MODSTORE_PARA_WAIT_TIMEOUT_SEC", "1800")
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._execute_employee_task_with_timeout",
        fake_timeout,
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.build_incident_team",
        lambda eid: {
            "event_id": eid,
            "code_owner_match": {},
            "team": [
                {"employee_id": "scout-1", "role": "scout"},
                {"employee_id": "fix-1", "role": "fix"},
                {"employee_id": "verify-1", "role": "verify"},
            ],
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )
    retry_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "success"},
    )

    result = dispatch_incident_team(event_id)
    assert result["ok"] is False
    assert calls == [("scout-1", 480), ("fix-1", 1920)]
    assert retry_calls == []
    by_role = {row["role"]: row for row in result["results"]}
    assert by_role["verify"]["status"] == "skipped_fix_unfinished"
    assert [fu["action"] for fu in result["follow_ups"]] == ["role_timeout_no_retry_need_human"]


def test_classify_distinguishes_role_timeout_model_unsupported_transient():
    from modstore_server.llm_failure_classifier import (
        FAILURE_KIND_MODEL_UNSUPPORTED,
        FAILURE_KIND_ROLE_TIMEOUT,
        FAILURE_KIND_TRANSIENT,
        classify_failure_kind,
    )

    assert classify_failure_kind("incident_team_role_timeout:480s") == FAILURE_KIND_ROLE_TIMEOUT
    assert (
        classify_failure_kind(
            "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."
        )
        == FAILURE_KIND_MODEL_UNSUPPORTED
    )
    assert classify_failure_kind("connection reset by peer 504") == FAILURE_KIND_TRANSIENT


def test_model_unsupported_is_not_retried(monkeypatch):
    """模型不支持应交降级层，不得同模型重派第二个 fix。"""
    retry_calls = []
    market_calls = []
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator._retry_member",
        lambda **kw: retry_calls.append(kw) or {"status": "success"},
    )
    monkeypatch.setattr(
        "modstore_server.employee_task_market.dispatch_incident_via_market",
        lambda eid: market_calls.append(eid) or {"ok": True, "claimed": True},
    )
    follow_ups = _follow_up_handler_failures(
        event_id=40,
        results=_make_results(
            "fix",
            "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.",
        ),
        team_plan={"team": [{"employee_id": "fix-1", "role": "fix"}]},
        payload={"summary": "test"},
        event_type="ops.intake.customer_ticket",
        source="pytest",
        uid=1,
    )
    assert [fu["action"] for fu in follow_ups] == ["model_unsupported_need_fallback"]
    assert follow_ups[0]["failure_kind"] == "model_unsupported"
    assert follow_ups[0]["ok"] is False
    assert retry_calls == []
    assert market_calls == []


def test_model_fallback_hook_used_when_gateway_present(monkeypatch):
    import sys
    import types

    gateway = types.ModuleType("modstore_server.model_fallback_gateway")
    seen = []
    gateway.request_fallback = lambda **kw: seen.append(kw) or {
        "ok": True,
        "model": "gpt-5.6-terra",
    }
    monkeypatch.setitem(sys.modules, "modstore_server.model_fallback_gateway", gateway)
    follow_ups = _follow_up_handler_failures(
        event_id=40,
        results=_make_results("fix", "The 'gpt-6.1-sol' model is not supported when using Codex"),
        team_plan={"team": []},
        payload={},
        event_type="ops.intake.customer_ticket",
        source="pytest",
        uid=1,
    )
    assert follow_ups[0]["action"] == "model_fallback_requested"
    assert follow_ups[0]["ok"] is True and follow_ups[0]["escalated_to"] == ""
    assert seen and seen[0]["role"] == "fix"


def test_failure_text_reads_nested_para_error():
    from modstore_server.incident_team_failure_loop import categorize, failure_text

    text = failure_text(
        {
            "handler_failed": True,
            "result": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "error": "",
                        "para_result": {"subtasks": [{"last_error": "Not logged in"}]},
                    }
                ]
            },
        }
    )
    assert text == "Not logged in"
    assert categorize(text)[1] == "environment"


def test_repair_loop_written_to_ticket_admin_only(fresh_db, admin_user):
    """分类、次数、原因、升级回写工单证据与审计；客户视图白名单不含 repair_loop。"""
    from modstore_server.customer_service_customer_view import customer_ticket
    from modstore_server.incident_team_dispatch import _write_repair_loop
    from modstore_server.models_cs import (
        CustomerServiceAuditLog,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    sf = models.get_session_factory()
    with sf() as s:
        owner = s.query(models.User).first()
        cs = CustomerServiceSession(user_id=owner.id)
        s.add(cs)
        s.flush()
        ticket = CustomerServiceTicket(
            ticket_no="CS-LOOP",
            session_id=cs.id,
            user_id=owner.id,
            title="t",
            summary="s",
            intent="product_issue",
            status="processing",
            evidence_json="{}",
        )
        s.add(ticket)
        s.flush()
        fu = {
            "role": "fix",
            "category": "code",
            "failure_kind": "prompt",
            "attempts": 3,
            "max_rounds": 3,
            "action": "code_retry_with_feedback",
            "ok": False,
            "escalated_to": "ultimate_employee",
            "reason": "code 失败，已自动处理 3/3 轮未恢复：CI 失败",
        }
        _write_repair_loop(s, ticket, 40, [fu])
        s.commit()
        evidence = json.loads(ticket.evidence_json)
        item = evidence["repair_loop"]["items"][0]
        assert item["category"] == "code" and item["attempts"] == 3
        assert item["escalated_to"] == "ultimate_employee"
        log = s.query(CustomerServiceAuditLog).filter_by(ticket_id=ticket.id).one()
        assert log.event_type == "incident.repair_loop_escalated"
        assert "repair_loop" not in customer_ticket({"evidence": evidence})["evidence"]
