"""The local broker must never borrow another session's market identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import market_account as market
from app.fastapi_routes import market_browser_handoff as routes


def test_actual_legacy_registration_with_real_cookie_session_chain(tmp_path, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.facades import session_facade
    from app.db import session as db_module
    from app.db.models.user import Session, User
    from app.infrastructure.session import session_manager
    from app.legacy.routes.legacy_compat import _register_early_critical_routes
    from app.utils.time import utc_now_naive

    engine = create_engine(f"sqlite:///{tmp_path / 'local-auth.sqlite'}")
    User.__table__.create(engine)
    Session.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "get_db", factory)
    monkeypatch.setattr(db_module, "get_host_db", factory)
    monkeypatch.setattr(session_manager, "get_host_db", factory)
    monkeypatch.setattr(session_facade, "get_session_service", session_manager.SessionManager)
    monkeypatch.setattr(market, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setattr(market, "_MARKET_SESSION_REFRESH_TOKENS", {})
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "0")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
    with factory() as db:
        db.add_all([User(id=i, username=f"test-{i}", password="test-hash") for i in (11, 22)])
        db.add_all(
            [
                Session(
                    session_id=sid,
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token=token,
                )
                for sid, uid, token in (
                    ("local-a", 11, "market-a"),
                    ("local-b", 22, "market-b"),
                    ("unbound", 11, None),
                )
            ]
        )
        db.commit()
    proxy = AsyncMock(
        return_value={
            "ok": True,
            "data": {
                "code": "a" * 43,
                "target": "/wallet",
                "purpose": "wallet",
                "expires_in": 60,
            },
        }
    )
    monkeypatch.setattr(market, "_proxy_json", proxy)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session", AsyncMock()
    )
    app = FastAPI()
    _register_early_critical_routes(app)
    paths = app.openapi()["paths"]
    assert "/api/market/browser-handoff" in paths
    assert "/api/market/api/market/browser-handoff" not in paths
    with TestClient(app) as client:
        target = {"target": "/wallet", "purpose": "wallet"}
        for cookie in (None, "missing", "unbound"):
            client.cookies.clear()
            if cookie:
                client.cookies.set("session_id", cookie)
            response = client.post("/api/market/browser-handoff", json=target)
            assert response.status_code == 401
            assert "market-a" not in response.text and "market-b" not in response.text
        proxy.assert_not_awaited()
        client.cookies.set("session_id", "local-a")
        # A conflicting explicit session must not borrow the cookie owner's market identity.
        denied = client.post(
            "/api/market/browser-handoff", headers={"X-Session-ID": "local-b"}, json=target
        )
        assert denied.status_code == 401
        assert (
            client.get(
                "/api/market/session-handoff", headers={"X-Session-ID": "local-b"}
            ).status_code
            == 401
        )
        response = client.post("/api/market/browser-handoff", json=target)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert proxy.await_args.kwargs["authorization"] == "Bearer market-a"
        legacy = client.get("/api/market/session-handoff")
        assert legacy.status_code == 200
        assert legacy.json()["data"]["market_access_token"] == "market-a"
        assert legacy.headers["cache-control"] == "no-store"
        with factory() as db:
            db.get(User, 11).is_active = False
            db.commit()
        assert client.post("/api/market/browser-handoff", json=target).status_code == 401
        disabled = client.get("/api/market/session-handoff")
        assert disabled.status_code == 401
        assert "market-a" not in disabled.text
    engine.dispose()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "resolve_session_user", lambda request: SimpleNamespace(id=11))
    monkeypatch.setattr(market, "session_id_from_request", lambda request: "session-a")
    monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 11)
    monkeypatch.setattr(market, "session_market_token", lambda sid: "market-a")
    monkeypatch.setattr(
        market,
        "latest_session_market_token",
        lambda *a, **kw: pytest.fail("global fallback forbidden"),
    )
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/market")
    with TestClient(app) as value:
        yield value


def test_issue_uses_only_authenticated_session_and_has_no_store(client, monkeypatch):
    proxy = AsyncMock(
        return_value={
            "ok": True,
            "data": {
                "code": "a" * 43,
                "target": "/wallet?recharge=30",
                "purpose": "wallet",
                "expires_in": 60,
                "access_token": "must-not-forward",
            },
        }
    )
    monkeypatch.setattr(market, "_proxy_json", proxy)
    response = client.post(
        "/api/market/browser-handoff", json={"target": "/wallet?recharge=30", "purpose": "wallet"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "access_token" not in response.text
    assert proxy.call_args.kwargs["authorization"] == "Bearer market-a"


@pytest.mark.parametrize("mode", ["anonymous", "other-session", "unbound", "disabled"])
def test_anonymous_wrong_owner_and_unbound_cannot_issue(client, monkeypatch, mode):
    if mode == "anonymous":
        monkeypatch.setattr(routes, "resolve_session_user", lambda request: None)
    elif mode == "other-session":
        monkeypatch.setattr(market, "_user_id_from_session", lambda sid: 22)
    elif mode == "disabled":
        monkeypatch.setattr(
            routes, "resolve_session_user", lambda request: SimpleNamespace(id=11, is_active=False)
        )
    else:
        monkeypatch.setattr(market, "session_market_token", lambda sid: "")
    proxy = AsyncMock()
    monkeypatch.setattr(market, "_proxy_json", proxy)
    response = client.post(
        "/api/market/browser-handoff", json={"target": "/wallet", "purpose": "wallet"}
    )
    assert response.status_code == 401
    proxy.assert_not_awaited()


@pytest.mark.parametrize(
    "target", ["https://evil.example/wallet", "//evil.example/wallet", "/admin", "/wallet#secret"]
)
def test_no_open_redirect(client, monkeypatch, target):
    proxy = AsyncMock()
    monkeypatch.setattr(market, "_proxy_json", proxy)
    assert (
        client.post(
            "/api/market/browser-handoff", json={"target": target, "purpose": "wallet"}
        ).status_code
        == 400
    )
    proxy.assert_not_awaited()


def test_error_payload_never_forwarded(client, monkeypatch):
    monkeypatch.setattr(
        market,
        "_proxy_json",
        AsyncMock(
            return_value={
                "__proxy_error__": True,
                "status_code": 503,
                "payload": {"token": "secret"},
            }
        ),
    )
    response = client.post(
        "/api/market/browser-handoff", json={"target": "/wallet", "purpose": "wallet"}
    )
    assert response.status_code == 503
    assert "secret" not in response.text


def test_refreshes_only_current_session_before_issuing(client, monkeypatch):
    issued = {
        "ok": True,
        "data": {"code": "b" * 43, "target": "/wallet", "purpose": "wallet", "expires_in": 60},
    }
    proxy = AsyncMock(
        side_effect=[
            {"__proxy_error__": True, "status_code": 401},
            {"access_token": "new-current", "refresh_token": "new-current-refresh"},
            issued,
        ]
    )
    monkeypatch.setattr(market, "_proxy_json", proxy)
    monkeypatch.setattr(market, "session_market_refresh_token", lambda sid: "current-refresh")
    monkeypatch.setattr(
        market,
        "latest_session_market_refresh_token",
        lambda: pytest.fail("global refresh forbidden"),
    )
    saved = []
    monkeypatch.setattr(market, "save_session_market_token", lambda *args: saved.append(args))
    response = client.post(
        "/api/market/browser-handoff", json={"target": "/wallet", "purpose": "wallet"}
    )
    assert response.status_code == 200
    assert proxy.await_args_list[1].kwargs["json_body"] == {"refresh_token": "current-refresh"}
    assert proxy.await_args_list[2].kwargs["authorization"] == "Bearer new-current"
    assert saved == [("session-a", "new-current", "new-current-refresh")]


def test_auth_failure_never_returns_exception_or_uses_fallback(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "resolve_session_user",
        lambda request: (_ for _ in ()).throw(RuntimeError("sensitive-session-context")),
    )
    response = client.post(
        "/api/market/browser-handoff", json={"target": "/wallet", "purpose": "wallet"}
    )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "sensitive-session-context" not in response.text


@pytest.mark.asyncio
async def test_auth_proxy_does_not_log_upstream_credential_error(monkeypatch, caplog):
    response = MagicMock(status_code=500)
    response.json.return_value = {"access_token": "must-never-be-logged", "detail": "upstream"}
    http_client = MagicMock()
    http_client.request = AsyncMock(return_value=response)
    http_client.get = AsyncMock()
    http_client.cookies.get.return_value = None
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=http_client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(market.httpx, "AsyncClient", lambda **kwargs: context)
    await market._proxy_json(
        "POST",
        "/api/auth/browser-handoff",
        authorization="Bearer must-never-be-logged",
        json_body={"target": "/wallet", "purpose": "wallet"},
        return_error_payload=True,
        sensitive=True,
        retries=1,
    )
    assert "must-never-be-logged" not in caplog.text
    assert "status=500" in caplog.text
