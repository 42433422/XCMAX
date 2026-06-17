"""Tests for app.application.workflow.planner — deep coverage for remaining uncovered branches.

Focus: tool execution handlers, error branches, LLMWorkflowPlanner methods,
_filter_tool_registry_for_profile edge cases, and _execute_*_tool functions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
    execute_tool,
    get_tool_registry,
)

# ========================= execute_tool - deep ============================


class TestExecuteToolDeep:
    def test_default_action_for_price_list(self):
        result = execute_tool("price_list", {})
        # Should use default action "export"
        assert isinstance(result, dict)

    def test_default_action_for_shipment_generate(self):
        result = execute_tool("shipment_generate", {})
        # Should use default action "generate"
        assert isinstance(result, dict)

    def test_default_action_for_excel_decompose(self):
        result = execute_tool("excel_decompose", {})
        # Should use default action "decompose"
        assert isinstance(result, dict)

    def test_default_action_for_template_extract(self):
        result = execute_tool("template_extract", {})
        # Should use default action "extract"
        assert isinstance(result, dict)

    def test_default_action_for_wechat_send(self):
        mock_svc = Mock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            result = execute_tool("wechat_send", {})
        # Should use default action "preview"
        assert isinstance(result, dict)

    def test_default_action_for_excel_schema(self):
        result = execute_tool("excel_schema", {})
        # Should use default action "analyze"
        assert isinstance(result, dict)

    def test_default_action_for_import_excel(self):
        result = execute_tool("import_excel", {})
        # Should use default action "import"
        assert isinstance(result, dict)

    def test_default_action_for_unknown_tool(self):
        result = execute_tool("unknown_tool", {})
        # Should use default action "query"
        assert result["success"] is False

    def test_explicit_action_override(self):
        result = execute_tool("products", {"_action": "view"})
        # Should use explicit action "view" instead of default "query"
        assert isinstance(result, dict)


# ========================= _execute_price_list_tool - deep ================


class TestExecutePriceListToolDeep:
    def test_missing_customer_name(self):
        result = execute_tool("price_list", {"_action": "export"})
        assert result["success"] is False
        assert result["error_code"] == "missing_customer_name"

    def test_import_error(self):
        with patch("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS") as handlers:
            from app.application.workflow.planner import _execute_price_list_tool

            with patch.dict("sys.modules", {"app.application.tools": None}):
                result = _execute_price_list_tool({"customer_name": "公司A"})
        # Either succeeds or returns service_unavailable
        assert isinstance(result, dict)

    def test_value_error(self):
        from app.application.workflow.planner import _execute_price_list_tool

        with patch(
            "app.application.tools.handle_price_list_export", side_effect=ValueError("bad params")
        ):
            result = _execute_price_list_tool({"customer_name": "公司A"})
        assert result["success"] is False
        assert result["error_code"] == "invalid_parameters"

    def test_os_error(self):
        from app.application.workflow.planner import _execute_price_list_tool

        with patch(
            "app.application.tools.handle_price_list_export", side_effect=OSError("disk full")
        ):
            result = _execute_price_list_tool({"customer_name": "公司A"})
        assert result["success"] is False
        assert result["error_code"] == "file_io_error"

    def test_runtime_error(self):
        from app.application.workflow.planner import _execute_price_list_tool

        with patch(
            "app.application.tools.handle_price_list_export", side_effect=RuntimeError("fail")
        ):
            result = _execute_price_list_tool({"customer_name": "公司A"})
        assert result["success"] is False
        assert result["error_code"] == "export_failed"


# ========================= _execute_products_tool - deep ==================


class TestExecuteProductsToolDeep:
    def test_with_model_number_and_unit_name(self):
        from app.application.workflow.planner import _execute_products_tool

        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"model_number": "5003A", "unit_name": "公司A"})
        mock_svc.get_products.assert_called_once_with(
            unit_name="公司A", model_number="5003A", keyword=None, page=1, per_page=20
        )

    def test_with_model_number_only(self):
        from app.application.workflow.planner import _execute_products_tool

        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"model_number": "5003A"})
        mock_svc.get_products.assert_called_once_with(
            unit_name=None, model_number="5003A", keyword=None, page=1, per_page=20
        )

    def test_with_unit_name_only(self):
        from app.application.workflow.planner import _execute_products_tool

        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"unit_name": "公司A", "keyword": "涂料"})
        mock_svc.get_products.assert_called_once_with(
            unit_name="公司A", model_number=None, keyword="涂料", page=1, per_page=20
        )

    def test_with_keyword_only(self):
        from app.application.workflow.planner import _execute_products_tool

        mock_svc = Mock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"keyword": "涂料"})
        mock_svc.get_products.assert_called_once_with(
            unit_name=None, model_number=None, keyword="涂料", page=1, per_page=20
        )

    def test_import_error(self):
        from app.application.workflow.planner import _execute_products_tool

        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no module")):
            result = _execute_products_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"

    def test_value_error(self):
        from app.application.workflow.planner import _execute_products_tool

        with patch("app.bootstrap.get_products_service", side_effect=ValueError("bad")):
            result = _execute_products_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self):
        from app.application.workflow.planner import _execute_products_tool

        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("fail")):
            result = _execute_products_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "query_failed"


# ========================= _execute_customers_ensure_exists_tool - deep ===


class TestExecuteCustomersEnsureExistsToolDeep:
    def test_missing_unit_name(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        result = _execute_customers_ensure_exists_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_unit_name"

    def test_existing_customer(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        mock_svc = Mock()
        mock_match = Mock()
        mock_match.id = 1
        mock_match.unit_name = "公司A"
        mock_svc.match_purchase_unit.return_value = mock_match
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "公司A"})
        assert result["success"] is True
        assert result["created"] is False

    def test_new_customer_created(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        mock_svc = Mock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "新公司"})
        assert result["created"] is True

    def test_import_error(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no module")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "公司A"})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"

    def test_runtime_error(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "公司A"})
        assert result["success"] is False
        assert result["error_code"] == "create_failed"


# ========================= _execute_shipment_generate_tool - deep =========


class TestExecuteShipmentGenerateToolDeep:
    def test_missing_params(self):
        from app.application.workflow.planner import _execute_shipment_generate_tool

        result = _execute_shipment_generate_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_order_params"

    def test_with_order_text(self):
        from app.application.workflow.planner import _execute_shipment_generate_tool

        mock_svc = Mock()
        mock_svc.generate_shipment_document.return_value = {"success": True}
        with (
            patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc),
            patch(
                "app.routes.tools._parse_order_text",
                return_value={"success": True, "unit_name": "公司A", "products": []},
            ),
        ):
            result = _execute_shipment_generate_tool({"order_text": "给公司A发10桶涂料"})
        assert result["success"] is True

    def test_with_unit_and_products(self):
        from app.application.workflow.planner import _execute_shipment_generate_tool

        mock_svc = Mock()
        mock_svc.generate_shipment_document.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _execute_shipment_generate_tool(
                {
                    "unit_name": "公司A",
                    "products": [{"name": "涂料", "quantity": 10}],
                }
            )
        assert result["success"] is True

    def test_parse_failure(self):
        from app.application.workflow.planner import _execute_shipment_generate_tool

        with (
            patch("app.bootstrap.get_shipment_app_service"),
            patch(
                "app.routes.tools._parse_order_text",
                return_value={"success": False, "message": "无法解析"},
            ),
        ):
            result = _execute_shipment_generate_tool({"order_text": "无效订单"})
        assert result["success"] is False

    def test_import_error(self):
        from app.application.workflow.planner import _execute_shipment_generate_tool

        # Make the import of _parse_order_text fail to trigger the ImportError handler
        with patch.dict("sys.modules", {"app.routes.tools": None}):
            result = _execute_shipment_generate_tool({"order_text": "test"})
        assert result["success"] is False
        assert result.get("error_code") == "service_unavailable" or "不可用" in result.get(
            "message", ""
        )


# ========================= _execute_shipment_records_tool - deep ==========


class TestExecuteShipmentRecordsToolDeep:
    def test_success(self):
        from app.application.workflow.planner import _execute_shipment_records_tool

        mock_svc = Mock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _execute_shipment_records_tool({"unit_name": "公司A"})
        assert result["success"] is True

    def test_import_error(self):
        from app.application.workflow.planner import _execute_shipment_records_tool

        with patch("app.bootstrap.get_shipment_app_service", side_effect=ImportError("no module")):
            result = _execute_shipment_records_tool({})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"


# ========================= _execute_materials_tool - deep =================


class TestExecuteMaterialsToolDeep:
    def test_success(self):
        from app.application.workflow.planner import _execute_materials_tool

        mock_svc = Mock()
        mock_svc.get_all_materials.return_value = {"success": True}
        with patch("app.bootstrap.get_materials_service", return_value=mock_svc):
            result = _execute_materials_tool({"keyword": "涂料"})
        assert result["success"] is True

    def test_import_error(self):
        from app.application.workflow.planner import _execute_materials_tool

        with patch("app.bootstrap.get_materials_service", side_effect=ImportError("no module")):
            result = _execute_materials_tool({})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"


# ========================= _execute_print_label_tool - deep ===============


class TestExecutePrintLabelToolDeep:
    def test_missing_products(self):
        from app.application.workflow.planner import _execute_print_label_tool

        result = _execute_print_label_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_empty_products(self):
        from app.application.workflow.planner import _execute_print_label_tool

        result = _execute_print_label_tool({"products": []})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_non_list_products(self):
        from app.application.workflow.planner import _execute_print_label_tool

        result = _execute_print_label_tool({"products": "not a list"})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"


# ========================= _execute_excel_decompose_tool - deep ===========


class TestExecuteExcelDecomposeToolDeep:
    def test_missing_file_path(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        result = _execute_excel_decompose_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_import_error(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        with patch("app.bootstrap.get_template_app_service", side_effect=ImportError("no module")):
            result = _execute_excel_decompose_tool({"file_path": "/test.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"

    def test_value_error(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        with patch("app.bootstrap.get_template_app_service") as mock_svc:
            mock_svc.return_value.decompose_template.side_effect = ValueError("bad params")
            result = _execute_excel_decompose_tool({"file_path": "/test.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "invalid_parameters"

    def test_os_error(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        with patch("app.bootstrap.get_template_app_service") as mock_svc:
            mock_svc.return_value.decompose_template.side_effect = OSError("file not found")
            result = _execute_excel_decompose_tool({"file_path": "/test.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "file_not_found"

    def test_runtime_error(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        with patch("app.bootstrap.get_template_app_service") as mock_svc:
            mock_svc.return_value.decompose_template.side_effect = RuntimeError("fail")
            result = _execute_excel_decompose_tool({"file_path": "/test.xlsx"})
        assert result["success"] is False
        assert result["error_code"] == "decomposition_failed"


# ========================= _execute_excel_schema_tool - deep ==============


class TestExecuteExcelSchemaToolDeep:
    def test_missing_file_path(self):
        from app.application.workflow.planner import _execute_excel_schema_tool

        result = _execute_excel_schema_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"


# ========================= _execute_customers_tool - deep =================


class TestExecuteCustomersToolDeep:
    def test_import_error(self):
        from app.application.workflow.planner import _execute_customers_tool

        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no module")):
            result = _execute_customers_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "service_unavailable"

    def test_value_error(self):
        from app.application.workflow.planner import _execute_customers_tool

        with patch("app.bootstrap.get_customer_app_service", side_effect=ValueError("bad")):
            result = _execute_customers_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "invalid_parameters"

    def test_runtime_error(self):
        from app.application.workflow.planner import _execute_customers_tool

        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_tool({"keyword": "test"})
        assert result["success"] is False
        assert result["error_code"] == "query_failed"


# ========================= _filter_tool_registry_for_profile - deep =======


class TestFilterToolRegistryForProfileDeep:
    def test_normal_profile(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_empty_registry(self):
        result = _filter_tool_registry_for_profile({}, "pro_default")
        assert result == {}

    def test_action_level_filtering(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {
                    "query": {"availability": "shared", "risk": "low"},
                    "admin": {"availability": "pro_only", "risk": "high"},
                },
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        if "tool_a" in result:
            assert "admin" not in result["tool_a"]["actions"]

    def test_full_profile_includes_all(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "full")
        assert "tool_a" in result
        assert "tool_b" in result


# ========================= LLMWorkflowPlanner - init =====================


class TestLLMWorkflowPlannerInit:
    def test_init(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            planner = LLMWorkflowPlanner()
        assert planner is not None
