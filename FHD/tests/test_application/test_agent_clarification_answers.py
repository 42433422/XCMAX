from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import apply_clarification_answer
from app.application.workflow.clarification_node import build_clarify_node
from app.application.workflow.types import PlanGraph, WorkflowNode


def test_stock_in_asks_warehouse_name_then_requires_approval():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("inbound", "产品 A100 入库 50 件", get_workflow_tool_registry())
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(user_id="owner", message="入库", plan=plan)
    assert run.status == "waiting_user"
    assert run.final_output["clarification"]["fields"] == [
        {"key": "warehouse_name", "label": "入库仓库名称", "type": "string"}
    ]
    assert run.tool_calls == []
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"warehouse_name": "主仓库"},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.status == "waiting_user"
    assert continued.steps[-1].status == "waiting_user"
    assert continued.steps[-1].params == {
        "model_number": "A100",
        "quantity": 50,
        "warehouse_name": "主仓库",
    }
    assert continued.tool_calls == []


def test_quote_missing_price_preserves_quantity_and_requires_approval():
    from copy import deepcopy

    import pytest

    from app.application.agent_orchestrator.clarification import ClarificationAnswerError
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan(
        "quote-input", "给客户甲的产品A100报个价，数量2", get_workflow_tool_registry()
    )
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(user_id="owner", message="报价", plan=plan)
    assert run.status == "waiting_user"
    assert run.final_output["clarification"]["fields"] == [
        {"key": "items.0.unit_price", "label": "A100 · 单价", "type": "number"}
    ]
    before = deepcopy(run.to_dict())
    with pytest.raises(ClarificationAnswerError):
        apply_clarification_answer(
            run,
            step_id=run.steps[0].step_id,
            parameters={"items.0.quantity": 99, "items.0.unit_price": 50},
        )
    assert run.to_dict() == before
    with pytest.raises(ClarificationAnswerError):
        apply_clarification_answer(
            run, step_id=run.steps[0].step_id, parameters={"items.0.unit_price": -1}
        )
    assert run.to_dict() == before
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"items.0.unit_price": 50},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.status == "waiting_user"
    assert continued.tool_calls == []
    assert continued.steps[-1].params["items"] == [
        {"model_number": "A100", "quantity": 2, "unit_price": 50}
    ]


def test_named_quote_answer_stops_at_write_approval():
    params = {"items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
    question = build_clarify_node(
        "请提供客户名称",
        ambient={"target_node_id": "quote", "clarification": {"reason": "missing_required"}},
    )
    quote = WorkflowNode(node_id="quote", tool_id="sales", action="quote", params=params)
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="报价",
        plan=PlanGraph(plan_id="named-quote", intent="sales", nodes=[question, quote]),
    )
    assert run.final_output["clarification"]["fields"] == [
        {"key": "customer_name", "label": "客户名称", "type": "string"}
    ]
    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"customer_name": "客户甲"},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.status == "waiting_user"
    assert continued.steps[1].status == "waiting_user"
    assert continued.steps[1].params == {**params, "customer_name": "客户甲"}
    assert continued.tool_calls == []


def test_answer_resolves_duplicate_missing_inputs_but_preserves_other_confirmation():
    nodes = [
        build_clarify_node(
            "请提供客户",
            ambient={
                "target_node_id": "write",
                "clarification": {"reason": reason},
            },
        )
        for reason in ("missing_required", "missing_required", "credit_limit_exceed")
    ]
    nodes.append(WorkflowNode(node_id="write", tool_id="customers", action="create", params={}))
    run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="u1",
        message="新增产品",
        plan=PlanGraph(plan_id="p", intent="create", nodes=nodes),
    )
    apply_clarification_answer(
        run, step_id=run.steps[0].step_id, parameters={"unit_name": "客户甲"}
    )
    assert [step.status for step in run.steps] == ["completed", "completed", "pending", "pending"]
    assert run.steps[3].params == {"unit_name": "客户甲"}


def test_clarification_metadata_does_not_share_mutable_candidates():
    detail = {"reason": "ambiguous_target", "candidates": [{"id": 1, "name": "客户甲"}]}
    node = build_clarify_node("请选择客户", ambient={"clarification": detail})
    detail["candidates"][0]["id"] = 99
    assert node.params["clarification"]["candidates"][0]["id"] == 1
