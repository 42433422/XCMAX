"""Payment object and refund-action authorization against isolated host RBAC."""

import json
from unittest.mock import Mock

import pytest

from app.db.models.permission import Permission, Role
from app.db.models.user import User
from app.fastapi_routes import model_payment
from app.infrastructure.payment import order_store
from tests.test_routes.test_payment_checkout_identity import payment_client  # noqa: F401

pytestmark = pytest.mark.release_gate


@pytest.fixture
def order_client(payment_client, tmp_path, monkeypatch):  # noqa: F811
    client, prefix, sessions = payment_client
    monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "json")
    path = tmp_path / "orders.json"
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(path))
    with sessions.begin() as db:
        user = db.get(User, 71)
        user.tenant_id, user.role = 11, "tenant:11:finance"
        permission = Permission(
            code="model_payment.refund", name="Refund own order", module="payment"
        )
        db.add(Role(name="tenant:11:finance", permissions=[permission]))
    providers = {}
    for name in ["query_order", "refund_order", "close_order", "query_refund"]:
        providers[name] = Mock(return_value={"success": True, "raw": {}})
        monkeypatch.setattr(model_payment.mp_ali, name, providers[name])
    row = {
        "out_trade_no": "owned-order",
        "local_user_id": 71,
        "tenant_id": 11,
        "status": "paid",
        "trade_no": "provider-owned",
    }
    path.write_text(json.dumps({"orders": {"owned-order": row}, "entitlements": {}}))
    return client, prefix, sessions, path, providers, row


def _call(client, prefix, action, *, sid="checkout-session-71", body=None):
    headers = {"X-User-ID": "71", "X-Tenant-ID": "11"}
    if sid:
        headers["X-Session-ID"] = sid
    if action == "query":
        return client.get(prefix + "/query/owned-order", headers=headers)
    if action == "refund-query":
        return client.get(
            prefix + "/refund/query", params={"out_trade_no": "owned-order"}, headers=headers
        )
    return client.post(
        prefix + "/" + action,
        headers=headers,
        json=body or {"out_trade_no": "owned-order", "refund_amount": "1.00"},
    )


@pytest.mark.parametrize("action", ["query", "refund-query", "refund", "close"])
def test_order_access_requires_identity_and_exact_scope(order_client, action):
    client, prefix, _, path, providers, row = order_client
    response = _call(client, prefix, action, sid="")
    assert response.status_code == 401, response.text
    variants = [
        None,
        {**row, "local_user_id": 72},
        {**row, "tenant_id": 12},
        {**row, "local_user_id": True},
        {**row, "tenant_id": True},
        {k: v for k, v in row.items() if k != "local_user_id"},
        {k: v for k, v in row.items() if k != "tenant_id"},
        {**row, "out_trade_no": "different-order"},
    ]
    for candidate in variants:
        path.write_text(json.dumps({"orders": {"owned-order": candidate} if candidate else {}}))
        before = path.read_bytes()
        response = _call(client, prefix, action)
        assert response.status_code == 404, response.text
        assert path.read_bytes() == before
    for provider in providers.values():
        provider.assert_not_called()


@pytest.mark.parametrize(
    "action,provider_name",
    [
        ("query", "query_order"),
        ("refund-query", "query_refund"),
        ("refund", "refund_order"),
        ("close", "close_order"),
    ],
)
def test_own_order_preserves_real_rbac_and_business_call(order_client, action, provider_name):
    client, prefix, _, path, providers, _ = order_client
    response = _call(client, prefix, action)
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    providers[provider_name].assert_called_once()
    assert providers[provider_name].call_args.kwargs["out_trade_no"] == "owned-order"
    row = json.loads(path.read_text())["orders"]["owned-order"]
    assert row["local_user_id"] == 71 and row["tenant_id"] == 11
    if action in {"refund", "close"}:
        assert row["status"] == {"refund": "refunded", "close": "closed"}[action]


def test_refund_requires_live_host_permission_not_mod_role(order_client):
    from app.db.session import SessionLocal

    client, prefix, sessions, path, providers, _ = order_client
    assert _call(client, prefix, "refund").status_code == 200
    providers["refund_order"].reset_mock()
    with sessions.begin() as db:
        db.query(Role).filter_by(name="tenant:11:finance").one().permissions = []
    with SessionLocal() as db:
        p = Permission(code="model_payment.refund", name="Wrong database", module="payment")
        db.add(Role(name="tenant:11:finance", permissions=[p]))
        db.commit()
    before = path.read_bytes()
    response = _call(client, prefix, "refund")
    assert response.status_code == 403, response.text
    assert "缺少订单操作权限" in response.text
    assert path.read_bytes() == before
    providers["refund_order"].assert_not_called()


def test_platform_admin_is_not_an_order_owner_bypass(order_client):
    client, prefix, sessions, path, providers, row = order_client
    with sessions.begin() as db:
        user = db.get(User, 71)
        user.role, user.tier, user.tenant_id = "admin", "admin", None
    row.update(local_user_id=72, tenant_id=None)
    path.write_text(json.dumps({"orders": {"owned-order": row}}))
    for action in ["query", "refund-query", "refund", "close"]:
        response = _call(client, prefix, action)
        assert response.status_code == 404, response.text
    for provider in providers.values():
        provider.assert_not_called()


