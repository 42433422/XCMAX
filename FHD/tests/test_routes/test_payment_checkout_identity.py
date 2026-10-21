"""Checkout identity at host and bundled Mod boundaries; no external payments."""

from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import Session, User
from app.fastapi_routes import market_account, model_payment
from app.infrastructure.payment import modstore_payment_proxy as proxy
from app.utils.time import utc_now_naive

pytestmark = pytest.mark.release_gate


@pytest.fixture(params=["host", "full-host", "mods", "XCAGI/mods"])
def payment_client(request, tmp_path, monkeypatch):
    import app.db as database

    engine = create_engine(f"sqlite:///{tmp_path / 'checkout.sqlite3'}")
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    mod_engine = create_engine(f"sqlite:///{tmp_path / 'mod.sqlite3'}")
    mod_sessions = sessionmaker(bind=mod_engine)
    Base.metadata.create_all(mod_engine)
    with mod_sessions.begin() as db:
        db.add(User(id=72, username="mod-user", password="unused", is_active=True))
        db.add(
            Session(
                session_id="checkout-session-71",
                user_id=72,
                expires_at=utc_now_naive() + timedelta(hours=1),
                market_access_token="synthetic-wrong-mod-token",
            )
        )
    monkeypatch.setattr("app.db.session.SessionLocal", mod_sessions)
    monkeypatch.setattr(market_account, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", "1")
    monkeypatch.setenv("XCAGI_MARKET_AUTH_TOKEN", "synthetic-global-must-not-be-used")
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "synthetic-other-global-must-not-be-used")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.invalid")
    with sessions.begin() as db:
        for uid in [71, 72]:
            db.add(User(id=uid, username=f"checkout-{uid}", password="unused", is_active=True))
            db.add(
                Session(
                    session_id=f"checkout-session-{uid}",
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token=f"synthetic-market-{uid}",
                )
            )
    app = FastAPI()
    if request.param == "full-host":
        from app.config import TestingConfig
        from app.fastapi_app import factory

        monkeypatch.setattr(factory, "_app_singleton", factory._app_singleton)
        monkeypatch.setenv("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "0")
        monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "0")
        monkeypatch.setattr(
            "app.fastapi_app.mod_startup.bootstrap_mod_extensions_sync", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "app.fastapi_app.mod_startup.schedule_background_mod_load", lambda app: None
        )
        app = factory.create_fastapi_app(TestingConfig, enable_cors=False)
        prefix = "/api/model-payment"
    elif request.param == "host":
        app.include_router(model_payment.router)
        prefix = "/api/model-payment"
    else:
        path = (
            Path(__file__).resolve().parents[2]
            / request.param
            / "xcagi-model-payment-bridge/backend/blueprints.py"
        )
        spec = spec_from_file_location("checkout_bridge_test", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register_fastapi_routes(app, "payment-test")
        prefix = "/api/mod/payment-test/model-payment"
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("csrf_token", "synthetic-payment-csrf")
    client.headers["X-CSRF-Token"] = "synthetic-payment-csrf"
    yield client, prefix, sessions
    client.close()
    engine.dispose()
    mod_engine.dispose()


@pytest.mark.parametrize("state", ["missing", "expired", "deleted", "disabled"])
@pytest.mark.parametrize("market", [False, True])
def test_invalid_identity_prevents_any_checkout(payment_client, monkeypatch, state, market):
    client, prefix, sessions = payment_client
    market_account._MARKET_SESSION_TOKENS["checkout-session-71"] = "synthetic-cached-71"
    with sessions.begin() as db:
        row = db.query(Session).filter_by(session_id="checkout-session-71").one()
        if state == "expired":
            row.expires_at = utc_now_naive() - timedelta(hours=1)
        elif state == "deleted":
            db.delete(row)
        elif state == "disabled":
            db.get(User, 71).is_active = False
    monkeypatch.setattr(model_payment, "is_modstore_payment_sot", lambda: market)
    provider, remote, write = Mock(), Mock(), Mock()
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", provider)
    monkeypatch.setattr(proxy, "proxy_checkout", remote)
    monkeypatch.setattr(model_payment.mp_orders, "record_checkout_pending", write)
    headers = {"X-User-ID": "72", "X-Tenant-ID": "99"}
    if state != "missing":
        headers["X-Session-ID"] = "checkout-session-71"
    result = client.post(
        prefix + "/checkout",
        headers=headers,
        json={"plan_id": "demo-starter", "market_user_id": 72},
    )
    assert result.status_code == (403 if state == "disabled" else 401), result.text
    assert "CSRF" not in result.text
    provider.assert_not_called()
    remote.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("credential", ["header", "cookie", "header-over-cookie"])
def test_market_checkout_uses_only_current_session_token(payment_client, monkeypatch, credential):
    client, prefix, _ = payment_client
    market_account._MARKET_SESSION_TOKENS["checkout-session-71"] = "synthetic-stale-token"
    monkeypatch.setattr(model_payment, "is_modstore_payment_sot", lambda: True)
    calls = []

    class HttpClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Mock(status_code=200, json=lambda: {"order_id": "synthetic-order"})

    monkeypatch.setattr(proxy.httpx, "Client", HttpClient)
    fallback = Mock(side_effect=AssertionError("global token fallback"))
    monkeypatch.setattr(proxy, "_auth_token", fallback)
    headers = {"X-Session-ID": "checkout-session-71"}
    if credential == "cookie":
        client.cookies.set("session_id", "checkout-session-71")
        headers = {}
    elif credential == "header-over-cookie":
        client.cookies.set("session_id", "checkout-session-72")
    response = client.post(
        prefix + "/checkout",
        headers=headers,
        json={"plan_id": "demo-starter", "market_user_id": 72, "user_id": 72},
    )
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert len(calls) == 2
    for _, call in calls:
        assert call["headers"]["Authorization"] == "Bearer synthetic-market-71"
        assert "market_user_id" not in call["json"]
        assert "user_id" not in call["json"]
    fallback.assert_not_called()


def test_missing_session_market_token_never_borrows_another(payment_client, monkeypatch):
    client, prefix, sessions = payment_client
    market_account._MARKET_SESSION_TOKENS["checkout-session-71"] = "synthetic-stale-token"
    with sessions.begin() as db:
        db.query(Session).filter_by(
            session_id="checkout-session-71"
        ).one().market_access_token = None
    monkeypatch.setattr(model_payment, "is_modstore_payment_sot", lambda: True)
    transport = Mock(side_effect=AssertionError("must not call market"))
    monkeypatch.setattr(proxy.httpx, "Client", transport)
    response = client.post(
        prefix + "/checkout",
        headers={"X-Session-ID": "checkout-session-71"},
        json={"plan_id": "demo-starter", "market_user_id": 72},
    )
    assert response.status_code == 401, response.text
    transport.assert_not_called()


def test_local_checkout_persists_authenticated_owner(payment_client, monkeypatch):
    client, prefix, _ = payment_client
    monkeypatch.setattr(model_payment, "is_modstore_payment_sot", lambda: False)
    monkeypatch.setattr(model_payment, "is_json_legacy_payment_sot", lambda: False)
    monkeypatch.setattr(model_payment.mp_ali, "alipay_ui_ready", lambda: True)
    monkeypatch.setattr(model_payment.mp_ali, "warn_notify_url_path_once", lambda: None)
    provider = Mock(return_value={"success": True, "type": "test", "raw": {}})
    write = Mock()
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", provider)
    monkeypatch.setattr(model_payment.mp_orders, "record_checkout_pending", write)
    response = client.post(
        prefix + "/checkout",
        headers={"X-Session-ID": "checkout-session-71"},
        json={"plan_id": "demo-starter", "local_user_id": 72, "user_id": 72},
    )
    assert response.status_code == 200, response.text
    provider.assert_called_once()
    write.assert_called_once()
    assert write.call_args.kwargs["local_user_id"] == 71


def test_proxy_missing_explicit_token_does_not_resolve_shared_credentials(monkeypatch):
    fallback, transport = Mock(), Mock()
    monkeypatch.setattr(proxy, "_auth_token", fallback)
    monkeypatch.setattr(proxy.httpx, "Client", transport)
    assert proxy.proxy_checkout(plan_id="demo-starter")["success"] is False
    fallback.assert_not_called()
    transport.assert_not_called()


def test_explicit_empty_transport_token_never_falls_back(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.invalid")
    fallback, transport = Mock(), Mock()
    monkeypatch.setattr(proxy, "_auth_token", fallback)
    monkeypatch.setattr(proxy.httpx, "Client", transport)
    data, error = proxy._post_json("/api/payment/checkout", payload={}, auth_token=" ")
    assert data is None and error
    fallback.assert_not_called()
    transport.assert_not_called()


def test_host_token_lookup_requires_matching_owner(payment_client):
    assert proxy.checkout_session_token("checkout-session-71", 72) == ""
    assert proxy.checkout_session_token("checkout-session-71", 71) == "synthetic-market-71"


def test_host_token_database_failure_does_not_fallback(payment_client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    monkeypatch.setattr(
        "app.db.session.get_host_db", Mock(side_effect=SQLAlchemyError("synthetic"))
    )
    assert proxy.checkout_session_token("checkout-session-71", 71) == ""


def test_direct_checkout_requires_identity(monkeypatch):
    from fastapi import HTTPException, Request

    provider, remote = Mock(), Mock()
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", provider)
    monkeypatch.setattr(proxy, "proxy_checkout", remote)
    with pytest.raises(HTTPException) as exc:
        model_payment.checkout(
            Request({"type": "http", "headers": []}), body={"plan_id": "demo-starter"}
        )
    assert exc.value.status_code == 401
    provider.assert_not_called()
    remote.assert_not_called()
