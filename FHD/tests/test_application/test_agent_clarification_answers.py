from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import apply_clarification_answer
from app.application.workflow.clarification_node import build_clarify_node
from app.application.workflow.types import PlanGraph, WorkflowNode


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
    nodes.append(
        WorkflowNode(
            node_id="write", tool_id="products", action="create", params={"name_or_model": "A100"}
        )
    )
    run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="u1",
        message="新增产品",
        plan=PlanGraph(plan_id="p", intent="create", nodes=nodes),
    )
    apply_clarification_answer(
        run, step_id=run.steps[0].step_id, parameters={"unit_name": "客户甲"}
    )
    assert [step.status for step in run.steps] == ["completed", "completed", "pending", "pending"]
    assert run.steps[3].params == {"name_or_model": "A100", "unit_name": "客户甲"}


def test_clarification_metadata_does_not_share_mutable_candidates():
    detail = {"reason": "ambiguous_target", "candidates": [{"id": 1, "name": "客户甲"}]}
    node = build_clarify_node("请选择客户", ambient={"clarification": detail})
    detail["candidates"][0]["id"] = 99
    assert node.params["clarification"]["candidates"][0]["id"] == 1
