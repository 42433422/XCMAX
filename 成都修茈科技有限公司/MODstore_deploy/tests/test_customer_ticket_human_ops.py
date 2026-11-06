"""Unassigned tickets stay open until a named admin accepts them."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from modstore_server import customer_service_api  # noqa: E402
from modstore_server.app import app  # noqa: E402
from modstore_server.models import User, get_session_factory  # noqa: E402
from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket  # noqa: E402


def _user(*, admin: bool) -> User:
    name = f"human_{uuid.uuid4().hex[:8]}"
    with get_session_factory()() as db:
        user = User(username=name, email=f"{name}@pytest.local", password_hash="x", is_admin=admin)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def _ticket(owner: User) -> int:
    with get_session_factory()() as db:
        session = CustomerServiceSession(user_id=owner.id, channel="customer_issue_intake")
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=owner.id,
            session_id=session.id,
            ticket_no=f"CI{uuid.uuid4().hex}",
            title="客户端产品缺陷 · 员工图谱无法显示",
            summary="登录后员工节点无法显示。步骤：打开员工图谱。期望：有节点。实际：暂无员工。",
            intent="product_issue",
            status="open",
            decision_status="pending",
        )
        db.add(ticket)
        db.commit()
        return int(ticket.id)


def _as(user: User):
    from fastapi import HTTPException

    from modstore_server import customer_issue_api
    from modstore_server.api import deps

    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[customer_issue_api.get_current_user] = lambda: user

    def gate():
        if not getattr(user, "is_admin", False):
            raise HTTPException(403, "需要管理员")
        return user

    app.dependency_overrides[customer_service_api._require_admin] = gate


def test_human_loop_blocks_false_close_and_keeps_history(client):
    customer = _user(admin=False)
    first = _user(admin=True)
    second = _user(admin=True)
    outsider = _user(admin=False)
    ticket_id = _ticket(customer)
    http = TestClient(app)

    _as(outsider)
    denied = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": first.id, "reason": "普通客户不能指派"},
    )
    assert denied.status_code == 403

    _as(first)
    assigned = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": first.id, "reason": "指派给技术管理员"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["ticket"]["status"] == "open"
    assert assigned.json()["ticket"]["assigned_admin_id"] == first.id

    _as(second)
    stolen = http.post(
        f"/api/customer-service/tickets/{ticket_id}/accept",
        json={"reason": "不是当前处理人"},
    )
    assert stolen.status_code == 403

    _as(first)
    accepted = http.post(
        f"/api/customer-service/tickets/{ticket_id}/accept",
        json={"reason": "开始核查员工图谱"},
    )
    assert accepted.json()["ticket"]["status"] == "processing"
    http.post(
        f"/api/customer-service/tickets/{ticket_id}/diagnose",
        json={"reason": "企业员工工作流全景四层均暂无员工 Mod，总工位为 0"},
    )
    blocked = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "原故障仍在，员工节点仍未出现", "fault_remains": True},
    )
    assert blocked.json()["ticket"]["status"] == "processing"
    _as(customer)
    visible = next(
        row
        for row in http.get("/api/customer-service/issues/mine").json()["items"]
        if row["id"] == ticket_id
    )
    assert visible["latest_result"]["source"] == "human"
    assert visible["latest_result"]["fault_remains"] is True
    assert "原故障仍在" in visible["latest_result"]["progress"]
    assert visible["can_resolve"] is False
    assert visible["can_reopen"] is False
    still_open = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "reopen",
            "note": "故障还在但不能重开",
            "idempotency_key": "reopen-while-open",
        },
    )
    assert still_open.status_code == 409
    _as(customer)
    close = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "resolved",
            "note": "我确认已经好了",
            "idempotency_key": "close-too-soon-1",
        },
    )
    assert close.status_code == 409

    _as(first)
    requested = http.post(
        f"/api/customer-service/tickets/{ticket_id}/sensitive-action",
        json={"change": "调整客户可见配置", "reason": "需要改显示配置才能复现"},
    )
    assert requested.json()["status"] == "waiting_approval"
    assert requested.json()["executed"] is False
    _as(second)
    rejected = http.post(
        f"/api/customer-service/tickets/{ticket_id}/sensitive-action/decision",
        json={
            "action_id": requested.json()["action_id"],
            "decision": "rejected",
            "reason": "没有充分理由",
        },
    )
    assert rejected.json()["executed"] is False
    assert rejected.json()["status"] == "rejected"

    _as(first)
    self_check = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "处理人自己宣布复测通过", "fault_remains": False},
    )
    assert self_check.status_code == 403
    _as(second)
    ready = http.post(
        f"/api/customer-service/tickets/{ticket_id}/result",
        json={"text": "另一位管理员复测员工图谱已显示节点", "fault_remains": False},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["ticket"]["status"] == "awaiting_customer"
    assert ready.json()["ticket"]["lifecycle_label"] == "待客户确认"
    _as(customer)
    confirmed = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={
            "decision": "resolved",
            "note": "员工节点已经显示",
            "idempotency_key": "customer-ok-0001",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["issue"]["status"] == "resolved"
    reopened = http.post(
        f"/api/customer-service/issues/{ticket_id}/decision",
        json={"decision": "reopen", "note": "节点再次消失", "idempotency_key": "customer-reopen-1"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["issue"]["status"] == "processing"
    assert reopened.json()["issue"]["reopen_count"] == 1

    _as(second)
    moved = http.post(
        f"/api/customer-service/tickets/{ticket_id}/assign",
        json={"assignee_id": second.id, "reason": "重开后改派"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()["ticket"]
    assert body["status"] == "open"
    assert body["assigned_admin_id"] == second.id
    history = body["evidence"]["assignment_history"]
    assert [row["assignee_id"] for row in history] == [first.id, second.id]
    assert any(row["action"] == "ticket_diagnosed" for row in body["evidence"]["handling_history"])
