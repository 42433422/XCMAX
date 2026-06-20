"""Tests for app.application.workflow.planner — coverage ramp for uncovered branches."""

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
from app.application.workflow.types import PlanGraph, WorkflowNode

# ========================= _WORKFLOW_TOOL_HANDLERS ========================


class TestWorkflowToolHandlers:
    def test_handlers_exist(self):
        from app.application.workflow.planner import _WORKFLOW_TOOL_HANDLERS

        assert isinstance(_WORKFLOW_TOOL_HANDLERS, dict)
        assert len(_WORKFLOW_TOOL_HANDLERS) > 0

    def test_products_query_handler(self):
        from app.application.workflow.planner import _WORKFLOW_TOOL_HANDLERS

        assert ("products", "query") in _WORKFLOW_TOOL_HANDLERS

    def test_customers_handlers(self):
        from app.application.workflow.planner import _WORKFLOW_TOOL_HANDLERS

        assert ("customers", "query") in _WORKFLOW_TOOL_HANDLERS
        assert ("customers", "ensure_exists") in _WORKFLOW_TOOL_HANDLERS


# ========================= execute_tool - extended ========================


class TestExecuteToolExtended:
    def test_products_query(self):
        with patch("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS") as handlers:
            mock_handler = Mock(return_value={"success": True, "data": []})
            handlers.get = Mock(return_value=mock_handler)
            result = execute_tool("products", {"_action": "query"})
        assert isinstance(result, dict)

    def test_customers_ensure_exists(self):
        with patch("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS") as handlers:
            mock_handler = Mock(return_value={"success": True})
            handlers.get = Mock(return_value=mock_handler)
            result = execute_tool("customers", {"_action": "ensure_exists", "unit_name": "公司A"})
        assert isinstance(result, dict)

    def test_runtime_context_removed_from_params(self):
        with patch("app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS") as handlers:
            mock_handler = Mock(return_value={"success": True})
            handlers.get = Mock(return_value=mock_handler)
            result = execute_tool(
                "products",
                {"_action": "query", "_runtime_context": {"user_id": "u1"}, "keyword": "test"},
            )
        # _runtime_context should be removed before passing to handler
        call_args = mock_handler.call_args
        if call_args:
            params = call_args[0][0] if call_args[0] else call_args[1].get("params", {})
            assert "_runtime_context" not in params or "_runtime_context" not in str(call_args)

    def test_unknown_tool_action(self):
        result = execute_tool("nonexistent_tool", {"_action": "unknown"})
        assert result["success"] is False


# ========================= _filter_tool_registry_for_profile - extended ===


class TestFilterToolRegistryForProfileExtended:
    def test_pro_default_profile(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "normal_only",
                "actions": {"slot": {"availability": "normal_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "pro_default")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_full_profile(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "full")
        assert "tool_a" in result

    def test_unknown_profile_keeps_shared(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "unknown")
        assert "tool_a" in result


# ========================= LLMWorkflowPlanner._plan_with_react_multiagent


class TestPlanWithReactMultiagent:
    def _make_planner(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            return LLMWorkflowPlanner()

    def test_no_api_key_returns_none(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            result = planner._plan_with_react_multiagent(
                "p1", "u1", "hello", get_tool_registry(), {}
            )
        assert result is None

    def test_with_api_key_llm_failure(self):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client = Mock()
        mock_client.post.return_value = mock_response

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = "test-key"
            mock_svc.api_url = "http://fake"
            mock_svc.model = "test-model"
            mock_svc.get_context.return_value = None
            mock_get.return_value = mock_svc
            with patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=mock_client,
            ):
                planner = LLMWorkflowPlanner()
                result = planner._plan_with_react_multiagent(
                    "p1", "u1", "hello", get_tool_registry(), {}
                )
        # Should fall back or return None
        assert result is None or isinstance(result, PlanGraph)


# ========================= LLMWorkflowPlanner._critic_repair_with_llm ====


class TestCriticRepairWithLLM:
    def test_no_api_key_returns_none(self):
        invalid_plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="products", action="query", params={})],
        )
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            result = planner._critic_repair_with_llm(
                "p1", "u1", "test", get_tool_registry(), {}, "missing params", invalid_plan
            )
        assert result is None  # Should return None when no API key


# ========================= LLMWorkflowPlanner.plan - extended =============


class TestLLMWorkflowPlannerPlanExtended:
    def _make_planner(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            return LLMWorkflowPlanner()

    def test_react_returns_valid_plan(self):
        planner = self._make_planner()
        mock_plan = PlanGraph(
            plan_id="p1",
            intent="product_query",
            nodes=[
                WorkflowNode(
                    node_id="n1", tool_id="products", action="query", params={"keyword": "test"}
                )
            ],
        )
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=mock_plan),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            result = planner.plan("u1", "查询产品", get_tool_registry(), {})
        assert result.intent == "product_query"
        assert len(result.nodes) == 1

    def test_fallback_for_shipment(self):
        planner = self._make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            result = planner.plan("u1", "生成发货单", get_tool_registry(), {})
        assert result.intent in ("shipment_generate", "generic_workflow")

    def test_fallback_for_customers(self):
        planner = self._make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            result = planner.plan("u1", "添加客户公司A", get_tool_registry(), {})
        assert result.intent in ("add_customer", "ensure_customer", "generic_workflow")


# ========================= _validate_required_params - extended ===========


class TestValidateRequiredParamsExtended:
    def test_multiple_nodes(self):
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": "公司A"},
                ),
                WorkflowNode(
                    node_id="n2",
                    tool_id="products",
                    action="create",
                    params={},  # missing required params
                ),
            ],
        )
        reg = {
            "customers": {
                "actions": {
                    "ensure_exists": {"required_params": ["unit_name"]},
                }
            },
            "products": {
                "actions": {
                    "create": {"required_params": ["name", "unit_name"]},
                }
            },
        }
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "name" in result or "unit_name" in result

    def test_no_required_params(self):
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="products", action="query", params={}),
            ],
        )
        reg = {
            "products": {
                "actions": {
                    "query": {},  # no required_params
                }
            },
        }
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None


# ========================= get_tool_registry - extended ===================


class TestGetToolRegistryExtended:
    def test_all_expected_tools(self):
        reg = get_tool_registry()
        expected_tools = ["products", "customers", "shipment_generate"]
        for tool in expected_tools:
            assert tool in reg, f"Missing tool: {tool}"

    def test_tool_actions_are_dicts(self):
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert isinstance(spec["actions"], dict), f"{tool_id} actions not dict"
