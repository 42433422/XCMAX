from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import apply_clarification_answer
from app.application.workflow.clarification_node import build_clarify_node
from app.application.workflow.types import PlanGraph, WorkflowNode


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
