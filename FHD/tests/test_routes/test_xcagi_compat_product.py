"""Tests for app.fastapi_routes.xcagi_compat_product — product/price-list routes with mocked dependencies."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import xcagi_compat_product as xp


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(xp.router)
    return TestClient(app, raise_server_exceptions=False)


def _install_lost_parse_price():
    """Temporarily install _parse_price on app.application.excel_imports.

    The module uses __getattr__ to raise ImportError for _LOST_LEGACY_SYMBOLS,
    which prevents ``patch(..., create=True)`` from working.  We inject a stub
    directly into the module dict so that the lazy ``from … import _parse_price``
    inside route handlers succeeds.
    """
    import app.application.excel_imports as _ei

    _ei._parse_price = MagicMock(return_value=0.0)
    return _ei


def _remove_lost_parse_price(_ei):
    """Remove the stub after the test."""
    _ei.__dict__.pop("_parse_price", None)


# ---------------------------------------------------------------------------
# products_units  (module-level import → patch route module)
# ---------------------------------------------------------------------------


class TestProductsUnits:
    def test_success(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._products_units_for_select",
                return_value={"success": True, "data": []},
            ),
        ):
            r = client.get("/products/units")
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# shipment_records_units
# ---------------------------------------------------------------------------


class TestShipmentRecordsUnits:
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcagi_compat_product._products_units_for_select",
            return_value={"success": True, "data": []},
        ):
            r = client.get("/shipment/shipment-records/units")
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# purchase_units_list
# ---------------------------------------------------------------------------


class TestPurchaseUnitsList:
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.xcagi_compat_product._merged_purchase_unit_entries",
            return_value=[],
        ):
            r = client.get("/purchase_units")
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# products_list  (lazy: erp_domain_dispatch, erp_products_facade)
# ---------------------------------------------------------------------------


class TestProductsList:
    def test_erp_dispatch(self, client: TestClient):
        with patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value={"success": True, "data": []},
        ):
            r = client.get("/products/list")
            assert r.json()["success"] is True

    def test_erp_products_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_list",
                return_value={"success": True, "data": [], "total": 0},
            ),
        ):
            r = client.get("/products/list")
            assert r.json()["success"] is True

    def test_fallback_pg(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_list_impl_pg",
                return_value=([], 0, None),
            ),
        ):
            r = client.get("/products/list")
            assert r.json()["success"] is True
            assert r.json()["total"] == 0

    def test_fallback_pg_with_schema_hint(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_list_impl_pg",
                return_value=([], 0, "hint"),
            ),
        ):
            r = client.get("/products/list")
            assert r.json()["schema_hint"] == "hint"

    def test_pg_error(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_list_impl_pg",
                side_effect=RuntimeError("db error"),
            ),
        ):
            r = client.get("/products/list")
            assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# products_get_by_id  (lazy: erp_products_facade, bootstrap)
# ---------------------------------------------------------------------------


class TestProductsGetById:
    def test_erp_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_get",
                return_value={"success": True, "data": {"id": 1}},
            ),
        ):
            r = client.get("/products/1")
            assert r.json()["success"] is True

    def test_fallback_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_product.return_value = {"success": True, "data": {"id": 1}}
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.bootstrap.get_products_service",
                return_value=mock_svc,
            ),
        ):
            r = client.get("/products/1")
            assert r.json()["success"] is True

    def test_fallback_not_found(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_product.return_value = {"success": False, "message": "not found"}
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.bootstrap.get_products_service",
                return_value=mock_svc,
            ),
        ):
            r = client.get("/products/999")
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# products_resolve_name_hints  (module-level imports only)
# ---------------------------------------------------------------------------


class TestProductsResolveNameHints:
    def test_invalid_hints_type(self, client: TestClient):
        with patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"):
            r = client.post("/products/resolve-name-hints", json={"hints": "not a list"})
            assert r.json()["success"] is False

    def test_empty_hints(self, client: TestClient):
        with patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"):
            r = client.post("/products/resolve-name-hints", json={"hints": []})
            assert r.json()["success"] is False

    def test_business_mod_blocked(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value={"success": False, "message": "blocked"},
            ),
        ):
            r = client.post("/products/resolve-name-hints", json={"hints": ["test"]})
            assert r.json()["success"] is False

    def test_not_implemented(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
        ):
            r = client.post("/products/resolve-name-hints", json={"hints": ["test"]})
            assert r.status_code == 501


# ---------------------------------------------------------------------------
# products_update  (lazy: erp_products_facade, excel_imports)
# ---------------------------------------------------------------------------


class TestProductsUpdate:
    def test_erp_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_update",
                return_value={"success": True, "data": {"id": 1}},
            ),
        ):
            r = client.post("/products/update", json={"id": 1, "product_name": "updated"})
            assert r.json()["success"] is True

    def test_invalid_id(self, client: TestClient):
        _ei = _install_lost_parse_price()
        try:
            with (
                patch(
                    "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                    return_value=False,
                ),
                patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                    return_value=None,
                ),
            ):
                r = client.post("/products/update", json={"id": "bad"})
                assert r.status_code == 400
        finally:
            _remove_lost_parse_price(_ei)

    def test_success(self, client: TestClient):
        _ei = _install_lost_parse_price()
        try:
            with (
                patch(
                    "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                    return_value=False,
                ),
                patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                    return_value=None,
                ),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                    return_value=1,
                ),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_update_row"),
            ):
                r = client.post("/products/update", json={"id": 1})
                assert r.json()["success"] is True
        finally:
            _remove_lost_parse_price(_ei)

    def test_business_mod_blocked(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value={"success": False, "message": "blocked"},
            ),
        ):
            r = client.post("/products/update", json={"id": 1})
            assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# products_add  (lazy: erp_products_facade, excel_imports)
# ---------------------------------------------------------------------------


class TestProductsAdd:
    def test_erp_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_add",
                return_value={"success": True, "data": {"id": 1}},
            ),
        ):
            r = client.post("/products/add", json={"product_name": "new"})
            assert r.json()["success"] is True

    def test_success(self, client: TestClient):
        _ei = _install_lost_parse_price()
        try:
            with (
                patch(
                    "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                    return_value=False,
                ),
                patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                    return_value=None,
                ),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_insert_row",
                    return_value=42,
                ),
            ):
                r = client.post("/products/add", json={"product_name": "new"})
                assert r.json()["success"] is True
                assert r.json()["data"]["id"] == 42
        finally:
            _remove_lost_parse_price(_ei)


# ---------------------------------------------------------------------------
# products_delete  (lazy: erp_products_facade)
# ---------------------------------------------------------------------------


class TestProductsDelete:
    def test_erp_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_delete",
                return_value={"success": True},
            ),
        ):
            r = client.post("/products/delete", json={"id": 1})
            assert r.json()["success"] is True

    def test_invalid_id(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
        ):
            r = client.post("/products/delete", json={"id": "bad"})
            assert r.status_code == 400

    def test_success(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                return_value=1,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_delete_row"),
        ):
            r = client.post("/products/delete", json={"id": 1})
            assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# products_batch_delete  (lazy: erp_products_facade)
# ---------------------------------------------------------------------------


class TestProductsBatchDelete:
    def test_erp_service(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_batch_delete",
                return_value={"success": True, "deleted": 2},
            ),
        ):
            r = client.post("/products/batch-delete", json={"ids": [1, 2]})
            assert r.json()["success"] is True

    def test_invalid_ids(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
        ):
            r = client.post("/products/batch-delete", json={"ids": []})
            assert r.status_code == 400

    def test_not_list(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
        ):
            r = client.post("/products/batch-delete", json={"ids": "bad"})
            assert r.status_code == 400

    def test_success(self, client: TestClient):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch(
                "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows",
                return_value=(2, 0),
            ),
        ):
            r = client.post("/products/batch-delete", json={"ids": [1, 2]})
            assert r.json()["success"] is True
            assert r.json()["deleted"] == 2


# ---------------------------------------------------------------------------
# products_price_list_export / products_export_docx  (lazy: price_list_export, mod_business_scope)
# ---------------------------------------------------------------------------


class TestProductsPriceListExport:
    def test_business_data_not_exposed(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=False,
            ),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value="mod not ready",
            ),
        ):
            r = client.get("/products/price-list-export")
            assert r.status_code == 503

    def test_template_not_found(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(Path("/nonexistent/template.docx"), "template.docx"),
            ),
        ):
            r = client.get("/products/price-list-export")
            assert r.status_code == 404

    def test_export_docx_alias(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=False,
            ),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value="mod not ready",
            ),
        ):
            r = client.get("/products/export.docx")
            assert r.status_code == 503


# ---------------------------------------------------------------------------
# products_price_list_template_preview  (lazy: price_list_export, mod_business_scope)
# ---------------------------------------------------------------------------


class TestProductsPriceListTemplatePreview:
    def test_business_data_not_exposed(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=False,
            ),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value="mod not ready",
            ),
        ):
            r = client.get("/products/price-list-template-preview")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        with (
            patch("app.fastapi_routes.xcagi_compat_product.verify_db_read_token_header"),
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_template_preview_json",
                return_value={"success": True, "preview": {}},
            ),
        ):
            r = client.get("/products/price-list-template-preview")
            assert r.json()["success"] is True
