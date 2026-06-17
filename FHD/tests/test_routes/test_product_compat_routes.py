"""Tests for app.fastapi_routes.domains.product.compat_routes — product CRUD & export routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.product.compat_routes import router


@pytest.fixture
def app_compat():
    """Create a FastAPI app with the product compat router mounted."""
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client_compat(app_compat):
    with TestClient(app_compat, raise_server_exceptions=False) as c:
        yield c


# ========================= GET /products/units ===========================


class TestProductsUnits:
    def test_products_units_returns_data(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_units_for_select",
            return_value={"units": ["kg", "个"]},
        ):
            r = client_compat.get("/products/units")
            assert r.status_code == 200


# ========================= GET /shipment/shipment-records/units ==========


class TestShipmentRecordsUnits:
    def test_shipment_records_units_returns_data(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes._products_units_for_select",
            return_value={"units": ["kg"]},
        ):
            r = client_compat.get("/shipment/shipment-records/units")
            assert r.status_code == 200


# ========================= GET /purchase_units ===========================


class TestPurchaseUnits:
    def test_purchase_units_returns_data(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes._merged_purchase_unit_entries",
            return_value=[{"name": "kg"}],
        ):
            r = client_compat.get("/purchase_units")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True


# ========================= GET /products/list ============================


class TestProductsList:
    def test_products_list_erp_handler_returns_data(self, client_compat):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value={"success": True, "data": []},
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ):
            r = client_compat.get("/products/list")
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_products_list_erp_handler_skipped_fallback_pg(self, client_compat):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            side_effect=ImportError("no erp"),
        ), patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
            return_value=([{"id": 1, "name": "Widget"}], 1, None),
        ):
            r = client_compat.get("/products/list")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["total"] == 1

    def test_products_list_pg_failure(self, client_compat):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            side_effect=ImportError("no erp"),
        ), patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
            side_effect=RuntimeError("db down"),
        ):
            r = client_compat.get("/products/list")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is False

    def test_products_list_via_service_enabled(self, client_compat):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            side_effect=ImportError("no erp"),
        ), patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_list",
            return_value={"success": True, "data": [], "total": 0},
        ):
            r = client_compat.get("/products/list")
            assert r.status_code == 200

    def test_products_list_with_schema_hint(self, client_compat):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            side_effect=ImportError("no erp"),
        ), patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
            return_value=([], 0, "missing columns"),
        ):
            r = client_compat.get("/products/list")
            body = r.json()
            assert body["schema_hint"] == "missing columns"


# ========================= GET /products/{product_id} ====================


class TestProductsGetById:
    def test_get_by_id_via_service(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_get",
            return_value={"success": True, "data": {"id": 1}},
        ):
            r = client_compat.get("/products/1")
            assert r.status_code == 200

    def test_get_by_id_local_success(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.bootstrap.get_products_service"
        ) as mock_svc:
            mock_svc.return_value.get_product.return_value = {
                "success": True, "data": {"id": 1, "name": "Widget"}
            }
            r = client_compat.get("/products/1")
            assert r.status_code == 200

    def test_get_by_id_local_not_found(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.bootstrap.get_products_service"
        ) as mock_svc:
            mock_svc.return_value.get_product.return_value = {
                "success": False, "message": "not found"
            }
            r = client_compat.get("/products/999")
            assert r.status_code == 404


# ========================= POST /products/resolve-name-hints =============


class TestProductsResolveNameHints:
    def test_resolve_name_hints_invalid_hints_type(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ):
            r = client_compat.post("/products/resolve-name-hints", json={"hints": "not_a_list"})
            body = r.json()
            assert body["success"] is False
            assert "数组" in body["message"]

    def test_resolve_name_hints_empty_hints(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ):
            r = client_compat.post("/products/resolve-name-hints", json={"hints": []})
            body = r.json()
            assert body["success"] is False
            assert "不能为空" in body["message"]

    def test_resolve_name_hints_business_mod_blocked(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value={"success": False, "message": "blocked"},
        ):
            r = client_compat.post("/products/resolve-name-hints", json={"hints": ["ABC"]})
            body = r.json()
            assert body["success"] is False

    def test_resolve_name_hints_raises_501(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ):
            r = client_compat.post("/products/resolve-name-hints", json={"hints": ["ABC"]})
            assert r.status_code == 501


# ========================= POST /products/update =========================


class TestProductsUpdate:
    def test_update_via_service(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_update",
            return_value={"success": True, "data": {"id": 1}},
        ):
            r = client_compat.post("/products/update", json={"id": 1, "name": "Updated"})
            assert r.status_code == 200

    def test_update_invalid_id(self, client_compat):
        mock_excel = MagicMock()
        mock_excel._parse_price = MagicMock(return_value=0)
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch.dict("sys.modules", {"app.application.excel_imports": mock_excel}):
            r = client_compat.post("/products/update", json={"id": None})
            assert r.status_code == 400

    def test_update_success(self, client_compat):
        mock_excel = MagicMock()
        mock_excel._parse_price = MagicMock(return_value=0)
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_update_row"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._product_parse_id",
            return_value=1,
        ), patch.dict("sys.modules", {"app.application.excel_imports": mock_excel}):
            r = client_compat.post("/products/update", json={"id": 1, "name": "Updated"})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_update_business_mod_blocked(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value={"success": False, "message": "blocked"},
        ):
            r = client_compat.post("/products/update", json={"id": 1})
            assert r.json()["success"] is False

    def test_update_pg_failure(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._product_parse_id",
            return_value=1,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_update_row",
            side_effect=RuntimeError("db error"),
        ):
            r = client_compat.post("/products/update", json={"id": 1})
            assert r.status_code == 500


# ========================= POST /products/add ============================


class TestProductsAdd:
    def test_add_via_service(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_add",
            return_value={"success": True, "data": {"id": 10}},
        ):
            r = client_compat.post("/products/add", json={"name": "New"})
            assert r.status_code == 200

    def test_add_success(self, client_compat):
        mock_excel = MagicMock()
        mock_excel._parse_price = MagicMock(return_value=0)
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
            return_value=10,
        ), patch.dict("sys.modules", {"app.application.excel_imports": mock_excel}):
            r = client_compat.post("/products/add", json={"name": "New Product"})
            assert r.status_code == 200
            assert r.json()["data"]["id"] == 10

    def test_add_pg_failure(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
            side_effect=RuntimeError("db error"),
        ):
            r = client_compat.post("/products/add", json={"name": "New"})
            assert r.status_code == 500


# ========================= POST /products/delete =========================


class TestProductsDelete:
    def test_delete_via_service(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_delete",
            return_value={"success": True},
        ):
            r = client_compat.post("/products/delete", json={"id": 1})
            assert r.status_code == 200

    def test_delete_invalid_id(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ):
            r = client_compat.post("/products/delete", json={"id": None})
            assert r.status_code == 400

    def test_delete_success(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._product_parse_id",
            return_value=1,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row"
        ):
            r = client_compat.post("/products/delete", json={"id": 1})
            assert r.status_code == 200
            assert r.json()["success"] is True

    def test_delete_pg_failure(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._product_parse_id",
            return_value=1,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row",
            side_effect=RuntimeError("db error"),
        ):
            r = client_compat.post("/products/delete", json={"id": 1})
            assert r.status_code == 500


# ========================= POST /products/batch-delete ===================


class TestProductsBatchDelete:
    def test_batch_delete_via_service(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ), patch(
            "app.mod_sdk.erp_products_facade.products_batch_delete",
            return_value={"success": True},
        ):
            r = client_compat.post("/products/batch-delete", json={"ids": [1, 2]})
            assert r.status_code == 200

    def test_batch_delete_invalid_ids(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ):
            r = client_compat.post("/products/batch-delete", json={"ids": []})
            assert r.status_code == 400

    def test_batch_delete_success(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
            return_value=(2, 0),
        ):
            r = client_compat.post("/products/batch-delete", json={"ids": [1, 2]})
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["deleted"] == 2

    def test_batch_delete_pg_failure(self, client_compat):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
            side_effect=RuntimeError("db error"),
        ):
            r = client_compat.post("/products/batch-delete", json={"ids": [1]})
            assert r.status_code == 500


# ========================= GET /products/price-list-export ===============


class TestProductsPriceListExport:
    def test_price_list_export_business_not_exposed(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ), patch(
            "app.shell.mod_business_scope.business_data_hidden_reason",
            return_value="mod not ready",
        ):
            r = client_compat.get("/products/price-list-export")
            assert r.status_code == 503

    def test_price_list_export_template_not_found(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=True,
        ), patch(
            "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
            return_value=(MagicMock(is_file=lambda: False), "missing.docx"),
        ):
            r = client_compat.get("/products/price-list-export")
            assert r.status_code == 404


# ========================= GET /products/price-list-template-preview =====


class TestProductsPriceListTemplatePreview:
    def test_template_preview_business_not_exposed(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ), patch(
            "app.shell.mod_business_scope.business_data_hidden_reason",
            return_value="mod not ready",
        ):
            r = client_compat.get("/products/price-list-template-preview")
            assert r.status_code == 503

    def test_template_preview_success(self, client_compat):
        with patch(
            "app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"
        ), patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=True,
        ), patch(
            "app.infrastructure.documents.price_list_export.build_price_list_template_preview_json",
            return_value={"template": "preview"},
        ):
            r = client_compat.get("/products/price-list-template-preview")
            assert r.status_code == 200
