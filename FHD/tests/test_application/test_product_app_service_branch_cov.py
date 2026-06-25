"""Branch-coverage tests for app/application/product_app_service.py.

Targets the 12 missing branches reported in coverage.json:
- [118, 119]: create_product price < 0 (true branch)
- [123, 126]: create_product result.success false branch
- [139, 140]: update_product price < 0 (true branch)
- [144, 147]: update_product result.success false branch
- [161, 164]: delete_product result.success false branch
- [179, 180] / [179, 182]: import_products result.success true/false
- [200, 201] / [200, 203]: get_product_labels product not found / found
- [233, 234] / [233, 236]: print_product_labels label fail / success
- [310, 312]: get_product_application_service singleton cached branch
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application import product_app_service as pas_mod
from app.application.product_app_service import (
    ProductApplicationService,
    _normalize_optional_str,
)


# ---------------------------------------------------------------------------
# _normalize_optional_str
# ---------------------------------------------------------------------------


class TestNormalizeOptionalStr:
    def test_none_returns_none(self):
        assert _normalize_optional_str(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_optional_str("") is None

    def test_whitespace_returns_none(self):
        assert _normalize_optional_str("   ") is None

    def test_strips_whitespace(self):
        assert _normalize_optional_str("  hello  ") == "hello"

    def test_non_empty_returns_stripped(self):
        assert _normalize_optional_str("abc") == "abc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    products_service: MagicMock | None = None,
    printer_service: MagicMock | None = None,
) -> ProductApplicationService:
    """Build a ProductApplicationService with mocked dependencies."""
    ps = products_service or MagicMock()
    prs = printer_service or MagicMock()
    with (
        patch("app.services.get_products_service", return_value=ps),
        patch("app.services.get_printer_service", return_value=prs),
    ):
        return ProductApplicationService(
            products_service=ps, printer_service=prs
        )


# ---------------------------------------------------------------------------
# create_product — branches [118, 119] / [123, 126]
# ---------------------------------------------------------------------------


class TestCreateProductBranches:
    def test_create_product_negative_price_returns_error(self):
        """price < 0 returns error (branch 118->119)."""
        service = _make_service()
        result = service.create_product(
            {"unit_name": "u1", "product_name": "p1", "price": -5}
        )
        assert result["success"] is False
        assert "价格不能为负数" in result["message"]

    def test_create_product_zero_price_passes(self):
        """price == 0 passes the validation (boundary)."""
        ps = MagicMock()
        ps.create_product.return_value = {"success": True, "product_id": 1}
        service = _make_service(products_service=ps)
        result = service.create_product(
            {"unit_name": "u1", "product_name": "p1", "price": 0}
        )
        assert result["success"] is True

    def test_create_product_no_unit_returns_error(self):
        """Missing unit_name returns error."""
        service = _make_service()
        result = service.create_product({"product_name": "p1"})
        assert result["success"] is False
        assert "单位名称不能为空" in result["message"]

    def test_create_product_empty_unit_returns_error(self):
        """Empty unit_name returns error."""
        service = _make_service()
        result = service.create_product(
            {"unit_name": "  ", "product_name": "p1"}
        )
        assert result["success"] is False

    def test_create_product_no_name_returns_error(self):
        """Missing product_name returns error."""
        service = _make_service()
        result = service.create_product({"unit_name": "u1"})
        assert result["success"] is False
        assert "产品名称不能为空" in result["message"]

    def test_create_product_unit_alias_unit_key(self):
        """unit key works as alias for unit_name."""
        ps = MagicMock()
        ps.create_product.return_value = {"success": True, "product_id": 7}
        service = _make_service(products_service=ps)
        result = service.create_product({"unit": "u-alias", "name": "p1"})
        assert result["success"] is True

    def test_create_product_name_alias_name_key(self):
        """name key works as alias for product_name."""
        ps = MagicMock()
        ps.create_product.return_value = {"success": True, "product_id": 7}
        service = _make_service(products_service=ps)
        result = service.create_product({"unit_name": "u1", "name": "p1"})
        assert result["success"] is True

    def test_create_product_success_logs_action(self):
        """Successful create logs the action (branch 123->124)."""
        ps = MagicMock()
        ps.create_product.return_value = {"success": True, "product_id": 42}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            service.create_product({"unit_name": "u1", "product_name": "p1"})
        mock_log.assert_called_once()

    def test_create_product_failure_skips_logging(self):
        """Failed create skips logging (branch 123->126)."""
        ps = MagicMock()
        ps.create_product.return_value = {"success": False, "message": "fail"}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            result = service.create_product({"unit_name": "u1", "product_name": "p1"})
        mock_log.assert_not_called()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# update_product — branches [139, 140] / [144, 147]
# ---------------------------------------------------------------------------


class TestUpdateProductBranches:
    def test_update_product_negative_price_returns_error(self):
        """price < 0 returns error (branch 139->140)."""
        service = _make_service()
        result = service.update_product(1, {"price": -10})
        assert result["success"] is False
        assert "价格不能为负数" in result["message"]

    def test_update_product_success_logs_action(self):
        """Successful update logs the action (branch 144->145)."""
        ps = MagicMock()
        ps.update_product.return_value = {"success": True}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            service.update_product(1, {"price": 10})
        mock_log.assert_called_once()

    def test_update_product_failure_skips_logging(self):
        """Failed update skips logging (branch 144->147)."""
        ps = MagicMock()
        ps.update_product.return_value = {"success": False, "message": "not found"}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            result = service.update_product(1, {"price": 10})
        mock_log.assert_not_called()
        assert result["success"] is False

    def test_update_product_no_price_passes(self):
        """Update without price key passes validation."""
        ps = MagicMock()
        ps.update_product.return_value = {"success": True}
        service = _make_service(products_service=ps)
        result = service.update_product(1, {"description": "new"})
        assert result["success"] is True


# ---------------------------------------------------------------------------
# delete_product — branch [161, 164]
# ---------------------------------------------------------------------------


class TestDeleteProductBranches:
    def test_delete_product_success_logs_action(self):
        """Successful delete logs the action (branch 161->162)."""
        ps = MagicMock()
        ps.delete_product.return_value = {"success": True}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            service.delete_product(1)
        mock_log.assert_called_once()

    def test_delete_product_failure_skips_logging(self):
        """Failed delete skips logging (branch 161->164)."""
        ps = MagicMock()
        ps.delete_product.return_value = {"success": False, "message": "not found"}
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            result = service.delete_product(1)
        mock_log.assert_not_called()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# import_products_from_excel — branches [179, 180] / [179, 182]
# ---------------------------------------------------------------------------


class TestImportProductsBranches:
    def test_import_success_logs_action(self):
        """Successful import logs the action (branch 179->180)."""
        ps = MagicMock()
        ps.import_products_from_excel.return_value = {
            "success": True,
            "count": 5,
        }
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            result = service.import_products_from_excel("/path/file.xlsx", "u1")
        mock_log.assert_called_once()
        assert result["success"] is True

    def test_import_failure_skips_logging(self):
        """Failed import skips logging (branch 179->182)."""
        ps = MagicMock()
        ps.import_products_from_excel.return_value = {
            "success": False,
            "message": "bad file",
        }
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            result = service.import_products_from_excel("/path/file.xlsx", "u1")
        mock_log.assert_not_called()
        assert result["success"] is False

    def test_import_success_with_zero_count(self):
        """Successful import with count=0 still logs."""
        ps = MagicMock()
        ps.import_products_from_excel.return_value = {
            "success": True,
            "count": 0,
        }
        service = _make_service(products_service=ps)
        with patch.object(service, "_log_action") as mock_log:
            service.import_products_from_excel("/path/file.xlsx", "u1")
        mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# get_product_labels — branches [200, 201] / [200, 203]
# ---------------------------------------------------------------------------


class TestGetProductLabelsBranches:
    def test_get_product_labels_product_not_found_returns_error(self):
        """Product not found returns the error result (branch 200->201)."""
        ps = MagicMock()
        ps.get_product.return_value = {"success": False, "message": "not found"}
        service = _make_service(products_service=ps)
        result = service.get_product_labels(999)
        assert result["success"] is False

    def test_get_product_labels_product_found_returns_label_data(self):
        """Product found returns label data (branch 200->203)."""
        ps = MagicMock()
        ps.get_product.return_value = {
            "success": True,
            "data": {
                "name": "Widget",
                "model_number": "M-100",
                "specification": "spec",
                "unit": "个",
            },
        }
        service = _make_service(products_service=ps)
        result = service.get_product_labels(1, quantity=5, label_type="barcode")
        assert result["success"] is True
        assert result["data"]["product_id"] == 1
        assert result["data"]["product_name"] == "Widget"
        assert result["data"]["quantity"] == 5
        assert result["data"]["label_type"] == "barcode"

    def test_get_product_labels_default_quantity_and_type(self):
        """Default quantity=1 and label_type='default'."""
        ps = MagicMock()
        ps.get_product.return_value = {
            "success": True,
            "data": {"name": "X", "model_number": None, "specification": None, "unit": None},
        }
        service = _make_service(products_service=ps)
        result = service.get_product_labels(1)
        assert result["data"]["quantity"] == 1
        assert result["data"]["label_type"] == "default"

    def test_get_product_labels_product_with_none_fields(self):
        """Product with None fields returns None in label data."""
        ps = MagicMock()
        ps.get_product.return_value = {
            "success": True,
            "data": {"name": None, "model_number": None, "specification": None, "unit": None},
        }
        service = _make_service(products_service=ps)
        result = service.get_product_labels(1)
        assert result["data"]["product_name"] is None
        assert result["data"]["model_number"] is None


# ---------------------------------------------------------------------------
# print_product_labels — branches [233, 234] / [233, 236]
# ---------------------------------------------------------------------------


class TestPrintProductLabelsBranches:
    def test_print_labels_label_failure_returns_error(self):
        """Label retrieval failure returns error (branch 233->234)."""
        ps = MagicMock()
        ps.get_product.return_value = {"success": False, "message": "not found"}
        service = _make_service(products_service=ps)
        result = service.print_product_labels(999)
        assert result["success"] is False

    def test_print_labels_success_calls_printer(self):
        """Label success calls printer service (branch 233->236)."""
        ps = MagicMock()
        ps.get_product.return_value = {
            "success": True,
            "data": {"name": "X", "model_number": "M", "specification": "S", "unit": "u"},
        }
        prs = MagicMock()
        prs.print_labels.return_value = {"success": True, "printed": 1}
        service = _make_service(products_service=ps, printer_service=prs)
        result = service.print_product_labels(1, quantity=3)
        prs.print_labels.assert_called_once()
        assert result["success"] is True

    def test_print_labels_custom_label_type(self):
        """Custom label_type passed through."""
        ps = MagicMock()
        ps.get_product.return_value = {
            "success": True,
            "data": {"name": "X", "model_number": None, "specification": None, "unit": None},
        }
        prs = MagicMock()
        prs.print_labels.return_value = {"success": True}
        service = _make_service(products_service=ps, printer_service=prs)
        service.print_product_labels(1, quantity=2, label_type="qr")
        call_args = prs.print_labels.call_args
        label_data = call_args[0][0][0]
        assert label_data["label_type"] == "qr"


# ---------------------------------------------------------------------------
# get_products — keyword/model normalization branches
# ---------------------------------------------------------------------------


class TestGetProductsBranches:
    def test_get_products_with_unit_name_takes_precedence(self):
        """unit_name takes precedence over unit."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products(unit="u1", unit_name="u2")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["unit_name"] == "u2"

    def test_get_products_with_only_unit(self):
        """Only unit provided — used as unit_name."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products(unit="u1")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["unit_name"] == "u1"

    def test_get_products_model_uppercased(self):
        """model_number is uppercased."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products(model_number="abc-123")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["model_number"] == "ABC-123"

    def test_get_products_empty_model_becomes_none(self):
        """Empty model_number becomes None."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products(model_number="  ")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["model_number"] is None

    def test_get_products_empty_keyword_becomes_none(self):
        """Empty keyword becomes None."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products(keyword="")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["keyword"] is None

    def test_get_products_no_filters_all_none(self):
        """No filters — all resolved values are None."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.get_products()
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["unit_name"] is None
        assert call_kwargs["model_number"] is None
        assert call_kwargs["keyword"] is None


# ---------------------------------------------------------------------------
# search_products / get_product_statistics / get_product_units / get_product_names
# ---------------------------------------------------------------------------


class TestSearchProducts:
    def test_search_with_no_filters(self):
        """Search with no filters uses defaults."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.search_products("widget")
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["keyword"] == "widget"
        assert call_kwargs["page"] == 1
        assert call_kwargs["per_page"] == 20

    def test_search_with_custom_filters(self):
        """Search with custom page/per_page."""
        ps = MagicMock()
        ps.get_products.return_value = {"success": True, "items": []}
        service = _make_service(products_service=ps)
        service.search_products("widget", {"page": 3, "per_page": 50, "unit": "u1"})
        call_kwargs = ps.get_products.call_args.kwargs
        assert call_kwargs["page"] == 3
        assert call_kwargs["per_page"] == 50
        assert call_kwargs["unit"] == "u1"


