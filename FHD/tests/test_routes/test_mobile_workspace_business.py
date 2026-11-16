from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mobile_extensions.routes_workspace import WorkspaceRoutes


@pytest.fixture
def native():
    current = {"user": SimpleNamespace(id=7, tenant_id=42)}
    router = WorkspaceRoutes(SimpleNamespace(), lambda: current["user"]).router
    app = FastAPI()
    app.include_router(router, prefix="/api/mobile/v1")
    return TestClient(app), current, router


def test_templates_require_owned_account_and_use_shared_handler(native, monkeypatch):
    from app.fastapi_routes import template_api
    from app.infrastructure.tenant_scope import current_tenant_id

    client, current, _ = native

    def read(request):
        assert current_tenant_id() == 42
        assert request.state.tenant_id == 42
        return {"success": True, "templates": [{"id": "db:42"}]}

    shared = Mock(side_effect=read)
    monkeypatch.setattr(template_api, "templates_list_compat", shared)
    assert client.get("/api/mobile/v1/workspace/templates").json()["templates"] == [{"id": "db:42"}]
    current["user"] = None
    assert client.get("/api/mobile/v1/workspace/templates").status_code == 401
    current["user"] = SimpleNamespace(id=7, tenant_id=None)
    assert client.get("/api/mobile/v1/workspace/templates").status_code == 403
    assert shared.call_count == 1


def test_shipment_aliases_keep_original_dependencies_and_no_broad_proxy(native):
    from starlette.requests import Request

    from app.fastapi_routes.domains.shipment.shipment_orders import router as original
    from app.infrastructure.auth.business_scope_gate import _request_path, uses_tenant_scoped_store

    client, current, router = native
    prefix = "/api/mobile/v1/workspace/shipment/shipment-records/"
    for route in router.routes:
        if "/shipment/" not in route.path:
            continue
        source = next(
            r
            for r in original.routes
            if r.endpoint is route.endpoint and r.methods == route.methods
        )
        assert route.dependencies[1:] == source.dependencies
        request = Request({"type": "http", "path": "/api/mobile/v1" + route.path, "headers": []})
        assert _request_path(request) == source.path
        assert uses_tenant_scoped_store(request)
    current["user"] = None
    for method in ("post", "patch", "delete"):
        assert client.request(method, prefix + "record", json={"id": 1}).status_code == 401
    assert client.get(prefix + "export").status_code == 401
    assert client.post("/api/mobile/v1/workspace/shipment/orders/clear-all").status_code == 404


def test_native_alias_preserves_enterprise_permission_denial(native, monkeypatch):
    from app.application.facades import session_facade
    from app.infrastructure.auth import business_scope_gate as gate

    client, current, _ = native
    monkeypatch.setattr(gate, "resolve_session_user", lambda request: current["user"])
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "enterprise")
    permission = Mock(return_value=False)
    monkeypatch.setattr(
        session_facade, "get_auth_service", lambda: SimpleNamespace(has_permission=permission)
    )
    response = client.patch(
        "/api/mobile/v1/workspace/shipment/shipment-records/record", json={"id": 1, "amount": 100}
    )
    assert response.status_code == 403
    assert permission.call_args.args[1] == "shipment.edit"
