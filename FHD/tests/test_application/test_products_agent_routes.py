from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes.domains.product import routes as product_routes
from app.fastapi_routes.tools_execute import router as tools_router
from app.legacy.routes.product import compat_routes as product_compat_routes
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_price_template_import_cannot_write_before_shared_approval(
    tmp_path, monkeypatch, trusted_actor
):
    from io import BytesIO

    from docx import Document

    actor = trusted_actor(tenant_id=None, role="admin", tier="admin")
    monkeypatch.setattr(
        "app.utils.path_io.upload_helpers.get_upload_dir", lambda: tmp_path / "inputs"
    )
    monkeypatch.setattr(
        "app.infrastructure.documents.price_list_export.fhd_repo_root", lambda: tmp_path
    )
    document = Document()
    document.add_paragraph("Original price template")
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    destination = tmp_path / "424" / "document_templates" / "price_list_default.docx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original active template")
    app = FastAPI()
    app.include_router(product_routes.router)
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(None), TestClient(app) as client:
        files = {"template_file": ("price.docx", source)}
        anonymous = client.post("/api/products/import/price-list-template", files=files)
        assert anonymous.status_code == 401
        response = client.post(
            "/api/products/import/price-list-template",
            files=files,
            headers={**actor.headers, "Idempotency-Key": "original-template-import"},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "approval_scope_required"
        assert response.json()["execution_status"] == "not_started"
        assert destination.read_bytes() == b"original active template"
    saved = list((tmp_path / "inputs").rglob("*.docx"))
    assert len(saved) == 1 and saved[0].read_bytes() == source


@pytest.mark.parametrize(
    "method,path,body,action,params",
    [
        (
            "POST",
            "/api/products/batch",
            {"products": [{"name": "5003"}]},
            "batch_create",
            {"products": [{"name": "5003"}]},
        ),
        (
            "PUT",
            "/api/products/7",
            {"name": "5003 v2"},
            "update",
            {"id": 7, "name": "5003 v2"},
        ),
        (
            "PATCH",
            "/api/products/7",
            {"unit_price": 13.0},
            "update",
            {"id": 7, "unit_price": 13.0},
        ),
        ("DELETE", "/api/products/7", None, "delete", {"id": 7}),
        (
            "POST",
            "/products/add",
            {"product_name": "5003", "unit": "个"},
            "create",
            None,
        ),
        ("POST", "/products/update", {"id": 11, "name": "5003 v2"}, "update", None),
        ("POST", "/products/delete", {"id": 11}, "delete", None),
        ("POST", "/products/batch-delete", {"ids": [11, 12]}, "batch_delete", None),
    ],
)
def test_product_global_routes_fail_closed_without_approval_scope(
    tmp_path, monkeypatch, trusted_actor, method, path, body, action, params
):
    actor = trusted_actor(user_id=7, tenant_id=None, role="admin", tier="admin")
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repo,
    )
    service = MagicMock()
    monkeypatch.setattr("app.services.get_products_service", lambda: service)
    monkeypatch.setattr(product_compat_routes, "_products_write_raise", lambda: None)
    monkeypatch.setattr(product_compat_routes, "_business_mod_json_block", lambda **_: None)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    app = FastAPI()
    app.include_router(product_routes.router)
    app.include_router(product_compat_routes.router)
    app.include_router(tools_router)
    headers = {
        **actor.headers,
        "Idempotency-Key": "product-command",
        "X-User-Id": "999",
    }
    from app.infrastructure.tenant_scope import tenant_scope

    with (
        tenant_scope(None),
        TestClient(app, headers=headers, raise_server_exceptions=False) as client,
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, response.text
        receipt = response.json()
        assert receipt["success"] is False
        assert receipt["error_code"] == "approval_scope_required"
        assert receipt["execution_status"] == "not_started"
        assert not receipt.get("run_id")
        if params is not None:
            canonical = client.post(
                "/api/tools/execute",
                json={"tool_id": "products", "action": action, "params": params},
            )
            assert canonical.status_code == response.status_code, canonical.text
            assert canonical.json()["error_code"] == receipt["error_code"]
    assert service.mock_calls == []


def test_product_route_spoof_cannot_gain_permissions(monkeypatch, trusted_actor):
    actor = trusted_actor(user_id=7, permissions=[])
    service = MagicMock()
    monkeypatch.setattr("app.services.get_products_service", lambda: service)
    app = FastAPI()
    app.include_router(product_routes.router)
    app.include_router(tools_router)
    with TestClient(
        app,
        headers={
            **actor.headers,
            "X-User-Id": "1",
            "Idempotency-Key": "denied-product",
        },
    ) as client:
        denied = client.post(
            "/api/products/batch",
            json={"products": [{"name": "denied"}], "user_id": "1", "role": "admin"},
        )
        assert denied.status_code == 403, denied.text
        canonical = client.post(
            "/api/tools/execute",
            json={
                "tool_id": "products",
                "action": "batch_create",
                "params": {"products": [{"name": "denied"}], "user_id": "1"},
            },
        )
        assert canonical.status_code == 403, canonical.text
        client.headers.pop("X-Session-ID")
        assert client.delete("/api/products/7").status_code == 401
    assert service.mock_calls == []
