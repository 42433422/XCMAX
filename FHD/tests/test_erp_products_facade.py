from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "bridge" / "xcagi-erp-domain-bridge"


def test_manifest_products_via_service():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("products_via_service") is True


def test_products_read_service_dispatch(monkeypatch):
    from unittest.mock import Mock

    from app.mod_sdk import erp_products_facade as pf

    service = Mock()
    service.get_products.return_value = {"success": True, "data": [], "total": 0}
    monkeypatch.setattr(pf, "_service", lambda: service)
    out = pf.products_list(None)
    assert out["success"] and out["execution_path"] == "products_service"


@pytest.mark.parametrize(
    "method,action,body",
    [
        ("products_add", "create", {"name": "P1"}),
        ("products_update", "update", {"id": 42, "name": "P2"}),
        ("products_delete", "delete", {"id": 42}),
        ("products_batch_delete", "batch_delete", {"ids": [42]}),
    ],
)
def test_products_write_facade_only_submits_canonical_contract(monkeypatch, method, action, body):
    from unittest.mock import Mock

    from starlette.requests import Request

    from app.mod_sdk import erp_products_facade as pf

    request = Request(
        {"type": "http", "method": "POST", "path": "/products/command", "headers": []}
    )
    entry = Mock(return_value=({"success": False, "state": "waiting_approval"}, 202))
    service = Mock()
    monkeypatch.setattr(pf, "_service", lambda: service)
    monkeypatch.setattr(pf, "_write_gate", lambda request: None)
    monkeypatch.setattr("app.fastapi_routes.tools_execute.run_tools_execute_agent", entry)
    response = getattr(pf, method)(request, body)
    assert response.status_code == 202
    assert service.mock_calls == []
    assert entry.call_count == 1
    submitted = entry.call_args.kwargs
    assert submitted["request"] is request
    assert set(submitted) == {"request", "body", "route_path"}
    assert submitted["body"]["tool_id"] == "products"
    assert submitted["body"]["action"] == action
    assert all(submitted["body"]["params"][key] == value for key, value in body.items())


def test_domain_handlers_products_list_uses_service(monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-erp-domain-bridge", "domain_handlers")
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.products_list",
        lambda request, **kw: {
            "success": True,
            "data": [],
            "total": 0,
            "source": "mod:xcagi-erp-domain-bridge",
            "execution_path": "products_service",
        },
    )
    out = mod.run_domain_handler("products", "list", page=1, per_page=10)
    assert out.get("execution_path") == "mod_domain_handler"
    assert out.get("source") == "mod:xcagi-erp-domain-bridge"


@pytest.mark.parametrize("extension", ["xlsx", "docx"])
def test_mod_export_routes_keep_filters_and_read_auth(monkeypatch, tmp_path, extension):
    from unittest.mock import Mock

    from fastapi import FastAPI, HTTPException, Response
    from fastapi.testclient import TestClient

    from app.fastapi_routes.domains.product import routes
    from app.infrastructure.mods.mod_manager import import_mod_backend_py
    from app.legacy.routes.product import compat_routes as compat

    artifact = tmp_path / "products.xlsx"
    artifact.write_bytes(b"export result")
    service = Mock()
    service.export_to_excel.return_value = {
        "success": True,
        "file_path": str(artifact),
        "filename": artifact.name,
    }
    monkeypatch.setattr(routes, "_svc", lambda: service)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    word = Mock(return_value=Response(b"word result"))
    monkeypatch.setattr(compat, "_products_price_list_word_response", word)
    auth = Mock()
    monkeypatch.setattr("app.infrastructure.auth.db_token.verify_db_read_token_header", auth)
    monkeypatch.setattr(compat, "verify_db_read_token_header", auth)
    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-erp-domain-bridge", "blueprints")
    app = FastAPI()
    mod.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    url = f"/api/mod/xcagi-erp-domain-bridge/products/export.{extension}"
    with TestClient(app) as client:
        response = client.get(
            url, params={"unit": "客户甲", "keyword": "DEMO-001", "template_id": "price"}
        )
        assert response.status_code == 200
        assert response.content == (b"export result" if extension == "xlsx" else b"word result")
        auth.assert_called_once()
        if extension == "xlsx":
            service.export_to_excel.assert_called_once_with(
                unit_name="客户甲", keyword="DEMO-001", template_id="price"
            )
        else:
            word.assert_called_once_with("客户甲", "DEMO-001", None, "price")
        auth.side_effect = HTTPException(status_code=403, detail="denied")
        assert client.get(url).status_code == 403
        assert service.export_to_excel.call_count + word.call_count == 1
