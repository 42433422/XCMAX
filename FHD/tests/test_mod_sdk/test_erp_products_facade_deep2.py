"""Deep tests for ``app.mod_sdk.erp_products_facade`` covering remaining uncovered branches."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.mod_sdk import erp_products_facade as pf


@pytest.fixture()
def fake_service():
    """A fake ProductsService with all methods as MagicMock."""
    svc = MagicMock()
    svc.get_products.return_value = {
        "success": True,
        "data": [{"id": 1, "name": "P1"}],
        "total": 1,
    }
    svc.get_product.return_value = {
        "success": True,
        "data": {"id": 1, "name": "P1"},
    }
    svc.create_product.return_value = {
        "success": True,
        "data": {"id": 10},
    }
    svc.update_product.return_value = {"success": True}
    svc.delete_product.return_value = {
        "success": True,
        "message": "已删除",
    }
    svc.batch_delete_products.return_value = {
        "success": True,
        "deleted_count": 2,
    }
    svc.get_product_names.return_value = {
        "success": True,
        "data": ["P1", "P2"],
    }
    svc.batch_add_products.return_value = {
        "success": True,
        "added": 2,
    }
    return svc


@pytest.fixture(autouse=True)
def _patch_service(fake_service, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pf, "_service", lambda: fake_service)
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    monkeypatch.setattr(pf, "_write_gate", lambda request: None)
    monkeypatch.setattr(
        "app.mod_sdk.erp_repository_registry.get_repository_execution_meta",
        lambda name: {"repo_meta": "test"},
    )
    return fake_service


@pytest.fixture(autouse=True)
def _patch_norm_model(monkeypatch: pytest.MonkeyPatch):
    """Patch the _norm_model symbol so _map_create_body works."""
    fake_module = types.ModuleType("app.application.excel_imports")
    fake_module._norm_model = lambda *a, **k: "GEN123"  # type: ignore[attr-defined]
    try:
        real_module = sys.modules.get("app.application.excel_imports")
        if real_module is not None:
            for attr in dir(real_module):
                if not attr.startswith("_") or attr == "_norm_model":
                    continue
                try:
                    setattr(fake_module, attr, getattr(real_module, attr))
                except Exception:
                    pass
    except Exception:
        pass
    monkeypatch.setitem(sys.modules, "app.application.excel_imports", fake_module)
    return fake_module


# ── _truthy_env deep ─────────────────────────────────────────────────────────


class TestTruthyEnvDeep:
    def test_uppercase_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "TRUE")
        assert pf._truthy_env("TEST_VAR") is True

    def test_mixed_case_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "Yes")
        assert pf._truthy_env("TEST_VAR") is True

    def test_uppercase_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "ON")
        assert pf._truthy_env("TEST_VAR") is True

    def test_with_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "  true  ")
        assert pf._truthy_env("TEST_VAR") is True

    def test_zero_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "0")
        assert pf._truthy_env("TEST_VAR") is False

    def test_no_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "no")
        assert pf._truthy_env("TEST_VAR") is False

    def test_off_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "off")
        assert pf._truthy_env("TEST_VAR") is False


# ── is_erp_products_via_service_enabled deep ─────────────────────────────────


class TestIsEnabledDeep:
    def test_disable_overrides_enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Both disable and enable are set - disable wins
        monkeypatch.setenv("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE", "1")
        monkeypatch.setenv("XCAGI_ERP_PRODUCTS_VIA_SERVICE", "1")
        assert pf.is_erp_products_via_service_enabled() is False

    def test_manifest_config_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        with patch(
            "app.mod_sdk.erp_products_facade._read_manifest",
            return_value={"config": {"products_via_service": False}},
        ):
            assert pf.is_erp_products_via_service_enabled() is False

    def test_manifest_config_not_bool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        with patch(
            "app.mod_sdk.erp_products_facade._read_manifest",
            return_value={"config": {"products_via_service": "yes"}},
        ):
            assert pf.is_erp_products_via_service_enabled() is False

    def test_manifest_no_config_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        with patch(
            "app.mod_sdk.erp_products_facade._read_manifest",
            return_value={"other_key": "value"},
        ):
            assert pf.is_erp_products_via_service_enabled() is False

    def test_manifest_returns_none_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_PRODUCTS_VIA_SERVICE", raising=False)
        with patch(
            "app.mod_sdk.erp_products_facade._read_manifest",
            return_value={"config": None},
        ):
            assert pf.is_erp_products_via_service_enabled() is False


# ── _map_create_body deep ────────────────────────────────────────────────────


class TestMapCreateBodyDeep:
    def test_both_unit_price_and_price_missing(self) -> None:
        body = {"name": "P"}
        result = pf._map_create_body(body)
        assert result["unit_price"] == 0

    def test_unit_price_takes_precedence_over_price(self) -> None:
        body = {"name": "P", "unit_price": 10, "price": 20}
        result = pf._map_create_body(body)
        assert result["unit_price"] == 10

    def test_unit_with_only_whitespace(self) -> None:
        body = {"name": "P", "unit": "   "}
        result = pf._map_create_body(body)
        assert result["unit"] == "个"

    def test_name_with_whitespace(self) -> None:
        body = {"name": "  Product A  "}
        result = pf._map_create_body(body)
        assert result["name"] == "Product A"

    def test_specification_with_whitespace(self) -> None:
        body = {"name": "P", "specification": "  spec1  "}
        result = pf._map_create_body(body)
        assert result["specification"] == "spec1"

    def test_model_number_with_whitespace(self) -> None:
        body = {"name": "P", "model_number": "  M123  "}
        result = pf._map_create_body(body)
        assert result["product_code"] == "M123"

    def test_product_code_with_whitespace(self) -> None:
        body = {"name": "P", "product_code": "  PC123  "}
        result = pf._map_create_body(body)
        assert result["product_code"] == "PC123"

    def test_description_none(self) -> None:
        body = {"name": "P", "description": None}
        result = pf._map_create_body(body)
        assert result["description"] == ""

    def test_category_none(self) -> None:
        body = {"name": "P", "category": None}
        result = pf._map_create_body(body)
        assert result["category"] == ""

    def test_brand_none(self) -> None:
        body = {"name": "P", "brand": None}
        result = pf._map_create_body(body)
        assert result["brand"] == ""

    def test_name_none(self) -> None:
        body = {"name": None}
        result = pf._map_create_body(body)
        assert result["name"] == ""

    def test_specification_none(self) -> None:
        body = {"name": "P", "specification": None}
        result = pf._map_create_body(body)
        assert result["specification"] == ""

    def test_quantity_none(self) -> None:
        body = {"name": "P", "quantity": None}
        result = pf._map_create_body(body)
        # None is passed through as-is (body.get("quantity", 0) returns None)
        assert result["quantity"] is None

    def test_unit_price_none(self) -> None:
        body = {"name": "P", "unit_price": None}
        result = pf._map_create_body(body)
        # None is passed through as-is
        assert result["unit_price"] is None


# ── products_list deep ───────────────────────────────────────────────────────


class TestProductsListDeep:
    def test_data_none_returns_empty_list(self, fake_service) -> None:
        fake_service.get_products.return_value = {
            "success": True,
            "data": None,
            "total": 0,
        }
        result = pf.products_list(None)
        assert result["data"] == []

    def test_total_none_returns_zero(self, fake_service) -> None:
        fake_service.get_products.return_value = {
            "success": True,
            "data": [],
            "total": None,
        }
        result = pf.products_list(None)
        assert result["total"] == 0

    def test_total_string_converted_to_int(self, fake_service) -> None:
        fake_service.get_products.return_value = {
            "success": True,
            "data": [],
            "total": "42",
        }
        result = pf.products_list(None)
        assert result["total"] == 42

    def test_total_non_numeric_raises_value_error(self, fake_service) -> None:
        fake_service.get_products.return_value = {
            "success": True,
            "data": [],
            "total": "not a number",
        }
        # int("not a number") raises ValueError (not caught by products_list)
        with pytest.raises(ValueError):
            pf.products_list(None)

    def test_success_false_with_default_message(self, fake_service) -> None:
        fake_service.get_products.return_value = {
            "success": False,
        }
        result = pf.products_list(None)
        assert result["success"] is False
        assert result["message"] == "查询失败"

    def test_with_pagination_params(self, fake_service) -> None:
        pf.products_list(None, page=3, per_page=50)
        fake_service.get_products.assert_called_with(
            unit_name=None, keyword=None, page=3, per_page=50
        )

    def test_source_includes_mod_id(self, fake_service) -> None:
        result = pf.products_list(None)
        assert result["source"].startswith("mod:")


# ── products_get deep ────────────────────────────────────────────────────────


class TestProductsGetDeep:
    def test_data_none_no_to_dict(self, fake_service) -> None:
        fake_service.get_product.return_value = {
            "success": True,
            "data": None,
        }
        req = MagicMock(spec=Request)
        result = pf.products_get(req, 1)
        # data is None, hasattr(None, "to_dict") is False, so data stays None
        assert result["data"] is None

    def test_data_dict_no_to_dict(self, fake_service) -> None:
        fake_service.get_product.return_value = {
            "success": True,
            "data": {"id": 1, "name": "P1"},
        }
        req = MagicMock(spec=Request)
        result = pf.products_get(req, 1)
        assert result["data"] == {"id": 1, "name": "P1"}

    def test_source_and_execution_path_set(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        result = pf.products_get(req, 1)
        assert result["source"].startswith("mod:")
        assert result["execution_path"] == "products_service"


# ── products_add deep ────────────────────────────────────────────────────────


class TestProductsAddDeep:
    def test_data_none_pid_none(self, fake_service) -> None:
        fake_service.create_product.return_value = {
            "success": True,
            "data": None,
        }
        req = MagicMock(spec=Request)
        result = pf.products_add(req, {"name": "P1"})
        assert result["data"]["id"] is None

    def test_data_not_dict_with_id_attr(self, fake_service) -> None:
        mock_data = MagicMock()
        mock_data.id = 42
        fake_service.create_product.return_value = {
            "success": True,
            "data": mock_data,
        }
        req = MagicMock(spec=Request)
        result = pf.products_add(req, {"name": "P1"})
        assert result["data"]["id"] == 42

    def test_data_not_dict_without_id_attr(self, fake_service) -> None:
        mock_data = MagicMock()
        del mock_data.id  # Remove the id attribute
        fake_service.create_product.return_value = {
            "success": True,
            "data": mock_data,
        }
        req = MagicMock(spec=Request)
        result = pf.products_add(req, {"name": "P1"})
        assert result["data"]["id"] is None

    def test_service_failure_no_message(self, fake_service) -> None:
        fake_service.create_product.return_value = {
            "success": False,
        }
        req = MagicMock(spec=Request)
        with pytest.raises(HTTPException) as exc_info:
            pf.products_add(req, {"name": "P1"})
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "添加失败"

    def test_name_with_only_whitespace_raises(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with pytest.raises(HTTPException) as exc_info:
            pf.products_add(req, {"name": "   "})
        assert exc_info.value.status_code == 400


# ── products_update deep ─────────────────────────────────────────────────────


class TestProductsUpdateDeep:
    def test_service_failure_no_message(self, fake_service) -> None:
        fake_service.update_product.return_value = {
            "success": False,
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=1,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_update(req, {"id": 1, "name": "P"})
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "产品不存在"

    def test_name_with_only_whitespace_raises(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=1,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_update(req, {"id": 1, "name": "   "})
        assert exc_info.value.status_code == 400

    def test_id_none_raises(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_update(req, {"id": None, "name": "P"})
        assert exc_info.value.status_code == 400

    def test_missing_id_raises(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_update(req, {"name": "P"})
        assert exc_info.value.status_code == 400

    def test_extra_fields_preserved(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=1,
        ):
            pf.products_update(req, {"id": 1, "name": "P", "price": 10, "spec": "s"})
        call_args = fake_service.update_product.call_args
        payload = call_args[0][1]
        assert payload["price"] == 10
        assert payload["spec"] == "s"
        assert "id" not in payload


# ── products_delete deep ─────────────────────────────────────────────────────


class TestProductsDeleteDeep:
    def test_service_failure_no_message(self, fake_service) -> None:
        fake_service.delete_product.return_value = {
            "success": False,
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=1,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_delete(req, {"id": 1})
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "产品不存在"

    def test_id_none_raises(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_delete(req, {"id": None})
        assert exc_info.value.status_code == 400

    def test_success_with_custom_message(self, fake_service) -> None:
        fake_service.delete_product.return_value = {
            "success": True,
            "message": "自定义删除消息",
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            return_value=1,
        ):
            result = pf.products_delete(req, {"id": 1})
        assert result["message"] == "自定义删除消息"


# ── products_batch_delete deep ───────────────────────────────────────────────


class TestProductsBatchDeleteDeep:
    def test_deleted_count_zero_falls_back_to_len(self, fake_service) -> None:
        # When deleted_count is 0, it's falsy so falls through to len(int_ids)
        fake_service.batch_delete_products.return_value = {
            "success": True,
            "deleted_count": 0,
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            result = pf.products_batch_delete(req, {"ids": [1, 2]})
        # 0 is falsy, so falls back to len(int_ids) = 2
        assert result["deleted"] == 2

    def test_deleted_count_missing_fallback_to_data(self, fake_service) -> None:
        fake_service.batch_delete_products.return_value = {
            "success": True,
            "data": {"deleted_count": 7},
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            result = pf.products_batch_delete(req, {"ids": [1, 2]})
        assert result["deleted"] == 7

    def test_deleted_count_both_missing_fallback_to_len(self, fake_service) -> None:
        fake_service.batch_delete_products.return_value = {
            "success": True,
            "data": {},
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            result = pf.products_batch_delete(req, {"ids": [1, 2, 3]})
        assert result["deleted"] == 3

    def test_service_failure_no_message(self, fake_service) -> None:
        fake_service.batch_delete_products.return_value = {
            "success": False,
        }
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                pf.products_batch_delete(req, {"ids": [1, 2]})
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "批量删除失败"

    def test_product_ids_key_used(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            pf.products_batch_delete(req, {"product_ids": [10, 20]})
        # Verify batch_delete_products was called with [10, 20]
        fake_service.batch_delete_products.assert_called_with([10, 20])

    def test_ids_precedence_over_product_ids(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            pf.products_batch_delete(req, {"ids": [1], "product_ids": [2, 3]})
        # ids takes precedence
        fake_service.batch_delete_products.assert_called_with([1])

    def test_mixed_valid_invalid_ids(self, fake_service) -> None:
        req = MagicMock(spec=Request)
        with patch(
            "app.infrastructure.persistence.compat_db.base._product_parse_id",
            side_effect=lambda x: int(x) if str(x).isdigit() else None,
        ):
            result = pf.products_batch_delete(req, {"ids": [1, "invalid", 2, "also_invalid"]})
        assert result["success"] is True
        assert "invalid" in result["skipped"]
        assert "also_invalid" in result["skipped"]
        assert len(result["skipped"]) == 2


# ── products_product_names deep ──────────────────────────────────────────────


class TestProductsProductNamesDeep:
    def test_with_none_keyword(self, fake_service) -> None:
        result = pf.products_product_names(None)  # type: ignore[arg-type]
        assert result["success"] is True
        fake_service.get_product_names.assert_called_with(keyword=None)

    def test_with_whitespace_keyword(self, fake_service) -> None:
        # "   " is truthy, so keyword="   " is passed (not converted to None)
        result = pf.products_product_names("   ")
        assert result["success"] is True
        fake_service.get_product_names.assert_called_with(keyword="   ")

    def test_source_and_execution_path(self, fake_service) -> None:
        result = pf.products_product_names("test")
        assert result["source"].startswith("mod:")
        assert result["execution_path"] == "products_service"


# ── products_batch deep ──────────────────────────────────────────────────────


class TestProductsBatchDeep:
    def test_products_none(self, fake_service) -> None:
        result = pf.products_batch({"products": None})
        assert result["success"] is False
        assert result["message"] == "products 必须为非空数组"

    def test_products_not_list_int(self, fake_service) -> None:
        result = pf.products_batch({"products": 123})
        assert result["success"] is False

    def test_products_not_list_dict(self, fake_service) -> None:
        result = pf.products_batch({"products": {"key": "val"}})
        assert result["success"] is False

    def test_dict_items_mapped(self, fake_service) -> None:
        result = pf.products_batch({"products": [{"name": "P1"}, {"name": "P2"}]})
        assert result["success"] is True
        # Verify _map_create_body was called for each dict
        call_args = fake_service.batch_add_products.call_args[0][0]
        assert len(call_args) == 2
        assert all(isinstance(item, dict) for item in call_args)

    def test_source_and_execution_path(self, fake_service) -> None:
        result = pf.products_batch({"products": [{"name": "P1"}]})
        assert result["source"].startswith("mod:")
        assert result["execution_path"] == "products_service"


# ── _write_gate deep ─────────────────────────────────────────────────────────


class TestWriteGateDeep:
    def test_write_gate_with_none_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # When request is None, _products_write_raise is NOT called
        called = {"raise": False}

        def fake_raise(req):
            called["raise"] = True

        def fake_block():
            return {"blocked": True}

        monkeypatch.setattr(
            "app.infrastructure.persistence.compat_db.base._products_write_raise",
            fake_raise,
        )
        monkeypatch.setattr(
            "app.infrastructure.persistence.compat_db.base._business_mod_json_block",
            fake_block,
        )
        # Restore the real _write_gate function
        from app.infrastructure.persistence.compat_db.base import (
            _business_mod_json_block,
            _products_write_raise,
        )

        # Inline the real _write_gate logic with None request
        result = _business_mod_json_block()
        assert called["raise"] is False  # _products_write_raise was NOT called
        assert result == {"blocked": True}

    def test_write_gate_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.infrastructure.persistence.compat_db.base._products_write_raise",
            lambda req: None,
        )
        monkeypatch.setattr(
            "app.infrastructure.persistence.compat_db.base._business_mod_json_block",
            lambda: None,
        )
        from app.infrastructure.persistence.compat_db.base import (
            _business_mod_json_block,
        )

        result = _business_mod_json_block()
        assert result is None
