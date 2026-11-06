"""B31–B82 工单闭环里可在本地 API 上复核的行为。

创建工单不等于闭环。这里核对分类、真实工具读库、审批闸门和未核验不得关闭。
"""

from __future__ import annotations

import uuid
from threading import enumerate as live_threads

import pytest

pytest.importorskip("fastapi")

from modstore_server import customer_issue_api, customer_service_api  # noqa: E402
from modstore_server.app import app  # noqa: E402
from modstore_server.models import get_session_factory  # noqa: E402

BASE = "/api/customer-service"


@pytest.fixture(autouse=True)
def isolate_customer_ticket_workers(monkeypatch):
    from modstore_server import incident_bus

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    monkeypatch.setenv("MODSTORE_INCIDENT_SYNC_DISPATCH", "1")
    monkeypatch.setattr(incident_bus, "_dispatch_incident", lambda _event_id: None)
    yield
    for worker in live_threads():
        if worker.name == "cs-ticket-incident":
            worker.join(timeout=5)


def _user(username: str, *, admin: bool = False):
    from modstore_server.models import User

    username = f"{username}_{uuid.uuid4().hex[:8]}"
    with get_session_factory()() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
            is_admin=admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def _as(user):
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    app.dependency_overrides[customer_issue_api.get_current_user] = lambda: user
    if user.is_admin:
        app.dependency_overrides[customer_service_api._require_admin] = lambda: user
    else:
        app.dependency_overrides.pop(customer_service_api._require_admin, None)


def _clear_auth():
    app.dependency_overrides.pop(customer_service_api._get_current_user, None)
    app.dependency_overrides.pop(customer_issue_api.get_current_user, None)
    app.dependency_overrides.pop(customer_service_api._require_admin, None)


