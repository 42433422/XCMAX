"""Real local login/session/model transport flow with synthetic remote boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application import auth_app_service, enterprise_login_flow
from app.application import elt_login_authorization as account_sessions
from app.db.models import Permission, Role, Tenant, User, UserSession, role_permissions
from app.fastapi_routes import market_account
from app.fastapi_routes import reviewed_excel_template as routes
from app.fastapi_routes.domains.auth.auth_routes import router as auth_router
from app.fastapi_routes.template_api import router as template_router
from tests.fixtures.elt_template.sources.generate import sample
from tests.test_application.test_reviewed_excel_boundaries import synthetic_document_answer


@pytest.fixture
def standard_login(tmp_path, monkeypatch):
    import app.db as databases
    from app.application import reviewed_excel_review_store
    from app.application.elt import archive_store, service_uploads
    from app.application.facades import session_facade
    from app.db import init_db
    from app.db import session as db_session
    from app.db.elt_bootstrap import ensure_sqlite_elt_bootstrap
    from app.enterprise import mod_entitlements
    from app.fastapi_routes.reviewed_excel import archive as archive_routes
    from app.utils.path_io import path_utils
    from app.utils.security.password_hash import generate_password_hash

    engine = create_engine(
        f"sqlite:///{tmp_path / 'synthetic-login.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    for table in (
        User.__table__,
        UserSession.__table__,
        Tenant.__table__,
        Role.__table__,
        Permission.__table__,
        role_permissions,
    ):
        table.create(engine)
    ensure_sqlite_elt_bootstrap(engine=engine, swallow_errors=False)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    monkeypatch.setattr(databases, "HostSessionLocal", factory)
    # This test owns the complete schema; bootstrap is a DDL boundary, not authentication.
    monkeypatch.setattr(init_db, "ensure_runtime_auth_bootstrap", lambda **_: None)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    monkeypatch.setenv("SESSION_COOKIE_NAME", "session_id")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic-platform.invalid")
    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setenv("FHD_ELT_NOTICE_PUBLICATION", "not-published")
    with factory.begin() as db:
        db.add(
            Role(
                name="synthetic-reviewer",
                permissions=[
                    Permission(name=code, code=code) for code in ("elt.read", "elt.template.manage")
                ],
            )
        )
        db.add(
            User(
                id=7,
                username="synthetic-user",
                password=generate_password_hash("synthetic-password"),
                display_name="Synthetic",
                role="synthetic-reviewer",
                tier="enterprise",
                tenant_id=9,
                market_user_id=9001,
                is_active=True,
            )
        )
        db.flush()
        db.add(Tenant(id=9, code="synthetic-tenant", name="Synthetic", owner_user_id=7))
    backend = auth_app_service.AuthApplicationService()
    monkeypatch.setattr(auth_app_service, "get_auth_app_service", lambda: backend)
    # Wire actual session/auth services to the isolated database; no identity dependency is replaced.
    monkeypatch.setattr(session_facade, "get_session_service", lambda: backend.session_manager)
    monkeypatch.setattr(session_facade, "get_auth_service", lambda: backend)
    monkeypatch.setattr(
        enterprise_login_flow,
        "bind_tenant_for_login",
        lambda **_: {
            "tenant_id": 9,
            "tenant_name": "Synthetic",
        },
    )
    monkeypatch.setattr(market_account, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setattr(market_account, "_MARKET_SESSION_REFRESH_TOKENS", {})
    market_result = {
        "success": True,
        "token": "synthetic-current-market-token",
        "is_enterprise": True,
        "is_market_admin": False,
        "raw": {"user": {"id": 9001, "username": "synthetic-user", "company_brand": "Synthetic"}},
    }
    password_login, phone_login = (
        AsyncMock(return_value=market_result),
        AsyncMock(return_value=market_result),
    )
    monkeypatch.setattr(market_account, "login_market_with_password", password_login)
    monkeypatch.setattr(market_account, "login_market_with_phone_code", phone_login)
    monkeypatch.setattr(market_account, "fetch_market_membership_tier", AsyncMock(return_value=""))
    monkeypatch.setattr(
        mod_entitlements, "refresh_session_entitlements_from_market", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(mod_entitlements, "reload_enterprise_mods_after_login", AsyncMock())
    monkeypatch.setattr(mod_entitlements, "get_cached_entitled_client_mod_ids", lambda: set())

    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(path_utils, "get_business_archive_dir", lambda **_: str(archive_root))
    for module in (archive_store, archive_routes, reviewed_excel_review_store):
        monkeypatch.setattr(module, "default_archive_root", lambda: archive_root)
    monkeypatch.setattr(archive_store, "get_business_archive_dir", lambda **_: str(archive_root))
    for module in (service_uploads, routes, reviewed_excel_review_store):
        monkeypatch.setattr(module, "get_app_data_dir", lambda: str(tmp_path))

    sent = []
    client_type = httpx.AsyncClient

    def remote(request):
        assert request.url.host == "synthetic-platform.invalid"
        assert request.headers["Authorization"] == "Bearer synthetic-current-market-token"
        assert account_sessions.current_model_session_id(7)
        assert account_sessions.current_model_session_id(8) == ""
        sent.append(
            (request.method, request.url.path, account_sessions.current_model_session_id(7))
        )
        if request.method == "GET":
            assert request.url.path == "/api/llm/resolve-chat-default" and not request.url.params
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "provider": "synthetic",
                    "model": "synthetic-account-model",
                    "key_source": "platform",
                    "config_revision": "synthetic-revision",
                    "route_token": "synthetic-route-snapshot",
                },
            )
        assert request.method == "POST" and request.url.path == "/api/llm/chat/stream"
        payload = json.loads(request.content)
        assert payload["provider"] == "synthetic" and payload["model"] == "synthetic-account-model"
        assert payload["user_id"] == 7 and payload["allow_failover"] is False
        assert payload["route_token"] == "synthetic-route-snapshot"
        assert payload["stream"] is True
        task = json.loads(payload["messages"][1]["content"])
        data = (
            {"candidates": [{"clear": [], "reason": "synthetic model result"} for _ in range(3)]}
            if "feedback" in task
            else synthetic_document_answer(task)
        )
        return httpx.Response(
            200,
            text=(
                'event: status\ndata: {"state":"processing"}\n\n'
                + "data: "
                + json.dumps({"choices": [{"delta": {"content": json.dumps(data)}}]})
                + "\n\ndata: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream", "x-request-id": "synthetic-response"},
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**{**kwargs, "transport": httpx.MockTransport(remote)}),
    )
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(template_router)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            database=factory,
            sent=sent,
            password=password_login,
            phone=phone_login,
            market_result=market_result,
        )
    engine.dispose()


@pytest.mark.parametrize("method", ["password", "phone"])
def test_standard_login_persists_sessions_only_for_implemented_methods(standard_login, method):
    flow, client = standard_login, standard_login.client
    assert client.get("/api/templates/reviewed-excel/identity").status_code == 401
    assert (
        client.post(
            "/api/templates/reviewed-excel/classifications/missing/analyze",
            data={"version": "synthetic"},
        ).status_code
        == 401
    )
    with flow.database() as db:
        assert db.scalars(select(UserSession)).all() == []
    endpoint, payload, market = (
        (
            "/api/auth/login",
            {"username": "synthetic-user", "password": "synthetic-password"},
            flow.password,
        )
        if method == "password"
        else (
            "/api/auth/login-with-phone-code",
            {"phone": "10000000000", "code": "synthetic-code"},
            flow.phone,
        )
    )
    market.return_value = {"success": False, "status_code": 401, "message": "synthetic rejected"}
    failed = client.post(endpoint, json=payload)
    assert failed.json()["success"] is False
    assert not failed.headers.get_list("set-cookie")
    with flow.database() as db:
        assert db.scalars(select(UserSession)).all() == []
    market.return_value = flow.market_result
    login = client.post(endpoint, json=payload)
    if method == "phone":
        assert failed.status_code == login.status_code == 501
        assert login.json()["error_code"] == "SMS_AUTH_UNAVAILABLE"
        assert login.json()["capability"]["available"] is False
        assert not login.headers.get_list("set-cookie")
        market.assert_not_awaited()
        with flow.database() as db:
            assert db.scalars(select(UserSession)).all() == []
        assert client.get("/api/templates/reviewed-excel/identity").status_code == 401
        return
    assert login.status_code == 200 and login.json()["success"] is True, login.text
    sid = client.cookies.get("session_id")
    assert sid and sid == login.json()["session_id"]
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "xcagi_elt_notice" not in client.cookies
    with flow.database() as db:
        persisted = db.scalar(select(UserSession).where(UserSession.session_id == sid))
        assert persisted.user_id == 7 and persisted.tenant_id == 9
        assert persisted.market_access_token == "synthetic-current-market-token"
    # Clear only the synthetic process cache to prove the next requests read the stored token.
    market_account._MARKET_SESSION_TOKENS.clear()
    identity = client.get("/api/templates/reviewed-excel/identity")
    assert identity.json() == {"actor": "9:7", "model_access": {"status": "available"}}
    assert "login_authorization" not in identity.text
    body = sample()
    classified = client.post(
        "/api/templates/reviewed-excel/archive-classify",
        files={"file": ("synthetic.xlsx", body)},
        data={"expected_actor": "9:7", "request_key": "synthetic-first-login"},
    )
    assert classified.status_code == 200, classified.text
    item = classified.json()
    path = f"/api/templates/reviewed-excel/classifications/{item['classification_id']}"
    analyzed = client.post(
        path + "/analyze", data={"version": item["version"], "auto_group": "true"}
    )
    assert analyzed.status_code == 200, analyzed.text
    result = analyzed.json()
    assert result["model_status"] == "returned"
    preview = client.post(
        "/api/templates/reviewed-excel/preview",
        files={"file": ("synthetic.xlsx", body)},
        data={
            "expected_actor": "9:7",
            "classification_id": item["classification_id"],
            "classification_version": result["version"],
            "auto_slice_index": "0",
        },
    )
    assert preview.status_code == 200, preview.text
    model = preview.json()["proposal"]["model"]
    assert model["status"] == "returned" and len(preview.json()["proposal"]["candidates"]) == 3
    assert "login_authorization" not in model and "notice_version" not in model["authorization"]
    calls = [call for call in flow.sent if call[0] == "POST"]
    assert len(calls) >= 2 and all(call[2] == sid for call in flow.sent)
    assert client.cookies.get("session_id") == sid and "xcagi_elt_notice" not in client.cookies
