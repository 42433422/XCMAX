"""扩展覆盖：tools_workflow_registered 缺失分支（update/delete/batch_delete 等）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_workflow_registered import (
    _registered_router_customers,
    _registered_router_inventory,
    _registered_router_materials,
    _registered_router_products,
    _registered_router_purchase,
    _registered_router_shipment_orders,
    _registered_router_shipment_records,
)

# ---------------------------------------------------------------------------
# customers — update / delete / batch_delete 分支
# ---------------------------------------------------------------------------


class TestCustomersRouterMissingBranches:
    def _mock_svc(self):
        return MagicMock()

    # update ----------------------------------------------------------------

    def test_update_success(self):
        svc = self._mock_svc()
        svc.update.return_value = {"success": True, "data": {"id": 5}}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "update", {"id": 5, "unit_name": "AcmeCo"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["data"] == {"id": 5}

    def test_update_failure(self):
        svc = self._mock_svc()
        svc.update.return_value = {"success": False, "message": "not found"}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "update", {"id": 5, "unit_name": "AcmeCo"}, {}, "admin", ""
            )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_update_missing_id(self):
        result = _registered_router_customers("update", {"unit_name": "X"}, {}, "admin", "")
        assert result["success"] is False
        assert "id" in result["message"]

    def test_update_zero_id(self):
        result = _registered_router_customers("update", {"id": 0}, {}, "admin", "")
        assert result["success"] is False

    def test_update_uses_customer_id_alias(self):
        svc = self._mock_svc()
        svc.update.return_value = {"success": True, "data": {}}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "update", {"customer_id": 7, "unit_name": "X"}, {}, "admin", ""
            )
        assert result["success"] is True
        svc.update.assert_called_once_with(7, {"customer_name": "X"})

    # delete ----------------------------------------------------------------

    def test_delete_success(self):
        svc = self._mock_svc()
        svc.delete.return_value = {"success": True, "deleted": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers("delete", {"id": 3}, {}, "admin", "")
        assert result["success"] is True

    def test_delete_with_force(self):
        svc = self._mock_svc()
        svc.delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            _registered_router_customers("delete", {"id": 3, "force": True}, {}, "admin", "")
        svc.delete.assert_called_once_with(3, force=True)

    def test_delete_missing_id(self):
        result = _registered_router_customers("delete", {}, {}, "admin", "")
        assert result["success"] is False
        assert "id" in result["message"]

    def test_delete_uses_customer_id_alias(self):
        svc = self._mock_svc()
        svc.delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            _registered_router_customers("delete", {"customer_id": 9}, {}, "admin", "")
        svc.delete.assert_called_once_with(9, force=False)

    # batch_delete ----------------------------------------------------------

    def test_batch_delete_success(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True, "deleted": 2}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "batch_delete", {"ids": [1, 2]}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_batch_delete_uses_customer_ids_alias(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            _registered_router_customers(
                "batch_delete", {"customer_ids": [4, 5]}, {}, "admin", ""
            )
        svc.batch_delete.assert_called_once_with([4, 5], force=False)

    def test_batch_delete_empty_list(self):
        result = _registered_router_customers("batch_delete", {"ids": []}, {}, "admin", "")
        assert result["success"] is False
        assert "非空" in result["message"]

    def test_batch_delete_not_list(self):
        result = _registered_router_customers("batch_delete", {"ids": "1,2"}, {}, "admin", "")
        assert result["success"] is False

    def test_batch_delete_all_invalid(self):
        result = _registered_router_customers(
            "batch_delete", {"ids": ["abc", "xyz"]}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "有效数字" in result["message"]

    def test_batch_delete_mixed_valid_invalid(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "batch_delete", {"ids": [1, "bad", 3]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "skipped" in result
        assert "bad" in result["skipped"]

    def test_batch_delete_with_force(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            _registered_router_customers(
                "batch_delete", {"ids": [1]}, {"force": True}, "admin", ""
            )
        svc.batch_delete.assert_called_once()

    def test_unknown_action(self):
        result = _registered_router_customers("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "customers" in result["message"]

    # fastapi_customer_route ------------------------------------------------

    def test_fastapi_customer_route_delegate(self):
        # Patch the function directly on the module: `from pkg import routes` uses
        # getattr(pkg, 'routes') which bypasses sys.modules when the module is
        # already cached as a parent-package attribute.
        with patch(
            "app.fastapi_routes.domains.customer.routes._execute_customers_route_action",
            return_value={"success": True},
        ):
            result = _registered_router_customers(
                "query",
                {},
                {"service_source": "fastapi_customer_route"},
                "admin",
                "",
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# products — batch_create / batch_delete / update / delete / create-failure
# ---------------------------------------------------------------------------


class TestProductsRouterMissingBranches:
    def _svc(self):
        return MagicMock()

    # create via fastapi product route -------------------------------------

    def test_create_via_fastapi_product_route(self):
        svc = self._svc()
        svc.create_product.return_value = {"success": True}
        # Patch _svc directly on the module: `from pkg import routes` uses
        # getattr(pkg, 'routes') which bypasses sys.modules when already cached.
        with patch("app.fastapi_routes.domains.product.routes._svc", return_value=svc):
            result = _registered_router_products(
                "create",
                {"name": "P1", "unit_price": 5.0},
                {"service_source": "fastapi_product_route"},
                "admin",
                "",
            )
        assert result["success"] is True

    # create failure -------------------------------------------------------

    def test_create_product_failure(self):
        svc = self._svc()
        svc.create_product.return_value = {"success": False, "message": "dup"}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "create",
                {"name_or_model": "P1", "unit_name": "U1"},
                {},
                "admin",
                "",
            )
        assert result["success"] is False
        assert "dup" in result["message"]

    # update ---------------------------------------------------------------

    def test_update_product(self):
        svc = self._svc()
        svc.update_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "update",
                {"id": 10, "unit_price": 9.9},
                {},
                "admin",
                "",
            )
        svc.update_product.assert_called_once_with(10, {"unit_price": 9.9})
        assert result["success"] is True

    # delete ---------------------------------------------------------------

    def test_delete_product(self):
        svc = self._svc()
        svc.delete_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products("delete", {"id": 7}, {}, "admin", "")
        svc.delete_product.assert_called_once_with(7)
        assert result["success"] is True

    # batch_create ---------------------------------------------------------

    def test_batch_create_success(self):
        svc = self._svc()
        svc.batch_add_products.return_value = {"success": True, "created": 2}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "batch_create",
                {"products": [{"name": "A"}, {"name": "B"}]},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_batch_create_empty(self):
        result = _registered_router_products("batch_create", {"products": []}, {}, "admin", "")
        assert result["success"] is False
        assert "非空" in result["message"]

    def test_batch_create_not_list(self):
        result = _registered_router_products("batch_create", {"products": "abc"}, {}, "admin", "")
        assert result["success"] is False

    # batch_delete ---------------------------------------------------------

    def test_batch_delete_products_success(self):
        svc = self._svc()
        svc.batch_delete_products.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "batch_delete", {"ids": [1, 2]}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_batch_delete_products_fallback_to_batch_delete(self):
        svc = self._svc()
        del svc.batch_delete_products  # ensure not callable via getattr
        svc.batch_delete = MagicMock(return_value={"success": True})
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "batch_delete", {"ids": [3]}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_batch_delete_products_empty(self):
        result = _registered_router_products("batch_delete", {"ids": []}, {}, "admin", "")
        assert result["success"] is False

    def test_batch_delete_products_all_invalid(self):
        result = _registered_router_products(
            "batch_delete", {"ids": ["bad", "nope"]}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "有效数字" in result["message"]

    def test_batch_delete_products_mixed(self):
        svc = self._svc()
        svc.batch_delete_products.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "batch_delete", {"ids": [1, "bad"]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "skipped" in result

    def test_batch_delete_product_ids_alias(self):
        svc = self._svc()
        svc.batch_delete_products.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            _registered_router_products(
                "batch_delete", {"product_ids": [5]}, {}, "admin", ""
            )
        svc.batch_delete_products.assert_called_once_with([5])

    # exists — product_name match path ------------------------------------

    def test_exists_model_in_list_but_name_matches(self):
        """行内 model_number 不匹配但 product_name 匹配。"""
        svc = self._svc()
        svc.get_products.return_value = {
            "success": True,
            "data": [{"name": "Widget Pro", "model_number": "ZZZZ"}],
        }
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "exists",
                {"product_name": "Widget Pro", "model_number": ""},
                {},
                "admin",
                "",
            )
        assert result["exists"] is True

    def test_exists_loop_continues_without_match(self):
        """两行都不匹配 → exists=False，循环继续执行完整迭代。"""
        svc = self._svc()
        svc.get_products.return_value = {
            "success": True,
            "data": [
                {"name": "A", "model_number": "X1"},
                {"name": "B", "model_number": "X2"},
            ],
        }
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "exists",
                {"product_name": "C", "model_number": "X3"},
                {},
                "admin",
                "",
            )
        assert result["exists"] is False
        assert result["matched_count"] == 2

    def test_unknown_action(self):
        result = _registered_router_products("unknown", {}, {}, "admin", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# shipment_records — create 分支
# ---------------------------------------------------------------------------


class TestShipmentRecordsRouterCreate:
    def test_create_success(self):
        svc = MagicMock()
        svc.create_shipment.return_value = {"success": True, "id": 1}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_records(
                "create",
                {
                    "unit_name": "TestCo",
                    "products": [{"id": 1, "qty": 2}],
                    "contact_person": "Alice",
                    "contact_phone": "1234",
                },
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_create_missing_unit_name(self):
        result = _registered_router_shipment_records("create", {}, {}, "admin", "")
        assert result["success"] is False
        assert "unit_name" in result["message"]

    def test_create_non_list_products_defaults_to_empty(self):
        svc = MagicMock()
        svc.create_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            _registered_router_shipment_records(
                "create", {"unit_name": "Co", "products": "not-a-list"}, {}, "admin", ""
            )
        svc.create_shipment.assert_called_once()
        call_kwargs = svc.create_shipment.call_args
        assert call_kwargs.kwargs["items_data"] == []

    def test_unknown_action(self):
        result = _registered_router_shipment_records("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# shipment_orders — 多分支
# ---------------------------------------------------------------------------


class TestShipmentOrdersRouterBranches:
    def _svc(self):
        return MagicMock()

    def test_generate_success(self):
        svc = self._svc()
        svc.generate_shipment_document.return_value = {"success": True, "file_path": "/tmp/s.pdf"}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate",
                {"unit_name": "Co", "products": [{"id": 1}]},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_generate_missing_unit_name(self):
        result = _registered_router_shipment_orders(
            "generate", {"products": [{"id": 1}]}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "unit_name" in result["message"]

    def test_generate_empty_products(self):
        result = _registered_router_shipment_orders(
            "generate", {"unit_name": "Co", "products": []}, {}, "admin", ""
        )
        assert result["success"] is False
        assert "products" in result["message"]

    def test_generate_batch_success(self):
        svc = self._svc()
        svc.generate_shipment_document.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {
                    "shipments": [
                        {"unit_name": "Co", "products": [{"id": 1}]},
                    ]
                },
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["data"]["processed"] == 1

    def test_generate_batch_empty(self):
        result = _registered_router_shipment_orders(
            "generate_batch", {"shipments": []}, {}, "admin", ""
        )
        assert result["success"] is False

    def test_generate_batch_non_dict_item(self):
        result = _registered_router_shipment_orders(
            "generate_batch", {"shipments": ["not-a-dict"]}, {}, "admin", ""
        )
        assert result["data"]["errors"][0]["error"] == "条目必须是对象"

    def test_generate_batch_missing_unit(self):
        result = _registered_router_shipment_orders(
            "generate_batch",
            {"shipments": [{"products": [1]}]},
            {},
            "admin",
            "",
        )
        assert result["data"]["errors"][0]["error"] == "单位名称不能为空"

    def test_generate_batch_empty_products(self):
        result = _registered_router_shipment_orders(
            "generate_batch",
            {"shipments": [{"unit_name": "Co", "products": []}]},
            {},
            "admin",
            "",
        )
        assert result["data"]["errors"][0]["error"] == "产品列表不能为空"

    def test_generate_batch_service_failure(self):
        svc = self._svc()
        svc.generate_shipment_document.return_value = {"success": False, "message": "err"}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {"shipments": [{"unit_name": "Co", "products": [1]}]},
                {},
                "admin",
                "",
            )
        assert result["data"]["errors"][0]["error"] == "err"

    def test_generate_batch_service_exception(self):
        svc = self._svc()
        svc.generate_shipment_document.side_effect = RuntimeError("boom")
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {"shipments": [{"unit_name": "Co", "products": [1]}]},
                {},
                "admin",
                "",
            )
        assert "boom" in result["data"]["errors"][0]["error"]

    def test_print_with_order_id(self):
        svc = self._svc()
        svc.mark_as_printed.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "print",
                {"file_path": "/tmp/s.pdf", "order_id": 42, "printer_name": "HP"},
                {},
                "admin",
                "",
            )
        assert result["file_path"] == "/tmp/s.pdf"
        assert "updated" in result

    def test_print_without_order_id(self):
        with patch("app.bootstrap.get_shipment_app_service", return_value=MagicMock()):
            result = _registered_router_shipment_orders(
                "print", {"file_path": "/tmp/s.pdf"}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["updated"] is False

    def test_print_missing_file_path(self):
        result = _registered_router_shipment_orders("print", {}, {}, "admin", "")
        assert result["success"] is False

    def test_clear_shipment(self):
        svc = self._svc()
        svc.clear_shipment_by_unit.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "clear_shipment", {"purchase_unit": "Co"}, {}, "admin", ""
            )
        assert result["purchase_unit"] == "Co"

    def test_clear_shipment_missing_unit(self):
        result = _registered_router_shipment_orders("clear_shipment", {}, {}, "admin", "")
        assert result["success"] is False

    def test_set_sequence(self):
        svc = self._svc()
        svc.set_order_sequence.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders(
                "set_sequence", {"sequence": 5}, {}, "admin", ""
            )
        assert result["sequence"] == 5

    def test_reset_sequence(self):
        svc = self._svc()
        svc.reset_order_sequence.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders("reset_sequence", {}, {}, "admin", "")
        assert result["success"] is True

    def test_clear_all(self):
        svc = self._svc()
        svc.clear_all_orders.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders("clear_all", {}, {}, "admin", "")
        assert result["success"] is True

    def test_delete_shipment(self):
        svc = self._svc()
        svc.delete_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
            result = _registered_router_shipment_orders("delete", {"id": 3}, {}, "admin", "")
        assert result["deleted_id"] == 3

    def test_unknown_action(self):
        result = _registered_router_shipment_orders("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------


class TestInventoryRouterBranches:
    def _svc(self):
        return MagicMock()

    def test_create_storage_location(self):
        svc = self._svc()
        svc.create_storage_location.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "create_storage_location", {"name": "A-01"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_storage_location(self):
        svc = self._svc()
        svc.update_storage_location.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "update_storage_location", {"location_id": 1, "name": "B"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_create_warehouse(self):
        svc = self._svc()
        svc.create_warehouse.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "create_warehouse", {"name": "WH-1"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_warehouse(self):
        svc = self._svc()
        svc.update_warehouse.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "update_warehouse", {"warehouse_id": 2, "name": "WH-2"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_delete_warehouse(self):
        svc = self._svc()
        svc.delete_warehouse.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "delete_warehouse", {"warehouse_id": 2}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_stock_in(self):
        svc = self._svc()
        svc.inventory_in.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "stock_in", {"product_id": 1, "quantity": 10}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_stock_out(self):
        svc = self._svc()
        svc.inventory_out.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "stock_out", {"product_id": 1, "quantity": 5}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_transfer(self):
        svc = self._svc()
        svc.inventory_transfer.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=svc
        ):
            result = _registered_router_inventory(
                "transfer",
                {"product_id": 1, "from_warehouse_id": 1, "to_warehouse_id": 2, "quantity": 3},
                {},
                "admin",
                "",
            )
        assert result["success"] is True

    def test_unknown_action(self):
        with patch(
            "app.application.inventory_app_service.InventoryAppService", return_value=self._svc()
        ):
            result = _registered_router_inventory("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# purchase
# ---------------------------------------------------------------------------


class TestPurchaseRouterBranches:
    def _svc(self):
        return MagicMock()

    def test_create_supplier(self):
        svc = self._svc()
        svc.create_supplier.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "create_supplier", {"name": "VendorA"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_supplier(self):
        svc = self._svc()
        svc.update_supplier.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "update_supplier", {"supplier_id": 1, "name": "V"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_delete_supplier(self):
        svc = self._svc()
        svc.delete_supplier.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "delete_supplier", {"supplier_id": 2}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_create_order(self):
        svc = self._svc()
        svc.create_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "create_order", {"supplier_id": 1}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_order(self):
        svc = self._svc()
        svc.update_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "update_order", {"order_id": 3, "status": "confirmed"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_approve_order(self):
        svc = self._svc()
        svc.approve_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "approve_order", {"order_id": 3, "approver": "boss"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_cancel_order(self):
        svc = self._svc()
        svc.cancel_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase("cancel_order", {"order_id": 3}, {}, "admin", "")
        assert result["success"] is True

    def test_create_inbound(self):
        svc = self._svc()
        svc.create_purchase_inbound.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=svc
        ):
            result = _registered_router_purchase(
                "create_inbound", {"order_id": 3}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_unknown_action(self):
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=self._svc()
        ):
            result = _registered_router_purchase("fly", {}, {}, "admin", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# materials — update returns non-dict / delete returns non-dict
# ---------------------------------------------------------------------------


class TestMaterialsRouterBranches:
    def test_update_non_dict_result(self):
        svc = MagicMock()
        svc.update_material.return_value = True  # non-dict
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials("update", {"id": 1, "name": "X"}, {}, "admin", "")
        assert result["success"] is True
        assert result["message"] == "更新成功"

    def test_delete_non_dict_result(self):
        svc = MagicMock()
        svc.delete_material.return_value = True  # non-dict
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials("delete", {"id": 2}, {}, "admin", "")
        assert result["success"] is True
        assert result["message"] == "删除成功"

    def test_delete_dict_sets_default_message(self):
        svc = MagicMock()
        svc.delete_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials("delete", {"id": 3}, {}, "admin", "")
        assert result["message"] == "删除成功"

    def test_batch_delete_service_exception(self):
        svc = MagicMock()
        svc.batch_delete_materials.side_effect = RuntimeError("db error")
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials(
                "batch_delete", {"ids": [1]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert "db error" in result["warning"]

    def test_batch_delete_non_dict_result(self):
        svc = MagicMock()
        svc.batch_delete_materials.return_value = None
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials(
                "batch_delete", {"ids": [1, 2]}, {}, "admin", ""
            )
        assert result["success"] is True
        assert result["deleted_count"] == 2
