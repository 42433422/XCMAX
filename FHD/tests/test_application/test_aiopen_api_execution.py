"""Actual authenticated routes, customer SQL writes and isolated Mod databases."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call, generate_api_key
from app.application.customer_app_service import CustomerApplicationService
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.user import Session
from app.infrastructure.request_context import reset_current_request, set_current_request
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.middleware.csrf import CSRFMiddleware
from app.middleware.industry_context import IndustryContextMiddleware
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)
from tests.test_application.test_aiopen_screen_identity import host as host
from tests.test_application.test_aiopen_screen_identity import request_for


@contextmanager
def caller(headers):
    token = set_current_request(request_for(**headers))
    try:
        yield
    finally:
        reset_current_request(token)


@pytest.fixture
def application(host, tmp_path, monkeypatch):
    from app.fastapi_routes import ai_open
    from app.fastapi_routes.domains.admin_audit.routes import router as admin_router
    from app.fastapi_routes.domains.auth.routes import router as auth_router
    from app.fastapi_routes.domains.customer.routes import router as customers_router

    engines = {
        name: create_engine(f"sqlite:///{tmp_path / (name + '.sqlite')}")
        for name in ("host-business", "mod-a", "mod-b")
    }
    factories = {name: sessionmaker(bind=engine) for name, engine in engines.items()}
    for name, engine in engines.items():
        PurchaseUnit.__table__.create(engine)
        for tenant in (7, 8):
            with tenant_scope(tenant), factories[name].begin() as db:
                db.add(
                    PurchaseUnit(
                        id=tenant, tenant_id=tenant, unit_name=f"{name}-{tenant}", is_active=True
                    )
                )
    with host.begin() as db:
        db.get(Session, 3).entitled_mod_ids_json = '["mod-a"]'
    selected = lambda: get_request_active_mod_id() or "host-business"
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", lambda: factories[selected()]())
    monkeypatch.setattr("app.bootstrap.get_customer_app_service", lambda: service)
    monkeypatch.setattr(
        "app.infrastructure.persistence.compat_db.base.get_sync_engine", lambda: engines[selected()]
    )
    # Select the shipped service-backed customer route, not downloaded plugins.
    monkeypatch.setenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", "1")
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.try_invoke_client_mod_customers_list", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(
        AIOPEN_STATE,
        "whitelist",
        {
            "/api/auth/profile": True,
            "/api/customers": True,
            "/api/admin/audit-logs": True,
            "/api/test": True,
        },
    )
    app = FastAPI()
    app.add_middleware(IndustryContextMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(customers_router, prefix="/api")
    app.include_router(ai_open.router)
    monkeypatch.setattr(ai_open, "_trace_aiopen_tool_call", lambda **kwargs: "")

    @app.get("/api/aiopen/manifest")
    def manifest():
        return {"success": True}

    @app.get("/api/test/redirect")
    def redirect():
        return RedirectResponse("https://elsewhere.invalid/collect", status_code=307)

    @app.delete("/api/test/delete")
    async def delete_body(request: Request):
        return {"success": True, "body": await request.json(), "tenant": current_tenant_id()}

    @app.api_route("/api/test/body", methods=["GET", "POST", "PATCH", "DELETE"])
    async def exact_body(request: Request):
        return {"success": True, "body": await request.json()}

    yield app, factories
    for engine in engines.values():
        engine.dispose()


def test_real_protected_profile_uses_key_owner_not_browser_or_model(application):
    app, _ = application
    key = generate_api_key(request=request_for(**{"X-Session-Id": "login-3"}))["key"]
    with caller({"X-AIOPEN-Key": key, "X-Session-Id": "login-5"}), tenant_scope(8):
        result = _tool_api_call(
            app,
            {"path": "/api/auth/profile", "owner_id": "5", "headers": {"X-Session-ID": "login-5"}},
        )
        assert result["success"], result
        assert result["data"]["data"]["user"]["id"] == 3
        assert result["execution_scope"] == {"owner_id": "3", "tenant_id": "7", "mod_id": ""}
        assert current_tenant_id() == 8
    assert "login-3" not in str(result) and key not in str(result)


def test_actual_customer_route_reads_writes_and_rejects_other_tenant(application):
    app, factories = application
    with caller({"X-Session-Id": "login-3"}):
        read = _tool_api_call(app, {"path": "/api/customers/list"})
        assert read["success"], read
        assert [row["id"] for row in read["data"]["data"]] == [7]
        update = _tool_api_call(
            app,
            {
                "path": "/api/customers/7",
                "method": "PUT",
                "body": {"customer_name": "真实接口更新"},
            },
        )
        assert update["success"], update
        denied = _tool_api_call(
            app,
            {"path": "/api/customers/8", "method": "PUT", "body": {"customer_name": "不得跨租户"}},
        )
        assert not denied["success"] and denied["status_code"] == 404, denied
    with tenant_scope(7), factories["host-business"]() as db:
        assert db.get(PurchaseUnit, 7).unit_name == "真实接口更新"
    with tenant_scope(8), factories["host-business"]() as db:
        assert db.get(PurchaseUnit, 8).unit_name == "host-business-8"


def test_mod_entitlement_and_database_scope_are_revalidated(application, host):
    app, factories = application
    key = generate_api_key(request=request_for(**{"X-Session-Id": "login-3"}))["key"]
    with caller({"X-AIOPEN-Key": key}):
        result = _tool_api_call(
            app,
            {
                "path": "/api/customers/7",
                "method": "PUT",
                "mod_id": "mod-a",
                "body": {"customer_name": "仅修改授权模块"},
            },
        )
        assert result["success"], result
        denied = _tool_api_call(app, {"path": "/api/customers/list", "mod_id": "mod-b"})
        assert not denied["success"] and denied["code"] == "API_IDENTITY_REQUIRED"
        with host.begin() as db:
            db.get(Session, 3).entitled_mod_ids_json = "[]"
        assert not _tool_api_call(app, {"path": "/api/customers/list", "mod_id": "mod-a"})[
            "success"
        ]
    for name, factory in factories.items():
        with tenant_scope(7), factory() as db:
            assert db.get(PurchaseUnit, 7).unit_name == (
                "仅修改授权模块" if name == "mod-a" else f"{name}-7"
            )
    assert get_request_active_mod_id() == ""


def test_api_has_no_authentication_bypass_and_preserves_delete_body(application, host):
    app, _ = application
    with caller({"X-Session-Id": "login-3"}):
        forbidden = _tool_api_call(app, {"path": "/api/admin/audit-logs"})
        assert not forbidden["success"] and forbidden["status_code"] == 403
        delete = _tool_api_call(
            app, {"path": "/api/test/delete", "method": "DELETE", "body": {"ids": [1, 2]}}
        )
        assert delete["success"] and delete["data"]["body"] == {"ids": [1, 2]}
        assert delete["data"]["tenant"] == 7
        redirect = _tool_api_call(app, {"path": "/api/test/redirect"})
        assert not redirect["success"] and redirect["status_code"] == 307
    assert _tool_api_call(app, {"path": "/api/auth/profile"})["code"] == "API_IDENTITY_REQUIRED"


def test_external_rest_call_reaches_real_authenticated_route(application):
    app, _ = application
    key = generate_api_key(request=request_for(**{"X-Session-Id": "login-3"}))["key"]
    with TestClient(app) as client:
        result = client.post(
            "/api/aiopen/invoke",
            headers={"X-AIOPEN-Key": key},
            json={"tool": "api_call", "args": {"path": "/api/auth/profile"}},
        ).json()
    assert result["success"], result
    assert result["data"]["data"]["user"]["id"] == 3


def test_disabled_child_api_is_not_reenabled_by_parent(application, monkeypatch):
    app, _ = application
    monkeypatch.setitem(AIOPEN_STATE, "whitelist", {"/api/auth": True, "/api/auth/profile": False})
    with caller({"X-Session-Id": "login-3"}):
        denied = _tool_api_call(app, {"path": "/api/auth/profile"})
        assert denied["code"] == "ROUTE_NOT_WHITELISTED"


@pytest.mark.parametrize(
    "method,body",
    [
        ("POST", {"quantity": 1}),
        ("POST", [1, True, {"name": "客户"}]),
        ("POST", None),
        ("GET", {"filter": 7}),
        ("DELETE", [1, 2]),
        ("PATCH", "exact string"),
    ],
)
def test_json_body_preserved_without_hidden_fields(application, method, body):
    app, _ = application
    with caller({"X-Session-Id": "login-3"}):
        result = _tool_api_call(app, {"path": "/api/test/body", "method": method, "body": body})
        assert result["success"], result
        assert result["data"]["body"] == body


def test_non_json_body_is_rejected_before_execution(application):
    app, _ = application
    with caller({"X-Session-Id": "login-3"}):
        assert (
            _tool_api_call(app, {"path": "/api/test/body", "method": "POST", "body": float("nan")})[
                "code"
            ]
            == "INVALID_API_BODY"
        )


def test_host_override_restores_mod_and_expired_login_cannot_write(application, host):
    app, factories = application
    token = set_request_active_mod_id("mod-b")
    try:
        with caller({"X-Session-Id": "login-3"}):
            result = _tool_api_call(app, {"path": "/api/customers/list", "mod_id": ""})
            assert result["success"] and result["execution_scope"]["mod_id"] == ""
            assert result["data"]["data"][0]["customer_name"] == "host-business-7"
            assert get_request_active_mod_id() == "mod-b"
            with host.begin() as db:
                db.get(Session, 3).expires_at = datetime.now(UTC) - timedelta(seconds=1)
            denied = _tool_api_call(
                app,
                {
                    "path": "/api/customers/7",
                    "method": "PUT",
                    "mod_id": "",
                    "body": {"customer_name": "invalid"},
                },
            )
            assert not denied["success"] and denied["code"] == "API_IDENTITY_REQUIRED"
            assert get_request_active_mod_id() == "mod-b"
    finally:
        reset_request_active_mod_id(token)
    with tenant_scope(7), factories["host-business"]() as db:
        assert db.get(PurchaseUnit, 7).unit_name == "host-business-7"


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/api/customers",
        "//example.com/api/customers",
        "/api/customers/../auth/profile",
        "/api/customers/%2e%2e/auth/profile",
        "/api/customers/%252e%252e/auth/profile",
        "/api/customers/%5c../auth/profile",
        "/api/customers/%0a",
        "/api/customers#fragment",
    ],
)
def test_credentials_never_attach_to_nonlocal_or_ambiguous_path(application, path):
    app, _ = application
    with caller({"X-Session-Id": "login-3"}):
        assert _tool_api_call(app, {"path": path})["code"] == "INVALID_API_PATH"


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_advertised_http_metadata_methods_are_executable_without_fake_exports(application, method):
    from fastapi.responses import Response

    app, _ = application
    requests = []

    @app.api_route("/api/test/metadata", methods=["HEAD", "OPTIONS"])
    async def metadata(request: Request):
        requests.append((request.method, await request.body()))
        return Response(
            b"" if request.method == "HEAD" else b'{"success":true}',
            media_type="application/octet-stream"
            if request.method == "HEAD"
            else "application/json",
            headers={
                "Content-Disposition": 'attachment; filename="large.xlsx"',
                "Set-Cookie": "session=not-for-model",
                "X-Internal-Token": "private-marker",
            }
            if request.method == "HEAD"
            else {"Allow": "GET, HEAD, OPTIONS"},
        )

    with caller({"X-Session-ID": "login-3"}):
        result = _tool_api_call(app, {"path": "/api/test/metadata", "method": method})
    assert result["success"], result
    assert requests == [(method, b"")]
    assert "artifacts" not in result
    assert "not-for-model" not in str(result) and "private-marker" not in str(result)
    if method == "HEAD":
        assert result["data"]["headers"]["content-disposition"].endswith('large.xlsx"')
