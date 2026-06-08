"""Coverage tests for the admin Webhook replay endpoint."""

from __future__ import annotations

import types
import uuid

import httpx
import pytest

pytest.importorskip("fastapi")


def _make_admin():
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"webhook_admin_{uuid.uuid4().hex[:8]}",
            email=f"webhook_admin_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, is_admin=True)


def _make_user():
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"webhook_user_{uuid.uuid4().hex[:8]}",
            email=f"webhook_user_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=False,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, is_admin=False)


@pytest.fixture
def admin_client(client):
    from modstore_server import webhook_api
    from modstore_server.app import app

    admin = _make_admin()
    app.dependency_overrides[webhook_api._get_current_user] = lambda: admin
    yield client, admin
    app.dependency_overrides.pop(webhook_api._get_current_user, None)


def _create_paid_order(tmp_path, monkeypatch, user_id, order_no=None):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    from modstore_server import payment_orders

    order_no = order_no or f"WHK-{uuid.uuid4().hex[:8]}"
    payment_orders.create(
        out_trade_no=order_no,
        subject="webhook test",
        total_amount="9.90",
        user_id=user_id,
        order_kind="plan",
        plan_id="plan_basic",
    )
    payment_orders.update_status(out_trade_no=order_no, status="paid", trade_no="T1")
    return order_no


def test_replay_requires_admin(client):
    from modstore_server import webhook_api
    from modstore_server.app import app

    user = _make_user()
    app.dependency_overrides[webhook_api._get_current_user] = lambda: user
    try:
        r = client.post("/api/webhooks/admin/replay", json={"order_no": "X"})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(webhook_api._get_current_user, None)


def test_replay_requires_event_id_or_order_no(admin_client):
    client, _admin = admin_client
    r = client.post("/api/webhooks/admin/replay", json={})
    assert r.status_code == 400
    assert "event_id" in r.text


def test_replay_by_event_id_returns_404_when_event_missing(admin_client):
    client, _admin = admin_client
    r = client.post("/api/webhooks/admin/replay", json={"event_id": "missing-event"})
    assert r.status_code == 404


def test_replay_by_event_id_uses_replay_event(admin_client, monkeypatch):
    client, _admin = admin_client
    from modstore_server import webhook_dispatcher

    monkeypatch.setattr(
        webhook_dispatcher,
        "replay_event",
        lambda event_id: {"ok": True, "echoed": event_id},
    )
    r = client.post("/api/webhooks/admin/replay", json={"event_id": "evt-1"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["result"]["echoed"] == "evt-1"


def test_replay_by_order_no_404_for_unknown_order(admin_client, monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    client, _admin = admin_client
    r = client.post(
        "/api/webhooks/admin/replay",
        json={"order_no": "MOD-DOES-NOT-EXIST"},
    )
    assert r.status_code == 404


def test_replay_rejects_non_paid_order(admin_client, monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    from modstore_server import payment_orders

    order_no = f"WHK-PEND-{uuid.uuid4().hex[:8]}"
    payment_orders.create(
        out_trade_no=order_no,
        subject="pending",
        total_amount="9.90",
        user_id=1,
        order_kind="plan",
        plan_id="plan_basic",
    )
    client, _admin = admin_client
    r = client.post("/api/webhooks/admin/replay", json={"order_no": order_no})
    assert r.status_code == 400


def test_replay_publishes_payment_paid(admin_client, monkeypatch, tmp_path):
    user = _make_user()
    order_no = _create_paid_order(tmp_path, monkeypatch, user.id)
    client, _admin = admin_client
    from modstore_server import webhook_dispatcher

    seen = []
    monkeypatch.setattr(
        webhook_dispatcher,
        "publish_event",
        lambda etype, oid, payload: seen.append((etype, oid, payload)) or {"ok": True},
    )
    r = client.post("/api/webhooks/admin/replay", json={"order_no": order_no})
    assert r.status_code == 200, r.text
    assert seen[-1][0] == "payment.paid"
    assert seen[-1][1] == order_no
    payload = seen[-1][2]
    for required in ("out_trade_no", "user_id", "subject", "total_amount", "order_kind"):
        assert required in payload


def test_replay_refund_event_publishes_refund_event(admin_client, monkeypatch, tmp_path):
    user = _make_user()
    order_no = _create_paid_order(tmp_path, monkeypatch, user.id)
    client, _admin = admin_client
    from modstore_server import webhook_dispatcher
    from modstore_server.models import RefundRequest, get_session_factory

    sf = get_session_factory()
    with sf() as db:
        refund = RefundRequest(
            user_id=user.id,
            order_no=order_no,
            amount=9.9,
            reason="pytest",
            status="rejected",
        )
        db.add(refund)
        db.commit()

    seen = []
    monkeypatch.setattr(
        webhook_dispatcher,
        "publish_event",
        lambda etype, oid, payload: seen.append((etype, oid)) or {"ok": True},
    )
    r = client.post(
        "/api/webhooks/admin/replay",
        json={"order_no": order_no, "event_type": "refund.rejected"},
    )
    assert r.status_code == 200, r.text
    assert seen[-1][0] == "refund.rejected"


def test_replay_forwards_to_java_when_backend_java(admin_client, monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://java")
    client, _admin = admin_client

    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            captured["called"] = True
            return {"ok": True, "echoed": "java"}

        @property
        def text(self):
            return ""

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)

    r = client.post(
        "/api/webhooks/admin/replay",
        json={"order_no": "MOD-JAVA"},
        headers={"Authorization": "Bearer test-jwt"},
    )
    assert r.status_code == 200, r.text
    assert captured["url"].endswith("/api/webhooks/admin/replay")
    assert captured["json"]["order_no"] == "MOD-JAVA"
    assert captured["headers"]["Authorization"] == "Bearer test-jwt"


def test_replay_returns_502_when_java_unreachable(admin_client, monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    client, _admin = admin_client

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            raise httpx.HTTPError("no route")

    monkeypatch.setattr(httpx, "Client", _Client)
    r = client.post("/api/webhooks/admin/replay", json={"order_no": "MOD-JAVA"})
    assert r.status_code == 502
