"""Tests for conditional edges in app.application.workflow.

Covers:
  - evaluate_branch: matches output against branch conditions,
  - engine routing: check_stock -> low_stock==true -> purchase_advice (exclusive),
  - engine routing: no condition match falls back to ``next`` default successor,
  - engine routing: no match and no ``next`` ends normally,
  - validate_plan_graph: missing / self / cycle detection for conditional edges.
"""

from __future__ import annotations

import pytest

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    validate_plan_graph,
)


def _make_engine(low_stock: bool):
    def dispatch(tool_id, action, params):
        if action == "check_stock":
            return {"success": True, "low_stock": low_stock}
        return {"success": True}

    return WorkflowEngine(tool_dispatcher=dispatch)


def _conditional_plan() -> PlanGraph:
    nodes = [
        WorkflowNode(
            node_id="check_stock",
            tool_id="inventory",
            action="check_stock",
            risk="low",
            idempotent=True,
            branches=[
                Branch(target="purchase_advice", condition={"key": "low_stock", "equals": True})
            ],
            next="normal_advice",
        ),
        WorkflowNode(
            node_id="purchase_advice",
            tool_id="purchase",
            action="advice",
            risk="low",
            idempotent=True,
            depends_on=["check_stock"],
        ),
        WorkflowNode(
            node_id="normal_advice",
            tool_id="inventory",
            action="normal_advice",
            risk="low",
            idempotent=True,
            depends_on=["check_stock"],
        ),
    ]
    return PlanGraph(plan_id="p_cond", intent="conditional", nodes=nodes)


def _executed(engine, plan):
    return set(engine.run(plan).final_context["workflow_status"]["executed_nodes"])


# ===========================================================================
# evaluate_branch
# ===========================================================================


class TestEvaluateBranch:
    def test_matches_first_condition(self):
        node = WorkflowNode(
            node_id="n1",
            tool_id="t",
            action="a",
            branches=[
                Branch(target="low", condition={"key": "low_stock", "equals": True}),
                Branch(target="high", condition={"key": "low_stock", "equals": False}),
            ],
        )
        assert WorkflowEngine.evaluate_branch(node, {"low_stock": True}) == "low"
        assert WorkflowEngine.evaluate_branch(node, {"low_stock": False}) == "high"

    def test_no_match_returns_none(self):
        node = WorkflowNode(
            node_id="n1",
            tool_id="t",
            action="a",
            branches=[Branch(target="low", condition={"key": "low_stock", "equals": True})],
        )
        assert WorkflowEngine.evaluate_branch(node, {"low_stock": False}) is None
        assert WorkflowEngine.evaluate_branch(node, {}) is None

    def test_non_dict_output_returns_none(self):
        node = WorkflowNode(
            node_id="n1",
            tool_id="t",
            action="a",
            branches=[Branch(target="low", condition={"key": "low_stock", "equals": True})],
        )
        assert WorkflowEngine.evaluate_branch(node, "oops") is None


# ===========================================================================
# engine conditional routing
# ===========================================================================


class TestEngineConditionalRouting:
    def test_condition_match_routes_to_purchase(self):
        engine = _make_engine(low_stock=True)
        result = engine.run(_conditional_plan())
        assert result.success is True
        assert _executed(engine, _conditional_plan()) == {"check_stock", "purchase_advice"}

    def test_condition_no_match_uses_next(self):
        engine = _make_engine(low_stock=False)
        assert _executed(engine, _conditional_plan()) == {"check_stock", "normal_advice"}

    def test_no_match_and_no_next_ends_normally(self):
        def dispatch(tool_id, action, params):
            return {"success": True, "flag": False}

        engine = WorkflowEngine(tool_dispatcher=dispatch)
        plan = PlanGraph(
            plan_id="p_gate",
            intent="gate",
            nodes=[
                WorkflowNode(
                    node_id="gate",
                    tool_id="x",
                    action="y",
                    risk="low",
                    idempotent=True,
                    branches=[Branch(target="target", condition={"key": "flag", "equals": True})],
                ),
                WorkflowNode(
                    node_id="target",
                    tool_id="z",
                    action="w",
                    risk="low",
                    idempotent=True,
                    depends_on=["gate"],
                ),
            ],
        )
        result = engine.run(plan)
        assert result.success is True
        assert _executed(engine, plan) == {"gate"}


# ===========================================================================
# validate_plan_graph conditional-edge checks
# ===========================================================================


class TestValidateConditionalGraph:
    def test_missing_branch_target(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="t",
                    action="a",
                    branches=[Branch(target="n_missing", condition={})],
                )
            ],
        )
        assert validate_plan_graph(plan) == "节点 n1 的 branch 目标不存在: n_missing"

    def test_missing_next_target(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", next="n_missing")],
        )
        assert validate_plan_graph(plan) == "节点 n1 的 next 目标不存在: n_missing"

    def test_next_cannot_point_to_self(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", next="n1")],
        )
        assert "next 不能指向自身" in validate_plan_graph(plan)

    def test_branch_cannot_point_to_self(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="t",
                    action="a",
                    branches=[Branch(target="n1", condition={"key": "x", "equals": 1})],
                )
            ],
        )
        assert "branch 不能指向自身" in validate_plan_graph(plan)

    def test_cycle_detected(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="t1", action="a1", next="n2"),
                WorkflowNode(
                    node_id="n2",
                    tool_id="t2",
                    action="a2",
                    branches=[Branch(target="n1", condition={"key": "x", "equals": 1})],
                ),
            ],
        )
        assert "环" in validate_plan_graph(plan)

    def test_valid_conditional_graph(self):
        plan = PlanGraph(
            plan_id="p",
            intent="x",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="t",
                    action="a",
                    branches=[Branch(target="n2", condition={"key": "x", "equals": 1})],
                    next="n3",
                ),
                WorkflowNode(node_id="n2", tool_id="t", action="a", depends_on=["n1"]),
                WorkflowNode(node_id="n3", tool_id="t", action="a", depends_on=["n1"]),
            ],
        )
        assert validate_plan_graph(plan) is None
