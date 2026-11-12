"""Behavior of injectable plan generation and bounded, read-only refinement."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.workflow.llm_plan_generation import LlmPlanGeneration
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def test_generation_uses_injected_transport_and_retains_request_evidence():
    conversation = SimpleNamespace(
        get_context=lambda _: SimpleNamespace(
            conversation_history=[{"role": "user", "content": "之前"}]
        )
    )
    payload = {
        "intent": "stock_read",
        "risk_level": "low",
        "nodes": [
            {
                "node_id": "stock",
                "tool_id": "inventory",
                "action": "read",
                "params": {"id": 7},
                "idempotent": True,
            }
        ],
    }
    completion = Mock(
        return_value={
            "choices": [{"message": {"content": "```json\n" + json.dumps(payload) + "\n```"}}]
        }
    )
    direct_client = Mock(side_effect=AssertionError("injected completion must own transport"))
    generator = LlmPlanGeneration(conversation, completion, direct_client)

    plan = generator.generate(
        "plan-1",
        "owner",
        "查询库存",
        {},
        {"memory_v2": {"summary": "已确认偏好"}},
    )

    assert plan.plan_id == "plan-1" and plan.nodes[0].params == {"id": 7}
    assert plan.metadata["memory_v2_summary"] == "已确认偏好"
    request = json.loads(completion.call_args.kwargs["messages"][1]["content"])
    assert request["recent_messages"] == [{"role": "user", "content": "之前"}]
    direct_client.assert_not_called()


def test_missing_model_plan_fails_closed_without_second_chat_executor(monkeypatch):
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock()
    planner.plan.return_value = None
    risk_gate = Mock()
    approval = Mock()
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry",
        lambda: {},
    )

    dispatch = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval)
    result = dispatch.handle(
        "owner",
        "查询当前库存",
        "pro",
        {"session_id": "session-1"},
        "查询当前库存",
    )

    assert result["success"] is False
    assert result["data"]["action"] == "workflow_planning_failed"
    assert result["data"]["execution_started"] is False
    risk_gate.evaluate.assert_not_called()


def test_plan_check_rejects_unregistered_tool_before_execution():
    plan = PlanGraph(
        plan_id="untrusted-plan",
        intent="query",
        nodes=[WorkflowNode("n1", "model_invented_tool", "delete", params={})],
    )

    error = validate_required_params(plan, {})

    assert error and "未授权工具" in error


def test_plan_check_owns_required_parameter_validation(monkeypatch):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import tool_spec

    monkeypatch.setattr(
        tool_spec,
        "validate_tool_call",
        lambda *_args, **_kwargs: SimpleNamespace(ok=True, message=""),
    )
    registry = {
        "catalog": {
            "actions": {
                "lookup": {
                    "required_params": ["sku"],
                    "risk": "low",
                    "idempotent": True,
                }
            }
        }
    }
    plan = PlanGraph(
        plan_id="checked-plan",
        intent="query",
        nodes=[WorkflowNode("n1", "catalog", "lookup", params={})],
    )

    error = validate_required_params(plan, registry)

    assert error and "sku" in error


def test_rejected_model_plan_never_enters_agent_run(monkeypatch):
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock()
    planner.plan.return_value = PlanGraph(
        plan_id="rejected-plan",
        intent="plan_rejected",
        metadata={"planning_rejected": True, "rejection_reason": "unsupported action"},
    )
    risk_gate = Mock()
    approval = Mock()
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry",
        lambda: {},
    )
    dispatch = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval)

    result = dispatch.handle("owner", "删除全部客户", "pro", {}, "删除全部客户")

    assert result["success"] is False
    assert result["data"]["execution_started"] is False
    assert result["data"]["error_code"] == "workflow_plan_rejected"
    risk_gate.evaluate.assert_not_called()


def test_missing_model_result_is_not_reported_as_invalid_business_plan(monkeypatch):
    from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

    plan = finalize_planned_graph(
        None,
        plan_id="missing",
        context={},
        validate=lambda _: None,
        warn=lambda _: None,
        plan_type=PlanGraph,
        node_type=WorkflowNode,
    )
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock()
    planner.plan.return_value = plan
    risk_gate = Mock()
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry", lambda: {}
    )
    result = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, Mock()).handle(
        "owner", "你好", "pro", {}, "你好"
    )
    assert result["data"]["error_code"] == "workflow_plan_unavailable"
    assert "模型连接" in result["response"]
    assert result["data"]["execution_started"] is False
    risk_gate.evaluate.assert_not_called()


def test_autonomy_guard_denial_stops_before_agent_run():
    from app.domain.autonomy.risk_types import RiskDecision, RiskLevel

    node = WorkflowNode("n1", "catalog", "write", params={})
    plan = PlanGraph(plan_id="denied-plan", intent="write", nodes=[node])
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock()
    planner.plan.return_value = plan
    risk_gate = Mock()
    risk_gate.evaluate.return_value = RiskDecision(
        requires_confirmation=False,
        reason="action denied by policy",
        blocking_nodes=[],
        allowed=False,
        risk_level=RiskLevel.BLOCKED,
        decision="blocked",
        denied_nodes=["n1"],
    )
    approval = Mock()
    dispatch = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval)

    result = dispatch.handle("owner", "删除全部客户", "pro", {}, "删除全部客户")

    assert result["success"] is False
    assert result["data"]["action"] == "workflow_risk_rejected"
    assert result["data"]["execution_started"] is False
    callbacks._merge_tool_runtime_context.assert_not_called()


def test_autonomy_guard_approval_is_attached_even_when_approval_registry_disagrees():
    from app.domain.autonomy.risk_types import RiskDecision, RiskLevel

    plan = PlanGraph(
        plan_id="approval-plan",
        intent="write",
        todo_steps=["create record"],
        nodes=[WorkflowNode("n1", "catalog", "write", params={})],
    )
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    callbacks._merge_tool_runtime_context.return_value = {"tenant_id": "1"}
    callbacks._build_workflow_thinking_steps.return_value = "checked plan"
    callbacks._persist_plan_state.return_value = True
    planner = Mock()
    planner.plan.return_value = plan
    risk_gate = Mock()
    risk_gate.evaluate.return_value = RiskDecision(
        requires_confirmation=True,
        reason="repeat action requires human review",
        blocking_nodes=["n1"],
        allowed=False,
        risk_level=RiskLevel.MEDIUM,
        decision="require_human",
    )
    approval = Mock()
    approval.get_approval_required_nodes.return_value = []
    dispatch = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval)

    result = dispatch.handle("owner", "创建记录", "pro", {}, "创建记录")

    assert result["data"]["action"] == "workflow_confirmation_required"
    assert dispatch.pending["owner"]["approval_required"] is True
    assert [item["node_id"] for item in dispatch.pending["owner"]["approval_nodes"]] == ["n1"]


def test_auto_approval_mode_skips_plan_confirmation_and_starts_run():
    from app.domain.autonomy.risk_types import RiskDecision, RiskLevel

    plan = PlanGraph(
        plan_id="auto-approval-plan",
        intent="write",
        todo_steps=["create record"],
        nodes=[WorkflowNode("n1", "catalog", "write", params={})],
    )
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    callbacks._merge_tool_runtime_context.return_value = {
        "tenant_id": "1",
        "chat_approval_mode": "auto",
    }
    callbacks._build_workflow_thinking_steps.return_value = "checked plan"
    callbacks._capture_agent_run_interaction.return_value = {
        "data": {"action": "workflow_done"}
    }
    planner = Mock()
    planner.plan.return_value = plan
    risk_gate = Mock()
    risk_gate.evaluate.return_value = RiskDecision(
        requires_confirmation=True,
        reason="write needs approval",
        blocking_nodes=["n1"],
        allowed=False,
        risk_level=RiskLevel.MEDIUM,
        decision="require_human",
    )
    approval = Mock()
    approval.get_approval_required_nodes.return_value = [plan.nodes[0]]
    dispatch = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval)

    with patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator:
        orchestrator.return_value.start_run_from_plan.return_value = SimpleNamespace(
            status="waiting_user"
        )
        dispatch.handle("owner", "创建记录", "pro", {}, "创建记录")

    orchestrator.return_value.start_run_from_plan.assert_called_once()
    callbacks._capture_agent_run_interaction.assert_called_once()
    assert "owner" not in dispatch.pending
