"""Company names survive refresh/login and failed market writes leave SQLite intact."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def company_app(tmp_path, monkeypatch):
    import app.db as database
    import app.db.session as db_session
    from app.db.base import Base
    from app.db.models.tenant import Tenant
    from app.db.models.user import Session, User
    from app.fastapi_routes.domains.auth import routes
    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "0")
    path = tmp_path / "company.sqlite3"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr(db_session, "SessionLocal", sessions)
    with sessions.begin() as db:
        for uid, market_id, active in (
            (1, 101, True),
            (2, 202, True),
            (3, None, True),
            (4, 404, False),
        ):
            db.add(Tenant(id=uid, code=f"company-{uid}", name=f"Original {uid}"))
            db.add(
                User(
                    id=uid,
                    username=f"company-{uid}",
                    password=generate_password_hash("fixture-only-password"),
                    role="user",
                    tier="enterprise",
                    is_active=active,
                    tenant_id=uid,
                    market_user_id=market_id,
                )
            )
            db.add(
                Session(
                    session_id=f"company-session-{uid}",
                    user_id=uid,
                    tenant_id=uid,
                    company_brand=f"Original {uid}",
                    account_kind="enterprise",
                    market_user_id=market_id,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )

    async def resolve_token(sid):
        return None if sid == "company-session-3" else "fixture-market-token"

    async def save_market(_method, _path, **kwargs):
        return {"ok": True, "company": kwargs["json_body"]["company"]}

    token = AsyncMock(side_effect=resolve_token)
    market = AsyncMock(side_effect=save_market)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token", token
    )
    monkeypatch.setattr("app.fastapi_routes.market_account._proxy_json", market)
    app = FastAPI()
    app.add_api_route("/api/auth/company-brand", routes.auth_update_company_brand, methods=["POST"])
    app.add_api_route("/api/auth/me", routes.auth_me, methods=["GET"])

    def snapshot():
        with sqlite3.connect(path) as db:
            return tuple(db.iterdump())

    def names():
        with sessions() as db:
            return (
                {row.id: row.name for row in db.query(Tenant)},
                {row.session_id: row.company_brand for row in db.query(Session)},
            )

    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            sessions=sessions,
            engine=engine,
            snapshot=snapshot,
            names=names,
            token=token,
            market=market,
        )
    engine.dispose()


def save(app, brand="New Company", sid="company-session-1", **extra):
    return app.client.post(
        "/api/auth/company-brand",
        json={"company_brand": brand, **extra},
        headers={"X-Session-ID": sid, "X-User-ID": "2", "X-Tenant-ID": "2"},
    )


def test_market_name_persists_on_refresh_and_only_current_tenant_changes(company_app):
    app = company_app
    response = save(app, "  新的公司  ", tenant_id=2, user_id=2)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "success": True,
        "company_brand": "新的公司",
        "tenant_name": "新的公司",
        "persistence_scope": "account",
    }
    tenants, sessions = app.names()
    assert tenants == {1: "新的公司", 2: "Original 2", 3: "Original 3", 4: "Original 4"}
    assert sessions["company-session-1"] == "新的公司"
    assert sessions["company-session-2"] == "Original 2"
    refreshed = app.client.get("/api/auth/me", headers={"X-Session-ID": "company-session-1"}).json()
    assert refreshed["data"]["company_brand"] == "新的公司"
    assert refreshed["data"]["tenant_name"] == "新的公司"
    assert app.market.call_args.kwargs["json_body"] == {"company": "新的公司"}


@pytest.mark.parametrize(
    "payload",
    [
        {"__proxy_error__": True, "status_code": 403},
        {"ok": False},
        {},
        {"success": True},
        {"ok": True, "company": "Wrong Company"},
        None,
    ],
)
def test_failed_or_unconfirmed_market_save_does_not_change_local_data(company_app, payload):
    app = company_app
    app.market.side_effect = None
    app.market.return_value = payload
    before = app.snapshot()
    response = save(app)
    assert response.status_code == 502
    assert response.json()["success"] is False
    assert app.snapshot() == before


def test_market_exception_does_not_change_local_data(company_app):
    app = company_app
    app.market.side_effect = RuntimeError("upstream unavailable")
    before = app.snapshot()
    assert save(app).status_code == 502
    assert app.snapshot() == before


def test_expired_market_token_cannot_fall_back_to_local_save(company_app):
    app = company_app
    app.token.side_effect = None
    app.token.return_value = None
    before = app.snapshot()
    response = save(app)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MARKET_NOT_BOUND"
    app.market.assert_not_awaited()
    assert app.snapshot() == before


@pytest.mark.parametrize("sid,status", [("", 401), ("missing", 401), ("company-session-4", 403)])
def test_company_save_preserves_real_session_auth(company_app, sid, status):
    app = company_app
    before = app.snapshot()
    assert save(app, sid=sid).status_code == status
    app.market.assert_not_awaited()
    assert app.snapshot() == before


def test_empty_name_does_not_clear_workspace_or_call_market(company_app):
    app = company_app
    before = app.snapshot()
    assert save(app, "  ").status_code == 400
    app.market.assert_not_awaited()
    assert app.snapshot() == before


def test_local_commit_failure_rolls_back_tenant_and_session_after_remote_success(company_app):
    app = company_app
    before = app.snapshot()

    def reject_session_update(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("UPDATE sessions"):
            raise RuntimeError("fixture local write failure")

    event.listen(app.engine, "before_cursor_execute", reject_session_update)
    try:
        response = save(app)
    finally:
        event.remove(app.engine, "before_cursor_execute", reject_session_update)
    assert response.status_code == 500
    assert "企业账号名称已同步" in response.json()["error"]["message"]
    assert app.snapshot() == before
    assert save(app).status_code == 200


@pytest.mark.asyncio
async def test_local_company_survives_real_password_login_with_new_session(company_app):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_finalize import finalize_enterprise_login

    app = company_app
    response = save(app, "本机团队", sid="company-session-3")
    assert response.status_code == 200, response.text
    assert response.json()["persistence_scope"] == "local"
    app.market.assert_not_awaited()
    login = get_auth_app_service().login("company-3", "fixture-only-password")
    assert login["success"], login
    assert login["session_id"] != "company-session-3"
    login["entitled_mod_ids"] = []
    result = await finalize_enterprise_login(
        result=login,
        session_id=login["session_id"],
        market_result=None,
        account_kind="enterprise",
        username="company-3",
        sku="generic",
        skip_market_sync=True,
    )
    assert result["company_brand"] == "本机团队"
    assert result["tenant_name"] == "本机团队"
    refreshed = app.client.get("/api/auth/me", headers={"X-Session-ID": login["session_id"]}).json()
    assert refreshed["data"]["company_brand"] == "本机团队"
    assert refreshed["data"]["tenant_name"] == "本机团队"


@pytest.mark.asyncio
async def test_new_local_workspace_uses_username_and_market_login_still_uses_market_company(
    company_app,
):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_finalize import finalize_enterprise_login
    from app.db.models.user import User

    app = company_app
    with app.sessions.begin() as db:
        db.query(User).filter(User.id == 3).one().tenant_id = None
    local = get_auth_app_service().login("company-3", "fixture-only-password")
    assert local["success"], local
    local["entitled_mod_ids"] = []
    local = await finalize_enterprise_login(
        result=local,
        session_id=local["session_id"],
        market_result=None,
        account_kind="enterprise",
        username="company-3",
        sku="generic",
        skip_market_sync=True,
    )
    assert local["company_brand"] == "company-3"
    assert local["tenant_name"] == "company-3"

    market = get_auth_app_service().login("company-1", "fixture-only-password")
    assert market["success"], market
    market["entitled_mod_ids"] = []
    market = await finalize_enterprise_login(
        result=market,
        session_id=market["session_id"],
        market_result={
            "success": True,
            "is_enterprise": True,
            "raw": {"user": {"id": 101, "company": "Market Company"}},
        },
        account_kind="enterprise",
        username="company-1",
        sku="generic",
    )
    assert market["company_brand"] == "Market Company"
    assert market["tenant_name"] == "Market Company"


@pytest.mark.parametrize("token", ["plain-token", "Bearer prefixed-token"])
def test_market_authorization_and_name_length_contract(company_app, token):
    app = company_app
    app.token.side_effect = None
    app.token.return_value = token
    response = save(app, "x" * 500)
    assert response.status_code == 200
    assert response.json()["company_brand"] == "x" * 256
    assert app.market.call_args.kwargs["authorization"] == (
        token if token.startswith("Bearer ") else f"Bearer {token}"
    )
