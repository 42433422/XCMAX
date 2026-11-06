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
    from modstore_server.customer_ticket_loop import reset_hooks

    reset_hooks()
    yield
    reset_hooks()
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
    submitted = _chat(client, user, "提交工单", session_id=opened["session"]["id"], context={})
    assert submitted["ticket"]["intent"] == "product_issue"
    assert submitted["ticket"]["status"] == "open"
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
        out = classify_customer_intent(text, extract_fields(text, {}), context={"scene": "account"})
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
        assert opened["ticket"]["status"] == "open"
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
    from modstore_server.customer_service_tools import (
        build_action,
        execute_action,
        json_loads,
    )

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
                request={
                    "ticket_id": "abc",
                    "user_id": user.id,
                    "file_path": "../secrets",
                },
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
            assert waiting.status == "pending_execution"
            assert json_loads(waiting.result_json, {})["executed"] is False
            assert json_loads(waiting.result_json, {})["approval_granted"] is True
            assert json_loads(waiting.result_json, {})["verified"] is False
            first = waiting.result_json
            execute_action(session, waiting, db_user)
            assert waiting.result_json == first
            assert waiting.status == "pending_execution"
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
            assert rejected.status == "rejected"
            rejected.status = "pending"
            rejected.request_json = json_dumps(
                {
                    "change": {"delete": True},
                    "approval": {"decision": "approved", "id": "ap-bypass"},
                    "consumed_approval_id": "ap-no",
                }
            )
            execute_action(session, rejected, db_user)
            assert rejected.status == "rejected"
            assert json_loads(rejected.result_json, {})["executed"] is False
            session.commit()
    finally:
        _clear_auth()


def _decide(client, ticket_id, decision, key):
    return client.post(
        f"{BASE}/issues/{ticket_id}/decision",
        json={
            "decision": decision,
            "note": "问题仍未消失，不能当成已经修好",
            "idempotency_key": key,
        },
    )


def _admin_close(client, ticket_id):
    return client.post(
        f"{BASE}/tickets/{ticket_id}/close",
        json={
            "request_id": str(uuid.uuid4()),
            "note": "管理员试图直接关闭工单",
            "verification": "没有复现员工图谱，只写了一段验收说明，不能当成已解决。",
        },
    )


def test_b71_b74_failed_verification_cannot_close(client):
    from modstore_server.customer_ticket_loop import HOOKS

    owner = _user("loop_close")
    admin = _user("loop_close_admin", admin=True)
    try:
        HOOKS["fail_verify"] = True
        opened = _chat(client, owner, "员工图谱无法正常显示")
        submitted = _chat(client, owner, "提交工单", session_id=opened["session"]["id"])
        ticket_id = submitted["ticket"]["id"]
        assert submitted["ticket"]["status"] == "failed"
        _as(owner)
        assert _decide(client, ticket_id, "resolved", "loop-close-001").status_code == 409
        _as(admin)
        assert _admin_close(client, ticket_id).status_code == 409
        _as(owner)
        assert client.get(f"{BASE}/tickets/{ticket_id}").json()["ticket"]["status"] == "failed"
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


def test_graph_account_and_tool_lanes_use_different_employees(client):
    owner = _user("loop_lanes")
    admin = _user("loop_lanes_admin", admin=True)
    try:
        graph = _open_product(client, owner, "员工图谱无法正常显示")
        _as(owner)
        visible = client.get(f"{BASE}/tickets/{graph['ticket']['id']}").json()["ticket"]
        assert visible["evidence"]["loop_public"]["employee_id"] == "emp.software"
        assert visible["evidence"]["loop_public"]["verified"] is True
        assert "尚未结案" in graph["message"]["content"]
        assert "已解决" not in graph["message"]["content"]
        tool_user = _user("loop_tool_lane")
        tool = _open_product(client, tool_user, "AI 工具调用失败")
        _as(admin)
        detail = client.get(f"{BASE}/tickets/{tool['ticket']['id']}").json()
        assert detail["ticket"]["evidence"]["loop_public"]["employee_id"] == "emp.ai_tools"
        registry = next(row for row in detail["actions"] if row["action_type"] == "tool.registry")
        assert registry["result"]["executed"] is True
        assert registry["result"]["registered"] is True
        balance_user = _user("loop_balance")
        filed = _chat(client, balance_user, "账户余额或充值未到账，请提交工单")
        assert filed["ticket"]["intent"] == "account_support"
        assert filed["ticket"]["status"] == "waiting_user"
        _as(admin)
        account = client.get(f"{BASE}/tickets/{filed['ticket']['id']}").json()
        assert account["ticket"]["evidence"]["loop"]["employee_id"] == "emp.account"
        lookup = next(row for row in account["actions"] if row["action_type"] == "account.lookup")
        assert lookup["result"]["executed"] is True
        assert lookup["result"]["mutated"] is False
        assert "ticket.apply_change" not in {row["action_type"] for row in account["actions"]}
        assert _admin_close(client, filed["ticket"]["id"]).status_code == 409
        assert account["ticket"]["status"] == "waiting_user"
    finally:
        _clear_auth()


