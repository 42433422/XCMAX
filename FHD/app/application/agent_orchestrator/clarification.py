"""Represent unanswered planner clarification as an interaction, never a tool call."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call


class ClarificationAnswerError(ValueError):
    """The answer does not resolve the currently pending input request."""


def apply_clarification_answer(run: AgentRun, *, step_id: str, parameters: dict[str, Any]) -> None:
    """Fill missing required inputs without approving the resulting business action."""
    step = next((item for item in run.steps if item.step_id == step_id), None)
    if (
        run.status != "waiting_user"
        or step is None
        or step.status != "waiting_user"
        or (step.tool_id, step.action) != ("clarify", "ask")
    ):
        raise ClarificationAnswerError("当前没有对应的待回答问题")
    target_id = step.params.get("target_node_id")
    target = next((item for item in run.steps if item.node_id == target_id), None)
    if target is None or target.status != "pending":
        raise ClarificationAnswerError("澄清目标已变化，请重新规划任务")
    spec = get_tool_action_spec(target.tool_id, target.action)
    missing = {
        key
        for key in (spec.required_params if spec else [])
        if target.params.get(key) in (None, "", [], {})
    }
    if not parameters or not set(parameters) <= missing:
        raise ClarificationAnswerError("答案只能补充当前目标缺失的必填参数")
    candidate = {**deepcopy(target.params), **deepcopy(parameters)}
    validation = validate_tool_call(target.tool_id, target.action, candidate)
    if not validation.ok:
        raise ClarificationAnswerError(validation.message)
    # Validate everything before changing either step. Invalid answers must leave
    # the pending request usable, and may never mutate unrelated plan nodes.
    target.params = candidate
    step.status = "completed"
    step.output = {**step.output, "answer_confirmed": True, "requires_confirmation": False}
    run.final_output = {}
    run.error = ""
    run.add_event(
        "step.clarification_answered",
        "执行参数已补齐",
        {
            "step_id": step.step_id,
            "target_node_id": target.node_id,
            "fields": sorted(parameters),
        },
    )


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
