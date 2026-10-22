from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "xcagi-erp-domain-bridge"


def test_customer_export_download_is_tenant_scoped(tmp_path, monkeypatch):
    import importlib.util
    from io import BytesIO

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.customer_app_service import CustomerApplicationService
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk import erp_customers_facade

    engine = create_engine(f"sqlite:///{tmp_path / 'export.db'}")
    PurchaseUnit.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all(
            [
                PurchaseUnit(unit_name="SUNBIRD验收客户", contact_person="验收联系人", tenant_id=1),
                PurchaseUnit(unit_name="其他租户客户", tenant_id=2),
            ]
        )
        session.commit()
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", factory)
    monkeypatch.setattr(erp_customers_facade, "_service", lambda: service)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header", lambda request: None
    )
    spec = importlib.util.spec_from_file_location(
        "customer_export_bridge", MOD_DIR / "backend/blueprints.py"
    )
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    app = FastAPI()

    @app.middleware("http")
    async def customer_scope(request, call_next):
        with tenant_scope(1):
            return await call_next(request)

    bridge.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    response = TestClient(app).get("/api/mod/xcagi-erp-domain-bridge/customers/export")
    assert response.status_code == 200
    assert "spreadsheetml.sheet" in response.headers["content-type"]
    assert ".xlsx" in response.headers["content-disposition"]
    rows = list(load_workbook(BytesIO(response.content)).active.values)
    assert len(rows) == 2 and rows[1][1:3] == ("SUNBIRD验收客户", "验收联系人")
    assert "其他租户客户" not in str(rows)
    engine.dispose()


@pytest.mark.parametrize(
    "failure,status", [("outside", 500), ("missing", 500), ("service", 400), ("auth", 401)]
)
def test_customer_export_rejects_unsafe_or_failed_download(tmp_path, monkeypatch, failure, status):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.mod_sdk import erp_customers_facade

    service = Mock()
    service.export_to_excel.return_value = {
        "success": failure != "service",
        "file_path": str(
            tmp_path.parent / "outside.xlsx" if failure == "outside" else tmp_path / "missing.xlsx"
        ),
        "message": "导出失败",
    }
    monkeypatch.setattr(erp_customers_facade, "_service", lambda: service)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))

    def authorize(request):
        if failure == "auth":
            raise HTTPException(status_code=401, detail="需要登录")

    monkeypatch.setattr("app.infrastructure.auth.db_token.verify_db_read_token_header", authorize)
    with pytest.raises(HTTPException) as exc:
        erp_customers_facade.customers_export(
            Request({"type": "http", "method": "GET", "path": "/"})
        )
    assert exc.value.status_code == status
    if failure == "auth":
        service.export_to_excel.assert_not_called()


def test_erp_domain_mod_manifest():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data["id"] == "xcagi-erp-domain-bridge"
    assert data.get("config", {}).get("erp_domain_facade") is True


def test_erp_domains_config():
    cfg = json.loads((MOD_DIR / "config" / "erp_domains.json").read_text(encoding="utf-8"))
    ids = {d["id"] for d in cfg.get("domains", [])}
    # wechat 域已从 erp-domain-bridge 移除，计划迁移至客来来
    assert {"products", "customers", "shipment"} <= ids
    assert "wechat" not in ids


def test_blueprints_has_erp_domains():
    text = (MOD_DIR / "backend" / "blueprints.py").read_text(encoding="utf-8")
    assert "/products/list" in text
    assert "/domains/registry" in text
    # wechat 域已移除，不应再挂载 /wechat/contacts
    assert "/wechat/contacts" not in text
    assert "mount_wechat_contacts_routes" not in text


def test_list_erp_domains_registry_host(monkeypatch):
    from app.mod_sdk import erp_domain_compat as ed

    monkeypatch.setattr(ed, "is_erp_domain_via_mod_enabled", lambda: False)
    data = ed.list_erp_domains_registry()
    assert data.get("success") is True
    assert data.get("execution_path") == "host.api"
    assert data.get("domain_count") == 3


def test_list_erp_domains_registry_mod_facade(monkeypatch):
    from app.mod_sdk import erp_domain_compat as ed

    monkeypatch.setattr(ed, "is_erp_domain_via_mod_enabled", lambda: True)
    data = ed.list_erp_domains_registry()
    assert data.get("execution_via_mod_facade") is True
    assert "xcagi-erp-domain-bridge" in str(data.get("registry_endpoint"))


def test_resolve_host_api_path():
    from app.mod_sdk.erp_domain_compat import ERP_DOMAIN_BRIDGE_MOD_ID, resolve_host_api_path

    facade = f"/api/mod/{ERP_DOMAIN_BRIDGE_MOD_ID}/products/list"
    assert resolve_host_api_path(facade) == "/api/products/list"


def test_platform_shell_includes_erp_bridge():
    from app.mod_sdk.platform_shell import BRIDGE_MOD_HOST_APIS

    assert "xcagi-erp-domain-bridge" in BRIDGE_MOD_HOST_APIS


def test_manifest_mod_domain_handlers():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    handlers = data.get("config", {}).get("mod_domain_handlers") or []
    assert {"products", "shipment", "customers"} <= set(handlers)
    assert "wechat" not in set(handlers)
    from tests.mod_sdk_expectations import ERP_PHASE_TOKENS, ERP_REPOSITORY_ADAPTERS

    cfg = data.get("config", {})
    phase = cfg.get("phase") or cfg.get("repository_phase") or ""
    assert phase in ERP_PHASE_TOKENS
    assert cfg.get("repository_adapter") in ERP_REPOSITORY_ADAPTERS
    assert data.get("config", {}).get("erp_extended_pages") is True
    assert data.get("config", {}).get("products_via_service") is True
    assert data.get("config", {}).get("customers_via_service") is True


