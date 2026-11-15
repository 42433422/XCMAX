"""计划修复闭环：错误分类、最小修改约束与规划器接线。"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from app.application.workflow.llm_plan_generation import _load_model_json
from app.application.workflow.plan_repair import (
    classify_plan_error,
    enforce_repair_scope,
    repair_plan,
)
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def _node(
    node_id: str,
    *,
    tool_id: str = "products",
    action: str = "query",
    params: dict | None = None,
    risk: str = "low",
) -> WorkflowNode:
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params if params is not None else {},
        risk=risk,
        idempotent=True,
    )


def _plan(*nodes: WorkflowNode) -> PlanGraph:
    return PlanGraph(plan_id="p1", intent="demo", nodes=list(nodes), metadata={})


def _completion(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_classify_plan_error_maps_known_failures() -> None:
    assert classify_plan_error("节点 n1 使用未授权动作: products.delete") == "unauthorized_action"
    assert classify_plan_error("节点 n1 缺少 required_params: keyword") == "missing_param"
    assert classify_plan_error("节点 n1 参数预检失败：引用不存在") == "bad_reference"
    assert classify_plan_error("计划图存在成环") == "graph_cycle"
    assert classify_plan_error("某种未知错误") == "graph_invalid"


def test_repair_plan_fixes_missing_param() -> None:
    planned = _plan(_node("n1"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        if not plan.nodes[0].params.get("keyword"):
            return "节点 n1 缺少 required_params: keyword"
        return None

    def complete(**kwargs):
        calls.append(kwargs)
        return _completion(
            {
                "mode": "workflow",
                "intent": "demo",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {"keyword": "木门"},
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is not None
    assert fixed.nodes[0].params["keyword"] == "木门"
    assert trace["fixed"] is True
    assert trace["attempts"] == 1
    assert trace["first_pass_valid"] is False
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.0


def test_repair_rejects_changes_to_unmentioned_nodes() -> None:
    planned = _plan(
        _node("n1"),
        _node("n2", action="export", params={"keyword": "a"}),
    )

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 缺少 required_params: keyword"

    def complete(**kwargs):
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {"keyword": "木门"},
                    },
                    {
                        "node_id": "n2",
                        "tool_id": "products",
                        "action": "export",
                        "params": {"keyword": "被篡改"},
                    },
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门并导出",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is None
    assert any(item["code"] == "scope_violation" for item in trace["errors"])
    assert "未报错" in trace["errors"][-1]["message"]


def test_repair_rejects_risk_downgrade() -> None:
    planned = _plan(_node("n1", risk="high"))

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 使用未授权动作: products.delete"

    def complete(**kwargs):
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "delete",
                        "params": {},
                        "risk": "low",
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="删除产品",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is None
    assert any("风险等级" in item["message"] for item in trace["errors"])


def test_non_repairable_shape_skips_model_call() -> None:
    planned = _plan(_node("reply", tool_id="conversation", action="reply"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        return "普通回复计划必须是唯一的内部 conversation.reply 节点"

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="你好",
        context={},
        tool_registry={},
        validate=validate,
        complete=lambda **kwargs: calls.append(kwargs),
    )

    assert fixed is None
    assert calls == []
    assert trace["errors"][0]["code"] == "reply_shape"


def test_repair_stops_after_attempt_limit() -> None:
    planned = _plan(_node("n1"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 缺少 required_params: keyword"

    def complete(**kwargs):
        calls.append(kwargs)
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {},
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
        max_attempts=2,
    )

    assert fixed is None
    assert trace["attempts"] == 2
    assert len(calls) == 2


def test_enforce_scope_allows_fixing_mentioned_node() -> None:
    original = _plan(_node("n1"))
    candidate = _plan(_node("n1", params={"keyword": "门"}))
    assert (
        enforce_repair_scope(original, candidate, "节点 n1 缺少 required_params: keyword") is None
    )


def test_model_json_falls_back_to_repair() -> None:
    parsed = _load_model_json('{"mode":"workflow","nodes":[{"node_id":"n1",}]}')
    assert parsed["nodes"][0]["node_id"] == "n1"


def test_planner_records_repair_trace(monkeypatch) -> None:
    ai = Mock()
    ai.get_context.return_value = None
    planner = LLMWorkflowPlanner(ai_service=ai)
    reply_node = _node("reply", tool_id="conversation", action="reply", params={"response": "ok"})
    broken = _plan(reply_node)
    broken.metadata = {"response_mode": "reply", "reply": "ok"}
    fixed = _plan(reply_node)
    fixed.metadata = {"response_mode": "reply", "reply": "ok"}

    monkeypatch.setattr(planner, "_plan_with_llm", lambda *args, **kwargs: broken)
    monkeypatch.setattr(
        "app.application.workflow.plan_repair.repair_plan",
        lambda **kwargs: (
            fixed,
            {"attempts": 1, "errors": [], "fixed": True, "first_pass_valid": False},
        ),
    )
    monkeypatch.setattr(
        "app.application.workflow.planner.validate_plan_graph", lambda plan: None, raising=False
    )

    result = planner.plan("7", "查木门", {}, context={"session_id": "s1"})

    assert result is fixed
    assert result.metadata["plan_repair"]["fixed"] is True
    assert result.metadata["plan_repair"]["attempts"] == 1


@pytest.mark.parametrize("risk", ["low", "medium", "high"])
def test_enforce_scope_never_raises_on_same_plan(risk: str) -> None:
    original = _plan(_node("n1", risk=risk))
    assert enforce_repair_scope(original, _plan(_node("n1", risk=risk)), "") is None
