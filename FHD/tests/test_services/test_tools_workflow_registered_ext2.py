"""扩展覆盖：tools_workflow_registered 缺失分支（update/delete/batch_delete 等）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.shared_services.tools_workflow_registered import (
    _registered_router_customers,
    _registered_router_inventory,
    _registered_router_materials,
    _registered_router_products,
    _registered_router_purchase,
    _registered_router_shipment_orders,
    _registered_router_shipment_records,
)
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_customer_cascade_authority import deletion as deletion
from tests.test_application.test_customer_cascade_authority import snapshot


class TestCustomersRouterMissingBranches:
    def _mock_svc(self):
        return MagicMock()

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

    def test_delete_success(self):
        svc = self._mock_svc()
        svc.delete.return_value = {"success": True, "deleted": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers("delete", {"id": 3}, {}, "admin", "")
        assert result["success"] is True

    def test_delete_with_force(self, deletion):
        _, actor, svc = deletion
        with patch("app.application.get_customer_app_service", return_value=svc), tenant_scope(7):
            result = _registered_router_customers(
                "delete", {"id": 1, "force": True}, actor.context, "admin", ""
            )
        assert result["success"] is True
        remaining = snapshot(actor)
        assert remaining[0] == [(2,), (3,), (101,), (102,), (103,)]
        assert remaining[1] == [(2,), (101,), (102,)]
        assert remaining[2] == [(2,), (101,), (102,)]
        assert len(remaining[3]) == 1

    def test_delete_missing_id(self):
        result = _registered_router_customers("delete", {}, {}, "admin", "")
        assert result["success"] is False
        assert "id" in result["message"]

    def test_delete_uses_customer_id_alias(self, deletion):
        _, actor, svc = deletion
        before = snapshot(actor)
        with patch("app.application.get_customer_app_service", return_value=svc), tenant_scope(7):
            result = _registered_router_customers(
                "delete", {"customer_id": 3}, actor.context, "admin", ""
            )
        assert result["success"] is True
        remaining = snapshot(actor)
        assert remaining[0] == [(1,), (2,), (101,), (102,), (103,)]
        assert remaining[1:] == before[1:]

    def test_batch_delete_success(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True, "deleted": 2}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers("batch_delete", {"ids": [1, 2]}, {}, "admin", "")
        assert result["success"] is True

    def test_batch_delete_uses_customer_ids_alias(self, deletion):
        _, actor, svc = deletion
        with patch("app.application.get_customer_app_service", return_value=svc), tenant_scope(7):
            result = _registered_router_customers(
                "batch_delete", {"customer_ids": [1, 2], "force": True}, actor.context, "admin", ""
            )
        assert result["success"] is True
        assert result["deleted_count"] == 2
        remaining = snapshot(actor)
        assert remaining[0] == [(3,), (101,), (102,), (103,)]
        assert remaining[1] == [(101,), (102,)]
        assert remaining[2] == [(101,), (102,)]
        assert len(remaining[3]) == 1

    def test_batch_delete_empty_list(self):
        result = _registered_router_customers("batch_delete", {"ids": []}, {}, "admin", "")
        assert result["success"] is False
        assert "非空" in result["message"]

    def test_batch_delete_not_list(self):
        result = _registered_router_customers("batch_delete", {"ids": "1,2"}, {}, "admin", "")
        assert result["success"] is False

    def test_batch_delete_all_invalid(self, deletion):
        _, actor, svc = deletion
        before = snapshot(actor)
        with patch("app.application.get_customer_app_service", return_value=svc), tenant_scope(7):
            result = _registered_router_customers(
                "batch_delete", {"ids": ["abc", "xyz"]}, actor.context, "admin", ""
            )
        assert result["success"] is False
        assert result["deleted_count"] == 0
        assert "非空正整数列表" in result["message"]
        assert snapshot(actor) == before

    @pytest.mark.parametrize("ids", [[3, "bad", 1], [3, 101], [3, 999]])
    def test_batch_delete_mixed_valid_invalid(self, deletion, ids):
        _, actor, svc = deletion
        before = snapshot(actor)
        with patch("app.application.get_customer_app_service", return_value=svc), tenant_scope(7):
            result = _registered_router_customers(
                "batch_delete", {"ids": ids, "force": True}, actor.context, "admin", ""
            )
        assert result["success"] is False
        assert result["deleted_count"] == 0
        assert "skipped" not in result
        assert snapshot(actor) == before

    def test_batch_delete_with_force(self):
        svc = self._mock_svc()
        svc.batch_delete.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=svc):
            _registered_router_customers("batch_delete", {"ids": [1]}, {"force": True}, "admin", "")
        svc.batch_delete.assert_called_once()

    def test_clear_collects_and_deletes_all_customers(self):
        svc = self._mock_svc()
        svc.get_all.return_value = {
            "success": True,
            "data": [{"id": 1}, {"id": 2}],
            "total": 2,
        }
        svc.batch_delete.return_value = {"success": True, "deleted_count": 2}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers("clear", {}, {}, "admin", "")
        svc.batch_delete.assert_called_once()
        assert svc.batch_delete.call_args.args[0] == [1, 2]
        assert result["success"] is True
        assert result["deleted_count"] == 2

    def test_clear_with_empty_library(self):
        svc = self._mock_svc()
        svc.get_all.return_value = {"success": True, "data": [], "total": 0}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers("clear", {}, {}, "admin", "")
        svc.batch_delete.assert_not_called()
        assert result["deleted_count"] == 0

    def test_unknown_action(self):
        result = _registered_router_customers("fly", {}, {}, "admin", "")
        assert result["success"] is False
        assert "customers" in result["message"]

    @pytest.mark.parametrize("source", [None, "fastapi_customer_route", "mcp", "employee"])
    def test_every_customer_entry_uses_the_same_service(self, source):
        svc = self._mock_svc()
        svc.get_all.return_value = {"success": True, "data": [{"id": 7}], "total": 1}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "query",
                {"keyword": "Acme"},
                {"service_source": source} if source else {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["data"] == [{"id": 7}]
        svc.get_all.assert_called_once_with(keyword="Acme", page=1, per_page=20)

    @pytest.mark.parametrize("source", [None, "fastapi_customer_route", "mcp", "employee"])
    def test_customer_update_preserves_explicit_clear_and_omitted_fields(self, source):
        svc = self._mock_svc()
        svc.update.return_value = {"success": True, "data": {"id": 7}}
        with patch("app.application.get_customer_app_service", return_value=svc):
            result = _registered_router_customers(
                "update",
                {"id": 7, "contact_person": "", "address": "", "expected_version": 4},
                {"service_source": source} if source else {},
                "admin",
                "",
            )
        assert result["success"] is True
        svc.update.assert_called_once_with(
            7, {"contact_person": "", "contact_address": "", "expected_version": 4}
        )


class TestProductsRouterMissingBranches:
    def _svc(self):
        return MagicMock()

    @pytest.mark.parametrize(
        "source", [None, "fastapi_product_route", "fastapi_product_compat_route", "mcp", "employee"]
    )
    def test_every_product_entry_uses_the_same_service_and_fields(self, source):
        svc = self._svc()
        svc.create_product.return_value = {"success": True, "product_id": 5}
        params = {
            "name": "P1",
            "unit_price": 5.0,
            "product_code": "m-1",
            "unit": "件",
            "quantity": 9,
            "description": "完整字段",
            "category": "材料",
            "brand": "B",
            "is_active": False,
        }
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(
                "create",
                params,
                {"service_source": source} if source else {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["product_id"] == 5
        svc.create_product.assert_called_once_with(
            {
                **params,
                "name": "P1",
                "product_name": "P1",
                "model_number": "M-1",
                "product_code": "M-1",
                "specification": None,
                "price": 5.0,
            }
        )

    @pytest.mark.parametrize(
        "source", [None, "fastapi_product_route", "fastapi_product_compat_route", "mcp", "employee"]
    )
    def test_product_update_normalization_is_entry_independent(self, source):
        svc = self._svc()
        svc.update_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            _registered_router_products(
                "update",
                {
                    "id": 10,
                    "unit_price": 0,
                    "product_code": "M-2",
                    "measure_unit": "箱",
                    "description": "",
                    "quantity": 0,
                    "is_active": False,
                },
                {"service_source": source} if source else {},
                "admin",
                "",
            )
        svc.update_product.assert_called_once_with(
            10,
            {
                "price": 0,
                "model_number": "M-2",
                "unit": "箱",
                "description": "",
                "quantity": 0,
                "is_active": False,
            },
        )

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
        svc.update_product.assert_called_once_with(10, {"price": 9.9})
        assert result["success"] is True

    def test_delete_product(self):
        svc = self._svc()
        svc.delete_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products("delete", {"id": 7}, {}, "admin", "")
        svc.delete_product.assert_called_once_with(7)
        assert result["success"] is True

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

    def test_batch_delete_products_success(self):
        svc = self._svc()
        svc.batch_delete_products.return_value = {"success": True, "deleted_count": 1}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products("batch_delete", {"ids": [1, 2]}, {}, "admin", "")
        assert result["success"] is True
        assert result["deleted_count"] == 1
        svc.batch_delete_products.assert_called_once_with([1, 2])
        svc.batch_delete.assert_not_called()

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
            _registered_router_products("batch_delete", {"product_ids": [5]}, {}, "admin", "")
        svc.batch_delete_products.assert_called_once_with([5])

    def test_clear_collects_and_deletes_all_products(self):
        svc = self._svc()
        svc.get_products.return_value = {"success": True, "data": [{"id": 3}, {"id": 4}]}
        svc.batch_delete_products.return_value = {"success": True, "deleted_count": 1}
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products("clear", {}, {}, "admin", "")
        svc.batch_delete_products.assert_called_once_with([3, 4])
        assert result["success"] is True
        assert result["deleted_count"] == 1
        svc.batch_delete.assert_not_called()

    @pytest.mark.parametrize("action", ["batch_delete", "clear"])
    def test_product_delete_preserves_failure_without_claiming_a_count(self, action):
        svc = self._svc()
        svc.get_products.return_value = {"success": True, "data": [{"id": 3}, {"id": 4}]}
        receipt = {"success": False, "error_code": "storage_rejected"}
        svc.batch_delete_products.return_value = receipt
        with patch("app.services.get_products_service", return_value=svc):
            result = _registered_router_products(action, {"ids": [3, 4]}, {}, "admin", "")
        assert result == receipt
        assert "deleted_count" not in result
        svc.batch_delete_products.assert_called_once_with([3, 4])
        svc.batch_delete.assert_not_called()

    def test_exists_model_in_list_but_name_matches(self):
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


class TestShipmentRecordsRouterCreate:
    def test_unknown_action(self):
        result = _registered_router_shipment_records("fly", {}, {}, "admin", "")
        assert result["success"] is False

    @pytest.mark.parametrize(
        "receipt",
        [{"success": True, "deleted_count": 151}, {"success": False, "message": "delete rejected"}],
    )
    def test_clear_preserves_canonical_service_receipt(self, receipt):
        svc = MagicMock()
        svc.clear_all_orders.return_value = receipt
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_records("clear", {}, {}, "admin", "")
        svc.clear_all_orders.assert_called_once_with()
        svc.get_shipment_records.assert_not_called()
        svc.delete_shipment_record.assert_not_called()
        assert result == receipt


class TestShipmentOrdersRouterBranches:
    def _svc(self):
        return MagicMock()

    def _products(self):
        return [
            {
                "id": 1,
                "product_name": "P1",
                "quantity_tins": 2,
                "tin_spec": 10,
                "unit_price": 5,
            }
        ]

    def test_generate_success(self):
        svc = self._svc()
        svc.generate_shipment_document.return_value = {"success": True, "file_path": "/tmp/s.pdf"}
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate",
                {"unit_name": "Co", "products": self._products()},
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        svc.generate_shipment_document.assert_called_once_with(
            unit_name="Co", products=self._products(), date=None
        )

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
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {
                    "shipments": [
                        {"unit_name": "Co", "products": self._products()},
                    ]
                },
                {},
                "admin",
                "",
            )
        assert result["success"] is True
        assert result["data"]["processed"] == 1
        svc.generate_shipment_document.assert_called_once_with(
            unit_name="Co", products=self._products(), date=None
        )

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
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {"shipments": [{"unit_name": "Co", "products": self._products()}]},
                {},
                "admin",
                "",
            )
        assert result["data"]["errors"][0]["error"] == "err"
        assert result["success"] is False and result["data"]["processed"] == 0
        svc.generate_shipment_document.assert_called_once_with(
            unit_name="Co", products=self._products(), date=None
        )

    def test_generate_batch_service_exception(self):
        svc = self._svc()
        svc.generate_shipment_document.side_effect = OSError("boom")
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders(
                "generate_batch",
                {"shipments": [{"unit_name": "Co", "products": self._products()}]},
                {},
                "admin",
                "",
            )
        assert "boom" in result["data"]["errors"][0]["error"]
        assert result["success"] is False and result["data"]["processed"] == 0
        svc.generate_shipment_document.assert_called_once_with(
            unit_name="Co", products=self._products(), date=None
        )

    def test_print_with_order_id(self):
        svc = self._svc()
        svc.mark_as_printed.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
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
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=MagicMock()):
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
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
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
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders(
                "set_sequence", {"sequence": 5}, {}, "admin", ""
            )
        assert result["sequence"] == 5

    def test_reset_sequence(self):
        svc = self._svc()
        svc.reset_order_sequence.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders("reset_sequence", {}, {}, "admin", "")
        assert result["success"] is True

    def test_clear_all(self):
        svc = self._svc()
        svc.clear_all_orders.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders("clear_all", {}, {}, "admin", "")
        assert result["success"] is True

    def test_delete_shipment(self):
        svc = self._svc()
        svc.delete_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_application_service_core", return_value=svc):
            result = _registered_router_shipment_orders("delete", {"id": 3}, {}, "admin", "")
        assert result["deleted_id"] == 3

    def test_unknown_action(self):
        result = _registered_router_shipment_orders("fly", {}, {}, "admin", "")
        assert result["success"] is False


class TestInventoryRouterBranches:
    def _svc(self):
        return MagicMock()

    def test_create_storage_location(self):
        svc = self._svc()
        svc.create_storage_location.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "create_storage_location", {"name": "A-01"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_storage_location(self):
        svc = self._svc()
        svc.update_storage_location.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "update_storage_location", {"location_id": 1, "name": "B"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_create_warehouse(self):
        svc = self._svc()
        svc.create_warehouse.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "create_warehouse", {"name": "WH-1"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_warehouse(self):
        svc = self._svc()
        svc.update_warehouse.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "update_warehouse", {"warehouse_id": 2, "name": "WH-2"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_delete_warehouse(self):
        svc = self._svc()
        svc.delete_warehouse.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "delete_warehouse", {"warehouse_id": 2}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_stock_in(self):
        svc = self._svc()
        svc.inventory_in.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "stock_in", {"product_id": 1, "quantity": 10}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_stock_out(self):
        svc = self._svc()
        svc.inventory_out.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
            result = _registered_router_inventory(
                "stock_out", {"product_id": 1, "quantity": 5}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_transfer(self):
        svc = self._svc()
        svc.inventory_transfer.return_value = {"success": True}
        with patch("app.application.inventory_app_service.InventoryAppService", return_value=svc):
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


class TestPurchaseRouterBranches:
    def _svc(self):
        return MagicMock()

    def test_create_supplier(self):
        svc = self._svc()
        svc.create_supplier.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "create_supplier", {"name": "VendorA"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_supplier(self):
        svc = self._svc()
        svc.update_supplier.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "update_supplier", {"supplier_id": 1, "name": "V"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_delete_supplier(self):
        svc = self._svc()
        svc.delete_supplier.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "delete_supplier", {"supplier_id": 2}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_create_order(self):
        svc = self._svc()
        svc.create_purchase_order.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "create_order", {"supplier_id": 1}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_update_order(self):
        svc = self._svc()
        svc.update_purchase_order.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "update_order", {"order_id": 3, "status": "confirmed"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_approve_order(self):
        svc = self._svc()
        svc.approve_purchase_order.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase(
                "approve_order", {"order_id": 3, "approver": "boss"}, {}, "admin", ""
            )
        assert result["success"] is True

    def test_cancel_order(self):
        svc = self._svc()
        svc.cancel_purchase_order.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase("cancel_order", {"order_id": 3}, {}, "admin", "")
        assert result["success"] is True

    def test_create_inbound(self):
        svc = self._svc()
        svc.create_purchase_inbound.return_value = {"success": True}
        with patch("app.application.facades.inventory_facade.PurchaseService", return_value=svc):
            result = _registered_router_purchase("create_inbound", {"order_id": 3}, {}, "admin", "")
        assert result["success"] is True

    def test_unknown_action(self):
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=self._svc()
        ):
            result = _registered_router_purchase("fly", {}, {}, "admin", "")
        assert result["success"] is False


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

    @pytest.mark.parametrize("action", ["batch_delete", "clear"])
    def test_batch_delete_service_exception(self, action):
        svc = MagicMock()
        svc.get_all_materials.return_value = {"success": True, "data": [{"id": 1}]}
        svc.batch_delete_materials.side_effect = ConnectionError("db error")
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials(action, {"ids": [1]}, {}, "admin", "")
        assert result["success"] is False
        assert result["execution_state"] == "unknown"
        assert result["outcome"] == "unknown"
        assert result["error_code"] == "material_delete_outcome_unknown"
        assert result["retryable"] is False and result["reconciliation_required"] is True
        assert "deleted_count" not in result and "warning" not in result
        svc.batch_delete_materials.assert_called_once_with([1])

    @pytest.mark.parametrize("action", ["batch_delete", "clear"])
    @pytest.mark.parametrize(
        "receipt", [None, {}, {"success": True}, {"success": True, "deleted_count": "2"}]
    )
    def test_batch_delete_missing_valid_receipt(self, action, receipt):
        svc = MagicMock()
        svc.get_all_materials.return_value = {"success": True, "data": [{"id": 1}, {"id": 2}]}
        svc.batch_delete_materials.return_value = receipt
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials(action, {"ids": [1, 2]}, {}, "admin", "")
        assert result["success"] is False
        assert result["execution_state"] == "unknown"
        assert result["retryable"] is False and result["reconciliation_required"] is True
        assert "deleted_count" not in result
        svc.batch_delete_materials.assert_called_once_with([1, 2])

    @pytest.mark.parametrize("action", ["batch_delete", "clear"])
    def test_delete_preserves_actual_service_failure(self, action):
        svc = MagicMock()
        svc.get_all_materials.return_value = {"success": True, "data": [{"id": 1}, {"id": 2}]}
        receipt = {"success": False, "error_code": "storage_rejected", "message": "未删除"}
        svc.batch_delete_materials.return_value = receipt
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials(action, {"ids": [1, 2]}, {}, "admin", "")
        assert result == receipt
        assert "deleted_count" not in result
        svc.batch_delete_materials.assert_called_once_with([1, 2])

    def test_clear_collects_and_deletes_all_materials(self):
        svc = MagicMock()
        svc.get_all_materials.return_value = {
            "success": True,
            "data": [{"id": 8}, {"id": 9}],
            "total": 2,
        }
        svc.batch_delete_materials.return_value = {"success": True, "deleted_count": 1}
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials("clear", {}, {}, "admin", "")
        svc.batch_delete_materials.assert_called_once_with([8, 9])
        assert result["success"] is True
        assert result["deleted_count"] == 1

    @pytest.mark.parametrize("listing", [None, {"success": False, "data": []}])
    def test_clear_cannot_report_empty_success_when_listing_fails(self, listing):
        svc = MagicMock()
        svc.get_all_materials.return_value = listing
        with patch("app.application.get_material_application_service", return_value=svc):
            result = _registered_router_materials("clear", {}, {}, "admin", "")
        assert result["success"] is False
        assert "deleted_count" not in result
        svc.batch_delete_materials.assert_not_called()
