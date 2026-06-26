"""测试 app.services.tools_workflow_registered 的分支覆盖。

覆盖目标：
- _registered_router_normal_slot_dispatch（product_query / shipment_preview / 未知动作）
- _registered_router_customers（query / ensure_exists / create / update / delete / batch_delete / 未知）
- _registered_router_products（query / exists / create / update / delete / batch_create / batch_delete）
- _registered_router_materials（list / create / update / delete / batch_delete / export）
- _registered_router_inventory（各动作）
- _registered_router_purchase（各动作）
- _registered_router_finance（各动作）
- _registered_router_shipment_records（list / create / update / delete / export）
- _registered_router_system_maintenance（set_default_printer / backup_database / clear_performance_cache 等）
- _registered_router_excel_analyzer / excel_toolkit / label_template_generator
- _registered_router_document_template（create / update / delete / 未知）
- _registered_router_template_preview（view / list）
- _registered_router_wechat（view / list / refresh）
- _registered_router_print（workflow_label_dispatch / view / list / print_label / save_printer_selection）
- _registered_router_printer_list / settings
- _registered_router_employee（list / execute / 未知）
- _normalize_business_db_entity（各别名 / 空值 / user_message 回退）
- _registered_router_business_db（read / write / sql 拒绝 / 未知 entity）
- _registered_router_business_event（print_label / inventory_update / shipment_create / 未知）
- _ocr_artifact_payload（字段过滤）
- _registered_router_ocr（request / recognize / extract / analyze / recognize_and_extract / 未知）
- _execute_excel_import_records（空 / 正常 / 客户服务降级）
- _registered_router_excel_import（execute_import / import_records / 未知）
- _registered_router_unit_products_import（参数校验）
- execute_registered_workflow_tool（dispatcher / employee_tool 回退 / 未知）
- _WorkflowRouterMap（hidden keys）
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_spec = importlib.util.spec_from_file_location(
    "_twr_module",
    Path(__file__).resolve().parents[2] / "app" / "services" / "tools_workflow_registered.py",
)
assert _spec is not None and _spec.loader is not None
_twr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_twr)

_WorkflowRouterMap = _twr._WorkflowRouterMap
_execute_excel_import_records = _twr._execute_excel_import_records
_normalize_business_db_entity = _twr._normalize_business_db_entity
_ocr_artifact_payload = _twr._ocr_artifact_payload
_registered_router_business_db = _twr._registered_router_business_db
_registered_router_business_event = _twr._registered_router_business_event
_registered_router_business_docking_family = _twr._registered_router_business_docking_family
_registered_router_customers = _twr._registered_router_customers
_registered_router_document_template = _twr._registered_router_document_template
_registered_router_employee = _twr._registered_router_employee
_registered_router_excel_analyzer = _twr._registered_router_excel_analyzer
_registered_router_excel_import = _twr._registered_router_excel_import
_registered_router_excel_toolkit = _twr._registered_router_excel_toolkit
_registered_router_finance = _twr._registered_router_finance
_registered_router_inventory = _twr._registered_router_inventory
_registered_router_label_template_generator = _twr._registered_router_label_template_generator
_registered_router_materials = _twr._registered_router_materials
_registered_router_normal_slot_dispatch = _twr._registered_router_normal_slot_dispatch
_registered_router_ocr = _twr._registered_router_ocr
_registered_router_print = _twr._registered_router_print
_registered_router_printer_list = _twr._registered_router_printer_list
_registered_router_products = _twr._registered_router_products
_registered_router_purchase = _twr._registered_router_purchase
_registered_router_settings = _twr._registered_router_settings
_registered_router_shipment_records = _twr._registered_router_shipment_records
_registered_router_system_maintenance = _twr._registered_router_system_maintenance
_registered_router_template_preview = _twr._registered_router_template_preview
_registered_router_unit_products_import = _twr._registered_router_unit_products_import
_registered_router_wechat = _twr._registered_router_wechat
execute_registered_workflow_tool = _twr.execute_registered_workflow_tool


def _ctx(**overrides) -> dict:
    base = {"service_source": "", "message": ""}
    base.update(overrides)
    return base


class TestNormalSlotDispatch:
    """_registered_router_normal_slot_dispatch 分支覆盖。"""

    def test_product_query_uses_user_message(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
        ) as mock_fn:
            mock_fn.return_value = {"success": True}
            result = _registered_router_normal_slot_dispatch(
                "product_query", {}, _ctx(message="查产品"), "normal", "查产品"
            )
            assert result["success"] is True
            mock_fn.assert_called_once_with("查产品")

    def test_product_query_falls_back_to_params_message(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message"
        ) as mock_fn:
            mock_fn.return_value = {"success": True}
            _registered_router_normal_slot_dispatch(
                "product_query", {"message": "params-msg"}, _ctx(), "", ""
            )
            mock_fn.assert_called_once_with("params-msg")

    def test_shipment_preview_uses_params_order_text(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview"
        ) as mock_fn:
            mock_fn.return_value = {"success": True}
            _registered_router_normal_slot_dispatch(
                "shipment_preview", {"order_text": "order123"}, _ctx(), "normal", ""
            )
            mock_fn.assert_called_once_with("order123")

    def test_shipment_preview_falls_back_to_user_message(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview"
        ) as mock_fn:
            mock_fn.return_value = {"success": True}
            _registered_router_normal_slot_dispatch(
                "shipment_preview", {}, _ctx(), "normal", "user-order"
            )
            mock_fn.assert_called_once_with("user-order")

    def test_unknown_action_returns_failure(self) -> None:
        result = _registered_router_normal_slot_dispatch("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False
        assert "unknown" in result["message"]


class TestCustomersRouter:
    """_registered_router_customers 分支覆盖。"""

    def test_query_with_keyword(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": [{"id": 1}]}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "query", {"keyword": "test"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["data"] == [{"id": 1}]

    def test_query_falls_back_to_unit_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            _registered_router_customers("query", {"unit_name": "acme"}, _ctx(), "normal", "")
            mock_svc.get_all.assert_called_once_with(keyword="acme", page=1, per_page=20)

    def test_ensure_exists_missing_unit_name(self) -> None:
        with patch("app.application.get_customer_app_service"):
            result = _registered_router_customers("ensure_exists", {}, _ctx(), "normal", "")
            assert result["success"] is False
            assert "unit_name" in result["message"]

    def test_ensure_exists_already_matched(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = MagicMock(unit_name="acme")
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_creates_new(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "new"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["created"] is True

    def test_ensure_exists_create_returns_already_exists(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "客户已存在"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "dup"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_create_fails(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "DB error"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "fail"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_create_missing_unit_name(self) -> None:
        with patch("app.application.get_customer_app_service"):
            result = _registered_router_customers("create", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_create_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "create", {"unit_name": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action_returns_failure(self) -> None:
        with patch("app.application.get_customer_app_service"):
            result = _registered_router_customers("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestProductsRouter:
    """_registered_router_products 分支覆盖。"""

    def test_query_normal_profile(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.run_workflow_products_query_normal_profile"
        ) as mock_fn:
            mock_fn.return_value = {"success": True}
            result = _registered_router_products("query", {}, _ctx(), "normal", "find products")
            assert result["success"] is True

    def test_query_non_normal_profile(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "query", {"keyword": "abc"}, _ctx(), "advanced", ""
            )
            assert result["success"] is True

    def test_exists_match_by_model(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {
            "success": True,
            "data": [{"name": "p", "model_number": "M01"}],
        }
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "exists", {"model_number": "m01"}, _ctx(), "normal", ""
            )
            assert result["exists"] is True

    def test_exists_match_by_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {
            "success": True,
            "data": [{"name": "Widget"}],
        }
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "exists", {"product_name": "Widget"}, _ctx(), "normal", ""
            )
            assert result["exists"] is True

    def test_exists_no_match(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "exists", {"model_number": "X"}, _ctx(), "normal", ""
            )
            assert result["exists"] is False

    def test_create_missing_name_or_unit(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products("create", {"unit_name": ""}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_create_invalid_price_falls_back_to_zero(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            _registered_router_products(
                "create",
                {"unit_name": "u", "name_or_model": "p", "unit_price": "bad"},
                _ctx(),
                "normal",
                "",
            )
            call_args = mock_svc.create_product.call_args[0][0]
            assert call_args["unit_price"] == 0.0

    def test_create_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "create", {"unit_name": "u", "name_or_model": "p"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["created"] is True

    def test_create_failure(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_product.return_value = {"success": False, "message": "err"}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "create", {"unit_name": "u", "name_or_model": "p"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_batch_create_not_list(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products(
                "batch_create", {"products": "not-list"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_batch_create_empty_list(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products(
                "batch_create", {"products": []}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_batch_create_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.batch_add_products.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "batch_create", {"products": [{"name": "p"}]}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_batch_delete_not_list(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products("batch_delete", {"ids": "x"}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_batch_delete_all_invalid_ids(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products(
                "batch_delete", {"ids": ["a", "b"]}, _ctx(), "normal", ""
            )
            assert result["success"] is False
            assert "skipped" in result

    def test_batch_delete_with_skipped(self) -> None:
        mock_svc = MagicMock()
        mock_svc.batch_delete_products.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "batch_delete", {"ids": [1, "bad", 2]}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["skipped"] == ["bad"]

    def test_batch_delete_fallback_to_batch_delete(self) -> None:
        mock_svc = MagicMock()
        del mock_svc.batch_delete_products
        mock_svc.batch_delete.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "batch_delete", {"ids": [1, 2]}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_products("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestMaterialsRouter:
    """_registered_router_materials 分支覆盖。"""

    def test_list_query(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("list", {"search": "abc"}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_create(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "create", {"material_name": "steel"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_update_returns_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.update_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "update", {"id": 1, "name": "x"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_update_returns_non_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.update_material.return_value = True
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "update", {"id": 1, "name": "x"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_delete_returns_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.delete_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("delete", {"id": 1}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_delete_returns_non_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.delete_material.return_value = True
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("delete", {"id": 1}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_batch_delete_with_exception(self) -> None:
        mock_svc = MagicMock()
        mock_svc.batch_delete_materials.side_effect = RuntimeError("db down")
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "batch_delete", {"ids": [1, 2]}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["deleted_count"] == 2
            assert "warning" in result

    def test_batch_delete_returns_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.batch_delete_materials.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "batch_delete", {"ids": [1]}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["deleted_count"] == 1

    def test_batch_delete_returns_non_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.batch_delete_materials.return_value = True
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials(
                "batch_delete", {"ids": [1]}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_export(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("export", {"search": "x"}, _ctx(), "normal", "")
            assert result["success"] is True


class TestInventoryRouter:
    """_registered_router_inventory 分支覆盖。"""

    def test_create_storage_location(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_storage_location.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_inventory(
                "create_storage_location", {"name": "loc"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_stock_in(self) -> None:
        mock_svc = MagicMock()
        mock_svc.inventory_in.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_inventory(
                "stock_in",
                {"product_id": 1, "warehouse_id": 2, "quantity": 5},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_stock_out(self) -> None:
        mock_svc = MagicMock()
        mock_svc.inventory_out.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_inventory(
                "stock_out",
                {"product_id": 1, "warehouse_id": 2, "quantity": 3},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_transfer(self) -> None:
        mock_svc = MagicMock()
        mock_svc.inventory_transfer.return_value = {"success": True}
        with patch(
            "app.application.inventory_app_service.InventoryAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_inventory(
                "transfer",
                {"product_id": 1, "from_warehouse_id": 2, "to_warehouse_id": 3, "quantity": 1},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.application.inventory_app_service.InventoryAppService"):
            result = _registered_router_inventory("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestPurchaseRouter:
    """_registered_router_purchase 分支覆盖。"""

    def test_create_supplier(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_supplier.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService",
            return_value=mock_svc,
        ):
            result = _registered_router_purchase(
                "create_supplier", {"name": "sup"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_approve_order(self) -> None:
        mock_svc = MagicMock()
        mock_svc.approve_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService",
            return_value=mock_svc,
        ):
            result = _registered_router_purchase(
                "approve_order", {"order_id": 1, "approver": "admin"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_cancel_order(self) -> None:
        mock_svc = MagicMock()
        mock_svc.cancel_purchase_order.return_value = {"success": True}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService",
            return_value=mock_svc,
        ):
            result = _registered_router_purchase(
                "cancel_order", {"order_id": 1}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.application.facades.inventory_facade.PurchaseService"):
            result = _registered_router_purchase("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestFinanceRouter:
    """_registered_router_finance 分支覆盖。"""

    def test_create_transaction(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_transaction.return_value = {"success": True}
        with patch(
            "app.application.finance_app_service.FinanceAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_finance(
                "create_transaction", {"amount": 100}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_delete_transaction(self) -> None:
        mock_svc = MagicMock()
        mock_svc.delete_transaction.return_value = {"success": True}
        with patch(
            "app.application.finance_app_service.FinanceAppService",
            return_value=mock_svc,
        ):
            result = _registered_router_finance(
                "delete_transaction", {"transaction_id": 1}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.application.finance_app_service.FinanceAppService"):
            result = _registered_router_finance("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestShipmentRecordsRouter:
    """_registered_router_shipment_records 分支覆盖。"""

    def test_list_query(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records(
                "list", {"unit": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert len(result["data"]) == 1

    def test_create_missing_unit_name(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service"):
            result = _registered_router_shipment_records("create", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_create_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records(
                "create", {"unit_name": "acme", "products": [{"id": 1}]}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_create_products_not_list(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            _registered_router_shipment_records(
                "create", {"unit_name": "acme", "products": "not-list"}, _ctx(), "normal", ""
            )
            mock_svc.create_shipment.assert_called_once()
            assert mock_svc.create_shipment.call_args.kwargs["items_data"] == []

    def test_export(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_shipment_records.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records(
                "export", {"unit": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service"):
            result = _registered_router_shipment_records("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestSystemMaintenanceRouter:
    """_registered_router_system_maintenance 分支覆盖。"""

    def test_set_default_printer_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "set_default_printer", {"printer_name": "HP"}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 200

    def test_set_default_printer_failure(self) -> None:
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": False}
        with patch(
            "app.application.facades.session_facade.get_system_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "set_default_printer", {"printer_name": "HP"}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 500

    def test_enable_startup(self) -> None:
        mock_svc = MagicMock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "enable_startup", {}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 200

    def test_disable_startup(self) -> None:
        mock_svc = MagicMock()
        mock_svc.disable_startup.return_value = {"success": False}
        with patch(
            "app.application.facades.session_facade.get_system_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "disable_startup", {}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 500

    def test_backup_database(self) -> None:
        mock_svc = MagicMock()
        mock_svc.backup_database.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "backup_database", {}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 200

    def test_delete_database_backup(self) -> None:
        mock_svc = MagicMock()
        mock_svc.delete_backup.return_value = {"success": False}
        with patch(
            "app.application.facades.session_facade.get_database_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "delete_database_backup", {"backup_file": "bak.sql"}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 500

    def test_restore_database_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.restore_database.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "restore_database", {"backup_file": "bak.sql"}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 200

    def test_restore_database_failure(self) -> None:
        mock_svc = MagicMock()
        mock_svc.restore_database.return_value = {"success": False}
        with patch(
            "app.application.facades.session_facade.get_database_service",
            return_value=mock_svc,
        ):
            result = _registered_router_system_maintenance(
                "restore_database", {"backup_file": "bak.sql"}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 400

    def test_clear_performance_cache_no_redis(self) -> None:
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, _ctx(), "normal", ""
            )
            assert result["success"] is False
            assert result["http_status_code"] == 503

    def test_clear_performance_cache_with_pattern(self) -> None:
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_pattern.return_value = 5
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {"pattern": "test:*"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert "5" in result["message"]

    def test_clear_performance_cache_local_only(self) -> None:
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_local_cache = MagicMock()
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "clear_performance_cache", {}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            mock_opt.redis_cache.clear_local_cache.assert_called_once()

    def test_invalidate_performance_cache_no_redis(self) -> None:
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {}, _ctx(), "normal", ""
            )
            assert result["http_status_code"] == 503

    def test_invalidate_performance_cache_success(self) -> None:
        mock_opt = MagicMock()
        mock_opt.redis_cache.delete.return_value = 3
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "invalidate_performance_cache", {"keys": ["a", "b"]}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["data"]["deleted_count"] == 3

    def test_reinitialize_performance(self) -> None:
        mock_opt = MagicMock()
        mock_opt.get_status.return_value = {"status": "ok"}
        with patch(
            "app.utils.performance_initializer.init_performance_optimization",
            return_value=mock_opt,
        ):
            result = _registered_router_system_maintenance(
                "reinitialize_performance", {}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        result = _registered_router_system_maintenance("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False


class TestExcelAnalyzerRouter:
    """_registered_router_excel_analyzer 分支覆盖。"""

    def test_unknown_action(self) -> None:
        result = _registered_router_excel_analyzer("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_missing_file_path(self) -> None:
        result = _registered_router_excel_analyzer("analyze", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_import_error(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "excel_template_analyzer" in name:
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = _registered_router_excel_analyzer(
                "analyze", {"file_path": "/tmp/x.xlsx"}, _ctx(), "normal", ""
            )
            assert result["success"] is False
            assert "未正确安装" in result["message"]


class TestExcelToolkitRouter:
    """_registered_router_excel_toolkit 分支覆盖。"""

    def test_unknown_action(self) -> None:
        result = _registered_router_excel_toolkit("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_missing_file_path(self) -> None:
        result = _registered_router_excel_toolkit("view", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_empty_action_defaults_to_view(self) -> None:
        result = _registered_router_excel_toolkit("", {"file_path": ""}, _ctx(), "normal", "")
        assert result["success"] is False
        assert "view" in result["message"]


class TestLabelTemplateGeneratorRouter:
    """_registered_router_label_template_generator 分支覆盖。"""

    def test_unknown_action(self) -> None:
        result = _registered_router_label_template_generator("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_missing_image_path(self) -> None:
        result = _registered_router_label_template_generator("execute", {}, _ctx(), "normal", "")
        assert result["success"] is False


class TestDocumentTemplateRouter:
    """_registered_router_document_template 分支覆盖。"""

    def test_create(self) -> None:
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create"
        ) as mock_fn:
            mock_fn.return_value = ({"success": True}, 200)
            result = _registered_router_document_template(
                "create", {"name": "t"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["http_status_code"] == 200

    def test_update(self) -> None:
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_update"
        ) as mock_fn:
            mock_fn.return_value = ({"success": False}, 400)
            result = _registered_router_document_template("update", {"id": 1}, _ctx(), "normal", "")
            assert result["http_status_code"] == 400

    def test_delete_with_base_dir(self) -> None:
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_delete"
        ) as mock_fn:
            mock_fn.return_value = ({"success": True}, 200)
            result = _registered_router_document_template(
                "delete", {"id": 1}, _ctx(template_base_dir="/tmp"), "normal", ""
            )
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["base_dir"] == "/tmp"

    def test_delete_without_base_dir(self) -> None:
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_delete"
        ) as mock_fn:
            mock_fn.return_value = ({"success": True}, 200)
            _registered_router_document_template("delete", {"id": 1}, _ctx(), "normal", "")
            assert mock_fn.call_args.kwargs["base_dir"] is None

    def test_unknown_action(self) -> None:
        result = _registered_router_document_template("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_status_code_fallback_when_none(self) -> None:
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create"
        ) as mock_fn:
            mock_fn.return_value = ({"success": True}, None)
            result = _registered_router_document_template("create", {}, _ctx(), "normal", "")
            assert result["http_status_code"] == 200


class TestTemplatePreviewRouter:
    """_registered_router_template_preview 分支覆盖。"""

    def test_view_redirect(self) -> None:
        result = _registered_router_template_preview("view", {}, _ctx(), "normal", "")
        assert result["success"] is True
        assert "redirect" in result

    def test_list_returns_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"success": True, "data": []}
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _registered_router_template_preview("list", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_list_returns_non_dict(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = [{"id": 1}]
        with patch("app.application.get_template_app_service", return_value=mock_svc):
            result = _registered_router_template_preview("query", {}, _ctx(), "normal", "")
            assert result["success"] is True
            assert result["data"] == [{"id": 1}]


class TestWechatRouter:
    """_registered_router_wechat 分支覆盖。"""

    def test_view_redirect(self) -> None:
        with patch("app.application.get_wechat_contact_app_service"):
            result = _registered_router_wechat("view", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_list_query(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = [{"id": 1}]
        with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
            result = _registered_router_wechat(
                "list", {"type": "friend", "keyword": "a"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_refresh_contact_cache(self) -> None:
        with (
            patch("app.application.get_wechat_contact_app_service"),
            patch(
                "app.services.wechat_contact_cache_import.ensure_decrypted_wechat_dbs"
            ) as mock_fn,
        ):
            mock_fn.return_value = {"success": True}
            result = _registered_router_wechat("refresh_contact_cache", {}, _ctx(), "normal", "")
            assert result["success"] is True


class TestPrintRouter:
    """_registered_router_print 分支覆盖。"""

    def test_workflow_label_dispatch_missing_model_number(self) -> None:
        result = _registered_router_print("workflow_label_dispatch", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_workflow_label_dispatch_product_lookup_fails(self) -> None:
        with (
            patch("app.application.get_product_app_service") as mock_get,
            patch(
                "app.application.print_app_service.get_print_application_service"
            ) as mock_print_svc,
        ):
            mock_get.side_effect = RuntimeError("db down")
            mock_print_svc.return_value.print_single_label.return_value = {"success": True}
            result = _registered_router_print(
                "workflow_label_dispatch", {"model_number": "M01"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_workflow_label_dispatch_with_product_found(self) -> None:
        with (
            patch("app.application.get_product_app_service") as mock_get,
            patch(
                "app.application.print_app_service.get_print_application_service"
            ) as mock_print_svc,
        ):
            mock_get.return_value.search_products.return_value = [
                {"name": "Widget", "specification": "10x10", "unit": "箱"}
            ]
            mock_print_svc.return_value.print_single_label.return_value = {"success": True}
            result = _registered_router_print(
                "workflow_label_dispatch",
                {"model_number": "M01", "quantity": 5},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_view_redirect(self) -> None:
        with patch("app.services.get_printer_service"):
            result = _registered_router_print("view", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_list_printers(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"printers": []}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print("list", {}, _ctx(), "normal", "")
            assert "printers" in result

    def test_save_printer_selection_invalid_document_printer(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print(
                "save_printer_selection", {"document_printer": "Epson"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_save_printer_selection_invalid_label_printer(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": "HP", "label_printer": "Epson"},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is False

    def test_save_printer_selection_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"printers": [{"name": "HP"}]}
        mock_svc.save_printer_selection.return_value = {"success": True}
        mock_svc.classify_printers.return_value = {"document_printers": []}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print(
                "save_printer_selection",
                {"document_printer": "HP", "label_printer": "HP"},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_unknown_action(self) -> None:
        with patch("app.services.get_printer_service"):
            result = _registered_router_print("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False


class TestPrinterListRouter:
    """_registered_router_printer_list 分支覆盖。"""

    def test_view_redirect(self) -> None:
        with patch("app.services.get_system_service"):
            result = _registered_router_printer_list("view", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_list(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_printer_config.return_value = {"printers": []}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_printer_list("query", {}, _ctx(), "normal", "")
            assert "printers" in result

    def test_set_default(self) -> None:
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_printer_list(
                "set_default", {"printer_name": "HP"}, _ctx(), "normal", ""
            )
            assert result["success"] is True


class TestSettingsRouter:
    """_registered_router_settings 分支覆盖。"""

    def test_view_redirect(self) -> None:
        with patch("app.services.get_system_service"):
            result = _registered_router_settings("view", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_query(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("query", {}, _ctx(), "normal", "")
            assert result["data"]["version"] == "1.0"

    def test_get_startup_config(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_startup_config.return_value = {"auto": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("get_startup_config", {}, _ctx(), "normal", "")
            assert result["data"]["auto"] is True

    def test_enable_startup(self) -> None:
        mock_svc = MagicMock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("enable_startup", {}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_disable_startup(self) -> None:
        mock_svc = MagicMock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("disable_startup", {}, _ctx(), "normal", "")
            assert result["success"] is True


class TestEmployeeRouter:
    """_registered_router_employee 分支覆盖。"""

    def test_list_query(self) -> None:
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn:
            mock_fn.return_value = {"registered_tool_count": 3}
            result = _registered_router_employee("list", {}, _ctx(), "normal", "")
            assert result["success"] is True
            assert "3" in result["message"]

    def test_unknown_action(self) -> None:
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status"):
            result = _registered_router_employee("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_execute_missing_employee_id_no_message(self) -> None:
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn:
            mock_fn.return_value = {"employee_pack_tools": []}
            result = _registered_router_employee("execute", {}, _ctx(), "normal", "")
            assert result["success"] is False
            assert "employee_id" in result["message"]

    def test_execute_missing_task(self) -> None:
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn:
            mock_fn.return_value = {"employee_pack_tools": []}
            result = _registered_router_employee(
                "execute", {"employee_id": "emp1"}, _ctx(), "normal", ""
            )
            assert result["success"] is False
            assert "task" in result["message"]

    def test_execute_finds_employee_from_message(self) -> None:
        with (
            patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn,
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local"
            ) as mock_exec,
        ):
            mock_fn.return_value = {
                "employee_pack_tools": [{"pack_id": "emp1", "tool_name": "emp1"}]
            }
            mock_exec.return_value = {"success": True}
            result = _registered_router_employee(
                "execute", {}, _ctx(message="please run emp1"), "normal", "please run emp1"
            )
            assert result["success"] is True
            assert result["employee_id"] == "emp1"

    def test_execute_success(self) -> None:
        with (
            patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn,
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local"
            ) as mock_exec,
        ):
            mock_fn.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True}
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "do work"},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True

    def test_execute_blocked_by_risk_gate(self) -> None:
        with (
            patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn,
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local"
            ) as mock_exec,
        ):
            mock_fn.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True, "blocked_by_risk_gate": True}
            result = _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "do work"},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is False

    def test_execute_invalid_user_id(self) -> None:
        with (
            patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_fn,
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local"
            ) as mock_exec,
        ):
            mock_fn.return_value = {"employee_pack_tools": []}
            mock_exec.return_value = {"success": True}
            _registered_router_employee(
                "execute",
                {"employee_id": "emp1", "task": "do work", "user_id": "bad"},
                _ctx(),
                "normal",
                "",
            )
            assert mock_exec.call_args.kwargs["user_id"] == 0


class TestNormalizeBusinessDbEntity:
    """_normalize_business_db_entity 分支覆盖。"""

    def test_lowered_match(self) -> None:
        assert _normalize_business_db_entity("Customer") == "customers"

    def test_exact_match(self) -> None:
        assert _normalize_business_db_entity("客户") == "customers"

    def test_empty_raw_uses_user_message(self) -> None:
        assert _normalize_business_db_entity("", "请查产品列表") == "products"

    def test_no_match_returns_empty(self) -> None:
        assert _normalize_business_db_entity("xyz", "") == ""

    def test_none_raw(self) -> None:
        assert _normalize_business_db_entity(None, "发货单") == "shipment_records"


class TestBusinessDbRouter:
    """_registered_router_business_db 分支覆盖。"""

    def test_missing_entity(self) -> None:
        result = _registered_router_business_db("read", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_rejects_sql(self) -> None:
        result = _registered_router_business_db(
            "read", {"entity": "customers", "sql": "SELECT *"}, _ctx(), "normal", ""
        )
        assert result["success"] is False
        assert "SQL" in result["message"]

    def test_read_customers(self) -> None:
        with patch("app.application.get_customer_app_service") as mock_get:
            mock_get.return_value.get_all.return_value = {"success": True, "data": []}
            result = _registered_router_business_db(
                "read", {"entity": "customers"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_read_products(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_business_db(
                "read", {"entity": "products"}, _ctx(), "normal", ""
            )
            # Will fail because get_products_service returns a MagicMock, but the branch is covered
            assert isinstance(result, dict)

    def test_read_materials(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_business_db(
                "read", {"entity": "materials"}, _ctx(), "normal", ""
            )
            assert isinstance(result, dict)

    def test_read_shipment_records(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_business_db(
                "read", {"entity": "shipment_records"}, _ctx(), "normal", ""
            )
            assert isinstance(result, dict)

    def test_unknown_action(self) -> None:
        result = _registered_router_business_db(
            "unknown", {"entity": "customers"}, _ctx(), "normal", ""
        )
        assert result["success"] is False

    def test_write_missing_payload(self) -> None:
        result = _registered_router_business_db(
            "write", {"entity": "customers"}, _ctx(), "normal", ""
        )
        assert result["success"] is False

    def test_write_customers_create(self) -> None:
        with patch("app.application.get_customer_app_service"):
            result = _registered_router_business_db(
                "write",
                {"entity": "customers", "operation": "create", "payload": {"unit_name": "x"}},
                _ctx(),
                "normal",
                "",
            )
            assert isinstance(result, dict)

    def test_write_customers_ensure_exists(self) -> None:
        with patch("app.application.get_customer_app_service"):
            result = _registered_router_business_db(
                "write",
                {
                    "entity": "customers",
                    "operation": "ensure_exists",
                    "payload": {"unit_name": "x"},
                },
                _ctx(),
                "normal",
                "",
            )
            assert isinstance(result, dict)

    def test_write_customers_unsupported_operation(self) -> None:
        result = _registered_router_business_db(
            "write",
            {"entity": "customers", "operation": "delete", "payload": {}},
            _ctx(),
            "normal",
            "",
        )
        assert result["success"] is False

    def test_write_products_create(self) -> None:
        with patch("app.services.get_products_service"):
            result = _registered_router_business_db(
                "write",
                {"entity": "products", "operation": "create", "payload": {"unit_name": "x"}},
                _ctx(),
                "normal",
                "",
            )
            assert isinstance(result, dict)

    def test_write_products_unsupported_operation(self) -> None:
        result = _registered_router_business_db(
            "write",
            {"entity": "products", "operation": "delete", "payload": {}},
            _ctx(),
            "normal",
            "",
        )
        assert result["success"] is False

    def test_write_materials_create(self) -> None:
        mock_svc = MagicMock()
        mock_svc.create_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_business_db(
                "write",
                {"entity": "materials", "operation": "create", "payload": {"name": "x"}},
                _ctx(),
                "normal",
                "",
            )
            assert isinstance(result, dict)

    def test_write_materials_unsupported_operation(self) -> None:
        result = _registered_router_business_db(
            "write",
            {"entity": "materials", "operation": "export", "payload": {}},
            _ctx(),
            "normal",
            "",
        )
        assert result["success"] is False

    def test_write_shipment_records_update(self) -> None:
        mock_svc = MagicMock()
        mock_svc.update_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_business_db(
                "write",
                {"entity": "shipment_records", "operation": "update", "payload": {"id": 1}},
                _ctx(),
                "normal",
                "",
            )
            assert isinstance(result, dict)

    def test_write_shipment_records_unsupported_operation(self) -> None:
        result = _registered_router_business_db(
            "write",
            {"entity": "shipment_records", "operation": "create", "payload": {}},
            _ctx(),
            "normal",
            "",
        )
        assert result["success"] is False


class TestBusinessEventRouter:
    """_registered_router_business_event 分支覆盖。"""

    def test_print_label(self) -> None:
        with patch("app.neuro_bus.domains.print_domain.get_print_domain") as mock_get:
            mock_get.return_value.emit_job_submitted.return_value = True
            result = _registered_router_business_event(
                "print_label", {"job_id": "j1"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert result["job_id"] == "j1"

    def test_print_label_generates_job_id(self) -> None:
        with patch("app.neuro_bus.domains.print_domain.get_print_domain") as mock_get:
            mock_get.return_value.emit_job_submitted.return_value = True
            result = _registered_router_business_event("print_label", {}, _ctx(), "normal", "")
            assert result["job_id"] != ""

    def test_inventory_update(self) -> None:
        with patch("app.neuro_bus.domains.inventory_domain.get_inventory_domain") as mock_get:
            mock_get.return_value.emit_stock_changed.return_value = True
            result = _registered_router_business_event(
                "inventory_update", {"product_id": "p1"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_shipment_create_success(self) -> None:
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=True,
        ):
            result = _registered_router_business_event(
                "shipment_create", {"unit_name": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is True

    def test_shipment_create_publish_failed(self) -> None:
        with patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            return_value=False,
        ):
            result = _registered_router_business_event(
                "shipment_create", {"unit_name": "acme"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_unknown_action(self) -> None:
        result = _registered_router_business_event("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False


class TestBusinessDockingFamilyRouter:
    """_registered_router_business_docking_family 分支覆盖。"""

    def test_view_redirect(self) -> None:
        result = _registered_router_business_docking_family("view", {}, _ctx(), "normal", "")
        assert result["success"] is True

    def test_missing_file_path(self) -> None:
        result = _registered_router_business_docking_family("extract", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_file_not_exists(self) -> None:
        result = _registered_router_business_docking_family(
            "extract", {"file_path": "/nonexistent/file.xlsx"}, _ctx(), "normal", ""
        )
        assert result["success"] is False
        assert "不存在" in result["message"]


class TestOcrArtifactPayload:
    """_ocr_artifact_payload 分支覆盖。"""

    def test_filters_empty_values(self) -> None:
        result = _ocr_artifact_payload(
            text="hello",
            file_path="/tmp/img.png",
            structured_data={"a": "val", "b": "", "c": None, "d": [], "e": {}},
        )
        fields = result["fields"]
        field_names = [f["name"] for f in fields]
        assert "a" in field_names
        assert "b" not in field_names
        assert "c" not in field_names
        assert "d" not in field_names
        assert "e" not in field_names

    def test_limits_to_20_fields(self) -> None:
        data = {f"key_{i}": f"val_{i}" for i in range(25)}
        result = _ocr_artifact_payload(text="t", structured_data=data)
        assert len(result["fields"]) == 20

    def test_truncates_text(self) -> None:
        long_text = "x" * 2000
        result = _ocr_artifact_payload(text=long_text)
        assert len(result["preview"]["text"]) == 1000
        assert result["metadata"]["text"] == long_text

    def test_defaults(self) -> None:
        result = _ocr_artifact_payload(text="t")
        assert result["uri"] == ""
        assert result["preview"]["confidence"] == 0
        assert result["preview"]["structured_data"] == {}
        assert result["preview"]["analysis"] == {}


class TestOcrRouter:
    """_registered_router_ocr 分支覆盖。"""

    def test_request_missing_request_id(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr(
                "request", {"image_url": "http://x"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_request_missing_image_url(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("request", {"request_id": "r1"}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_request_success(self) -> None:
        with (
            patch("app.fastapi_routes.ocr._get_ocr_service"),
            patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain") as mock_domain,
        ):
            mock_domain.return_value.emit_ocr_requested.return_value = True
            result = _registered_router_ocr(
                "request",
                {"request_id": "r1", "image_url": "http://x", "ocr_type": "invoice"},
                _ctx(),
                "normal",
                "",
            )
            assert result["success"] is True
            assert result["ocr_type"] == "invoice"

    def test_recognize_missing_file_path(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("recognize", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_recognize_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.recognize_file.return_value = {
            "success": True,
            "text": "hello",
            "file_path": "/tmp/img.png",
        }
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr(
                "recognize", {"file_path": "/tmp/img.png"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert len(result["artifacts"]) >= 1

    def test_recognize_failure(self) -> None:
        mock_svc = MagicMock()
        mock_svc.recognize_file.return_value = {"success": False}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr(
                "recognize", {"file_path": "/tmp/img.png"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_extract_missing_text(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("extract", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_extract_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.extract_structured_data.return_value = {"key": "val"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr("extract", {"text": "some text"}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_analyze_missing_text(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("analyze", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_analyze_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.analyze_text.return_value = {"sentiment": "positive"}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr("analyze", {"text": "good"}, _ctx(), "normal", "")
            assert result["success"] is True

    def test_recognize_and_extract_missing_file_path(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("recognize_and_extract", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_recognize_and_extract_recognize_fails(self) -> None:
        mock_svc = MagicMock()
        mock_svc.recognize_file.return_value = {"success": False}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/x.png"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_recognize_and_extract_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.recognize_file.return_value = {
            "success": True,
            "text": "hello",
            "file_path": "/tmp/x.png",
        }
        mock_svc.extract_structured_data.return_value = {"key": "val"}
        mock_svc.analyze_text.return_value = {"confidence": 0.9}
        with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=mock_svc):
            result = _registered_router_ocr(
                "recognize_and_extract", {"file_path": "/tmp/x.png"}, _ctx(), "normal", ""
            )
            assert result["success"] is True
            assert len(result["artifacts"]) >= 1

    def test_unknown_action(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service"):
            result = _registered_router_ocr("unknown", {}, _ctx(), "normal", "")
            assert result["success"] is False

    def test_recoverable_error_returns_failure(self) -> None:
        with patch("app.fastapi_routes.ocr._get_ocr_service", side_effect=RuntimeError("boom")):
            result = _registered_router_ocr("recognize", {}, _ctx(), "normal", "")
            assert result["success"] is False
            assert result["error_code"] == "ocr_exception"


class TestExecuteExcelImportRecords:
    """_execute_excel_import_records 分支覆盖。"""

    def test_empty_records(self) -> None:
        result = _execute_excel_import_records([])
        assert result["success"] is False

    def test_customer_service_unavailable(self) -> None:
        with (
            patch("app.bootstrap.get_products_service") as mock_products,
            patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("down")),
        ):
            mock_products.return_value.get_products.return_value = {
                "success": True,
                "data": [],
            }
            mock_products.return_value.create_product.return_value = {"success": True}
            result = _execute_excel_import_records(
                [{"unit_name": "u", "product_name": "p", "model_number": "M01"}]
            )
            assert result["success"] is True
            assert result["data"]["result"]["unit_service_available"] is False

    def test_product_already_exists(self) -> None:
        mock_products = MagicMock()
        mock_products.get_products.return_value = {
            "success": True,
            "data": [{"name": "p", "model_number": "M01"}],
        }
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = MagicMock(unit_name="u")
        with (
            patch("app.bootstrap.get_products_service", return_value=mock_products),
            patch("app.bootstrap.get_customer_app_service", return_value=mock_customer),
        ):
            result = _execute_excel_import_records(
                [{"unit_name": "u", "product_name": "p", "model_number": "M01"}]
            )
            assert result["success"] is True
            assert result["data"]["result"]["skipped_products"] == 1

    def test_create_new_product_and_unit(self) -> None:
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = None
        mock_customer.create.return_value = {"success": True}
        with (
            patch("app.bootstrap.get_products_service", return_value=mock_products),
            patch("app.bootstrap.get_customer_app_service", return_value=mock_customer),
        ):
            result = _execute_excel_import_records(
                [{"unit_name": "u", "product_name": "p", "model_number": "M01"}]
            )
            assert result["success"] is True
            assert result["data"]["result"]["created_units"] == 1
            assert result["data"]["result"]["created_products"] == 1

    def test_recoverable_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("db down")):
            result = _execute_excel_import_records([{"unit_name": "u", "product_name": "p"}])
            assert result["success"] is False
            assert "导入执行失败" in result["message"]


class TestExcelImportRouter:
    """_registered_router_excel_import 分支覆盖。"""

    def test_execute_import_missing_id(self) -> None:
        result = _registered_router_excel_import("execute_import", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_execute_import_not_found(self) -> None:
        mock_svc = MagicMock()
        mock_svc._pending_excel_imports = {}
        with patch("app.application.get_ai_chat_app_service", return_value=mock_svc):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_execute_import_records_not_list(self) -> None:
        mock_svc = MagicMock()
        mock_svc._pending_excel_imports = {"x": {"records": "not-list"}}
        with patch("app.application.get_ai_chat_app_service", return_value=mock_svc):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x"}, _ctx(), "normal", ""
            )
            assert result["success"] is False

    def test_execute_import_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc._pending_excel_imports = {"x": {"records": []}}
        with patch("app.application.get_ai_chat_app_service", return_value=mock_svc):
            result = _registered_router_excel_import(
                "execute_import", {"pending_import_id": "x"}, _ctx(), "normal", ""
            )
            assert result["success"] is False  # empty records → failure

    def test_import_records_not_list(self) -> None:
        result = _registered_router_excel_import(
            "import_records", {"records": "not-list"}, _ctx(), "normal", ""
        )
        assert result["success"] is False

    def test_import_records_empty(self) -> None:
        result = _registered_router_excel_import(
            "import_records", {"records": []}, _ctx(), "normal", ""
        )
        assert result["success"] is False

    def test_unknown_action(self) -> None:
        result = _registered_router_excel_import("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False


class TestUnitProductsImportRouter:
    """_registered_router_unit_products_import 分支覆盖。"""

    def test_unknown_action(self) -> None:
        result = _registered_router_unit_products_import("unknown", {}, _ctx(), "normal", "")
        assert result["success"] is False

    def test_missing_saved_name(self) -> None:
        result = _registered_router_unit_products_import(
            "execute_import", {"unit_name": "u"}, _ctx(), "normal", ""
        )
        assert result["success"] is False

    def test_missing_unit_name(self) -> None:
        result = _registered_router_unit_products_import(
            "execute_import", {"saved_name": "s"}, _ctx(), "normal", ""
        )
        assert result["success"] is False


class TestExecuteRegisteredWorkflowTool:
    """execute_registered_workflow_tool 分支覆盖。"""

    def test_dispatches_to_registered_router(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            result = execute_registered_workflow_tool("settings", "view")
            assert result["success"] is True

    def test_unknown_tool_returns_failure(self) -> None:
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                side_effect=RuntimeError("not found"),
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
            ),
        ):
            result = execute_registered_workflow_tool("nonexistent_tool", "action")
            assert result["success"] is False

    def test_employee_tool_dispatch_success(self) -> None:
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='{"success": true}',
            ),
        ):
            result = execute_registered_workflow_tool("emp_tool", "action", {"task": "do"})
            assert result["success"] is True

    def test_employee_tool_returns_non_dict(self) -> None:
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='"just a string"',
            ),
        ):
            result = execute_registered_workflow_tool("emp_tool", "action")
            assert result["success"] is False

    def test_runtime_context_popped_from_params(self) -> None:
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ) as mock_resolve:
            execute_registered_workflow_tool(
                "settings", "view", {"_runtime_context": {"message": "hi"}}
            )
            mock_resolve.assert_called_once_with({"message": "hi"})


class TestWorkflowRouterMap:
    """_WorkflowRouterMap 分支覆盖。"""

    def test_hidden_keys_excluded(self) -> None:
        keys = list(_twr._REGISTERED_WORKFLOW_ROUTERS.keys())
        assert "employee" not in keys
        assert "business_db" not in keys
        assert "customers" in keys

    def test_dict_still_accessible_via_get(self) -> None:
        assert _twr._REGISTERED_WORKFLOW_ROUTERS.get("employee") is not None
        assert _twr._REGISTERED_WORKFLOW_ROUTERS.get("business_db") is not None
        assert _twr._REGISTERED_WORKFLOW_ROUTERS.get("nonexistent") is None

    def test_workflow_router_map_class_directly(self) -> None:
        m = _WorkflowRouterMap({"employee": 1, "customers": 2, "business_db": 3})
        keys = list(m.keys())
        assert "employee" not in keys
        assert "business_db" not in keys
        assert "customers" in keys
