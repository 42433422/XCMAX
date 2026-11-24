"""Product preflight, real business handlers and export projection tests."""

from __future__ import annotations

from contextlib import contextmanager as _shared_scope_contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.legacy.routes.product import compat_routes as xp


@_shared_scope_contextmanager
def _shared_scope_case_0():
    with (
        patch(
            "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
            return_value=False,
        ),
        patch("app.legacy.routes.product.compat_routes._products_write_raise"),
        patch(
            "app.legacy.routes.product.compat_routes._business_mod_json_block",
            return_value=None,
        ),
    ):
        yield None


# ---------------------------------------------------------------------------
# _agent_node_output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _products_compat_agent_user_id
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _products_compat_status_code
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _normalize_products_create_payload
# ---------------------------------------------------------------------------


class TestNormalizeProductsCreatePayload:
    def test_name_from_name(self):
        data = xp._normalize_products_create_payload({"name": "Widget"})
        assert data["name"] == "Widget"
        assert data["product_name"] == "Widget"
        assert data["name_or_model"] == "Widget"

    def test_name_from_product_name(self):
        data = xp._normalize_products_create_payload({"product_name": "Gadget"})
        assert data["name"] == "Gadget"

    def test_name_from_name_or_model(self):
        data = xp._normalize_products_create_payload({"name_or_model": "Model-X"})
        assert data["name"] == "Model-X"

    def test_name_from_model_number(self):
        data = xp._normalize_products_create_payload({"model_number": "M123"})
        assert data["name"] == "M123"

    def test_name_from_product_code(self):
        data = xp._normalize_products_create_payload({"product_code": "PC-001"})
        assert data["name"] == "PC-001"

    def test_name_empty(self):
        data = xp._normalize_products_create_payload({"price": 10})
        assert "name" not in data or data.get("name") == ""

    def test_unit_name_from_unit(self):
        data = xp._normalize_products_create_payload({"unit": "箱"})
        assert data["unit_name"] == "箱"

    def test_unit_name_default(self):
        data = xp._normalize_products_create_payload({})
        assert data["unit_name"] == "个"

    def test_none_payload(self):
        data = xp._normalize_products_create_payload(None)
        assert data["unit_name"] == "个"


# ---------------------------------------------------------------------------
# _products_compat_via_service_enabled
# ---------------------------------------------------------------------------


class TestProductsCompatViaServiceEnabled:
    def test_enabled_true(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True
        ):
            assert xp._products_compat_via_service_enabled() is True

    def test_enabled_false(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ):
            assert xp._products_compat_via_service_enabled() is False

    def test_import_error_returns_false(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            side_effect=ImportError("no"),
        ):
            assert xp._products_compat_via_service_enabled() is False

    def test_programming_error_does_not_select_legacy_fallback(self):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                side_effect=RuntimeError("invalid ERP service state"),
            ),
            pytest.raises(RuntimeError, match="invalid ERP service state"),
        ):
            xp._products_compat_via_service_enabled()


# ---------------------------------------------------------------------------
# _products_compat_preflight
# ---------------------------------------------------------------------------