class TestGetProductStatistics:
    def test_statistics_with_unit(self):
        """Statistics with unit filter."""
        ps = MagicMock()
        ps.get_products.return_value = {"total": 42, "items": []}
        service = _make_service(products_service=ps)
        result = service.get_product_statistics(unit="u1")
        assert result["success"] is True
        assert result["data"]["total_products"] == 42
        assert result["data"]["unit"] == "u1"

    def test_statistics_without_unit(self):
        """Statistics without unit shows '全部'."""
        ps = MagicMock()
        ps.get_products.return_value = {"total": 0, "items": []}
        service = _make_service(products_service=ps)
        result = service.get_product_statistics()
        assert result["data"]["unit"] == "全部"
        assert result["data"]["total_products"] == 0

    def test_statistics_missing_total_defaults_zero(self):
        """Missing total in response defaults to 0."""
        ps = MagicMock()
        ps.get_products.return_value = {"items": []}
        service = _make_service(products_service=ps)
        result = service.get_product_statistics()
        assert result["data"]["total_products"] == 0


class TestSimpleDelegates:
    def test_get_product_units_delegates(self):
        ps = MagicMock()
        ps.get_product_units.return_value = {"个", "箱"}
        service = _make_service(products_service=ps)
        result = service.get_product_units()
        ps.get_product_units.assert_called_once()
        assert result == {"个", "箱"}

    def test_get_product_names_delegates(self):
        ps = MagicMock()
        ps.get_product_names.return_value = {"success": True, "names": []}
        service = _make_service(products_service=ps)
        result = service.get_product_names(keyword="abc")
        ps.get_product_names.assert_called_once_with(keyword="abc")

    def test_get_product_delegates(self):
        ps = MagicMock()
        ps.get_product.return_value = {"success": True, "data": {}}
        service = _make_service(products_service=ps)
        result = service.get_product(1)
        ps.get_product.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# Singleton / init functions — branch [310, 312]
