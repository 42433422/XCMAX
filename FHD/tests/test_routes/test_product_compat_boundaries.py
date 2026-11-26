"""Product route boundaries: gates, fallback order and durable Agent callbacks."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app.legacy.routes.product import compat_routes as routes

MUTATIONS = [
    ("create", "/products/add", {"product_name": "Widget", "unit": "个"}),
    ("update", "/products/update", {"id": 7, "name": "Updated"}),
    ("delete", "/products/delete", {"id": 7}),
    ("batch_delete", "/products/batch-delete", {"ids": [7, 8]}),
]


@pytest.fixture
def product_client(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.auth.business_scope_gate.resolve_product_sku",
        lambda: "generic",
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.business_scope_gate.resolve_session_user",
        lambda _request: None,
    )
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("action,path,payload", MUTATIONS)
def test_mod_denial_precedes_validation_and_agent(
    product_client, monkeypatch, action, path, payload
):
    calls = []
    denial = {"success": False, "message": "Mod unavailable"}
    monkeypatch.setattr(routes, "_products_compat_via_service_enabled", lambda: False)
    monkeypatch.setattr(routes, "_products_write_raise", lambda _request: calls.append("write"))

    def deny():
        calls.append("mod")
        return denial

    monkeypatch.setattr(routes, "_business_mod_json_block", deny)
    parse_id = Mock(side_effect=AssertionError("validation followed a denied Mod gate"))
    execute = Mock(side_effect=AssertionError("Agent started after a denied Mod gate"))
    monkeypatch.setattr(routes, "_product_parse_id", parse_id)
    monkeypatch.setattr(routes, "_run_products_compat_agent", execute)
    response = product_client.post(path, json=payload)
    assert response.status_code == 200
    assert response.json() == denial
    assert calls == ["write", "mod"]
    parse_id.assert_not_called()
    execute.assert_not_called()


def test_write_gate_http_denial_stops_before_mod_gate(product_client, monkeypatch):
    monkeypatch.setattr(routes, "_products_compat_via_service_enabled", lambda: False)
    monkeypatch.setattr(
        routes,
        "_products_write_raise",
        Mock(side_effect=HTTPException(403, "write denied")),
    )
    mod_gate = Mock()
    agent = Mock()
    monkeypatch.setattr(routes, "_business_mod_json_block", mod_gate)
    monkeypatch.setattr(routes, "_run_products_compat_agent", agent)
    response = product_client.post("/products/delete", json={"id": 7})
    assert response.status_code == 403
    assert response.json() == {"detail": "write denied"}
    mod_gate.assert_not_called()
    agent.assert_not_called()


def test_query_fallback_order_preserves_arguments_and_read_gate(product_client, monkeypatch):
    calls = []

    def dispatch(*args, **kwargs):
        calls.append(("mod", args, kwargs["keyword"], kwargs["unit"]))
        raise ConnectionError("Mod temporarily unavailable")

    def enabled():
        calls.append("flag")
        return True

    def service(request, **kwargs):
        calls.append(("service", kwargs))
        raise ConnectionError("service temporarily unavailable")

    def legacy(*args):
        calls.append(("legacy", args))
        return [{"id": 7}], 1, "compat schema"

    monkeypatch.setattr("app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler", dispatch)
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", enabled
    )
    monkeypatch.setattr("app.mod_sdk.erp_products_facade.products_list", service)
    monkeypatch.setattr(
        routes, "verify_db_read_token_header", lambda _request: calls.append("read")
    )
    monkeypatch.setattr(routes, "_load_products_list_impl_pg", legacy)
    params = {"page": 3, "per_page": 4, "keyword": "x'; --", "unit": "销售部"}
    response = product_client.get("/products/list", params=params)
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": [{"id": 7}],
        "total": 1,
        "schema_hint": "compat schema",
    }
    assert calls == [
        ("mod", ("products", "list"), params["keyword"], params["unit"]),
        "flag",
        ("service", params),
        "read",
        ("legacy", (3, 4, params["keyword"], params["unit"])),
    ]


@pytest.mark.parametrize("status", [401, 403])
def test_query_http_denial_does_not_fall_back(product_client, monkeypatch, status):
    monkeypatch.setattr(
        "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
        Mock(side_effect=HTTPException(status, "denied by Mod")),
    )
    enabled = Mock()
    legacy = Mock()
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", enabled
    )
    monkeypatch.setattr(routes, "_load_products_list_impl_pg", legacy)
    response = product_client.get("/products/list")
    assert response.status_code == status
    assert response.json() == {"detail": "denied by Mod"}
    enabled.assert_not_called()
    legacy.assert_not_called()


@pytest.mark.parametrize("error", [TypeError, KeyError, IndexError, AttributeError, RuntimeError])
def test_query_programming_error_does_not_fall_back(product_client, monkeypatch, error):
    monkeypatch.setattr(
        "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
        Mock(side_effect=error("invalid adapter contract")),
    )
    legacy = Mock()
    monkeypatch.setattr(routes, "_load_products_list_impl_pg", legacy)
    response = product_client.get("/products/list")
    assert response.status_code == 500
    legacy.assert_not_called()


@pytest.mark.parametrize("path", ["/products/price-list-export", "/products/export.docx"])
def test_export_aliases_share_guard_and_public_response_callback(product_client, monkeypatch, path):
    calls = []
    monkeypatch.setattr(
        routes, "verify_db_read_token_header", lambda _request: calls.append("read")
    )

    def document(*args):
        calls.append(args)
        return Response(
            b"document", media_type="application/test-docx", headers={"X-Template": "t"}
        )

    monkeypatch.setattr(routes, "_products_price_list_word_response", document)
    response = product_client.get(
        path,
        params={
            "unit": "销售部",
            "keyword": "Widget",
            "export_date": "2026-10-22",
            "template_id": "t",
        },
    )
    assert response.status_code == 200
    assert response.content == b"document"
    assert response.headers["content-type"] == "application/test-docx"
    assert response.headers["x-template"] == "t"
    assert calls == ["read", ("销售部", "Widget", "2026-10-22", "t")]


def test_preview_denial_does_not_resolve_or_build_template(product_client, monkeypatch):
    read_gate = Mock()
    preview = Mock()
    monkeypatch.setattr(routes, "verify_db_read_token_header", read_gate)
    monkeypatch.setattr("app.shell.mod_business_scope.business_data_exposed", lambda: False)
    monkeypatch.setattr(
        "app.shell.mod_business_scope.business_data_hidden_reason", lambda: "hidden"
    )
    monkeypatch.setattr(
        "app.infrastructure.documents.price_list_export.build_price_list_template_preview_json",
        preview,
    )
    response = product_client.get(
        "/products/price-list-template-preview", params={"template_id": "t"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "hidden"}
    read_gate.assert_called_once()
    preview.assert_not_called()
