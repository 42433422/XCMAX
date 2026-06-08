from __future__ import annotations

import types
import uuid

import pytest

pytest.importorskip("fastapi")


def _make_user(username: str, *, admin: bool = False):
    from modstore_server.models import User, get_session_factory

    username = f"{username}_{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
            is_admin=admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(
            id=user.id, username=user.username, email=user.email, is_admin=user.is_admin
        )


def _paid_order(tmp_path, monkeypatch, user_id: int) -> str:
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    from modstore_server import payment_orders

    order_no = f"CS-PYTEST-{uuid.uuid4().hex[:10]}"
    payment_orders.create(
        out_trade_no=order_no,
        subject="customer service order",
        total_amount="19.90",
        user_id=user_id,
        order_kind="plan",
        plan_id="plan_basic",
    )
    payment_orders.update_status(
        out_trade_no=order_no, status="paid", trade_no="TRADE1", paid_at="2026-01-01T00:00:00Z"
    )
    return order_no


def test_customer_service_refund_chat_creates_ticket_action_and_refund(
    client, tmp_path, monkeypatch
):
    from modstore_server import customer_service_api, webhook_dispatcher
    from modstore_server.app import app
    from modstore_server.models import RefundRequest, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user = _make_user("cs_user")
    order_no = _paid_order(tmp_path, monkeypatch, user.id)
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    monkeypatch.setattr(
        webhook_dispatcher, "dispatch_event", lambda event: {"ok": True, "event": event}
    )
    try:
        r = client.post(
            "/api/customer-service/chat",
            json={
                "message": f"订单号：{order_no} 我想退款，重复购买了",
                "context": {"channel": "web"},
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["ticket"]["intent"] == "refund"
        assert data["decision"]["decision"] == "approved"
        assert data["actions"][0]["action_type"] == "refund.apply"
        assert data["actions"][0]["status"] == "completed"

        sf = get_session_factory()
        with sf() as session:
            assert (
                session.query(CustomerServiceTicket)
                .filter(CustomerServiceTicket.ticket_no == data["ticket"]["ticket_no"])
                .first()
            )
            refund = session.query(RefundRequest).filter(RefundRequest.order_no == order_no).first()
            assert refund is not None
            assert refund.status == "pending"
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_customer_service_missing_fields_requests_more_info(client):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    user = _make_user("cs_missing")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post("/api/customer-service/chat", json={"message": "我要退款", "context": {}})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ticket"]["intent"] == "refund"
        assert data["decision"]["decision"] == "needs_more_info"
        assert data["actions"] == []
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_admin_can_manage_customer_service_standard(client):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    admin = _make_user("cs_admin", admin=True)
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
    app.dependency_overrides[customer_service_api._require_admin] = lambda: admin
    try:
        payload = {
            "name": "pytest 标准",
            "scenario": "pytest_case",
            "description": "测试标准",
            "rules": {"required_fields": ["subject"]},
            "action_policy": {"auto_actions": ["ticket.note"]},
            "auto_enabled": True,
            "risk_level": "low",
            "priority": 5,
        }
        r = client.post("/api/customer-service/standards", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["scenario"] == "pytest_case"
        assert created["action_policy"]["auto_actions"] == ["ticket.note"]

        updated_payload = {**payload, "name": "pytest 标准更新", "priority": 6}
        r = client.put(f"/api/customer-service/standards/{created['id']}", json=updated_payload)
        assert r.status_code == 200, r.text
        assert r.json()["priority"] == 6
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)
        app.dependency_overrides.pop(customer_service_api._require_admin, None)