class TestProductsCompatPreflight:
    def _req(self):
        return MagicMock()

    def test_via_service_enabled_returns_none(self):
        with patch(
            "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
            return_value=True,
        ):
            assert xp._products_compat_preflight(self._req(), "create", {}) is None

    def test_business_mod_blocked_returns_gate(self):
        with (
            patch(
                "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
                return_value=False,
            ),
            patch("app.legacy.routes.product.compat_routes._products_write_raise"),
            patch(
                "app.legacy.routes.product.compat_routes._business_mod_json_block",
                return_value={"success": False, "message": "blocked"},
            ),
        ):
            result = xp._products_compat_preflight(self._req(), "create", {})
            assert result == {"success": False, "message": "blocked"}

    def test_update_valid_id(self):
        payload = {"id": 42}
        with (
            patch(
                "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
                return_value=False,
            ),
            patch("app.legacy.routes.product.compat_routes._products_write_raise"),
            patch(
                "app.legacy.routes.product.compat_routes._business_mod_json_block",
                return_value=None,
            ),
            patch("app.legacy.routes.product.compat_routes._product_parse_id", return_value=42),
        ):
            assert xp._products_compat_preflight(self._req(), "update", payload) is None
            assert payload["id"] == 42

    def test_update_invalid_id_raises(self):
        with (
            patch(
                "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
                return_value=False,
            ),
            patch("app.legacy.routes.product.compat_routes._products_write_raise"),
            patch(
                "app.legacy.routes.product.compat_routes._business_mod_json_block",
                return_value=None,
            ),
            patch("app.legacy.routes.product.compat_routes._product_parse_id", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "update", {"id": "bad"})
            assert exc_info.value.status_code == 400

    def test_delete_valid_id(self):
        payload = {"id": 7}
        with (
            patch(
                "app.legacy.routes.product.compat_routes._products_compat_via_service_enabled",
                return_value=False,
            ),
            patch("app.legacy.routes.product.compat_routes._products_write_raise"),
            patch(
                "app.legacy.routes.product.compat_routes._business_mod_json_block",
                return_value=None,
            ),
            patch("app.legacy.routes.product.compat_routes._product_parse_id", return_value=7),
        ):
            assert xp._products_compat_preflight(self._req(), "delete", payload) is None

    def test_batch_delete_valid_ids(self):
        payload = {"ids": [1, 2, 3]}
        with _shared_scope_case_0():
            assert xp._products_compat_preflight(self._req(), "batch_delete", payload) is None

    def test_batch_delete_product_ids_fallback(self):
        payload = {"product_ids": [4, 5]}
        with _shared_scope_case_0():
            assert xp._products_compat_preflight(self._req(), "batch_delete", payload) is None
            assert payload["ids"] == [4, 5]

    def test_batch_delete_not_list_raises(self):
        with _shared_scope_case_0():
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "batch_delete", {"ids": "bad"})
            assert exc_info.value.status_code == 400

    def test_batch_delete_empty_raises(self):
        with _shared_scope_case_0():
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "batch_delete", {"ids": []})
            assert exc_info.value.status_code == 400

    def test_create_action_no_id_check(self):
        with _shared_scope_case_0():
            assert xp._products_compat_preflight(self._req(), "create", {}) is None


# ---------------------------------------------------------------------------
# _execute_products_compat_action
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _run_products_compat_agent
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _products_price_list_word_response
# ---------------------------------------------------------------------------


class TestProductsPriceListWordResponse:
    def test_business_data_not_exposed_with_reason(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason", return_value="not ready"
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None)
            assert exc_info.value.status_code == 503
            assert "not ready" in exc_info.value.detail

    def test_business_data_not_exposed_without_reason(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch("app.shell.mod_business_scope.business_data_hidden_reason", return_value=""),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response(None, None, None)
            assert exc_info.value.status_code == 503
            assert "扩展 Mod" in exc_info.value.detail

    def test_template_not_found(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(Path("/nonexistent/tpl.docx"), "tpl.docx"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None, "customer-missing")
            assert exc_info.value.status_code == 404

    def test_build_docx_recoverable_error(self, tmp_path):
        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.legacy.routes.product.compat_routes._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                side_effect=OSError("docx fail"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None)
            assert exc_info.value.status_code == 500

    def test_success_with_export_date(self, tmp_path):
        from fastapi.responses import Response

        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.legacy.routes.product.compat_routes._load_products_all_for_export",
                return_value=[{"name": "P1"}],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"docx-bytes",
            ),
        ):
            resp = xp._products_price_list_word_response("acme", "kw", "2026-01-01")
            assert isinstance(resp, Response)
            assert resp.body == b"docx-bytes"
            assert "attachment" in resp.headers["content-disposition"]

    def test_success_without_export_date_uses_today(self, tmp_path):
        from fastapi.responses import Response

        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.legacy.routes.product.compat_routes._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"docx-bytes",
            ),
        ):
            resp = xp._products_price_list_word_response("", None, "")
            assert isinstance(resp, Response)
            # Empty customer → "全部单位" label
            assert "UTF-8" in resp.headers["content-disposition"]


# ---------------------------------------------------------------------------
# _http_exception_result
# ---------------------------------------------------------------------------