def test_domain_handlers_products_list(monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-erp-domain-bridge", "domain_handlers")
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.domains.db.product_queries._load_products_list_impl_pg",
        lambda page, per_page, keyword, unit: ([{"id": 1, "name": "A"}], 1, None),
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    out = mod.run_domain_handler("products", "list", page=1, per_page=20)
    assert out.get("success") is True
    assert out.get("source") == "mod:xcagi-erp-domain-bridge"
    assert out.get("execution_path") == "mod_domain_handler"


def test_domain_handlers_shipment_records(monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-erp-domain-bridge", "domain_handlers")

    class FakeShipment:
        def get_shipment_records(self, unit):
            return [{"id": 9, "unit_name": unit or "all"}]

    monkeypatch.setattr(
        "app.bootstrap.get_shipment_application_service_core",
        lambda: FakeShipment(),
    )
    out = mod.run_domain_handler("shipment", "records_list", unit="测试单位")
    assert out.get("success") is True
    assert out["data"][0]["id"] == 9
    assert out.get("source") == "mod:xcagi-erp-domain-bridge"


def test_try_invoke_products_list(monkeypatch):
    from app.mod_sdk import erp_domain_dispatch as ed

    monkeypatch.setattr(ed, "is_erp_domain_handlers_enabled", lambda: True)
    monkeypatch.setattr(ed, "_mod_domain_handler_domains", lambda: ["products", "shipment"])
    monkeypatch.setattr(
        ed,
        "_resolve_mod_path",
        lambda: ("xcagi-erp-domain-bridge", str(MOD_DIR)),
    )
    monkeypatch.setattr(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.domains.db.product_queries._load_products_list_impl_pg",
        lambda page, per_page, keyword, unit: ([], 0, None),
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    out = ed.try_invoke_erp_domain_handler("products", "list", page=1, per_page=10)
    assert out is not None
    assert out.get("source") == "mod:xcagi-erp-domain-bridge"


def test_try_invoke_propagates_schema_errors(monkeypatch):
    """DB schema 错误必须原样上抛，不得伪装成 handler missing。"""
    import sqlite3

    import pytest as _pytest
    from sqlalchemy.exc import OperationalError as SQLAOperationalError

    from app.mod_sdk import erp_domain_dispatch as ed

    monkeypatch.setattr(ed, "is_erp_domain_handlers_enabled", lambda: True)
    monkeypatch.setattr(ed, "_mod_domain_handler_domains", lambda: ["products"])
    monkeypatch.setattr(
        ed,
        "_resolve_mod_path",
        lambda: ("xcagi-erp-domain-bridge", str(MOD_DIR)),
    )
    monkeypatch.setattr(
        ed,
        "_load_domain_handlers_module",
        lambda _path, _mod_id: Mock(
            run_domain_handler=Mock(
                side_effect=SQLAOperationalError(
                    "no such column: products.base_uom_id",
                    None,
                    sqlite3.OperationalError("no such column: products.base_uom_id"),
                )
            )
        ),
    )

    with _pytest.raises(SQLAOperationalError):
        ed.try_invoke_erp_domain_handler("products", "list", page=1, per_page=10)


def test_try_invoke_still_swallows_generic_recoverable(monkeypatch):
    """非 schema 类可恢复错误仍按原契约吞掉返回 None（走宿主 fallback）。"""
    from app.mod_sdk import erp_domain_dispatch as ed

    monkeypatch.setattr(ed, "is_erp_domain_handlers_enabled", lambda: True)
    monkeypatch.setattr(ed, "_mod_domain_handler_domains", lambda: ["products"])
    monkeypatch.setattr(
        ed,
        "_resolve_mod_path",
        lambda: ("xcagi-erp-domain-bridge", str(MOD_DIR)),
    )
    monkeypatch.setattr(
        ed,
        "_load_domain_handlers_module",
        lambda _path, _mod_id: Mock(run_domain_handler=Mock(side_effect=ValueError("boom"))),
    )

    out = ed.try_invoke_erp_domain_handler("products", "list", page=1, per_page=10)
    assert out is None


def test_registry_phase_g_domains(monkeypatch):
    from app.mod_sdk import erp_domain_compat as ed

    monkeypatch.setattr(ed, "is_erp_domain_via_mod_enabled", lambda: True)
    monkeypatch.setattr(
        ed,
        "_mod_handler_domains",
        lambda: {"products", "shipment", "customers"},
    )
    data = ed.list_erp_domains_registry()
    assert data.get("execution_path") == "mod_domain_handler"
    for dom_id in ("products", "customers", "shipment"):
        row = next(d for d in data["domains"] if d["domain_id"] == dom_id)
        assert row.get("delegate") == "mod.domain_handlers"


def test_domain_handlers_customers_list(monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(str(MOD_DIR), "xcagi-erp-domain-bridge", "domain_handlers")
    monkeypatch.setattr(
        "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.domains.db.queries._load_customers_rows",
        lambda: [{"id": 1, "customer_name": "测试"}],
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    out = mod.run_domain_handler("customers", "list", page=1, per_page=10)
    assert out.get("success") is True
    assert out.get("total") == 1
    assert out.get("source") == "mod:xcagi-erp-domain-bridge"
