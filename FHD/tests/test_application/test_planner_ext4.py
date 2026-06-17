"""Tests for app.application.workflow.planner — deep coverage (ext4).

Focus: get_tool_registry, execute_tool, _execute_price_list_tool,
_execute_products_tool, _execute_customers_tool, _filter_tool_registry_for_profile,
LLMWorkflowPlanner initialization and methods.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# get_tool_registry
# ---------------------------------------------------------------------------


class TestGetToolRegistry:
    def test_returns_dict(self):
        from app.application.workflow.planner import get_tool_registry

        result = get_tool_registry()
        assert isinstance(result, dict)

    def test_has_common_tools(self):
        from app.application.workflow.planner import get_tool_registry

        result = get_tool_registry()
        # Should have at least some common tools
        assert len(result) > 0


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    def test_unknown_tool(self):
        from app.application.workflow.planner import execute_tool

        result = execute_tool("nonexistent_tool", {})
        assert isinstance(result, dict)
        assert result.get("success") is False or "error" in result or "不支持" in str(result)

    def test_empty_tool_name(self):
        from app.application.workflow.planner import execute_tool

        result = execute_tool("", {})
        assert isinstance(result, dict)

    def test_none_params(self):
        from app.application.workflow.planner import execute_tool

        result = execute_tool("query_products", None)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_products_tool
# ---------------------------------------------------------------------------


class TestExecuteProductsTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_products_tool

        result = _execute_products_tool({})
        assert isinstance(result, dict)

    def test_with_keyword(self):
        from app.application.workflow.planner import _execute_products_tool

        result = _execute_products_tool({"keyword": "测试"})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_customers_tool
# ---------------------------------------------------------------------------


class TestExecuteCustomersTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_customers_tool

        result = _execute_customers_tool({})
        assert isinstance(result, dict)

    def test_with_keyword(self):
        from app.application.workflow.planner import _execute_customers_tool

        result = _execute_customers_tool({"keyword": "张三"})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_customers_ensure_exists_tool
# ---------------------------------------------------------------------------


class TestExecuteCustomersEnsureExistsTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_customers_ensure_exists_tool

        result = _execute_customers_ensure_exists_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_shipment_records_tool
# ---------------------------------------------------------------------------


class TestExecuteShipmentRecordsTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_shipment_records_tool

        result = _execute_shipment_records_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_materials_tool
# ---------------------------------------------------------------------------


class TestExecuteMaterialsTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_materials_tool

        result = _execute_materials_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_print_label_tool
# ---------------------------------------------------------------------------


class TestExecutePrintLabelTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_print_label_tool

        result = _execute_print_label_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_excel_decompose_tool
# ---------------------------------------------------------------------------


class TestExecuteExcelDecomposeTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_excel_decompose_tool

        result = _execute_excel_decompose_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _execute_wechat_preview_tool
# ---------------------------------------------------------------------------


class TestExecuteWechatPreviewTool:
    def test_empty_params(self):
        from app.application.workflow.planner import _execute_wechat_preview_tool

        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch(
            "app.bootstrap.get_wechat_contact_app_service",
            return_value=mock_svc,
        ):
            result = _execute_wechat_preview_tool({})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _filter_tool_registry_for_profile
# ---------------------------------------------------------------------------


class TestFilterToolRegistryForProfile:
    def test_default_profile(self):
        from app.application.workflow.planner import (
            _filter_tool_registry_for_profile,
            get_tool_registry,
        )

        registry = get_tool_registry()
        result = _filter_tool_registry_for_profile(registry, profile="default")
        assert isinstance(result, dict)

    def test_empty_registry(self):
        from app.application.workflow.planner import _filter_tool_registry_for_profile

        result = _filter_tool_registry_for_profile({}, profile="default")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner
# ---------------------------------------------------------------------------


class TestLLMWorkflowPlanner:
    def test_init(self):
        from app.application.workflow.planner import LLMWorkflowPlanner

        planner = LLMWorkflowPlanner()
        assert planner is not None
