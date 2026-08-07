"""Tests for planner absorbing conditional edges (branches) and clarify (反问) nodes.

Covers:
  - planner produces a PlanGraph with ``branches`` for "查库存 → 按 low_stock 分支"（确定性规则）;
  - planner inserts a ``clarify`` node for "删除客户（多同名）"（歧义反问）;
  - finalize_planned_graph validates graphs containing conditional edges / clarify nodes.
"""

from __future__ import annotations

import pytest

from app.application.workflow.clarification_node import build_clarify_node, insert_clarify_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode, validate_plan_graph
from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph


def _make_planner() -> LLMWorkflowPlanner:
    from unittest.mock import patch

    with patch("app.application.workflow.planner.get_ai_conversation_service"):
        return LLMWorkflowPlanner()


def _customers_registry() -> dict:
    return {
        "customers": {
            "actions": {
                "query": {"risk": "low", "idempotent": True},
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                },
            }
        }
    }


def _ambiguous_delete_plan(plan_id: str = "p_delete") -> PlanGraph:
    delete_node = WorkflowNode(
        node_id="delete_customer",
        tool_id="customers",
        action="delete",
        params={
            "_candidates": [
                {"id": "cust_1", "name": "北京智造科技"},
                {"id": "cust_2", "name": "北京智造科技"},
            ]
        },
        risk="high",
        idempotent=False,
        description="删除客户",
    )
    return PlanGraph(
        plan_id=plan_id,
        intent="delete_customer",
        todo_steps=["查询候选", "确认目标", "删除客户"],
        nodes=[delete_node],
        risk_level="high",
    )


# ===========================================================================
# 规划器：查库存 → low_stock 分支（确定性规则，走 fallback 路径）
# ===========================================================================


class TestPlannerConditionalEdges:
    def test_inventory_purchase_plan_has_low_stock_branch(self):
        from unittest.mock import patch

        from app.application.workflow.planner import get_tool_registry

        planner = _make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError,
            ),
        ):
            plan = planner.plan("u1", "查一下库存，库存不足就安排采购", get_tool_registry())

        assert plan.intent == "inventory_purchase"
        check = next(n for n in plan.nodes if n.node_id == "check_stock")
        assert check.tool_id == "inventory"
        assert check.action == "check_stock"
        assert check.branches == [
            Branch(target="purchase_advice", condition={"key": "low_stock", "equals": True})
        ]
        assert any(n.node_id == "purchase_advice" for n in plan.nodes)
        # 条件边必须通过图校验（目标存在、无环）。
        assert validate_plan_graph(plan) is None

    def test_non_inventory_message_has_no_branch(self):
        from unittest.mock import patch

        from app.application.workflow.planner import get_tool_registry

        planner = _make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=None),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError,
            ),
        ):
            plan = planner.plan("u1", "查询一些产品信息", get_tool_registry())

        assert all(not n.branches for n in plan.nodes)


# ===========================================================================
# 规划器：删除客户（多同名）→ 图首部插入 clarify 节点
# ===========================================================================


class TestPlannerClarifyNode:
    def test_ambiguous_delete_inserts_clarify_at_head(self):
        from unittest.mock import patch

        planner = _make_planner()
        with (
            patch.object(
                planner, "_plan_with_react_multiagent", return_value=_ambiguous_delete_plan()
            ),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError,
            ),
        ):
            plan = planner.plan("u1", "删除客户：北京智造科技", _customers_registry())

        # 反问节点必须位于图首部，且分支目标指向原删除节点。
        assert plan.nodes[0].tool_id == "clarify"
        clarify = plan.nodes[0]
        assert clarify.action == "ask"
        assert clarify.params["target_node_id"] == "delete_customer"
        assert clarify.branches == [
            Branch(target="delete_customer", condition={"key": "answer_confirmed", "equals": True})
        ]
        assert any(n.node_id == "delete_customer" for n in plan.nodes)
        assert validate_plan_graph(plan) is None

    def test_read_only_plan_gets_no_clarify(self):
        from unittest.mock import patch

        plan_in = PlanGraph(
            plan_id="p_read",
            intent="query",
            nodes=[
                WorkflowNode(
                    node_id="query_customers",
                    tool_id="customers",
                    action="query",
                    params={},
                    risk="low",
                    idempotent=True,
                )
            ],
        )
        planner = _make_planner()
        with (
            patch.object(planner, "_plan_with_react_multiagent", return_value=plan_in),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError,
            ),
        ):
            plan = planner.plan("u1", "看看有哪些客户", _customers_registry())

        assert all(n.tool_id != "clarify" for n in plan.nodes)


# ===========================================================================
# finalize_planned_graph：含条件边 / 反问节点的图校验通过
# ===========================================================================


class TestFinalizeValidateDecoratedGraph:
    def _noop_warn(self, _msg: str) -> None:
        pass

    def test_finalize_accepts_conditional_and_clarify_graph(self):
        check = WorkflowNode(
            node_id="check_stock",
            tool_id="inventory",
            action="check_stock",
            risk="low",
            idempotent=True,
            branches=[
                Branch(target="purchase_advice", condition={"key": "low_stock", "equals": True})
            ],
        )
        purchase = WorkflowNode(
            node_id="purchase_advice",
            tool_id="purchase",
            action="advice",
            risk="low",
            idempotent=True,
            depends_on=["check_stock"],
        )
        delete = WorkflowNode(
            node_id="delete_customer",
            tool_id="customers",
            action="delete",
            params={"_candidates": [{"id": "c1"}, {"id": "c2"}]},
            risk="high",
            idempotent=False,
        )
        clarify = build_clarify_node(
            "确定删除哪个？", ambient={"target_node_id": "delete_customer"}
        )
        plan = PlanGraph(
            plan_id="p_mixed",
            intent="mixed",
            nodes=[check, purchase, delete],
        )
        insert_clarify_node(plan, clarify)

        result = finalize_planned_graph(
            plan,
            plan_id="p_mixed",
            context={},
            validate=validate_plan_graph,
            fallback_factory=lambda: (_ for _ in ()).throw(AssertionError("不应回退")),
            warn=self._noop_warn,
        )
        assert result is plan
        assert any(n.tool_id == "clarify" for n in result.nodes)

    def test_finalize_rejects_clarify_with_missing_target(self):
        bad_clarify = build_clarify_node("确定删除哪个？", ambient={"target_node_id": "ghost_node"})
        plan = PlanGraph(
            plan_id="p_bad",
            intent="x",
            nodes=[bad_clarify],
        )
        fallback = PlanGraph(plan_id="p_fallback", intent="generic", nodes=[])
        result = finalize_planned_graph(
            plan,
            plan_id="p_bad",
            context={},
            validate=validate_plan_graph,
            fallback_factory=lambda: fallback,
            warn=self._noop_warn,
        )
        assert result is fallback