def test_explicit_personal_scope_is_not_missing_legacy_scope(order_client):
    client, prefix, sessions, path, providers, row = order_client
    with sessions.begin() as db:
        db.get(User, 71).tenant_id = None
    row["tenant_id"] = None
    path.write_text(json.dumps({"orders": {"owned-order": row}}))
    assert _call(client, prefix, "query").status_code == 200
    providers["query_order"].reset_mock()
    del row["tenant_id"]
    path.write_text(json.dumps({"orders": {"owned-order": row}}))
    assert _call(client, prefix, "query").status_code == 404
    providers["query_order"].assert_not_called()


def test_close_rejects_unbound_provider_identifiers(order_client):
    client, prefix, _, _, providers, _ = order_client
    response = _call(client, prefix, "close", body={"trade_no": "provider-owned"})
    assert response.status_code == 400
    response = _call(
        client,
        prefix,
        "close",
        body={"out_trade_no": "owned-order", "trade_no": "other-provider-order"},
    )
    assert response.status_code == 404
    providers["close_order"].assert_not_called()


def test_postgres_configuration_cannot_silently_use_json(order_client, monkeypatch):
    client, prefix, _, path, providers, _ = order_client
    monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "postgres")
    checkout = Mock()
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", checkout)
    before = path.read_bytes()
    for action in ["query", "refund-query", "refund", "close", "checkout"]:
        response = _call(client, prefix, action)
        assert response.status_code == 503, response.text
    assert path.read_bytes() == before
    checkout.assert_not_called()
    for provider in providers.values():
        provider.assert_not_called()


def test_status_update_cannot_replace_identity(order_client):
    order_store.update_order_status(
        out_trade_no="owned-order",
        status="paid",
        extra={"local_user_id": 72, "tenant_id": 12, "out_trade_no": "other"},
    )
    row = order_store.get_order("owned-order")
    assert (row["local_user_id"], row["tenant_id"], row["out_trade_no"]) == (71, 11, "owned-order")


def test_tenant_change_invalidates_order_access_without_new_login(order_client):
    client, prefix, sessions, _, providers, _ = order_client
    assert _call(client, prefix, "query").status_code == 200
    providers["query_order"].reset_mock()
    with sessions.begin() as db:
        db.get(User, 71).tenant_id = 12
    assert _call(client, prefix, "query").status_code == 404
    providers["query_order"].assert_not_called()


def test_checkout_records_trusted_tenant_not_request_fields(order_client, monkeypatch):
    client, prefix, _, path, _, _ = order_client
    monkeypatch.setattr(model_payment.mp_ali, "alipay_ui_ready", lambda: True)
    monkeypatch.setattr(model_payment.mp_ali, "warn_notify_url_path_once", lambda: None)
    provider = Mock(return_value={"success": True, "type": "test", "raw": {}})
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", provider)
    response = _call(
        client, prefix, "checkout", body={"plan_id": "demo-starter", "user_id": 72, "tenant_id": 99}
    )
    assert response.status_code == 200, response.text
    order_id = response.json()["data"]["order_id"]
    row = json.loads(path.read_text())["orders"][order_id]
    assert (row["local_user_id"], row["tenant_id"]) == (71, 11)
    provider.assert_called_once()


def test_postgres_notify_and_entitlements_do_not_touch_json(order_client, monkeypatch):
    client, prefix, _, path, _, _ = order_client
    monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "postgres")
    notify, entitlements = Mock(), Mock()
    monkeypatch.setattr(model_payment.mp_orders, "apply_notify_paid", notify)
    monkeypatch.setattr(model_payment.mp_orders, "list_entitlements", entitlements)
    before = path.read_bytes()
    assert client.post(prefix + "/notify/alipay", data={"sign": "synthetic"}).status_code == 503
    assert client.get(prefix + "/entitlements").status_code == 503
    assert path.read_bytes() == before
    notify.assert_not_called()
    entitlements.assert_not_called()


@pytest.mark.parametrize("state", ["deleted-session", "expired-session", "disabled"])
def test_order_actions_recheck_live_identity(order_client, state):
    from datetime import timedelta

    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    client, prefix, sessions, path, providers, _ = order_client
    with sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="checkout-session-71").one()
        if state == "deleted-session":
            db.delete(row)
        elif state == "expired-session":
            row.expires_at = utc_now_naive() - timedelta(hours=1)
        else:
            db.get(User, 71).is_active = False
    before = path.read_bytes()
    for action in ["query", "refund-query", "refund", "close"]:
        response = _call(client, prefix, action)
        assert response.status_code == (403 if state == "disabled" else 401), response.text
        assert "CSRF" not in response.text
    assert path.read_bytes() == before
    for provider in providers.values():
        provider.assert_not_called()
