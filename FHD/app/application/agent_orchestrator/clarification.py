"""Represent unanswered planner clarification as an interaction, never a tool call."""

from __future__ import annotations

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep


def pause_for_clarification(run: AgentRun, step: AgentStep) -> bool:
    if (step.tool_id, step.action) != ("clarify", "ask"):
        return False
    step.status = "waiting_user"
    run.status = "waiting_user"
    step.output = {
        "requires_confirmation": True,
        "question": str(step.params.get("question") or "请补充执行所需的信息"),
        "target_node_id": str(step.params.get("target_node_id") or ""),
    }
    run.final_output = {"clarification": {"step_id": step.step_id, **step.output}}
    run.add_event("step.clarification_required", step.output["question"], run.final_output)
    return True