def test_customer_confirms_only_after_verification_and_reopen_keeps_history(client):
    owner = _user("loop_confirm")
    admin = _user("loop_confirm_admin", admin=True)
    try:
        opened = _open_product(client, owner, "员工图谱无法正常显示")
        ticket_id = opened["ticket"]["id"]
        reviewer = _user("loop_confirm_reviewer", admin=True)
        _as(admin)
        assert _admin_close(client, ticket_id).status_code == 409
        _as(owner)
        assert _decide(client, ticket_id, "resolved", "loop-confirm-early").status_code == 409
        _as(admin)
        assert (
            client.post(
                f"{BASE}/tickets/{ticket_id}/assign",
                json={"assignee_id": admin.id, "reason": "指派给诊断人"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"{BASE}/tickets/{ticket_id}/accept",
                json={"reason": "开始核查"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"{BASE}/tickets/{ticket_id}/diagnose",
                json={"reason": "画面仍需另一位管理员复测"},
            ).status_code
            == 200
        )
        _as(reviewer)
        ready = client.post(
            f"{BASE}/tickets/{ticket_id}/result",
            json={"text": "复测通过，待客户确认", "fault_remains": False},
        )
        assert ready.status_code == 200, ready.text
        _as(owner)
        assert _decide(client, ticket_id, "resolved", "loop-confirm").status_code == 200
        assert client.get(f"{BASE}/tickets/{ticket_id}").json()["ticket"]["status"] == "resolved"
        reopened = _decide(client, ticket_id, "reopen", "loop-reopen")
        assert reopened.status_code == 200, reopened.text
        assert client.get(f"{BASE}/tickets/{ticket_id}").json()["ticket"]["status"] == "processing"
        assert _decide(client, ticket_id, "resolved", "loop-confirm-again").status_code == 409
        _as(admin)
        detail = client.get(f"{BASE}/tickets/{ticket_id}").json()
        assert detail["ticket"]["evidence"]["reopen_history"]
        assert any(row["action_type"] == "ticket.diagnose" for row in detail["actions"])
        audit = client.get(f"{BASE}/tickets/{ticket_id}/audit").json()
        seqs = [item["seq"] for item in audit["timeline"]]
        assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
        assert audit["task_id"].startswith("TSK")
        assert audit["employee_id"] == "emp.software"
        assert audit["actions"]
        _as(_user("loop_stranger"))
        assert client.get(f"{BASE}/tickets/{ticket_id}/audit").status_code in {403, 404}
    finally:
        _clear_auth()


def test_offline_employee_can_be_rescheduled_without_dropping_the_ticket(client):
    from modstore_server.customer_ticket_loop import HOOKS

    owner = _user("loop_offline")
    admin = _user("loop_offline_admin", admin=True)
    try:
        HOOKS["offline"].add("emp.software")
        opened = _chat(client, owner, "Excel 导入异常")
        filed = _chat(client, owner, "提交工单", session_id=opened["session"]["id"])
        ticket_id = filed["ticket"]["id"]
        assert filed["ticket"]["status"] == "pending_assignment"
        _as(admin)
        first = client.get(f"{BASE}/tickets/{ticket_id}").json()
        assert first["ticket"]["evidence"]["loop"]["task_id"]
        before = len(first["actions"])
        stayed = client.post(f"{BASE}/tickets/{ticket_id}/loop/resume")
        assert stayed.status_code == 409, stayed.text
        assert len(client.get(f"{BASE}/tickets/{ticket_id}").json()["actions"]) == before
        HOOKS["offline"].clear()
        resumed = client.post(f"{BASE}/tickets/{ticket_id}/loop/resume")
        assert resumed.status_code == 200, resumed.text
        after = client.get(f"{BASE}/tickets/{ticket_id}").json()
        assert after["ticket"]["status"] == "processing"
        assert (
            after["ticket"]["evidence"]["loop"]["task_id"]
            == first["ticket"]["evidence"]["loop"]["task_id"]
        )
        assert any(
            row["action_type"] == "ticket.diagnose" and row["status"] == "completed"
            for row in after["actions"]
        )
        assert client.post(f"{BASE}/tickets/{ticket_id}/loop/resume").status_code == 409
    finally:
        _clear_auth()


def test_sensitive_write_waits_for_one_approval(client):
    owner = _user("loop_gate")
    admin = _user("loop_gate_admin", admin=True)
    try:
        opened = _chat(client, owner, "员工图谱无法显示，请删除页面配置")
        filed = _chat(client, owner, "提交工单", session_id=opened["session"]["id"])
        ticket_id = filed["ticket"]["id"]
        assert filed["ticket"]["status"] == "waiting_approval"
        _as(admin)
        waiting = client.get(f"{BASE}/tickets/{ticket_id}").json()
        change = next(
            row for row in waiting["actions"] if row["action_type"] == "ticket.apply_change"
        )
        assert change["status"] == "waiting_approval"
        assert change["result"]["executed"] is False
        _as(owner)
        assert _decide(client, ticket_id, "resolved", "gate-close").status_code == 409
        _as(admin)
        approved = client.post(
            f"{BASE}/tickets/{ticket_id}/loop/approve",
            json={"approval_id": "ap-loop-1"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["changed"] is True
        again = client.post(
            f"{BASE}/tickets/{ticket_id}/loop/approve",
            json={"approval_id": "ap-loop-2"},
        )
        assert again.json()["changed"] is False
        detail = client.get(f"{BASE}/tickets/{ticket_id}").json()
        done = [row for row in detail["actions"] if row["action_type"] == "ticket.apply_change"]
        assert len(done) == 1
        assert done[0]["status"] == "pending_execution"
        assert done[0]["result"]["executed"] is False
        assert done[0]["result"]["approval_granted"] is True
        assert done[0]["result"]["verified"] is False
        assert done[0]["result"]["approval_id"] == "ap-loop-1"
    finally:
        _clear_auth()


def test_restart_timeout_and_repeat_do_not_double_write(client):
    from modstore_server.customer_ticket_loop import HOOKS, recover_ticket_loop
    from modstore_server.models import User
    from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

    owner = _user("loop_recover")
    try:
        HOOKS["pause_after"] = "ticket.read"
        opened = _chat(client, owner, "页面加载失败")
        filed = _chat(client, owner, "提交工单", session_id=opened["session"]["id"])
        ticket_id = filed["ticket"]["id"]
        assert filed["ticket"]["status"] == "open"
        with get_session_factory()() as session:
            paused = session.query(CustomerServiceAction).filter_by(ticket_id=ticket_id).count()
        HOOKS["pause_after"] = ""
        HOOKS["stale"] = True
        with get_session_factory()() as session:
            ticket = session.get(CustomerServiceTicket, ticket_id)
            user = session.get(User, owner.id)
            assert recover_ticket_loop(session, ticket, user)
            session.commit()
            assert ticket.status == "failed"
            assert (
                session.query(CustomerServiceAction).filter_by(ticket_id=ticket_id).count()
                == paused
            )
        with get_session_factory()() as session:
            ticket = session.get(CustomerServiceTicket, ticket_id)
            ticket.status = "processing"
            evidence = __import__("json").loads(ticket.evidence_json)
            evidence["loop"]["state"] = "processing"
            evidence["loop"]["verified"] = False
            ticket.evidence_json = __import__("json").dumps(evidence, ensure_ascii=False)
            session.commit()
        HOOKS["stale"] = False
        with get_session_factory()() as session:
            ticket = session.get(CustomerServiceTicket, ticket_id)
            user = session.get(User, owner.id)
            recover_ticket_loop(session, ticket, user)
            session.commit()
            reads = (
                session.query(CustomerServiceAction)
                .filter_by(ticket_id=ticket_id, action_type="ticket.read")
                .count()
            )
            assert reads == 1
            assert ticket.status == "processing"
            again = len(recover_ticket_loop(session, ticket, user))
            session.commit()
            assert (
                session.query(CustomerServiceAction).filter_by(ticket_id=ticket_id).count() == again
            )
    finally:
        _clear_auth()


def test_supplement_reply_and_capability_checks(client):
    from modstore_server.customer_service_tools import (
        build_action,
        execute_action,
        json_loads,
    )
    from modstore_server.models import User

    owner = _user("loop_extra")
    other = _user("loop_extra_other")
    admin = _user("loop_extra_admin", admin=True)
    try:
        opened = _open_product(client, owner, "软件异常打不开")
        ticket_id = opened["ticket"]["id"]
        session_id = opened["ticket"]["session_id"]
        _as(owner)
        added = client.post(
            f"{BASE}/tickets/{ticket_id}/supplement",
            json={"note": "补充：刷新后窗口仍然空白", "attachment_name": "blank.png"},
        )
        assert added.status_code == 200, added.text
        bad = client.post(
            f"{BASE}/tickets/{ticket_id}/supplement",
            json={"note": "补充路径不对", "attachment_name": "../secret.txt"},
        )
        assert bad.status_code == 422
        _as(other)
        assert client.post(
            f"{BASE}/tickets/{ticket_id}/supplement",
            json={"note": "别人的补充说明"},
        ).status_code in {403, 404}
        _as(admin)
        replied = client.post(
            f"{BASE}/tickets/{ticket_id}/reply",
            json={"request_id": str(uuid.uuid4()), "note": "已看到你补充的空白截图"},
        )
        assert replied.status_code == 200, replied.text
        _as(owner)
        messages = client.get(f"{BASE}/sessions/{session_id}").json()["messages"]
        assert any("空白截图" in (item.get("content") or "") for item in messages)
        _as(admin)
        stored = client.get(f"{BASE}/tickets/{ticket_id}").json()
        notes = stored["ticket"]["evidence"]["loop"]["supplements"]
        assert notes[-1]["note"].startswith("补充")
        assert stored["ticket"]["evidence"]["loop"]["notified_employee_id"] == "emp.software"
        with get_session_factory()() as session:
            db_user = session.get(User, owner.id)
            wrong = build_action(
                session,
                ticket_id=ticket_id,
                user_id=owner.id,
                action_type="ticket.assign",
                target_type="ticket",
                target_id="wrong-employee",
                request={
                    "ticket_id": ticket_id,
                    "user_id": owner.id,
                    "employee_id": "emp.account",
                    "lane": "software",
                    "online": True,
                },
            )
            execute_action(session, wrong, db_user)
            missing = build_action(
                session,
                ticket_id=ticket_id,
                user_id=owner.id,
                action_type="ticket.observe_status",
                target_type="ticket",
                target_id="no-prior",
                request={
                    "ticket_id": ticket_id,
                    "user_id": other.id,
                    "employee_id": "emp.software",
                },
            )
            execute_action(session, missing, db_user)
            session.commit()
            assert json_loads(wrong.result_json, {})["code"] == "employee_unqualified"
            assert json_loads(missing.result_json, {})["code"] in {
                "missing_dependency",
                "user_mismatch",
            }
    finally:
        _clear_auth()


def test_session_stays_usable_and_ticket_reads_do_not_return_502(client):
    owner = _user("loop_session")
    try:
        opened = _open_product(client, owner, "白屏打不开首页")
        _as(owner)
        assert client.get(f"{BASE}/sessions").status_code == 200
        assert client.get(f"{BASE}/sessions/{opened['ticket']['session_id']}").status_code == 200
        for _ in range(2):
            response = client.get(f"{BASE}/tickets/{opened['ticket']['id']}")
            assert response.status_code == 200
        _clear_auth()
        assert client.get(f"{BASE}/tickets").status_code == 401
    finally:
        _clear_auth()
