"""Tests for app.services.tools_workflow_registered — registered workflow tool routers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.tools_workflow_registered import (
    _REGISTERED_WORKFLOW_ROUTERS,
    _registered_router_business_docking_family,
    _registered_router_customers,
    _registered_router_finance,
    _registered_router_generate_office_document,
    _registered_router_inventory,
    _registered_router_materials,
    _registered_router_mrp,
    _registered_router_normal_slot_dispatch,
    _registered_router_print,
    _registered_router_printer_list,
    _registered_router_products,
    _registered_router_purchase,
    _registered_router_reports,
    _registered_router_sales,
    _registered_router_settings,
    _registered_router_shipment_records,
    _registered_router_suppliers,
    execute_registered_workflow_tool,
)

# ---------------------------------------------------------------------------
# _registered_router_normal_slot_dispatch
# ---------------------------------------------------------------------------


class TestNormalSlotDispatch:
    def test_product_query(self):
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message",
            return_value={"success": True, "products": []},
        ):
            result = _registered_router_normal_slot_dispatch(
                "product_query", {}, {}, "normal", "hello"
            )
            assert result["success"] is True

    def test_product_query_uses_params_message(self):
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_product_query_from_message",
            return_value={"success": True},
        ) as mock:
            _registered_router_normal_slot_dispatch(
                "product_query", {"message": "from_params"}, {}, "normal", ""
            )
            mock.assert_called_once_with("from_params")

    def test_shipment_preview(self):
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
            return_value={"success": True, "records": []},
        ):
            result = _registered_router_normal_slot_dispatch(
                "shipment_preview", {"order_text": "order1"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_shipment_preview_uses_user_message(self):
        with patch(
            "app.application.normal_chat_dispatch.run_normal_slot_shipment_preview",
            return_value={"success": True},
        ) as mock:
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
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "TestCo"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_creates_new(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "NewCo"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["created"] is True

    def test_ensure_exists_create_fails_with_duplicate(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "客户已存在"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "DupCo"}, {}, "normal", ""
            )
            assert result["success"] is True
            assert result["exists"] is True

    def test_ensure_exists_create_fails_other(self):
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "DB error"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "ensure_exists", {"unit_name": "FailCo"}, {}, "normal", ""
            )
            assert result["success"] is False

    def test_ensure_exists_missing_name(self):
        result = _registered_router_customers("ensure_exists", {}, {}, "normal", "")
        assert result["success"] is False

    def test_create_action_success(self):
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": True, "data": {"id": 1}}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "create", {"unit_name": "NewCo"}, {}, "normal", ""
            )
            assert result["success"] is True

    def test_create_action_failure(self):
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": False, "message": "error"}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            result = _registered_router_customers(
                "create", {"unit_name": "NewCo"}, {}, "normal", ""
            )
            assert result["success"] is False

    def test_create_missing_name(self):
        result = _registered_router_customers("create", {}, {}, "normal", "")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _registered_router_products
# ---------------------------------------------------------------------------


class TestProductsRouter:
    def test_query_normal_profile(self):
        with patch(
            "app.application.normal_chat_dispatch.run_workflow_products_query_normal_profile",
            return_value={"success": True, "data": []},
        ):
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
        mock_svc.get_products.return_value = {
            "success": True,
            "data": [{"model_number": "M1", "name": "P1"}],
        }
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products("exists", {"model_number": "M1"}, {}, "admin", "")
            assert result["exists"] is True

    def test_exists_action_match_by_name(self):
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {
            "success": True,
            "data": [{"name": "Widget", "model_number": ""}],
        }
        with patch("app.services.get_products_service", return_value=mock_svc):
            result = _registered_router_products(
                "exists", {"product_name": "Widget"}, {}, "admin", ""
            )
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
                "create",
                {"name_or_model": "P1", "unit_name": "U1", "unit_price": 10.0},
                {},
                "admin",
                "",
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
                "create",
                {"name_or_model": "P1", "unit_name": "U1", "unit_price": "not_a_number"},
                {},
                "admin",
                "",
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
            result = _registered_router_materials(
                "update", {"id": 1, "name": "Updated"}, {}, "admin", ""
            )
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
            result = _registered_router_materials(
                "batch_delete", {"ids": [1, 2, 3]}, {}, "admin", ""
            )
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
            result = _registered_router_shipment_records(
                "list", {"unit": "TestCo"}, {}, "admin", ""
            )
            assert result["success"] is True

    def test_update_action(self):
        mock_svc = MagicMock()
        mock_svc.update_shipment_record.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _registered_router_shipment_records(
                "update", {"id": 1, "status": "shipped"}, {}, "admin", ""
            )
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
            result = _registered_router_shipment_records(
                "export", {"unit": "TestCo"}, {}, "admin", ""
            )
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
            result = _registered_router_print(
                "print_label", {"file_path": "/tmp/label.pdf", "copies": 2}, {}, "admin", ""
            )
            assert result["success"] is True

    def test_print_document_action(self):
        mock_svc = MagicMock()
        mock_svc.print_document.return_value = {"success": True}
        with patch("app.services.get_printer_service", return_value=mock_svc):
            result = _registered_router_print(
                "print_document", {"file_path": "/tmp/doc.pdf"}, {}, "admin", ""
            )
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
            result = _registered_router_printer_list(
                "set_default", {"printer_name": "HP"}, {}, "admin", ""
            )
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
            result = _registered_router_business_docking_family(
                "preview", {"file_path": "/nonexistent.xlsx"}, {}, "admin", ""
            )
            assert result["success"] is False
            assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# _registered_router_generate_office_document
# ---------------------------------------------------------------------------


class TestGenerateOfficeDocumentRouter:
    def test_execute_uses_existing_workflow_tool(self):
        with patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value='{"success": true, "file_name": "out.docx", "artifacts": [{"artifact_type": "office_document"}]}',
        ):
            result = _registered_router_generate_office_document(
                "execute",
                {"output_format": "docx"},
                {},
                "normal",
                "生成合同",
            )

        assert result["success"] is True
        assert result["file_name"] == "out.docx"
        assert result["artifacts"][0]["artifact_type"] == "office_document"

    def test_unknown_action(self):
        result = _registered_router_generate_office_document("view", {}, {}, "normal", "")
        assert result["success"] is False
        assert "未知" in result["message"]


# ---------------------------------------------------------------------------
# execute_registered_workflow_tool
# ---------------------------------------------------------------------------


class TestExecuteRegisteredWorkflowTool:
    def test_known_tool(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            result = execute_registered_workflow_tool("customers", "query", {"keyword": "test"})
            assert isinstance(result, dict)

    def test_unknown_tool(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            result = execute_registered_workflow_tool("nonexistent_tool", "query", {})
            assert result["success"] is False
            assert "未注册" in result["message"]

    def test_runtime_context_extracted(self):
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ) as mock_profile:
            execute_registered_workflow_tool(
                "customers", "query", {"keyword": "test", "_runtime_context": {"message": "hello"}}
            )
            mock_profile.assert_called_once()

    def test_registered_routers_dict_completeness(self):
        expected_keys = {
            "normal_slot_dispatch",
            "customers",
            "products",
            "materials",
            "shipment_records",
            "shipment_orders",
            "business_docking",
            "business_event",
            "template_extract",
            "template_preview",
            "document_template",
            "label_template_generator",
            "print",
            "printer_list",
            "settings",
            "excel_analysis",
            "excel_analyzer",
            "excel_toolkit",
            "excel_import",
            "excel_vector_index",
            "generate_office_document",
            "unit_products_import",
            "inventory",
            "purchase",
            "sales",
            "reports",
            "finance",
            "mrp",
            "suppliers",
            "ocr",
            "dataset_rag",
            "memory_v2",
            "system_maintenance",
        }
        assert set(_REGISTERED_WORKFLOW_ROUTERS.keys()) == expected_keys


# ---------------------------------------------------------------------------
# ERP 工具注册表扩容（Task 5，吸收 Odoo 18）
# ---------------------------------------------------------------------------


def _workflow_registry():
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    return get_workflow_tools_from_registry()


class TestErpToolRegistry:
    """config/risk_actions.registry.json 中新增 ERP 工具与必填参数。"""

    def test_sales_tool_registered(self):
        reg = _workflow_registry()
        assert "sales" in reg
        actions = set(reg["sales"]["actions"])
        assert {"quote", "confirm", "deliver", "invoice", "payment", "cancel", "query"} <= actions

    def test_sales_actions_risk_and_idempotency(self):
        reg = _workflow_registry()
        sales = reg["sales"]["actions"]
        assert sales["query"]["risk"] == "low" and sales["query"]["idempotent"] is True
        assert sales["quote"]["risk"] == "medium" and sales["quote"]["idempotent"] is False
        for a in ("confirm", "deliver", "invoice", "payment", "cancel"):
            assert sales[a]["idempotent"] is False

    def test_sales_required_params(self):
        reg = _workflow_registry()
        sales = reg["sales"]["actions"]
        assert set(sales["quote"]["required_params"]) == {"customer_id", "items"}
        assert set(sales["payment"]["required_params"]) == {"order_id", "amount"}
        assert sales["confirm"]["required_params"] == ["order_id"]

    def test_reports_tool_registered(self):
        reg = _workflow_registry()
        assert "reports" in reg
        actions = set(reg["reports"]["actions"])
        assert {
            "sales_summary",
            "inventory_summary",
            "purchase_summary",
            "dashboard",
            "export",
        } <= actions
        # 报表动作均为只读低风险幂等
        for action in reg["reports"]["actions"].values():
            assert action["risk"] == "low" and action["idempotent"] is True

    def test_inventory_extended_with_alerts(self):
        reg = _workflow_registry()
        inventory = reg["inventory"]["actions"]
        assert "low_stock_alert" in inventory and "replenishment_suggest" in inventory
        assert inventory["low_stock_alert"]["risk"] == "low"
        assert inventory["replenishment_suggest"]["idempotent"] is True

    def test_finance_extended_with_ledger(self):
        reg = _workflow_registry()
        finance = reg["finance"]["actions"]
        assert "ledger_query" in finance and "journal_entry_create" in finance
        assert (
            finance["ledger_query"]["risk"] == "low"
            and finance["ledger_query"]["idempotent"] is True
        )
        assert finance["journal_entry_create"]["risk"] == "high"
        assert set(finance["journal_entry_create"]["required_params"]) == {"lines"}


class TestErpCapabilityGate:
    """resolve_registered_capability_call 对新增 ERP 工具的校验。"""

    def test_sales_quote_valid(self):
        from app.application.tools.registered_capabilities import (
            resolve_registered_capability_call,
        )

        r = resolve_registered_capability_call(
            {
                "tool_id": "sales",
                "action": "quote",
                "params": {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}]},
            }
        )
        assert r["success"] is True
        assert r["risk"] == "medium"
        assert r["idempotent"] is False

    def test_sales_payment_missing_amount(self):
        from app.application.tools.registered_capabilities import (
            resolve_registered_capability_call,
        )

        r = resolve_registered_capability_call(
            {"tool_id": "sales", "action": "payment", "params": {"order_id": 1}}
        )
        assert r["success"] is False
        assert set(r.get("required_params") or []) == {"order_id", "amount"}

    def test_journal_entry_create_rejects_unbalanced_via_required(self):
        from app.application.tools.registered_capabilities import (
            resolve_registered_capability_call,
        )

        r = resolve_registered_capability_call(
            {"tool_id": "finance", "action": "journal_entry_create", "params": {}}
        )
        assert r["success"] is False


class TestErpRouterDispatch:
    """新 ERP 工具路由分发到对应服务。"""

    def test_sales_router_quotes_via_service(self):
        from app.application.sales_app_service import SalesAppService

        with patch.object(SalesAppService, "quote", return_value={"success": True}) as mock:
            r = _registered_router_sales(
                "quote",
                {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1, "unit_price": 1}]},
                {},
                "shared",
                "",
            )
            assert r["success"] is True
            mock.assert_called_once()

    def test_sales_router_unknown_action(self):
        r = _registered_router_sales("hack", {}, {}, "shared", "")
        assert r["success"] is False

    def test_reports_router_sales_summary(self):
        from app.services.report_service import ReportService

        with patch.object(ReportService, "get_sales_report", return_value={"success": True}) as m:
            r = _registered_router_reports("sales_summary", {}, {}, "shared", "")
            assert r["success"] is True
            m.assert_called_once()

    def test_finance_router_ledger_query(self):
        from app.services import accounting_services

        with patch.object(
            accounting_services, "query_financial_ledger", return_value={"success": True}
        ) as m:
            r = _registered_router_finance("ledger_query", {}, {}, "shared", "")
            assert r["success"] is True
            m.assert_called_once()

    def test_inventory_router_low_stock(self):
        with patch(
            "app.application.material_app_service.get_material_app_service",
            return_value=MagicMock(
                get_low_stock_materials=MagicMock(return_value={"success": True})
            ),
        ):
            r = _registered_router_inventory("low_stock_alert", {}, {}, "shared", "")
            assert r["success"] is True


# ---------------------------------------------------------------------------
# Task 6 新动作路由：mrp / suppliers / inventory_count / customers / finance / purchase
# ---------------------------------------------------------------------------


class TestMrpRouter:
    """_registered_router_mrp：建 BOM → 工单 → 领料 → 完工全链路路由。"""

    def test_create_bom(self):
        mock_svc = MagicMock()
        mock_svc.create_bom.return_value = {"success": True, "data": {"id": 1}}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp(
                "create_bom", {"product_id": 1, "lines": []}, {}, "shared", ""
            )
        assert r["success"] is True
        mock_svc.create_bom.assert_called_once()

    def test_query_boms(self):
        mock_svc = MagicMock()
        mock_svc.query_boms.return_value = {"success": True, "data": [], "total": 0}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp("query_boms", {}, {}, "shared", "")
        assert r["success"] is True

    def test_get_bom(self):
        mock_svc = MagicMock()
        mock_svc.get_bom.return_value = {"success": True, "data": {"id": 9}}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp("get_bom", {"bom_id": 9}, {}, "shared", "")
        assert r["success"] is True

    def test_get_bom_missing_id(self):
        r = _registered_router_mrp("get_bom", {}, {}, "shared", "")
        assert r["success"] is False

    def test_create_order(self):
        mock_svc = MagicMock()
        mock_svc.create_order.return_value = {"success": True, "data": {"id": 1}}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp(
                "create_order", {"bom_id": 1, "quantity": 2}, {}, "shared", ""
            )
        assert r["success"] is True

    def test_confirm_order(self):
        mock_svc = MagicMock()
        mock_svc.confirm_order.return_value = {"success": True}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp("confirm_order", {"order_id": 1}, {}, "shared", "")
        assert r["success"] is True

    def test_consume(self):
        mock_svc = MagicMock()
        mock_svc.consume.return_value = {"success": True}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp(
                "consume", {"order_id": 1, "warehouse_id": 2}, {}, "shared", ""
            )
        assert r["success"] is True
        mock_svc.consume.assert_called_once_with(order_id=1, warehouse_id=2, operator=None)

    def test_finish(self):
        mock_svc = MagicMock()
        mock_svc.finish.return_value = {"success": True}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp(
                "finish", {"order_id": 1, "warehouse_id": 2}, {}, "shared", ""
            )
        assert r["success"] is True

    def test_query_orders(self):
        mock_svc = MagicMock()
        mock_svc.query_orders.return_value = {"success": True, "data": [], "total": 0}
        with patch(
            "app.services.manufacturing_service.ManufacturingService", return_value=mock_svc
        ):
            r = _registered_router_mrp("query_orders", {}, {}, "shared", "")
        assert r["success"] is True

    def test_unknown_action(self):
        r = _registered_router_mrp("hack", {}, {}, "shared", "")
        assert r["success"] is False


class TestSuppliersRouter:
    """_registered_router_suppliers：供应商查询。"""

    def test_query_suppliers(self):
        mock_svc = MagicMock()
        mock_svc.get_suppliers.return_value = {"success": True, "data": []}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=mock_svc
        ):
            r = _registered_router_suppliers("query_suppliers", {}, {}, "shared", "")
        assert r["success"] is True

    def test_get_supplier(self):
        mock_svc = MagicMock()
        mock_svc.get_supplier.return_value = {"success": True, "data": {"id": 1}}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=mock_svc
        ):
            r = _registered_router_suppliers("get_supplier", {"supplier_id": 1}, {}, "shared", "")
        assert r["success"] is True

    def test_get_supplier_missing_id(self):
        r = _registered_router_suppliers("get_supplier", {}, {}, "shared", "")
        assert r["success"] is False


class TestInventoryCountAndTransactionsRouter:
    """inventory_count / query_transactions 走 InventoryService。"""

    def test_inventory_count(self):
        mock_inv = MagicMock()
        mock_inv.inventory_count.return_value = {
            "success": True,
            "difference": 2,
            "confirmed": False,
        }
        with patch("app.services.inventory_service.InventoryService", return_value=mock_inv):
            r = _registered_router_inventory(
                "inventory_count",
                {"product_id": 1, "warehouse_id": 1, "actual_quantity": 10},
                {},
                "shared",
                "",
            )
        assert r["success"] is True
        mock_inv.inventory_count.assert_called_once()

    def test_query_transactions(self):
        mock_inv = MagicMock()
        mock_inv.query_transactions.return_value = {"success": True, "data": []}
        with patch("app.services.inventory_service.InventoryService", return_value=mock_inv):
            r = _registered_router_inventory(
                "query_transactions", {"warehouse_id": 1}, {}, "shared", ""
            )
        assert r["success"] is True


class TestCustomersCreditAndAddressRouter:
    """customers add_address / set_credit_limit / get_addresses。"""

    def test_add_address(self):
        mock_svc = MagicMock()
        mock_svc.add_address.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            r = _registered_router_customers(
                "add_address",
                {"customer_id": 1, "address_type": "送货", "address": "xx"},
                {},
                "shared",
                "",
            )
        assert r["success"] is True

    def test_set_credit_limit(self):
        mock_svc = MagicMock()
        mock_svc.set_credit_limit.return_value = {"success": True}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            r = _registered_router_customers(
                "set_credit_limit", {"customer_id": 1, "credit_limit": 5000}, {}, "shared", ""
            )
        assert r["success"] is True

    def test_set_credit_limit_missing_id(self):
        r = _registered_router_customers("set_credit_limit", {}, {}, "shared", "")
        assert r["success"] is False

    def test_get_addresses(self):
        mock_svc = MagicMock()
        mock_svc.get_addresses.return_value = {"success": True, "data": []}
        with patch("app.application.get_customer_app_service", return_value=mock_svc):
            r = _registered_router_customers("get_addresses", {"customer_id": 1}, {}, "shared", "")
        assert r["success"] is True


class TestFinanceNewActionsRouter:
    """finance journal_entry_reverse / aging_report / chart_seed。"""

    def test_journal_entry_reverse(self):
        from app.services import accounting_services

        with patch.object(
            accounting_services, "journal_entry_reverse", return_value={"success": True}
        ) as m:
            r = _registered_router_finance(
                "journal_entry_reverse", {"entry_id": 1}, {}, "shared", ""
            )
        assert r["success"] is True
        m.assert_called_once()

    def test_journal_entry_reverse_missing_id(self):
        r = _registered_router_finance("journal_entry_reverse", {}, {}, "shared", "")
        assert r["success"] is False

    def test_aging_report(self):
        from app.services import accounting_services

        with patch.object(accounting_services, "aging_report", return_value={"success": True}) as m:
            r = _registered_router_finance(
                "aging_report", {"account_type": "应收", "party_id": 1}, {}, "shared", ""
            )
        assert r["success"] is True
        m.assert_called_once()

    def test_chart_seed(self):
        from app.services import accounting_services

        with patch.object(
            accounting_services, "seed_default_chart_of_accounts", return_value={"success": True}
        ) as m:
            r = _registered_router_finance("chart_seed", {}, {}, "shared", "")
        assert r["success"] is True
        m.assert_called_once()


class TestPurchaseReadOnlyRouter:
    """purchase query_suppliers / query_orders / query_inbounds 只读动作。"""

    def test_query_suppliers(self):
        mock_svc = MagicMock()
        mock_svc.get_suppliers.return_value = {"success": True, "data": []}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=mock_svc
        ):
            r = _registered_router_purchase("query_suppliers", {}, {}, "shared", "")
        assert r["success"] is True

    def test_query_orders(self):
        mock_svc = MagicMock()
        mock_svc.get_purchase_orders.return_value = {"success": True, "data": []}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=mock_svc
        ):
            r = _registered_router_purchase("query_orders", {}, {}, "shared", "")
        assert r["success"] is True

    def test_query_inbounds(self):
        mock_svc = MagicMock()
        mock_svc.get_purchase_inbounds.return_value = {"success": True, "data": []}
        with patch(
            "app.application.facades.inventory_facade.PurchaseService", return_value=mock_svc
        ):
            r = _registered_router_purchase("query_inbounds", {}, {}, "shared", "")
        assert r["success"] is True
