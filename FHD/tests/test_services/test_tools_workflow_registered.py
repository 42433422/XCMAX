"""Tests for app.services.tools_workflow_registered — registered workflow tool routers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_workflow_registered import (
    _REGISTERED_WORKFLOW_ROUTERS,
    _registered_router_business_docking_family,
    _registered_router_customers,
    _registered_router_materials,
    _registered_router_normal_slot_dispatch,
    _registered_router_print,
    _registered_router_printer_list,
    _registered_router_products,
    _registered_router_settings,
    _registered_router_shipment_records,
    _registered_router_wechat,
    execute_registered_workflow_tool,
)


# ---------------------------------------------------------------------------
# _registered_router_normal_slot_dispatch
# ---------------------------------------------------------------------------


class TestNormalSlotDispatch:
    def test_product_query(self):
        with patch("app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message",
                    return_value={"success": True, "products": []}):
            result = _registered_router_normal_slot_dispatch(
                "product_query", {}, {}, "normal", "hello"
            )
            assert result["success"] is True

    def test_product_query_uses_params_message(self):
        with patch("app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message",
                    return_value={"success": True}) as mock:
            _registered_router_normal_slot_dispatch(
                "product_query", {"message": "from_params"}, {}, "normal", ""
            )
            mock.assert_called_once_with("from_params")

    def test_shipment_preview(self):
        with patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
                    return_value={"success": True, "records": []}):
            result = _registered_router_normal_slot_dispatch(
                "shipment_preview", {"order_text": "order1"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_shipment_preview_uses_user_message(self):
        with patch("app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
                    return_value={"success": True}) as mock:
            _registered_router_normal_slot_dispatch(
                "shipment_preview", {}, {}, "normal", "user order text"
            )
            mock.assert_called_once_with("user order text")

    def test_unknown_action(self):
        result = _registered_router_normal_slot_dispatch("unknown_action", {}, {}, "normal", "")
        assert result["success"] is False
        assert "未注册" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_customers
# ---------------------------------------------------------------------------


class TestCustomersRouter:
    def test_query_action(self):
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": [{"id": 1}]}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("query", {"keyword": "test"}, {}, "normal", "")
            assert result["success"] is True

    def test_ensure_exists_matched(self):
        mock_svc = MagicMock()
        mock_match = MagicMock()
        mock_match.unit_name = "TestCo"
        mock_svc.match_purchase_unit.return_value = mock_match
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("ensure_exists", {"unit_name": "TestCo"}, {}, "normal", "")
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_creates_new(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("ensure_exists", {"unit_name": "NewCo"}, {}, "normal", "")
            assert result["success"] is True
            assert result["created"] is True

    def test_ensure_exists_create_fails_with_duplicate(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "客户已存在"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("ensure_exists", {"unit_name": "DupCo"}, {}, "normal", "")
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_create_fails_other(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "DB error"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("ensure_exists", {"unit_name": "FailCo"}, {}, "normal", "")
            assert result["success"] is False

    def test_ensure_exists_missing_name(self):
        result = _registered_router_customers("ensure_exists", {}, {}, "normal", "")
        assert result["success"] is False

    def test_create_action_success(self):
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("create", {"unit_name": "NewCo"}, {}, "normal", "")
            assert result["success"] is True

    def test_create_action_failure(self):
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": False, "message": "error"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers("create", {"unit_name": "NewCo"}, {}, "normal", "")
            assert result["success"] is False

    def test_create_missing_name(self):
        result = _registered_router_customers("create", {}, {}, "normal", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _registered_router_products
# ---------------------------------------------------------------------------


class TestProductsRouter:
    def test_query_normal_profile(self):
        with patch("app.application.normal_chat_dispatch.run_workflow_products_query_normal_profile",
                    return_value={"success": True, "data": []}):
            result = _registered_router_products("query", {}, {}, "normal", "show products")
            assert result["success"] is True

    def test_query_other_profile(self):
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products("query", {"keyword": "abc"}, {}, "admin", "")
            assert result["success"] is True

    def test_exists_action_match_by_model(self):
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": [{"model_number": "M1", "name": "P1"}]}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products("exists", {"model_number": "M1"}, {}, "admin", "")
            assert result["exists"] is True

    def test_exists_action_match_by_name(self):
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": [{"name": "Widget", "model_number": ""}]}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products("exists", {"product_name": "Widget"}, {}, "admin", "")
            assert result["exists"] is True

    def test_exists_action_no_match(self):
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products("exists", {"model_number": "X99"}, {}, "admin", "")
            assert result["exists"] is False

    def test_create_action_success(self):
        mock_svc = MagicMock()
        mock_svc.create_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "create", {"name_or_model": "P1", "unit_name": "U1", "unit_price": 10.0}, {}, "admin", ""
            )
            assert result["success"] is True

    def test_create_action_missing_fields(self):
        result = _registered_router_products("create", {}, {}, "admin", "")
        assert result["success"] is False

    def test_create_action_invalid_price(self):
        mock_svc = MagicMock()
        mock_svc.create_product.return_value = {"success": True}
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "create", {"name_or_model": "P1", "unit_name": "U1", "unit_price": "not_a_number"}, {}, "admin", ""
            )
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_materials
# ---------------------------------------------------------------------------


class TestMaterialsRouter:
    def test_list_action(self):
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("list", {"search": "steel"}, {}, "admin", "")
            assert result["success"] is True

    def test_query_alias(self):
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("query", {}, {}, "admin", "")
            assert result["success"] is True

    def test_create_action(self):
        mock_svc = MagicMock()
        mock_svc.create_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("create", {"name": "Steel"}, {}, "admin", "")
            assert result["success"] is True

    def test_update_action(self):
        mock_svc = MagicMock()
        mock_svc.update_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("update", {"id": 1, "name": "Updated"}, {}, "admin", "")
            assert result["success"] is True

    def test_delete_action(self):
        mock_svc = MagicMock()
        mock_svc.delete_material.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("delete", {"id": 1}, {}, "admin", "")
            assert result["success"] is True

    def test_batch_delete_action(self):
        mock_svc = MagicMock()
        mock_svc.batch_delete_materials.return_value = {"success": True}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("batch_delete", {"ids": [1, 2, 3]}, {}, "admin", "")
            assert result["success"] is True

    def test_export_action(self):
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True, "file_path": "/tmp/out.xlsx"}
        with patch("app.application.get_material_application_service", return_value=mock_svc):
            result = _registered_router_materials("export", {"search": "steel"}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_shipment_records
# ---------------------------------------------------------------------------


class TestShipmentRecordsRouter:
    def test_list_action(self):
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records("list", {"unit": "TestCo"}, {}, "admin", "")
            assert result["success"] is True

    def test_update_action(self):
        mock_svc = MagicMock()
        mock_svc.update_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records("update", {"id": 1, "status": "shipped"}, {}, "admin", "")
            assert result["success"] is True

    def test_delete_action(self):
        mock_svc = MagicMock()
        mock_svc.delete_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records("delete", {"id": 1}, {}, "admin", "")
            assert result["success"] is True

    def test_export_action(self):
        mock_svc = MagicMock()
        mock_svc.export_shipment_records.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records("export", {"unit": "TestCo"}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_wechat
# ---------------------------------------------------------------------------


class TestWechatRouter:
    def test_view_action(self):
        result = _registered_router_wechat("view", {}, {}, "admin", "")
        assert result["success"] is True
        assert "redirect" in result

    def test_list_action(self):
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
            result = _registered_router_wechat("list", {"type": "all"}, {}, "admin", "")
            assert result["success"] is True

    def test_refresh_cache_action(self):
        mock_module = MagicMock()
        mock_module.ensure_decrypted_wechat_dbs.return_value = {"success": True}
        with patch.dict("sys.modules", {"app.services.wechat_contact_cache_import": mock_module}):
            result = _registered_router_wechat("refresh_contact_cache", {}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_print
# ---------------------------------------------------------------------------


class TestPrintRouter:
    def test_view_action(self):
        result = _registered_router_print("view", {}, {}, "admin", "")
        assert result["success"] is True

    def test_list_action(self):
        mock_svc = MagicMock()
        mock_svc.get_printers.return_value = {"success": True, "printers": []}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print("list", {}, {}, "admin", "")
            assert result["success"] is True

    def test_print_label_action(self):
        mock_svc = MagicMock()
        mock_svc.print_label.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print("print_label", {"file_path": "/tmp/label.pdf", "copies": 2}, {}, "admin", "")
            assert result["success"] is True

    def test_print_document_action(self):
        mock_svc = MagicMock()
        mock_svc.print_document.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print("print_document", {"file_path": "/tmp/doc.pdf"}, {}, "admin", "")
            assert result["success"] is True

    def test_test_action(self):
        mock_svc = MagicMock()
        mock_svc.test_printer.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print("test", {"printer_name": "HP"}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_printer_list
# ---------------------------------------------------------------------------


class TestPrinterListRouter:
    def test_view_action(self):
        result = _registered_router_printer_list("view", {}, {}, "admin", "")
        assert result["success"] is True

    def test_list_action(self):
        mock_svc = MagicMock()
        mock_svc.get_printer_config.return_value = {"printers": []}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_printer_list("list", {}, {}, "admin", "")
            assert result == {"printers": []}

    def test_set_default_action(self):
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_printer_list("set_default", {"printer_name": "HP"}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_settings
# ---------------------------------------------------------------------------


class TestSettingsRouter:
    def test_view_action(self):
        result = _registered_router_settings("view", {}, {}, "admin", "")
        assert result["success"] is True

    def test_query_action(self):
        mock_svc = MagicMock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("query", {}, {}, "admin", "")
            assert result["success"] is True

    def test_get_system_info_action(self):
        mock_svc = MagicMock()
        mock_svc.get_system_info.return_value = {"version": "1.0"}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("get_system_info", {}, {}, "admin", "")
            assert result["success"] is True

    def test_get_startup_config_action(self):
        mock_svc = MagicMock()
        mock_svc.get_startup_config.return_value = {"auto_start": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("get_startup_config", {}, {}, "admin", "")
            assert result["success"] is True

    def test_enable_startup_action(self):
        mock_svc = MagicMock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("enable_startup", {}, {}, "admin", "")
            assert result["success"] is True

    def test_disable_startup_action(self):
        mock_svc = MagicMock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch("app.services.get_system_service", return_value=mock_svc):
            result = _registered_router_settings("disable_startup", {}, {}, "admin", "")
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _registered_router_business_docking_family
# ---------------------------------------------------------------------------


class TestBusinessDockingRouter:
    def test_view_action(self):
        result = _registered_router_business_docking_family("view", {}, {}, "admin", "")
        assert result["success"] is True
        assert "redirect" in result

    def test_missing_file_path(self):
        result = _registered_router_business_docking_family("preview", {}, {}, "admin", "")
        assert result["success"] is False

    def test_file_not_found(self):
        with patch("os.path.exists", return_value=False):
            result = _registered_router_business_docking_family("preview", {"file_path": "/nonexistent.xlsx"}, {}, "admin", "")
            assert result["success"] is False
            assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# execute_registered_workflow_tool
# ---------------------------------------------------------------------------


class TestExecuteRegisteredWorkflowTool:
    def test_known_tool(self):
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            result = execute_registered_workflow_tool("customers", "query", {"keyword": "test"})
            assert isinstance(result, dict)

    def test_unknown_tool(self):
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            result = execute_registered_workflow_tool("nonexistent_tool", "query", {})
            assert result["success"] is False
            assert "未注册" in result["message"]

    def test_runtime_context_extracted(self):
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal") as mock_profile:
            execute_registered_workflow_tool("customers", "query", {"keyword": "test", "_runtime_context": {"message": "hello"}})
            mock_profile.assert_called_once()

    def test_registered_routers_dict_completeness(self):
        expected_keys = {
            "normal_slot_dispatch", "customers", "products", "materials",
            "shipment_records", "business_docking", "template_extract",
            "template_preview", "wechat", "print", "printer_list",
            "settings", "excel_analysis", "excel_import",
        }
        assert set(_REGISTERED_WORKFLOW_ROUTERS.keys()) == expected_keys