def _chat(client, user, message, **extra):
    _as(user)
    response = client.post(f"{BASE}/chat", json={"message": message, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _open_product(client, user, message):
    opened = _chat(client, user, message)
    assert opened["ticket"] is None
    assert opened["intent"]["intent"] == "product_issue"
    submitted = _chat(
        client, user, "提交工单", session_id=opened["session"]["id"], context={}
    )
    assert submitted["ticket"]["intent"] == "product_issue"
    assert submitted["ticket"]["status"] == "processing"
    return submitted


def test_b32_b33_technical_cases_are_not_account(monkeypatch):
    from modstore_server.customer_service_orchestrator import (
        classify_customer_intent,
        extract_fields,
    )

    cases = {
        "员工图谱无法正常显示": "product_issue",
        "登录后员工图谱无法显示": "product_issue",
        "页面加载失败": "product_issue",
        "工具无法调用": "product_issue",
        "AI 工具调用失败": "product_issue",
        "Excel 导入异常": "product_issue",
        "软件异常打不开": "product_issue",
        "账号登录后余额不对": "account_support",
        "账户余额或充值未到账": "account_support",
    }
    for text, expected in cases.items():
        out = classify_customer_intent(
            text, extract_fields(text, {}), context={"scene": "account"}
        )
        assert out["intent"] == expected, text
        if expected == "product_issue":
            assert out["intent"] != "account_support"


def test_b34_mixed_issue_stays_pending_verification():
    from modstore_server.customer_service_orchestrator import (
        classify_customer_intent,
        extract_fields,
    )

    text = "账户余额没到账，同时员工图谱无法显示"
    out = classify_customer_intent(text, extract_fields(text, {}), context={"scene": "account"})
    assert out["intent"] == "general"
    assert out["classification_status"] == "pending_verification"
    assert out["intent"] != "account_support"


def test_b31_b35_b36_submit_preserves_content_and_dedupes(client):
    user = _user("loop_owner")
    try:
        first = _open_product(client, user, "员工图谱无法正常显示")
        ticket = first["ticket"]
        assert ticket["ticket_no"]
        assert "员工图谱" in (ticket.get("summary") or ticket.get("title") or "")
        again = _chat(
            client,
            user,
            "员工图谱无法正常显示，请提交工单",
            session_id=ticket["session_id"],
        )
        assert again["ticket"]["id"] == ticket["id"]
        assert again["ticket"]["ticket_no"] == ticket["ticket_no"]
        with get_session_factory()() as session:
            from modstore_server.models_cs import CustomerServiceTicket

            rows = (
                session.query(CustomerServiceTicket)
                .filter(CustomerServiceTicket.user_id == user.id)
                .all()
            )
        assert len(rows) == 1
        assert "员工图谱无法正常显示" in (rows[0].summary or "")
    finally:
        _clear_auth()


def test_b37_b40_admin_sees_ticket_and_other_callers_do_not(client):
    owner = _user("loop_owner")
    other = _user("loop_other")
    admin = _user("loop_admin", admin=True)
    try:
        opened = _open_product(client, owner, "工具无法调用")
        ticket_id = opened["ticket"]["id"]
        _as(admin)
        listed = client.get(f"{BASE}/tickets")
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == ticket_id for item in listed.json()["items"])
        detail = client.get(f"{BASE}/tickets/{ticket_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["ticket"]["id"] == ticket_id
        assert "工具无法调用" in (body["ticket"].get("summary") or "")
        kinds = {row["action_type"] for row in body["actions"]}
        assert {"ticket.diagnose", "ticket.report_diagnosis"} <= kinds
        diagnose = next(row for row in body["actions"] if row["action_type"] == "ticket.diagnose")
        assert diagnose["status"] == "completed"
        assert diagnose["result"]["executed"] is True
        assert diagnose["result"]["ticket_no"] == body["ticket"]["ticket_no"]
        assert "已记录客服处理建议" not in str(diagnose["result"])
        report = next(
            row for row in body["actions"] if row["action_type"] == "ticket.report_diagnosis"
        )
        assert report["result"]["ticket_no"] == diagnose["result"]["ticket_no"]
        _as(other)
        hidden = client.get(f"{BASE}/tickets/{ticket_id}")
        assert hidden.status_code in {403, 404}
        _clear_auth()
        anon = client.get(f"{BASE}/tickets")
        assert anon.status_code == 401
    finally:
        _clear_auth()


def test_b43_b53_b64_product_ticket_is_not_closed_by_diagnosis(client):
    user = _user("loop_diag")
    try:
        opened = _open_product(client, user, "员工图谱无法正常显示")
        assert opened["ticket"]["status"] == "processing"
        assert opened["ticket"].get("closed_at") in (None, "")
        kinds = {row["action_type"] for row in opened["actions"]}
        assert "ticket.diagnose" in kinds
        assert "已解决" not in opened["message"]["content"]
    finally:
        _clear_auth()


def test_b47_distinct_tickets_do_not_share_ids(client):
    messages = [
        "员工图谱无法正常显示",
        "工具无法调用",
        "Excel 导入异常",
        "页面加载失败",
        "软件异常打不开",
        "AI 工具调用失败",
        "按钮没反应点不了",
        "白屏打不开首页",
        "导入失败无法写入",
        "调用失败报错",
    ]
    ids = set()
    try:
        for index, message in enumerate(messages):
            opened = _open_product(client, _user(f"loop_{index}"), message)
            ids.add(opened["ticket"]["id"])
            assert opened["ticket"]["intent"] == "product_issue"
        assert len(ids) == len(messages)
    finally:
        _clear_auth()


def test_b49_b52_b55_unknown_or_bad_tool_call_is_rejected(client):
    from modstore_server.customer_service_tools import build_action, execute_action, json_loads

    user = _user("loop_tool")
    try:
        opened = _open_product(client, user, "工具无法调用")
        ticket_id = opened["ticket"]["id"]
        with get_session_factory()() as session:
            db_user = session.get(type(user), user.id)
            unknown = build_action(
                session,
                ticket_id=ticket_id,
                user_id=user.id,
                action_type="ticket.missing_tool",
                target_type="tool",
                target_id="missing",
                request={"ticket_id": ticket_id},
            )
            execute_action(session, unknown, db_user)
            bad = build_action(
                session,
                ticket_id=ticket_id,
                user_id=user.id,
                action_type="ticket.diagnose",
                target_type="ticket",
                target_id="not-this-ticket",
                request={"ticket_id": "abc", "user_id": user.id, "file_path": "../secrets"},
            )
            execute_action(session, bad, db_user)
            denied = build_action(
                session,
                ticket_id=ticket_id,
                user_id=user.id,
                action_type="ticket.report_diagnosis",
                target_type="ticket",
                target_id="denied",
                request={
                    "ticket_id": ticket_id,
                    "ticket_no": opened["ticket"]["ticket_no"],
                    "granted": False,
                },
            )
            execute_action(session, denied, db_user)
            session.commit()
            assert unknown.status == "failed"
            assert json_loads(unknown.result_json, {})["code"] == "tool_unregistered"
            assert bad.status == "failed"
            assert json_loads(bad.result_json, {})["executed"] is False
            assert denied.status == "failed"
            assert json_loads(denied.result_json, {})["code"] == "tool_forbidden"
    finally:
        _clear_auth()


def test_b56_b61_sensitive_change_requires_one_approval(client):
    from modstore_server.customer_service_tools import (
        build_action,
        execute_action,
        json_dumps,
        json_loads,
    )

    user = _user("loop_approve")
    try:
        opened = _open_product(client, user, "员工图谱无法正常显示")
        ticket_id = opened["ticket"]["id"]
        with get_session_factory()() as session:
            db_user = session.get(type(user), user.id)
            waiting = build_action(
                session,
                ticket_id=ticket_id,
                user_id=user.id,
                action_type="ticket.apply_change",
                target_type="config",
                target_id="display",
                request={"change": {"enabled": False}},
            )
            execute_action(session, waiting, db_user)
            assert waiting.status == "waiting_approval"
            assert json_loads(waiting.result_json, {})["executed"] is False
            waiting.request_json = json_dumps(
                {
                    "change": {"enabled": False},
                    "approval": {"decision": "approved", "id": "ap-once"},
                }
            )
            execute_action(session, waiting, db_user)
            assert waiting.status == "completed"
            first = waiting.result_json
            execute_action(session, waiting, db_user)
            assert waiting.result_json == first
            rejected = build_action(
                session,
                ticket_id=ticket_id,
                user_id=user.id,
                action_type="ticket.apply_change",
                target_type="config",
                target_id="delete",
                request={
                    "change": {"delete": True},
                    "approval": {"decision": "rejected", "id": "ap-no"},
                },
            )
            execute_action(session, rejected, db_user)
            assert rejected.status == "failed"
            rejected.request_json = json_dumps(
                {
                    "change": {"delete": True},
                    "approval": {"decision": "approved", "id": "ap-bypass"},
                }
            )
            execute_action(session, rejected, db_user)
            assert rejected.status == "failed"
            assert json_loads(rejected.result_json, {})["executed"] is False
            session.commit()
    finally:
        _clear_auth()


def test_b71_b74_unverified_product_ticket_cannot_close(client):
    owner = _user("loop_close")
    admin = _user("loop_close_admin", admin=True)
    try:
        opened = _open_product(client, owner, "员工图谱无法正常显示")
        ticket_id = opened["ticket"]["id"]
        _as(owner)
        decision = client.post(
            f"{BASE}/issues/{ticket_id}/decision",
            json={
                "decision": "resolved",
                "note": "我还没复现成功",
                "idempotency_key": "loop-close-001",
            },
        )
        assert decision.status_code == 409, decision.text
        reopen = client.post(
            f"{BASE}/issues/{ticket_id}/decision",
            json={
                "decision": "reopen",
                "note": "问题还在",
                "idempotency_key": "loop-reopen-001",
            },
        )
        assert reopen.status_code == 409, reopen.text
        _as(admin)
        closed = client.post(
            f"{BASE}/tickets/{ticket_id}/close",
            json={
                "request_id": str(uuid.uuid4()),
                "note": "管理员试图直接关闭工单",
                "verification": (
                    "没有复现员工图谱，只写了一段验收说明，不能当成已解决。"
                ),
            },
        )
        assert closed.status_code == 409, closed.text
        _as(owner)
        still = client.get(f"{BASE}/tickets/{ticket_id}")
        assert still.json()["ticket"]["status"] == "processing"
    finally:
        _clear_auth()


def test_b34_mixed_submission_waits_instead_of_account_close(client):
    user = _user("loop_mixed")
    try:
        data = _chat(
            client,
            user,
            "账户余额没到账，同时员工图谱无法显示，请提交工单",
        )
        assert data["ticket"]["intent"] == "general"
        assert data["ticket"]["status"] == "waiting_user"
        assert data["intent"]["classification_status"] == "pending_verification"
        assert data["ticket"]["title"] == "待核实问题"
        assert data["actions"] == []
    finally:
        _clear_auth()
