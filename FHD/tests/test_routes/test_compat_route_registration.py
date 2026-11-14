"""Exercise the mounted compatibility contracts, including prefix and match order."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app.fastapi_routes import ai_assistant
from app.fastapi_routes.domains.customer import customer_routes
from app.fastapi_routes.domains.product import product_routes
from app.infrastructure.auth import business_scope_gate
from app.legacy.routes import legacy_compat
from app.legacy.routes.openapi_route_compat import iter_effective_routes
from app.legacy.routes.product import compat_routes

PRODUCT_PATHS = (
    ("DELETE", "/api/products/{product_id}"),
    ("POST", "/api/products/import/price-list-template"),
    ("GET", "/api/products/export.xlsx"),
    ("GET", "/api/products/product_names"),
    ("GET", "/api/products/product_names/search"),
    ("GET", "/api/products/search"),
    ("POST", "/api/products/batch"),
    ("POST", "/api/products/{product_id}"),
    ("PUT", "/api/products/{product_id}"),
    ("PATCH", "/api/products/{product_id}"),
)


@pytest.fixture
def local_compat(monkeypatch):
    # Preserve the local generic edition's existing policy. Enterprise denials
    # are exercised separately without overriding the router dependencies.
    monkeypatch.setattr(business_scope_gate, "resolve_product_sku", lambda: "generic")
    monkeypatch.setattr(business_scope_gate, "resolve_session_user", lambda _request: None)


@pytest.mark.parametrize("debug_gap", [False, True])
def test_product_paths_mount_once_and_dispatch_without_a_second_api(
    local_compat, monkeypatch, tmp_path, debug_gap
):
    app = FastAPI()
    legacy_compat._register_xcagi_compat_routes(app)
    monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "1" if debug_gap else "0")
    legacy_compat._register_legacy_gap_if_enabled(app)
    routes = list(iter_effective_routes(app.routes))
    assert not any(route.path.startswith("/api/api/products") for route in routes)
    for method, path in PRODUCT_PATHS:
        assert sum(route.path == path and method in (route.methods or ()) for route in routes) == 1

    exported = tmp_path / "products.xlsx"
    exported.write_bytes(b"exported worksheet")
    service = Mock()
    service.get_product_names.return_value = {"success": True, "data": []}
    service.get_products.return_value = {"success": True, "data": []}
    service.export_to_excel.return_value = {
        "success": True,
        "file_path": str(exported),
        "filename": exported.name,
    }
    monkeypatch.setattr(product_routes, "_svc", lambda: service)
    monkeypatch.setattr(product_routes, "_run_products_agent", lambda **_kwargs: {"success": True})
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header", lambda _r: None
    )
    monkeypatch.setattr(compat_routes, "_products_compat_preflight", lambda *_args: None)
    compat_update = Mock(return_value={"success": True, "source": "named-compat"})
    monkeypatch.setattr(compat_routes, "_run_products_compat_agent", compat_update)
    with TestClient(app) as client:
        for method, path in PRODUCT_PATHS:
            kwargs = {"json": {"products": [{"name": "test"}]}} if method != "GET" else {}
            response = client.request(method, path.replace("{product_id}", "7"), **kwargs)
            expected = 400 if path.endswith("/price-list-template") else 200
            assert response.status_code == expected, (method, path, response.text)
        response = client.post("/api/products/update", json={"id": 7, "name": "updated"})
        assert response.status_code == 200 and response.json()["source"] == "named-compat"
        compat_update.assert_called_once()
        if not debug_gap:
            assert client.get("/api/api/products/search").status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/print/single_label"),
        ("POST", "/api/print/pdf_labels"),
        ("POST", "/api/print-last"),
        ("GET", "/api/customers/export"),
        ("GET", "/api/customers/export/"),
        ("POST", "/api/products/resolve-name-hints"),
        ("POST", "/api/products/resolve-name-hints/"),
        ("GET", "/api/products/product_names"),
    ],
)
@pytest.mark.parametrize("authenticated,status", [(False, 401), (True, 403)])
def test_fixed_compat_paths_preserve_enterprise_business_boundary(
    monkeypatch, method, path, authenticated, status
):
    monkeypatch.setattr(business_scope_gate, "resolve_product_sku", lambda: "enterprise")

    def principal(_request):
        if not authenticated:
            raise HTTPException(401, "login required")
        return SimpleNamespace(id=8, tenant_id=23, role="user", tier="enterprise")

    monkeypatch.setattr(business_scope_gate, "get_logged_in_user", principal)
    app = FastAPI()
    app.include_router(ai_assistant.router)
    app.include_router(customer_routes.router, prefix="/api")
    app.include_router(compat_routes.router, prefix="/api")
    app.include_router(product_routes.router)
    with TestClient(app) as client:
        response = client.request(method, path, json={"hints": ["test"]})
    assert response.status_code == status


def test_retired_compat_routes_keep_status_shape_and_migration_guidance(local_compat, monkeypatch):
    app = FastAPI()
    app.include_router(ai_assistant.router)
    app.include_router(customer_routes.router, prefix="/api")
    app.include_router(compat_routes.router, prefix="/api")
    monkeypatch.setattr(compat_routes, "verify_db_read_token_header", lambda _r: None)
    monkeypatch.setattr(compat_routes, "_business_mod_json_block", lambda: None)
    with TestClient(app) as client:
        for path, replacement in (
            ("/api/print-last", "/api/print/{filename}"),
            ("/api/print/pdf_labels", "/api/print/single_label"),
        ):
            response = client.post(path)
            assert response.status_code == 501
            assert response.json()["success"] is False
            assert response.json()["replacement"] == replacement
            operation = app.openapi()["paths"][path]["post"]
            assert operation["deprecated"] and "501" in operation["responses"]
        for suffix in ("", "/"):
            response = client.get(f"/api/customers/export{suffix}")
            assert response.status_code == 501 and "/customers 客户页" in response.json()["detail"]
            response = client.post(
                f"/api/products/resolve-name-hints{suffix}", json={"hints": ["test"]}
            )
            assert response.status_code == 501 and "name_hint" in response.json()["detail"]
        hints = app.openapi()["paths"]["/api/products/resolve-name-hints"]["post"]
        assert hints["deprecated"] and "501" in hints["responses"]


def test_mod_docx_export_uses_current_compat_implementation_and_read_gate(
    local_compat, monkeypatch
):
    from app.mod_sdk import host_services

    assert host_services.products_export_docx is compat_routes.products_export_docx
    source = (
        Path(__file__).resolve().parents[2]
        / "mods/bridge/xcagi-erp-domain-bridge/backend/blueprints.py"
    )
    spec = importlib.util.spec_from_file_location("compat_cleanup_erp_bridge", source)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    render = Mock(return_value=Response(b"document", media_type="application/test-docx"))
    read = Mock()
    monkeypatch.setattr(compat_routes, "_products_price_list_word_response", render)
    monkeypatch.setattr(compat_routes, "verify_db_read_token_header", read)
    app = FastAPI()
    app.include_router(compat_routes.router, prefix="/api")
    bridge.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    params = {"unit": "A", "keyword": "B", "export_date": "2026-11-07", "template_id": "t"}
    with TestClient(app) as client:
        for prefix in ("/api", "/api/mod/xcagi-erp-domain-bridge"):
            response = client.get(f"{prefix}/products/export.docx", params=params)
            assert response.status_code == 200 and response.content == b"document"
            render.assert_called_with("A", "B", "2026-11-07", "t")
        assert read.call_count == render.call_count == 2
        read.side_effect = HTTPException(401, "read denied")
        response = client.get("/api/mod/xcagi-erp-domain-bridge/products/export.docx")
        assert response.status_code == 401
        assert render.call_count == 2
