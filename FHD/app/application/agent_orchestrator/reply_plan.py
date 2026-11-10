"""Execute only the planner's single, side-effect-free reply graph."""

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.workflow.workflow_types import PlanGraph, validate_plan_graph


def execute_reply_plan(run: AgentRun, plan: PlanGraph, context: dict[str, Any]) -> bool:
    if plan.metadata.get("response_mode") != "reply":
        return False
    nodes = plan.nodes
    text = str(plan.metadata.get("reply") or "").strip()
    valid = (
        not validate_plan_graph(plan)
        and len(nodes) == len(run.steps) == 1
        and (nodes[0].tool_id, nodes[0].action) == ("conversation", "reply")
        and nodes[0].params == {"response": text}
        and bool(text)
        and len(text) <= 12_000
        and not nodes[0].depends_on
        and nodes[0].risk == "low"
        and nodes[0].idempotent is True
        and not plan.metadata.get("approval_required_node_ids")
        and not run.tool_calls
        and run.steps[0].risk == nodes[0].risk
        and run.steps[0].idempotent is nodes[0].idempotent
    )
    if not valid:
        run.status, run.error = "blocked", "普通回复计划包含非回复动作或不一致内容，拒绝执行"
        run.add_event("workflow.plan_audit_rejected", run.error)
        return True
    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch

    result = PlannedWorkflowDispatch._execute_reply_plan(plan, context)
    success = result.get("success") is True
    run.status = "completed" if success else "failed"
    run.error = "" if success else str(result.get("message") or "普通回复执行失败")
    step = run.steps[0]
    step.status = "completed" if success else "failed"
    step.output = {"success": success, "response": result.get("response", "")}
    step.error = run.error
    run.final_output = {
        "response": result.get("response", ""),
        "node_outputs": {step.node_id: step.output},
        "artifacts": [artifact.to_dict() for artifact in run.artifacts],
        "tool_calls": [],
        "workflow_trace": (result.get("data") or {}).get("workflow_trace", []),
    }
    run.add_event(
        "run.completed" if success else "run.failed", "普通回复执行完成" if success else run.error
    )
    return True
