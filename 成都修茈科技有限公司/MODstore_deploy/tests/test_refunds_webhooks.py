from __future__ import annotations

import types
import uuid

import pytest

pytest.importorskip("fastapi")


def _make_user(username: str, *, admin: bool = False):
    username = f"{username}_{uuid.uuid4().hex[:8]}"
    from modstore_server.models import User, get_session_factory

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


@pytest.fixture
def refund_users():
    return _make_user("refund_user", admin=False), _make_user("refund_admin", admin=True)


@pytest.fixture
def refund_auth(client, refund_users):
    from modstore_server import refund_api, webhook_api
    from modstore_server.app import app

    user, _admin = refund_users
    app.dependency_overrides[refund_api._get_current_user] = lambda: user
    app.dependency_overrides[webhook_api._get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(refund_api._get_current_user, None)
    app.dependency_overrides.pop(webhook_api._get_current_user, None)


@pytest.fixture
def refund_admin_auth(client, refund_users):
    from modstore_server import refund_api, webhook_api
    from modstore_server.app import app

    _user, admin = refund_users
    app.dependency_overrides[refund_api._get_current_user] = lambda: admin
    app.dependency_overrides[webhook_api._get_current_user] = lambda: admin
    yield admin
    app.dependency_overrides.pop(refund_api._get_current_user, None)
    app.dependency_overrides.pop(webhook_api._get_current_user, None)


def _create_paid_order(tmp_path, monkeypatch, user_id: int, order_no: str | None = None):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    from modstore_server import payment_orders

    order_no = order_no or f"RF-PYTEST-{uuid.uuid4().hex[:10]}"
    payment_orders.create(
        out_trade_no=order_no,
        subject="pytest order",
        total_amount="9.90",
        user_id=user_id,
        order_kind="plan",
        plan_id="plan_basic",
    )
    payment_orders.update_status(
        out_trade_no=order_no, status="paid", trade_no="TRADE1", paid_at="2026-01-01T00:00:00Z"
    )
    return order_no


def test_refund_apply_and_duplicate_rejected(client, tmp_path, monkeypatch, refund_auth):
    order_no = _create_paid_order(tmp_path, monkeypatch, refund_auth.id)

    r = client.post("/api/refunds/apply", json={"order_no": order_no, "reason": "pytest 退款原因"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    duplicate = client.post(
        "/api/refunds/apply", json={"order_no": order_no, "reason": "再次申请退款"}
    )
    assert duplicate.status_code == 400
    assert "已有退款申请" in duplicate.text


def test_admin_reject_refund_dispatches_webhook(client, tmp_path, monkeypatch, refund_users):
    user, admin = refund_users
    order_no = _create_paid_order(
        tmp_path, monkeypatch, user.id, f"RF-PYTEST-REJECT-{uuid.uuid4().hex[:8]}"
    )
    from modstore_server import refund_api, webhook_api, webhook_dispatcher
    from modstore_server.app import app

    app.dependency_overrides[refund_api._get_current_user] = lambda: user
    applied = client.post(
        "/api/refunds/apply", json={"order_no": order_no, "reason": "pytest 拒绝原因"}
    )
    refund_id = applied.json()["refund_id"]

    events = []
    monkeypatch.setattr(
        webhook_dispatcher, "dispatch_event", lambda event: events.append(event) or {"ok": True}
    )
    app.dependency_overrides[refund_api._get_current_user] = lambda: admin
    app.dependency_overrides[webhook_api._get_current_user] = lambda: admin
    try:
        r = client.post(
            f"/api/refunds/admin/{refund_id}/review", json={"action": "reject", "admin_note": "no"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
        assert events[-1]["type"] == "refund.rejected"
        assert events[-1]["aggregate_id"] == order_no
    finally:
        app.dependency_overrides.pop(refund_api._get_current_user, None)
        app.dependency_overrides.pop(webhook_api._get_current_user, None)


def test_admin_approve_refund_dispatches_webhook(client, tmp_path, monkeypatch, refund_users):
    user, admin = refund_users
    order_no = _create_paid_order(
        tmp_path, monkeypatch, user.id, f"RF-PYTEST-APPROVE-{uuid.uuid4().hex[:8]}"
    )
    from modstore_server import alipay_service, refund_api, webhook_api, webhook_dispatcher
    from modstore_server.app import app

    app.dependency_overrides[refund_api._get_current_user] = lambda: user
    applied = client.post(
        "/api/refunds/apply", json={"order_no": order_no, "reason": "pytest 通过原因"}
    )
    refund_id = applied.json()["refund_id"]

    events = []
    monkeypatch.setattr(alipay_service, "refund_order", lambda **_kw: {"ok": True})
    monkeypatch.setattr(
        webhook_dispatcher, "dispatch_event", lambda event: events.append(event) or {"ok": True}
    )
    app.dependency_overrides[refund_api._get_current_user] = lambda: admin
    app.dependency_overrides[webhook_api._get_current_user] = lambda: admin
    try:
        r = client.post(
            f"/api/refunds/admin/{refund_id}/review", json={"action": "approve", "admin_note": "ok"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "refunded"
        assert events[-1]["type"] == "refund.approved"
    finally:
        app.dependency_overrides.pop(refund_api._get_current_user, None)
        app.dependency_overrides.pop(webhook_api._get_current_user, None)


def test_webhook_replay_by_order_no(client, tmp_path, monkeypatch, refund_users):
    user, admin = refund_users
    order_no = _create_paid_order(
        tmp_path, monkeypatch, user.id, f"RF-PYTEST-REPLAY-{uuid.uuid4().hex[:8]}"
    )
    from modstore_server import webhook_api, webhook_dispatcher
    from modstore_server.app import app

    events = []
    monkeypatch.setattr(
        webhook_dispatcher, "dispatch_event", lambda event: events.append(event) or {"ok": True}
    )
    app.dependency_overrides[webhook_api._get_current_user] = lambda: admin
    try:
        r = client.post("/api/webhooks/admin/replay", json={"order_no": order_no})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert events[-1]["type"] == "payment.paid"
    finally:
        app.dependency_overrides.pop(webhook_api._get_current_user, None)
