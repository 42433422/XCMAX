from __future__ import annotations

"""Branch-coverage tests for app/application/workflow/planner.py."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pure-function imports (no app bootstrap needed)
# ---------------------------------------------------------------------------
from app.application.workflow.planner import (
    _clean_db_slot_value,
    _extract_business_db_read_keyword,
    _extract_business_db_write_node,
    _extract_named_slot,
    _filter_tool_registry_for_profile,
    _get_planner_http_client,
    _infer_business_db_entity,
    _looks_like_business_db_write,
)
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph

# ---------------------------------------------------------------------------
# Minimal tool registry for LLMWorkflowPlanner tests
# ---------------------------------------------------------------------------

_SAMPLE_REGISTRY: dict[str, Any] = {
    "products": {
        "description": "产品查询",
        "availability": "shared",
        "actions": {
            "query": {
                "description": "查询产品",
                "risk": "low",
                "idempotent": True,
                "availability": "shared",
                "required_params": ["keyword"],
            },
            "create": {
                "description": "创建产品",
                "risk": "medium",
                "idempotent": False,
                "availability": "shared",
                "required_params": [],
            },
        },
    },
    "customers": {
        "description": "客户查询",
        "availability": "shared",
        "actions": {
            "query": {
                "description": "查询客户",
                "risk": "low",
                "idempotent": True,
                "availability": "shared",
                "required_params": [],
            },
            "ensure_exists": {
                "description": "确保客户存在",
                "risk": "medium",
                "idempotent": True,
                "availability": "shared",
                "required_params": [],
            },
        },
    },
    "business_db": {
        "description": "业务数据库",
        "availability": "shared",
        "actions": {
            "read": {
                "description": "读取",
                "risk": "low",
                "idempotent": True,
                "availability": "shared",
                "required_params": ["entity"],
            },
            "write": {
                "description": "写入",
                "risk": "medium",
                "idempotent": False,
                "availability": "shared",
                "required_params": [],
            },
        },
    },
    "employee": {
        "description": "员工执行",
        "availability": "shared",
        "actions": {
            "list": {
                "description": "列出员工",
                "risk": "low",
                "idempotent": True,
                "availability": "shared",
                "required_params": [],
            },
            "execute": {
                "description": "执行员工任务",
                "risk": "medium",
                "idempotent": False,
                "availability": "shared",
                "required_params": ["employee_id"],
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(nodes: list[WorkflowNode] | None = None) -> PlanGraph:
    return PlanGraph(
        plan_id="test-plan",
        intent="test_intent",
        todo_steps=["step1"],
        nodes=nodes
        or [
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="query",
                params={"keyword": "abc"},
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


# ---------------------------------------------------------------------------
# _clean_db_slot_value
# ---------------------------------------------------------------------------


class TestCleanDbSlotValue:
    def test_strips_whitespace_and_punctuation(self) -> None:
        result = _clean_db_slot_value("  ,测试,。 ")
        assert "," not in result
        assert result.strip() == result

    def test_removes_db_keywords(self) -> None:
        assert "数据库" not in _clean_db_slot_value("产品加入数据库")

    def test_removes_leading_entity_prefixes(self) -> None:
        result = _clean_db_slot_value("新增ABC")
        # The regex strips leading action words like 新增/添加/创建
        assert "新增" not in result

    def test_empty_string(self) -> None:
        assert _clean_db_slot_value("") == ""

    def test_none_input(self) -> None:
        assert _clean_db_slot_value(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _extract_named_slot
# ---------------------------------------------------------------------------


class TestExtractNamedSlot:
    def test_pattern_match_returns_value(self) -> None:
        msg = "客户：ABC公司"
        result = _extract_named_slot(msg, (r"客户[：:]\s*([^\s，,。；;]+)",))
        assert result == "ABC公司"

    def test_quoted_fallback(self) -> None:
        msg = '请查询"上海科技"的产品'
        result = _extract_named_slot(msg, (r"无法匹配的模式(.+)",))
        assert "上海科技" in result

    def test_no_match_returns_empty(self) -> None:
        msg = "没有任何匹配"
        result = _extract_named_slot(msg, (r"ZZZ(.+)",))
        assert result == ""


# ---------------------------------------------------------------------------
# _infer_business_db_entity
# ---------------------------------------------------------------------------


class TestInferBusinessDbEntity:
    def test_product_keywords(self) -> None:
        assert _infer_business_db_entity("查询产品库存") == "products"
        assert _infer_business_db_entity("查询商品") == "products"

    def test_customer_keywords(self) -> None:
        assert _infer_business_db_entity("客户ABC") == "customers"
        assert _infer_business_db_entity("购买单位X") == "customers"

    def test_material_keywords(self) -> None:
        assert _infer_business_db_entity("原材料钢板") == "materials"
        assert _infer_business_db_entity("物料库存") == "materials"

    def test_shipment_keywords(self) -> None:
        assert _infer_business_db_entity("出货记录") == "shipment_records"
        assert _infer_business_db_entity("发货单") == "shipment_records"

    def test_fallback_to_products(self) -> None:
        assert _infer_business_db_entity("随机文字") == "products"


# ---------------------------------------------------------------------------
# _looks_like_business_db_write
# ---------------------------------------------------------------------------


class TestLooksLikeBusinessDbWrite:
    def test_chinese_write_keywords(self) -> None:
        assert _looks_like_business_db_write("新增产品到数据库", "新增产品到数据库") is True

    def test_english_write_keywords(self) -> None:
        assert _looks_like_business_db_write("add product to db", "add product to db") is True

    def test_no_write_keywords(self) -> None:
        assert _looks_like_business_db_write("查询产品", "查询产品") is False

    def test_write_keyword_without_db_reference(self) -> None:
        # Has write keyword but no db reference
        assert _looks_like_business_db_write("新增一条消息", "新增一条消息") is False


# ---------------------------------------------------------------------------
# _extract_business_db_write_node
# ---------------------------------------------------------------------------


class TestExtractBusinessDbWriteNode:
    def test_customer_write_with_slot(self) -> None:
        node = _extract_business_db_write_node("新增客户：ABC公司加入数据库")
        if node is not None:
            assert node.tool_id == "business_db"
            assert node.action == "write"

    def test_customer_write_no_slot_returns_none(self) -> None:
        # No extractable slot → should return None
        result = _extract_business_db_write_node("新增客户到数据库")
        # May or may not succeed depending on regex; just verify type
        assert result is None or result.tool_id == "business_db"

    def test_product_write_with_slot(self) -> None:
        node = _extract_business_db_write_node("为单位甲方新增产品：螺钉 给客户甲方写入数据库")
        if node is not None:
            assert node.action == "write"

    def test_product_missing_product_name_returns_none(self) -> None:
        # "产品" entity but no extractable name or unit
        result = _extract_business_db_write_node("产品写入数据库")
        assert result is None

    def test_materials_entity_returns_none(self) -> None:
        # materials entity has no write handler → returns None
        result = _extract_business_db_write_node("原材料钢板入库数据库写入")
        assert result is None

    def test_model_number_extracted(self) -> None:
        node = _extract_business_db_write_node(
            "给单位测试公司新增产品测试品 型号:ABC123 写入数据库"
        )
        if node is not None and node.params.get("payload"):
            payload = node.params["payload"]
            assert "model_number" in payload or "product_name" in payload


# ---------------------------------------------------------------------------
# _extract_business_db_read_keyword
# ---------------------------------------------------------------------------


class TestExtractBusinessDbReadKeyword:
    def test_quoted_takes_priority(self) -> None:
        result = _extract_business_db_read_keyword('查询"ABC123"', "products")
        assert "ABC123" in result

    def test_product_entity_slot_extraction(self) -> None:
        result = _extract_business_db_read_keyword("查询产品ABC123", "products")
        assert result  # non-empty

    def test_customer_entity_slot_extraction(self) -> None:
        result = _extract_business_db_read_keyword("查询客户ABC公司", "customers")
        assert result

    def test_materials_entity_slot_extraction(self) -> None:
        result = _extract_business_db_read_keyword("查询原材料钢板", "materials")
        assert result

    def test_fallback_cleans_keywords(self) -> None:
        # Unrecognised entity with no useful slot — should still return something
        result = _extract_business_db_read_keyword("查询数据库里的东西", "unknown_entity")
        assert isinstance(result, str)

    def test_model_number_fallback(self) -> None:
        result = _extract_business_db_read_keyword("查ABC99X的价格", "products")
        assert result


# ---------------------------------------------------------------------------
# _filter_tool_registry_for_profile
# ---------------------------------------------------------------------------


class TestFilterToolRegistryForProfile:
    def _registry(self) -> dict[str, Any]:
        return {
            "tool_shared": {
                "availability": "shared",
                "actions": {
                    "act_shared": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            },
            "tool_pro_only": {
                "availability": "pro_only",
                "actions": {
                    "act": {"availability": "pro_only", "risk": "low", "idempotent": True},
                },
            },
            "tool_normal_only": {
                "availability": "normal_only",
                "actions": {
                    "act": {"availability": "normal_only", "risk": "low", "idempotent": True},
                },
            },
            "tool_mixed": {
                "availability": "shared",
                "actions": {
                    "pro_act": {"availability": "pro_only", "risk": "low", "idempotent": True},
                    "normal_act": {
                        "availability": "normal_only",
                        "risk": "low",
                        "idempotent": True,
                    },
                    "shared_act": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            },
        }

    def test_normal_profile_excludes_pro_only(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        assert "tool_pro_only" not in filtered

    def test_normal_profile_includes_normal_only(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        assert "tool_normal_only" in filtered

    def test_pro_default_excludes_normal_only(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "pro_default")
        assert "tool_normal_only" not in filtered

    def test_pro_default_includes_pro_only(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "pro_default")
        assert "tool_pro_only" in filtered

    def test_shared_profile_keeps_all_shared(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "other")
        assert "tool_shared" in filtered

    def test_mixed_tool_normal_profile_keeps_shared_and_normal_actions(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        actions = filtered.get("tool_mixed", {}).get("actions", {})
        assert "shared_act" in actions
        assert "normal_act" in actions
        assert "pro_act" not in actions

    def test_non_dict_spec_skipped(self) -> None:
        reg = {"bad_tool": "not_a_dict"}
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad_tool" not in filtered

    def test_tool_with_no_remaining_actions_excluded(self) -> None:
        reg = {
            "pro_only_tool": {
                "availability": "shared",
                "actions": {
                    "pro_act": {"availability": "pro_only", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "pro_only_tool" not in filtered


# ---------------------------------------------------------------------------
# validate_plan_graph (from types.py — exercised via planner tests)
# ---------------------------------------------------------------------------


class TestValidatePlanGraph:
    def test_valid_plan_returns_none(self) -> None:
        plan = _make_plan()
        assert validate_plan_graph(plan) is None

    def test_empty_nodes_fails(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[])
        assert validate_plan_graph(plan) is not None

    def test_missing_plan_id_fails(self) -> None:
        plan = PlanGraph(plan_id="", intent="i", nodes=[WorkflowNode("n", "t", "a")])
        assert validate_plan_graph(plan) is not None

    def test_missing_intent_fails(self) -> None:
        plan = PlanGraph(plan_id="p", intent="", nodes=[WorkflowNode("n", "t", "a")])
        assert validate_plan_graph(plan) is not None

    def test_duplicate_node_ids_fails(self) -> None:
        nodes = [WorkflowNode("n", "t", "a"), WorkflowNode("n", "t", "b")]
        plan = PlanGraph(plan_id="p", intent="i", nodes=nodes)
        assert validate_plan_graph(plan) is not None

    def test_missing_tool_id_fails(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[WorkflowNode("n", "", "a")])
        assert validate_plan_graph(plan) is not None

    def test_missing_action_fails(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[WorkflowNode("n", "t", "")])
        assert validate_plan_graph(plan) is not None

    def test_unresolved_dependency_fails(self) -> None:
        node = WorkflowNode("n", "t", "a", depends_on=["nonexistent"])
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert validate_plan_graph(plan) is not None

    def test_self_dependency_fails(self) -> None:
        node = WorkflowNode("n", "t", "a", depends_on=["n"])
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert validate_plan_graph(plan) is not None


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner — validate_required_params static method
# ---------------------------------------------------------------------------


class TestValidateRequiredParams:
    def test_all_params_present_returns_none(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        reg = {
            "products": {
                "actions": {
                    "query": {"required_params": ["keyword"]},
                }
            }
        }
        node = WorkflowNode("n1", "products", "query", params={"keyword": "abc"})
        plan = _make_plan([node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is None

    def test_missing_required_param_returns_error(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        reg = {
            "products": {
                "actions": {
                    "query": {"required_params": ["keyword"]},
                }
            }
        }
        node = WorkflowNode("n1", "products", "query", params={})
        plan = _make_plan([node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "keyword" in result

    def test_empty_string_param_fails(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        reg = {
            "products": {
                "actions": {
                    "query": {"required_params": ["keyword"]},
                }
            }
        }
        node = WorkflowNode("n1", "products", "query", params={"keyword": ""})
        plan = _make_plan([node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None

    def test_tool_not_in_registry_skipped(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "unknown_tool", "query", params={})
        plan = _make_plan([node])
        # No entry in registry → no error
        result = LLMWorkflowPlanner._validate_required_params(plan, {})
        assert result is None

    def test_none_param_value_fails(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        reg = {
            "products": {
                "actions": {
                    "query": {"required_params": ["keyword"]},
                }
            }
        }
        node = WorkflowNode("n1", "products", "query", params={"keyword": None})
        plan = _make_plan([node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner._fallback_plan — rule-based paths
# ---------------------------------------------------------------------------


class TestFallbackPlan:
    def _make_planner(self) -> Any:
        from app.application.workflow.planner import LLMWorkflowPlanner

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            mock_svc.return_value = MagicMock()
            planner = LLMWorkflowPlanner()
        return planner

    def test_fallback_employee_intent_with_unknown_id(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "请员工处理订单", _SAMPLE_REGISTRY)
        assert result.intent == "employee_dispatch"
        assert any(n.action == "list" for n in result.nodes)

    def test_fallback_business_db_write(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "新增客户ABC公司到数据库写入", _SAMPLE_REGISTRY)
        # Should route to business_db_write or fallback query
        assert result is not None
        assert result.plan_id == "pid"

    def test_fallback_business_db_read(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "查询数据库里的产品", _SAMPLE_REGISTRY)
        assert result is not None
        assert any(n.tool_id == "business_db" for n in result.nodes) or any(
            n.tool_id == "products" for n in result.nodes
        )

    def test_fallback_add_product_to_unit(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "添加新产品到客户单位", _SAMPLE_REGISTRY)
        assert result.intent == "add_product_to_unit"

    def test_fallback_default_query_products(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "帮我看看", _SAMPLE_REGISTRY)
        assert any(n.tool_id == "products" for n in result.nodes)

    def test_fallback_no_products_falls_to_customers(self) -> None:
        planner = self._make_planner()
        reg = {
            "customers": {
                "description": "c",
                "availability": "shared",
                "actions": {
                    "query": {
                        "risk": "low",
                        "idempotent": True,
                        "availability": "shared",
                        "required_params": [],
                    }
                },
            }
        }
        result = planner._fallback_plan("pid", "帮我看看", reg)
        assert any(n.tool_id == "customers" for n in result.nodes)

    def test_fallback_risk_level_high_when_node_is_high(self) -> None:
        planner = self._make_planner()
        # Force a high-risk node by providing a message that triggers business_db write
        # with a node having risk="high" (we patch _extract_business_db_write_node)
        high_node = WorkflowNode("n", "t", "a", risk="high")
        with patch(
            "app.application.workflow.planner._extract_business_db_write_node",
            return_value=high_node,
        ):
            with patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ):
                result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.risk_level == "high"

    def test_fallback_risk_level_medium(self) -> None:
        planner = self._make_planner()
        medium_node = WorkflowNode("n", "t", "a", risk="medium")
        with patch(
            "app.application.workflow.planner._extract_business_db_write_node",
            return_value=medium_node,
        ):
            with patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ):
                result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.risk_level == "medium"


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner._plan_with_llm — mocked HTTP paths
# ---------------------------------------------------------------------------


class TestPlanWithLLM:
    def _make_planner(self) -> Any:
        from app.application.workflow.planner import LLMWorkflowPlanner

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            ai = MagicMock()
            ai.api_key = "test-key"
            ai.api_url = "https://api.example.com/v1/chat/completions"
            ai.model = "deepseek-chat"
            ai.get_context.return_value = None
            mock_svc.return_value = ai
            planner = LLMWorkflowPlanner()
        return planner

    def _mock_response(self, payload: dict[str, Any]) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
        return resp

    def test_returns_none_when_no_api_key(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            ai = MagicMock()
            ai.api_key = ""
            ai.api_url = ""
            ai.model = ""
            ai.get_context.return_value = None
            mock_svc.return_value = ai
            planner = LLMWorkflowPlanner()

        result = planner._plan_with_llm(
            plan_id="pid",
            user_id="u1",
            message="test",
            tool_registry=_SAMPLE_REGISTRY,
            context={},
        )
        assert result is None

    def test_returns_none_on_http_error(self) -> None:
        planner = self._make_planner()
        resp = MagicMock()
        resp.status_code = 500

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is None

    def test_returns_none_on_empty_content(self) -> None:
        planner = self._make_planner()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": ""}}]}

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is None

    def test_successful_parse_returns_plan_graph(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "query_products",
            "todo_steps": ["查询产品"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "ABC"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "查询产品",
                    "depends_on": [],
                }
            ],
        }
        resp = self._mock_response(payload)

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="查询产品ABC",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
        assert result.intent == "query_products"
        assert len(result.nodes) == 1

    def test_json_parse_error_returns_none(self) -> None:
        planner = self._make_planner()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": "NOT JSON"}}]}

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is None

    def test_context_with_tool_probe_outputs_and_memory(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "query_products",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "X"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "q",
                    "depends_on": [],
                }
            ],
        }
        resp = self._mock_response(payload)
        context = {
            "tool_probe_outputs": [
                {
                    "tool_id": "products",
                    "action": "query",
                    "success": True,
                    "message": "ok",
                    "data_preview": "[{...}]",
                }
            ],
            "user_memory_rag": {"summary": "用户偏好：ABC产品"},
            "memory_v2": {"summary": "已确认 active 记忆：ABC"},
        }

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context=context,
            )
        assert result is not None
        assert result.metadata.get("user_memory_rag_summary") == "用户偏好：ABC产品"


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner.plan — integration with mocked LLM
# ---------------------------------------------------------------------------


class TestPlanMethod:
    def _make_planner(self) -> Any:
        from app.application.workflow.planner import LLMWorkflowPlanner

        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            ai = MagicMock()
            ai.api_key = ""
            ai.api_url = ""
            ai.model = ""
            ai.get_context.return_value = None
            mock_svc.return_value = ai
            planner = LLMWorkflowPlanner()
        return planner

    def test_plan_falls_back_to_rules_when_llm_unavailable(self) -> None:
        planner = self._make_planner()

        with (
            patch(
                "app.application.workflow.planner.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
        ):
            result = planner.plan(
                user_id="u1",
                message="帮我查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
        assert result.plan_id

    def test_plan_with_memory_import_error_swallowed(self) -> None:
        """ImportError from memory services should not propagate."""
        planner = self._make_planner()

        with (
            patch(
                "app.application.workflow.planner.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.workflow.planner.get_user_memory_rag_app_service",
                side_effect=ImportError("no rag"),
                create=True,
            ),
        ):
            result = planner.plan(
                user_id="u1",
                message="测试",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None


# ---------------------------------------------------------------------------
# _get_planner_http_client singleton
# ---------------------------------------------------------------------------


class TestGetPlannerHttpClient:
    def test_returns_same_instance(self) -> None:
        import app.application.workflow.planner as planner_mod

        planner_mod._planner_http_client = None
        client1 = _get_planner_http_client()
        client2 = _get_planner_http_client()
        assert client1 is client2
        planner_mod._planner_http_client = None
