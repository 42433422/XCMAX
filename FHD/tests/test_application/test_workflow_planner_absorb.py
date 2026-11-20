"""Tests for model plan admission, conditional edges (branches) and clarify nodes.

Covers:
  - deterministic preflight adds a clarify node to an incomplete model plan;
  - finalize_planned_graph validates graphs containing conditional edges / clarify nodes.
"""

from __future__ import annotations

import json

import pytest

from app.application.workflow.clarification_node import build_clarify_node, insert_clarify_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    validate_plan_graph,
)
from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph
from tests.fixtures.planner_model import goal_review_response
from tests.pure_builders import customers_registry as _customers_registry


def _make_planner(completion=None) -> LLMWorkflowPlanner:
    from unittest.mock import patch

    with patch("app.application.workflow.planner.get_ai_conversation_service"):
        return LLMWorkflowPlanner(completion=completion)


@pytest.mark.parametrize("kind", ["reply", "clarify"])
def test_batch_import_can_ask_for_clarification_before_planning_writes(monkeypatch, kind):
    question = "请确认这两份文件分别导入什么数据？"
    if kind == "reply":
        node = WorkflowNode("reply", "conversation", "reply", params={"response": question})
        metadata = {"response_mode": "reply", "reply": question, "planning_tier": "light"}
    else:
        node = WorkflowNode("question", "clarify", "ask", params={"question": question})
        metadata = {}
    planner = _make_planner()
    monkeypatch.setattr(
        planner,
        "_plan_with_llm",
        lambda *args: PlanGraph(
            plan_id="p",
            intent="clarification",
            nodes=[node],
            metadata=metadata,
        ),
    )
    files = [
        {"id": "one", "name": "one.xlsx", "suffix": ".xlsx"},
        {"id": "two", "name": "two.xlsx", "suffix": ".xlsx"},
    ]
    result = planner.plan(
        "1",
        "导入",
        {"elt_import": {"actions": {"execute": {}}}},
        {
            "artifact_ids": ["one", "two"],
            "file_context": {"attachment_manifest": files},
        },
    )
    assert not result.metadata.get("planning_rejected")
    assert len(result.nodes) == 1
    assert (result.nodes[0].tool_id, result.nodes[0].action) == ("conversation", "reply")
    assert result.nodes[0].params["response"] == question


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


# ===========================================================================
# 规划器：删除客户（多同名）→ 图首部插入 clarify 节点
# ===========================================================================


class TestPlannerClarifyNode:
    def test_ambiguous_delete_inserts_clarify_at_head(self):
        from unittest.mock import patch

        planner = _make_planner(
            completion=lambda **kwargs: goal_review_response(
                json.loads(kwargs["messages"][1]["content"]),
                source="删除客户：北京智造科技",
                node_ids=["clarify_delete_customer", "delete_customer"],
                outcome="clarify",
            )
        )
        with (
            patch.object(planner, "_plan_with_llm", return_value=_ambiguous_delete_plan()),
            patch(
                "app.application.workflow.planning_graph_policy.build_clarify_node",
                side_effect=lambda question, ambient: build_clarify_node(
                    question, {**ambient, "node_id": "clarify_delete_customer"}
                ),
            ),
            patch(
                "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.domain.shared_services.user_memory_service.get_user_memory_service",
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
        planner = _make_planner(
            completion=lambda **kwargs: goal_review_response(
                json.loads(kwargs["messages"][1]["content"]),
                source="看看有哪些客户",
                node_ids=["query_customers"],
                outcome="execute",
            )
        )
        with (
            patch.object(planner, "_plan_with_llm", return_value=plan_in),
            patch(
                "app.application.workflow.tool_profile.resolve_tool_execution_profile",
                return_value="full",
            ),
            patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
            patch(
                "app.domain.shared_services.user_memory_service.get_user_memory_service",
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
            warn=self._noop_warn,
            plan_type=PlanGraph,
            node_type=WorkflowNode,
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
        result = finalize_planned_graph(
            plan,
            plan_id="p_bad",
            context={},
            validate=validate_plan_graph,
            warn=self._noop_warn,
            plan_type=PlanGraph,
            node_type=WorkflowNode,
        )
        assert result.metadata["planning_rejected"] is True
        assert result.nodes[0].tool_id == "clarify"


def test_read_plan_without_independent_review_is_not_admitted():
    from unittest.mock import patch

    planner = _make_planner(completion=lambda **kwargs: None)
    candidate = PlanGraph(
        plan_id="read-without-review",
        intent="query",
        nodes=[WorkflowNode(node_id="query_customers", tool_id="customers", action="query")],
    )
    with patch.object(planner, "_plan_with_llm", return_value=candidate):
        rejected = planner.plan("u1", "看看有哪些客户", _customers_registry())
    assert rejected.metadata["planning_rejected"] is True
    assert "目标覆盖" in rejected.metadata["rejection_reason"]
    assert all(node.tool_id == "clarify" for node in rejected.nodes)
