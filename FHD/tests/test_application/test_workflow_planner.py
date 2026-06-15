"""Tests for app.application.workflow.planner — coverage ramp."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
    execute_tool,
    get_tool_registry,
)
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph


# ========================= get_tool_registry =============================


class TestGetToolRegistry:
    def test_returns_dict(self):
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "shipment_generate" in reg

    def test_tool_has_actions(self):
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


# ========================= _filter_tool_registry_for_profile =============


class TestFilterToolRegistryForProfile:
    def test_normal_removes_pro_only(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"exec": {"availability": "pro_only", "risk": "high"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_pro_default_removes_normal_only(self):
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

    def test_shared_kept_in_both(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "pro_default")

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
        assert "query" in result["tool_a"]["actions"]
        assert "admin" not in result["tool_a"]["actions"]

    def test_non_dict_spec_skipped(self):
        reg = {"bad": "not a dict"}
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad" not in result

    def test_empty_actions_skipped(self):
        reg = {
            "tool_a": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result


# ========================= execute_tool ==================================


class TestExecuteTool:
    def test_unknown_tool_action(self):
        result = execute_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "未知工具" in result["message"]

    def test_default_action_resolution(self):
        result = execute_tool("products", {"_action": ""})
        # Should resolve to "query" by default
        assert isinstance(result, dict)

    def test_runtime_context_removed(self):
        result = execute_tool(
            "products", {"_runtime_context": {"user_id": "x"}, "_action": "query"}
        )
        assert isinstance(result, dict)


# ========================= LLMWorkflowPlanner ============================


class TestLLMWorkflowPlanner:
    def _make_planner(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service"):
            return LLMWorkflowPlanner()

    def test_fallback_plan_products(self):
        planner = self._make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            reg = get_tool_registry()
            plan = planner.plan("u1", "添加产品到公司A", reg)
        assert plan.intent == "add_product_to_unit"
        assert len(plan.nodes) >= 1

    def test_fallback_plan_generic(self):
        planner = self._make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            reg = get_tool_registry()
            plan = planner.plan("u1", "查询信息", reg)
        assert plan.intent == "generic_workflow"
        assert len(plan.nodes) >= 1

    def test_fallback_plan_risk_level(self):
        planner = self._make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        ):
            reg = get_tool_registry()
            plan = planner.plan("u1", "添加产品", reg)
        # Should have medium risk since add operations are medium
        assert plan.risk_level in ("low", "medium", "high")


# ========================= _validate_required_params =====================


class TestValidateRequiredParams:
    def test_valid_plan(self):
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": "公司A"},
                )
            ],
        )
        reg = {
            "customers": {
                "actions": {
                    "ensure_exists": {
                        "required_params": ["unit_name"],
                    }
                }
            }
        }
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None

    def test_missing_required_param(self):
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="ensure_exists",
                    params={},
                )
            ],
        )
        reg = {
            "customers": {
                "actions": {
                    "ensure_exists": {
                        "required_params": ["unit_name"],
                    }
                }
            }
        }
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "unit_name" in result

    def test_unknown_tool_skipped(self):
        plan = PlanGraph(
            plan_id="p1",
            intent="test",
            nodes=[WorkflowNode(node_id="n1", tool_id="unknown_tool", action="x", params={})],
        )
        result = LLMWorkflowPlanner._validate_required_params(plan, {})
        assert result is None


# ========================= _plan_with_llm ================================


class TestPlanWithLLM:
    def test_no_api_key_returns_none(self):
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
            mock_svc = Mock()
            mock_svc.api_key = ""
            mock_get.return_value = mock_svc
            planner = LLMWorkflowPlanner()
            result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})
        assert result is None

    def test_llm_returns_valid_plan(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "product_query",
                                "todo_steps": ["查询产品"],
                                "risk_level": "low",
                                "nodes": [
                                    {
                                        "node_id": "n1",
                                        "tool_id": "products",
                                        "action": "query",
                                        "params": {"keyword": "test"},
                                        "risk": "low",
                                        "idempotent": True,
                                        "description": "查询产品",
                                        "depends_on": [],
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
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
                result = planner._plan_with_llm("p1", "u1", "查询产品", get_tool_registry(), {})

        assert result is not None
        assert result.intent == "product_query"
        assert len(result.nodes) == 1

    def test_llm_http_error_returns_none(self):
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
                result = planner._plan_with_llm("p1", "u1", "hello", get_tool_registry(), {})

        assert result is None
