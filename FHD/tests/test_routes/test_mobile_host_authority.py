"""Mobile account state and market credentials belong to the host, not a Mod DB."""

import json
from datetime import timedelta
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db as databases
from app.db.models.user import Session, User
from app.fastapi_routes import market_account as market
from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_api_extensions import extension_router
from app.infrastructure.mods.mod_auth import ModContextMiddleware
from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id
from app.security import mobile_jwt
from app.utils.time import utc_now_naive

_MOD = "mobile-authority-test"
_SID = "host-owned-session"


@pytest.fixture
def host_and_mod(tmp_path, monkeypatch):
    host_url = f"sqlite:///{tmp_path / 'host.sqlite'}"
    mod_url = f"sqlite:///{tmp_path / 'mod.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", host_url)
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URLS", json.dumps({_MOD: mod_url}))
    monkeypatch.setattr(databases, "_get_test_db_manager", lambda: None)
    monkeypatch.setattr(market, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setattr(market, "_MARKET_SESSION_REFRESH_TOKENS", {})
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "0")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active", lambda: False
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready", lambda *a, **k: True
    )
    engines = [databases._get_engine_for_url(url) for url in (host_url, mod_url)]
    factories = [sessionmaker(bind=engine) for engine in engines]
    for index, (engine, factory) in enumerate(zip(engines, factories, strict=True)):
        User.__table__.create(engine)
        Session.__table__.create(engine)
        with factory.begin() as db:
            db.add_all(
                User(
                    id=uid,
                    username=f"user-{uid}",
                    password="unused",
                    role="admin" if index else "user",
                )
                for uid in (71, 72)
            )
            db.flush()
            db.add(
                Session(
                    session_id=_SID,
                    user_id=72 if index else 71,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token="mod-token" if index else "host-token",
                    market_refresh_token="mod-refresh" if index else "host-refresh",
                )
            )
    try:
        yield factories
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("credential", ["cookie", "header", "bearer"])
def test_mobile_market_routes_use_host_credentials_under_active_mod(
    host_and_mod, monkeypatch, credential
):
    proxy = AsyncMock(return_value={"balance": "10.50", "user": {"id": 71}})
    monkeypatch.setattr(market, "_proxy_json", proxy)
    app = FastAPI()
    app.add_middleware(ModContextMiddleware)
    app.include_router(extension_router, prefix="/api/mobile/v1")
    headers = {"X-XCAGI-Active-Mod-Id": _MOD}
    if credential == "header":
        headers["X-Session-ID"] = _SID
    elif credential == "bearer":
        token = mobile_jwt.issue_mobile_tokens(user_id=71, session_id=_SID)["access_token"]
        headers["Authorization"] = f"Bearer {token}"
    with TestClient(app) as client:
        if credential == "cookie":
            client.cookies.set("session_id", _SID)
        queried = client.get("/api/mobile/v1/payment/query/test-order", headers=headers)
        assert queried.status_code == 200
        assert queried.json()["success"] is True
        wallet = client.get("/api/mobile/v1/wallet/balance", headers=headers)
        assert wallet.status_code == 200
        assert wallet.json()["data"]["synced"] is True
    assert proxy.await_count >= 4
    assert all(
        call.kwargs["authorization"] == "Bearer host-token" for call in proxy.await_args_list
    )
    active = set_request_active_mod_id(_MOD)
    try:
        market.save_session_market_token(_SID, "host-replacement", "host-new-refresh")
    finally:
        reset_request_active_mod_id(active)
    for index, factory in enumerate(host_and_mod):
        with factory() as db:
            row = db.query(Session).filter_by(session_id=_SID).one()
            assert row.market_access_token == ("mod-token" if index else "host-replacement")
            assert row.market_refresh_token == ("mod-refresh" if index else "host-new-refresh")


@pytest.mark.asyncio
@pytest.mark.parametrize("token_type", ["access", None])
@pytest.mark.parametrize("host_active", [True, False])
async def test_legacy_relay_uses_host_state_despite_shadow_mod_user(
    host_and_mod, token_type, host_active
):
    with host_and_mod[0].begin() as db:
        db.get(User, 71).is_active = host_active
    token = mobile_jwt.issue_mobile_tokens(user_id=71, session_id="mobile-relay-owned")[
        "access_token"
    ]
    if token_type is None:
        claims = mobile_jwt.verify_mobile_jwt(token)
        del claims["typ"]
        token = jwt.encode(claims, mobile_jwt._secret_key(), algorithm=mobile_jwt.MOBILE_JWT_ALG)
    active = set_request_active_mod_id(_MOD)
    try:
        request = Request({"type": "http", "path": "/api/mobile/v1/me", "headers": []})
        user = await get_mobile_user(request, authorization=f"Bearer {token}")
    finally:
        reset_request_active_mod_id(active)
    if host_active:
        assert user is not None
        assert user.id == 71
        assert user.role == "user"
    else:
        assert user is None