# ---------------------------------------------------------------------------


class TestSingletonBranches:
    def test_get_product_application_service_returns_cached(self):
        """When already initialized — returns cached instance (branch 310->312)."""
        cached = MagicMock()
        pas_mod._product_app_service = cached
        result = pas_mod.get_product_application_service()
        assert result is cached

    def test_get_product_application_service_creates_new(self):
        """When None — creates new instance (branch 310->311)."""
        pas_mod._product_app_service = None
        with (
            patch("app.services.get_products_service"),
            patch("app.services.get_printer_service"),
        ):
            result = pas_mod.get_product_application_service()
        assert result is not None
        assert isinstance(result, ProductApplicationService)
        pas_mod._product_app_service = None

    def test_get_product_app_service_alias(self):
        """get_product_app_service is an alias for get_product_application_service."""
        cached = MagicMock()
        pas_mod._product_app_service = cached
        result = pas_mod.get_product_app_service()
        assert result is cached

    def test_init_product_application_service_sets_singleton(self):
        """init_product_application_service sets the singleton."""
        pas_mod._product_app_service = None
        ps = MagicMock()
        prs = MagicMock()
        result = pas_mod.init_product_application_service(ps, prs)
        assert pas_mod._product_app_service is result
        pas_mod._product_app_service = None

    def test_init_product_app_service_alias(self):
        """init_product_app_service is an alias."""
        pas_mod._product_app_service = None
        ps = MagicMock()
        result = pas_mod.init_product_app_service(ps)
        assert pas_mod._product_app_service is result
        pas_mod._product_app_service = None

    def test_init_product_app_service_with_none_printer(self):
        """init with printer_service=None works."""
        pas_mod._product_app_service = None
        ps = MagicMock()
        result = pas_mod.init_product_app_service(ps, None)
        assert result is not None
        pas_mod._product_app_service = None
