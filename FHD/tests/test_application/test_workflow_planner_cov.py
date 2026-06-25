from __future__ import annotations

"""Behavior tests for app/application/workflow/planner.py.

These assert concrete return values / state changes (not just non-None), and
cover both branches of each helper. No source under app/** is modified — where
a test pins a surprising-but-real behavior, that is the planner's actual output.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

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
    def test_strips_surrounding_whitespace_and_punctuation(self) -> None:
        # Leading/trailing spaces + commas/periods are stripped; inner content kept.
        assert _clean_db_slot_value("  ,测试,。 ") == "测试"

    def test_db_phrase_is_entirely_consumed(self) -> None:
        # "产品" prefix and "加入数据库" token both stripped → empty.
        assert _clean_db_slot_value("产品加入数据库") == ""

    def test_removes_leading_action_prefix(self) -> None:
        assert _clean_db_slot_value("新增ABC") == "ABC"
        assert _clean_db_slot_value("添加XYZ") == "XYZ"

    def test_removes_trailing_entity_suffix(self) -> None:
        assert _clean_db_slot_value("XYZ产品") == "XYZ"

    def test_empty_string(self) -> None:
        assert _clean_db_slot_value("") == ""

    def test_none_input(self) -> None:
        assert _clean_db_slot_value(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _extract_named_slot
# ---------------------------------------------------------------------------


class TestExtractNamedSlot:
    def test_pattern_match_returns_cleaned_value(self) -> None:
        result = _extract_named_slot("客户：ABC公司", (r"客户[：:]\s*([^\s，,。；;]+)",))
        assert result == "ABC公司"

    def test_quoted_fallback_when_pattern_misses(self) -> None:
        # Pattern can't match → falls back to the quoted span.
        result = _extract_named_slot('请查询"上海科技"的产品', (r"无法匹配的模式(.+)",))
        assert result == "上海科技"

    def test_no_match_and_no_quote_returns_empty(self) -> None:
        assert _extract_named_slot("没有任何匹配", (r"ZZZ(.+)",)) == ""

    def test_pattern_match_takes_priority_over_quote(self) -> None:
        # Both a pattern hit and a quote exist; the pattern result is used
        # (not the quoted "乙方" fallback). A space ends the captured run.
        result = _extract_named_slot('客户：甲方 "乙方"', (r"客户[：:]\s*([^\s，,。；;]+)",))
        assert result == "甲方"


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

    def test_product_wins_over_customer_when_both_present(self) -> None:
        # "产品" is checked before "客户"; first match wins.
        assert _infer_business_db_entity("给客户新增产品") == "products"

    def test_fallback_to_products(self) -> None:
        assert _infer_business_db_entity("随机文字") == "products"


# ---------------------------------------------------------------------------
# _looks_like_business_db_write
# ---------------------------------------------------------------------------


class TestLooksLikeBusinessDbWrite:
    def test_chinese_write_keyword_with_db_reference(self) -> None:
        assert _looks_like_business_db_write("新增产品到数据库", "新增产品到数据库") is True

    def test_english_write_keyword_with_db_reference(self) -> None:
        assert _looks_like_business_db_write("add product to db", "add product to db") is True

    def test_no_write_keyword_at_all(self) -> None:
        assert _looks_like_business_db_write("查询产品", "查询产品") is False

    def test_write_keyword_without_db_reference(self) -> None:
        # Has 新增 (write keyword) but no 数据库/db/database → not a DB write.
        assert _looks_like_business_db_write("新增一条消息", "新增一条消息") is False

    def test_db_reference_without_write_keyword(self) -> None:
        # Mentions 数据库 but only a read verb → not a write.
        assert _looks_like_business_db_write("查询数据库", "查询数据库") is False


# ---------------------------------------------------------------------------
# _extract_business_db_write_node
# ---------------------------------------------------------------------------


class TestExtractBusinessDbWriteNode:
    def test_customer_write_builds_upsert_node(self) -> None:
        node = _extract_business_db_write_node("新增客户：ABC公司加入数据库")
        assert node is not None
        assert node.node_id == "write_business_customer"
        assert node.tool_id == "business_db"
        assert node.action == "write"
        assert node.risk == "medium"
        assert node.idempotent is True
        assert node.params["entity"] == "customers"
        assert node.params["operation"] == "upsert"
        assert node.params["payload"] == {
            "unit_name": "ABC公司",
            "customer_name": "ABC公司",
        }

    def test_customer_write_without_extractable_unit_returns_none(self) -> None:
        # "新增客户到数据库": after slot-cleaning the unit name is empty → None.
        assert _extract_business_db_write_node("新增客户到数据库") is None

    def test_product_write_builds_create_node(self) -> None:
        node = _extract_business_db_write_node("为单位甲方新增产品：螺钉 给客户甲方写入数据库")
        assert node is not None
        assert node.node_id == "write_business_product"
        assert node.tool_id == "business_db"
        assert node.action == "write"
        assert node.idempotent is False
        assert node.params["entity"] == "products"
        assert node.params["operation"] == "create"
        assert node.params["payload"]["product_name"] == "螺钉"
        assert node.params["payload"]["name_or_model"] == "螺钉"
        # No 型号/model token in the message → payload omits model_number.
        assert "model_number" not in node.params["payload"]

    def test_product_write_missing_name_returns_none(self) -> None:
        # "产品" entity inferred but neither product nor unit name extractable.
        assert _extract_business_db_write_node("产品写入数据库") is None

    def test_materials_entity_has_no_write_handler(self) -> None:
        # materials/shipment_records entities are not handled → always None.
        assert _extract_business_db_write_node("原材料钢板入库数据库写入") is None

    def test_model_number_extracted_and_uppercased(self) -> None:
        node = _extract_business_db_write_node(
            "给单位测试公司新增产品测试品 型号:ABC123 写入数据库"
        )
        assert node is not None
        payload = node.params["payload"]
        assert payload["product_name"] == "测试品"
        # 型号:ABC123 → model_number is captured and upper-cased.
        assert payload["model_number"] == "ABC123"


# ---------------------------------------------------------------------------
# _extract_business_db_read_keyword
# ---------------------------------------------------------------------------


class TestExtractBusinessDbReadKeyword:
    def test_quoted_takes_priority(self) -> None:
        assert _extract_business_db_read_keyword('查询"ABC123"', "products") == "ABC123"

    def test_product_entity_slot_extraction(self) -> None:
        assert _extract_business_db_read_keyword("查询产品ABC123", "products") == "ABC123"

    def test_customer_entity_slot_extraction(self) -> None:
        assert _extract_business_db_read_keyword("查询客户ABC公司", "customers") == "ABC公司"

    def test_materials_entity_slot_extraction(self) -> None:
        assert _extract_business_db_read_keyword("查询原材料钢板", "materials") == "钢板"

    def test_unknown_entity_falls_back_to_keyword_stripping(self) -> None:
        # Unrecognised entity: strips query/db tokens, keeps the remainder.
        assert (
            _extract_business_db_read_keyword("查询数据库里的东西", "unknown_entity") == "里的东西"
        )

    def test_product_model_number_fallback(self) -> None:
        # No explicit 产品/型号 marker; the alnum token is recovered as keyword.
        assert _extract_business_db_read_keyword("查ABC99X的价格", "products") == "ABC99X"


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

    def test_normal_profile_drops_pro_keeps_normal_and_shared(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        assert set(filtered) == {"tool_shared", "tool_normal_only", "tool_mixed"}
        assert "tool_pro_only" not in filtered

    def test_pro_default_drops_normal_keeps_pro_and_shared(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "pro_default")
        assert set(filtered) == {"tool_shared", "tool_pro_only", "tool_mixed"}
        assert "tool_normal_only" not in filtered

    def test_unknown_profile_keeps_everything(self) -> None:
        # Any profile other than normal/pro_default applies no exclusions.
        filtered = _filter_tool_registry_for_profile(self._registry(), "other")
        assert set(filtered) == {
            "tool_shared",
            "tool_pro_only",
            "tool_normal_only",
            "tool_mixed",
        }

    def test_mixed_tool_normal_profile_filters_actions(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        actions = filtered["tool_mixed"]["actions"]
        assert set(actions) == {"shared_act", "normal_act"}
        assert "pro_act" not in actions

    def test_mixed_tool_pro_default_filters_actions(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "pro_default")
        actions = filtered["tool_mixed"]["actions"]
        assert set(actions) == {"shared_act", "pro_act"}
        assert "normal_act" not in actions

    def test_filter_does_not_mutate_input_registry(self) -> None:
        reg = self._registry()
        _filter_tool_registry_for_profile(reg, "normal")
        # Original registry still has the pro-only action on tool_mixed.
        assert "pro_act" in reg["tool_mixed"]["actions"]
        assert "tool_pro_only" in reg

    def test_non_dict_spec_skipped(self) -> None:
        filtered = _filter_tool_registry_for_profile({"bad_tool": "not_a_dict"}, "normal")
        assert filtered == {}

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
        assert filtered == {}


# ---------------------------------------------------------------------------
# validate_plan_graph (from types.py — exercised via planner tests)
# ---------------------------------------------------------------------------


class TestValidatePlanGraph:
    def test_valid_plan_returns_none(self) -> None:
        assert validate_plan_graph(_make_plan()) is None

    def test_empty_nodes_message(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[])
        assert validate_plan_graph(plan) == "nodes 不能为空"

    def test_missing_plan_id_message(self) -> None:
        plan = PlanGraph(plan_id="", intent="i", nodes=[WorkflowNode("n", "t", "a")])
        assert validate_plan_graph(plan) == "plan_id 不能为空"

    def test_missing_intent_message(self) -> None:
        plan = PlanGraph(plan_id="p", intent="", nodes=[WorkflowNode("n", "t", "a")])
        assert validate_plan_graph(plan) == "intent 不能为空"

    def test_duplicate_node_ids_message(self) -> None:
        nodes = [WorkflowNode("n", "t", "a"), WorkflowNode("n", "t", "b")]
        plan = PlanGraph(plan_id="p", intent="i", nodes=nodes)
        assert validate_plan_graph(plan) == "node_id 不能重复"

    def test_missing_tool_id_message(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[WorkflowNode("n", "", "a")])
        assert validate_plan_graph(plan) == "节点 n 缺少 tool_id"

    def test_missing_action_message(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[WorkflowNode("n", "t", "")])
        assert validate_plan_graph(plan) == "节点 n 缺少 action"

    def test_unresolved_dependency_message(self) -> None:
        node = WorkflowNode("n", "t", "a", depends_on=["nonexistent"])
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert validate_plan_graph(plan) == "节点 n 依赖不存在: nonexistent"

    def test_self_dependency_message(self) -> None:
        node = WorkflowNode("n", "t", "a", depends_on=["n"])
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert validate_plan_graph(plan) == "节点 n 不能依赖自身"

    def test_valid_multi_node_with_resolved_dependency(self) -> None:
        nodes = [
            WorkflowNode("a", "t", "x"),
            WorkflowNode("b", "t", "y", depends_on=["a"]),
        ]
        plan = PlanGraph(plan_id="p", intent="i", nodes=nodes)
        assert validate_plan_graph(plan) is None


# ---------------------------------------------------------------------------
# LLMWorkflowPlanner — validate_required_params static method
# ---------------------------------------------------------------------------


class TestValidateRequiredParams:
    _REG = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}

    def test_all_params_present_returns_none(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "products", "query", params={"keyword": "abc"})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), self._REG)
        assert result is None

    def test_missing_required_param_error_message(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "products", "query", params={})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), self._REG)
        assert result == "节点 n1 缺少 required_params: keyword"

    def test_empty_string_param_fails(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "products", "query", params={"keyword": ""})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), self._REG)
        assert result == "节点 n1 缺少 required_params: keyword"

    def test_none_param_value_fails(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "products", "query", params={"keyword": None})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), self._REG)
        assert result == "节点 n1 缺少 required_params: keyword"

    def test_whitespace_only_param_fails(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "products", "query", params={"keyword": "   "})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), self._REG)
        assert result == "节点 n1 缺少 required_params: keyword"

    def test_tool_not_in_registry_skipped(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        node = WorkflowNode("n1", "unknown_tool", "query", params={})
        result = LLMWorkflowPlanner._validate_required_params(_make_plan([node]), {})
        assert result is None

    def test_first_failing_node_is_reported(self) -> None:
        from app.application.workflow.planner import LLMWorkflowPlanner

        reg = {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
        nodes = [
            WorkflowNode("ok", "products", "query", params={"keyword": "x"}),
            WorkflowNode("bad", "products", "query", params={}),
        ]
        plan = PlanGraph(plan_id="p", intent="i", nodes=nodes)
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result == "节点 bad 缺少 required_params: keyword"


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

    def test_employee_intent_lists_employees_when_id_unknown(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "请员工处理订单", _SAMPLE_REGISTRY)
        assert result.intent == "employee_dispatch"
        assert result.plan_id == "pid"
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.node_id == "list_employees"
        assert node.tool_id == "employee"
        assert node.action == "list"
        assert node.params == {}
        assert result.risk_level == "low"

    def test_business_db_write_routes_to_write_node(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "新增客户ABC公司到数据库写入", _SAMPLE_REGISTRY)
        assert result.plan_id == "pid"
        assert result.intent == "business_db_write"
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.tool_id == "business_db"
        assert node.action == "write"
        assert node.params["entity"] == "customers"
        assert node.params["operation"] == "upsert"
        # Medium-risk write node lifts the plan risk to medium.
        assert result.risk_level == "medium"

    def test_business_db_read_routes_to_read_node(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "查询数据库里的产品", _SAMPLE_REGISTRY)
        assert result.intent == "business_db_read"
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.tool_id == "business_db"
        assert node.action == "read"
        assert node.params["entity"] == "products"
        assert "keyword" in node.params
        assert result.risk_level == "low"

    def test_add_product_to_unit_builds_two_dependent_nodes(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "添加新产品到客户单位", _SAMPLE_REGISTRY)
        assert result.intent == "add_product_to_unit"
        ids = [n.node_id for n in result.nodes]
        assert ids == ["check_or_create_unit", "create_product"]
        check, create = result.nodes
        assert check.tool_id == "customers"
        assert check.action == "ensure_exists"
        assert create.tool_id == "products"
        assert create.action == "create"
        # create_product depends on the unit-ensure step.
        assert create.depends_on == ["check_or_create_unit"]
        assert result.risk_level == "medium"

    def test_default_falls_back_to_product_query_with_message_keyword(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "帮我看看", _SAMPLE_REGISTRY)
        assert result.intent == "generic_workflow"
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.tool_id == "products"
        assert node.action == "query"
        # The whole message becomes the search keyword.
        assert node.params == {"keyword": "帮我看看"}

    def test_default_uses_customers_when_no_products_tool(self) -> None:
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
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.tool_id == "customers"
        assert node.action == "query"
        assert node.params == {"keyword": "帮我看看"}

    def test_risk_level_high_when_write_node_is_high(self) -> None:
        planner = self._make_planner()
        high_node = WorkflowNode("n", "t", "a", risk="high")
        with (
            patch(
                "app.application.workflow.planner._extract_business_db_write_node",
                return_value=high_node,
            ),
            patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ),
        ):
            result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.nodes == [high_node]
        assert result.risk_level == "high"

    def test_risk_level_medium_when_write_node_is_medium(self) -> None:
        planner = self._make_planner()
        medium_node = WorkflowNode("n", "t", "a", risk="medium")
        with (
            patch(
                "app.application.workflow.planner._extract_business_db_write_node",
                return_value=medium_node,
            ),
            patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ),
        ):
            result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.nodes == [medium_node]
        assert result.risk_level == "medium"

    def test_fallback_metadata_records_planner_and_message(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "帮我看看", _SAMPLE_REGISTRY)
        assert result.metadata["planner"] == "fallback"
        assert result.metadata["message"] == "帮我看看"


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

        # No API key short-circuits before any HTTP call is attempted.
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
            mock_client.return_value.post.assert_not_called()
        assert result is None

    def test_returns_none_on_http_error_status(self) -> None:
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

    def test_successful_parse_builds_plan_graph(self) -> None:
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
        assert result.plan_id == "pid"
        assert result.intent == "query_products"
        assert result.todo_steps == ["查询产品"]
        assert result.risk_level == "low"
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.node_id == "n1"
        assert node.tool_id == "products"
        assert node.action == "query"
        assert node.params == {"keyword": "ABC"}
        assert node.idempotent is True
        assert result.metadata["planner"] == "llm"

    def test_strips_markdown_fence_before_parsing(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "query_products",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {"node_id": "n1", "tool_id": "products", "action": "query", "params": {}},
            ],
        }
        resp = MagicMock()
        resp.status_code = 200
        # Content wrapped in a ```json fence — planner must strip it.
        fenced = "```json\n" + json.dumps(payload) + "\n```"
        resp.json.return_value = {"choices": [{"message": {"content": fenced}}]}

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
        assert result.intent == "query_products"
        assert result.nodes[0].tool_id == "products"

    def test_node_defaults_applied_for_missing_fields(self) -> None:
        planner = self._make_planner()
        # Node omits node_id, params, risk, idempotent, depends_on → defaults fill in.
        payload = {
            "nodes": [
                {"tool_id": "products", "action": "query"},
            ],
        }
        resp = self._mock_response(payload)

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
        # intent defaults when omitted.
        assert result.intent == "dynamic_workflow"
        assert result.risk_level == "low"
        node = result.nodes[0]
        # node_id is synthesised from the enumeration index (start=1).
        assert node.node_id == "node_1"
        assert node.params == {}
        assert node.risk == "low"
        assert node.idempotent is False
        assert node.depends_on == []

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

    def test_memory_and_probe_context_surfaced_in_metadata(self) -> None:
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
        assert result.metadata["user_memory_rag_summary"] == "用户偏好：ABC产品"
        assert result.metadata["memory_v2_summary"] == "已确认 active 记忆：ABC"
        probes = result.metadata["tool_probe_outputs"]
        assert len(probes) == 1
        assert probes[0]["tool_id"] == "products"
        assert probes[0]["success"] is True
        assert probes[0]["message"] == "ok"

    def test_request_payload_carries_model_and_auth_header(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "q",
            "nodes": [{"node_id": "n1", "tool_id": "products", "action": "query"}],
        }
        resp = self._mock_response(payload)

        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            post = mock_client.return_value.post
            post.return_value = resp
            planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
            assert post.call_count == 1
            call = post.call_args
            # api_url passed positionally; model + temperature in json body.
            assert call.args[0] == "https://api.example.com/v1/chat/completions"
            assert call.kwargs["json"]["model"] == "deepseek-chat"
            assert call.kwargs["json"]["temperature"] == 0.1
            assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"


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

        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
            create=True,
        ):
            result = planner.plan(
                user_id="u1",
                message="帮我查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        # LLM has no key → react/LLM path returns None → rule fallback produces a plan.
        assert result.metadata["planner"] == "fallback"
        assert result.plan_id
        assert len(result.nodes) == 1
        node = result.nodes[0]
        assert node.tool_id == "products"
        assert node.action == "query"
        assert node.params == {"keyword": "帮我查产品"}
        # Plan is internally consistent.
        assert validate_plan_graph(result) is None

    def test_plan_applies_profile_filter_to_registry(self) -> None:
        """normal profile must hide a pro_only tool from the fallback registry."""
        planner = self._make_planner()
        reg = {
            "products": {
                "description": "p",
                "availability": "shared",
                "actions": {
                    "query": {
                        "risk": "low",
                        "idempotent": True,
                        "availability": "shared",
                        "required_params": [],
                    }
                },
            },
            "pro_secret": {
                "description": "pro",
                "availability": "pro_only",
                "actions": {
                    "query": {
                        "risk": "low",
                        "idempotent": True,
                        "availability": "pro_only",
                        "required_params": [],
                    }
                },
            },
        }
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
            create=True,
        ):
            result = planner.plan(
                user_id="u1",
                message="帮我看看",
                tool_registry=reg,
                context={},
            )
        # Fallback chose products.query — never the filtered-out pro_secret tool.
        assert {n.tool_id for n in result.nodes} == {"products"}

    def test_plan_swallows_memory_rag_import_error(self) -> None:
        """ImportError from the memory RAG service must not propagate."""
        planner = self._make_planner()

        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
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
        # Despite the import failure, a fallback plan is still produced.
        assert result.metadata["planner"] == "fallback"
        assert len(result.nodes) >= 1


# ---------------------------------------------------------------------------
# _get_planner_http_client singleton
# ---------------------------------------------------------------------------


class TestGetPlannerHttpClient:
    def test_returns_cached_singleton(self) -> None:
        import httpx

        import app.application.workflow.planner as planner_mod

        planner_mod._planner_http_client = None
        try:
            client1 = _get_planner_http_client()
            client2 = _get_planner_http_client()
            assert isinstance(client1, httpx.Client)
            # Second call reuses the exact same cached instance.
            assert client1 is client2
            # Cached on the module global, not rebuilt each call.
            assert planner_mod._planner_http_client is client1
        finally:
            planner_mod._planner_http_client = None

    def test_rebuilds_after_reset(self) -> None:
        import app.application.workflow.planner as planner_mod

        planner_mod._planner_http_client = None
        try:
            first = _get_planner_http_client()
            planner_mod._planner_http_client = None
            second = _get_planner_http_client()
            # After clearing the global a fresh client is constructed.
            assert second is not first
        finally:
            planner_mod._planner_http_client = None
