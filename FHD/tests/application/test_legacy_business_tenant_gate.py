"""Enterprise tenant users cannot reach unscoped host business data."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.infrastructure.auth import business_scope_gate as gate


@pytest.fixture
def client(monkeypatch):
    from app.fastapi_routes.ai_assistant import router as ai_router
    from app.fastapi_routes.domains.customer.routes import router as customer_router
    from app.fastapi_routes.excel_extract import router as excel_router
    from app.fastapi_routes.materials import router as material_router
    from app.fastapi_routes.print_routes import router as print_router
    from app.fastapi_routes.shipment_orders import router as shipment_router
    from app.legacy.routes.product.compat_routes import router as product_router
    from app.legacy.routes.sidebar_capability_compat import router as sidebar_router

    principal = [SimpleNamespace(id=11, role="user", tier="enterprise", tenant_id=7)]
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(gate, "get_logged_in_user", lambda _request: principal[0])
    app = FastAPI()
    app.include_router(customer_router, prefix="/api")
    app.include_router(product_router, prefix="/api")
    for router in (
        ai_router,
        excel_router,
        material_router,
        print_router,
        shipment_router,
        sidebar_router,
    ):
        app.include_router(router)
    return TestClient(app), principal


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/customers/list"),
        ("POST", "/api/customers"),
        ("GET", "/api/products/list"),
        ("POST", "/api/products/add"),
        ("GET", "/api/shipment/orders"),
        ("POST", "/api/shipment/generate"),
        ("GET", "/api/materials"),
        ("POST", "/api/materials"),
        ("GET", "/api/print/printers"),
        ("GET", "/api/print/jobs"),
        ("POST", "/api/print/label"),
        ("GET", "/api/product_names"),
        ("GET", "/api/shipment-records/records"),
        ("POST", "/api/excel/data/import/products"),
        ("POST", "/api/excel/data/import/customers"),
    ],
)
def test_two_tenant_founders_and_member_cannot_reach_unscoped_business(client, method, path):
    http, principal = client
    for user in (
        SimpleNamespace(id=11, role="user", tier="enterprise", tenant_id=7),
        SimpleNamespace(id=22, role="user", tier="enterprise", tenant_id=8),
        SimpleNamespace(id=23, role="tenant:8:member", tier="enterprise", tenant_id=8),
    ):
        principal[0] = user
        response = http.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 403, (method, path, user, response.text)
        assert "租户数据隔离" in response.text


def test_anonymous_enterprise_request_cannot_bypass_tenant_gate(client, monkeypatch):
    http, _principal = client

    def unauthorized(_request):
        raise HTTPException(status_code=401, detail="请先登录")

    monkeypatch.setattr(gate, "get_logged_in_user", unauthorized)
    response = http.get("/api/customers/list")
    assert response.status_code == 401


def test_tenant_session_cannot_bypass_gate_when_sku_is_not_enterprise(client, monkeypatch):
    http, principal = client
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "generic")
    monkeypatch.setattr(gate, "resolve_session_user", lambda _request: principal[0])

    response = http.get("/api/customers/list")
    assert response.status_code == 403
    assert "租户数据隔离" in response.text


def test_non_tenant_generic_session_retains_legacy_route(client, monkeypatch):
    http, _principal = client
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "generic")
    monkeypatch.setattr(gate, "resolve_session_user", lambda _request: None)

    response = http.get("/api/print/jobs")
    assert response.status_code == 200
    assert response.json()["jobs"] == []


def test_non_tenant_platform_admin_permission_still_controls_legacy_route(client, monkeypatch):
    from app.application.facades import session_facade

    http, principal = client
    principal[0] = SimpleNamespace(id=1, role="admin", tier="admin", tenant_id=None)
    allowed = [False]
    monkeypatch.setattr(
        session_facade,
        "get_auth_service",
        lambda: SimpleNamespace(
            has_permission=lambda _user, code: code == "print.label" and allowed[0]
        ),
    )

    denied = http.get("/api/print/jobs")
    assert denied.status_code == 403
    assert "权限不足" in denied.text

    allowed[0] = True
    accepted = http.get("/api/print/jobs")
    assert accepted.status_code == 200
    assert accepted.json()["jobs"] == []
