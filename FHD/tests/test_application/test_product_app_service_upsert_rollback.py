"""Tests for app.application.product_app_service — coverage ramp C3.2-b.

Covers:
* ``get_product_units`` / ``get_product_names`` / ``get_products`` delegation.
* ``get_product`` delegation.
* ``create_product`` missing required field / service failure.
* ``update_product`` / ``delete_product`` delegation.
* Singleton initialization paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.product_app_service import ProductApplicationService


def _svc(prod=None, printer=None) -> ProductApplicationService:
    return ProductApplicationService(
        products_service=prod or MagicMock(), printer_service=printer or MagicMock()
    )


class TestGetProducts:
    def test_resolves_unit_aliases(self) -> None:
        prod = MagicMock()
        prod.get_products.return_value = {"success": True, "data": []}
        svc = _svc(prod)
        svc.get_products(unit_name="ACME", model_number=" m-1 ", keyword=" x ", page=2, per_page=5)
        kw = prod.get_products.call_args.kwargs
        assert kw["unit_name"] == "ACME"
        assert kw["model_number"] == "M-1"
        assert kw["keyword"] == "x"
        assert kw["page"] == 2
        assert kw["per_page"] == 5

    def test_unit_precedence(self) -> None:
        prod = MagicMock()
        prod.get_products.return_value = {"success": True}
        svc = _svc(prod)
        svc.get_products(unit="U1", unit_name="U2")
        kw = prod.get_products.call_args.kwargs
        assert kw["unit_name"] == "U2"

    def test_empty_strings_become_none(self) -> None:
        prod = MagicMock()
        prod.get_products.return_value = {"success": True}
        svc = _svc(prod)
        svc.get_products(unit="", model_number="", keyword="")
        kw = prod.get_products.call_args.kwargs
        assert kw["unit_name"] is None
        assert kw["model_number"] is None
        assert kw["keyword"] is None

    def test_get_product_units_delegates(self) -> None:
        prod = MagicMock()
        prod.get_product_units.return_value = {"success": True, "data": []}
        svc = _svc(prod)
        out = svc.get_product_units()
        assert out["success"] is True
        prod.get_product_units.assert_called_once()

    def test_get_product_names_delegates(self) -> None:
        prod = MagicMock()
        prod.get_product_names.return_value = {"success": True}
        svc = _svc(prod)
        out = svc.get_product_names(keyword="abc")
        prod.get_product_names.assert_called_once_with(keyword="abc")
        assert out["success"] is True

    def test_get_product_delegates(self) -> None:
        prod = MagicMock()
        prod.get_product.return_value = {"success": True, "data": {"id": 1}}
        svc = _svc(prod)
        out = svc.get_product(1)
        prod.get_product.assert_called_once_with(1)
        assert out["data"]["id"] == 1


class TestCreateProduct:
    def test_missing_unit_name(self) -> None:
        svc = _svc()
        out = svc.create_product({})
        assert out["success"] is False
        assert "单位" in out.get("message", "") or "unit" in out.get("message", "").lower()

    def test_missing_product_name(self) -> None:
        svc = _svc()
        out = svc.create_product({"unit_name": "U"})
        assert out["success"] is False

    def test_service_success(self) -> None:
        prod = MagicMock()
        prod.create_product.return_value = {"success": True, "data": {"id": 7}}
        svc = _svc(prod)
        out = svc.create_product({"unit_name": "U", "product_name": "P", "price": 1.0})
        assert out["success"] is True
        prod.create_product.assert_called_once()


class TestUpdateAndDelete:
    def test_update_delegates(self) -> None:
        prod = MagicMock()
        prod.update_product.return_value = {"success": True}
        svc = _svc(prod)
        out = svc.update_product(1, {"price": 2})
        prod.update_product.assert_called_once_with(1, {"price": 2})
        assert out["success"] is True

    def test_delete_delegates(self) -> None:
        prod = MagicMock()
        prod.delete_product.return_value = {"success": True, "message": "deleted"}
        svc = _svc(prod)
        out = svc.delete_product(1)
        prod.delete_product.assert_called_once_with(1)
        assert "deleted" in out["message"]


class TestSingleton:
    def test_uses_gateway_defaults(self) -> None:
        with (
            patch("app.application.product_app_service.get_products_service") as gp,
            patch("app.application.product_app_service.get_printer_service") as gpr,
        ):
            gp.return_value = MagicMock(name="prod")
            gpr.return_value = MagicMock(name="printer")
            svc = ProductApplicationService()
        assert svc._products_service is gp.return_value
        assert svc._printer_service is gpr.return_value
