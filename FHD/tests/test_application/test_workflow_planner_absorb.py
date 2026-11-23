"""Formal graph validation retains conditional-edge and clarification safety."""

from app.application.workflow.clarification_node import build_clarify_node, insert_clarify_node
from app.application.workflow.workflow_types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    validate_plan_graph,
)


class TestValidateDecoratedGraph:
    def test_graph_accepts_conditional_and_clarify_graph(self):
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

        assert validate_plan_graph(plan) is None
        assert any(n.tool_id == "clarify" for n in plan.nodes)

    def test_graph_rejects_clarify_with_missing_target(self):
        bad_clarify = build_clarify_node("确定删除哪个？", ambient={"target_node_id": "ghost_node"})
        plan = PlanGraph(
            plan_id="p_bad",
            intent="x",
            nodes=[bad_clarify],
        )
        error = validate_plan_graph(plan)
        assert error and "ghost_node" in error
