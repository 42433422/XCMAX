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
    if target.tool_id == "sales" and target.action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import missing_quote_fields

        missing = set(missing_quote_fields(target.params))
    if (target.tool_id, target.action) == ("inventory", "stock_in"):
        from app.application.inventory_inputs import missing_stock_in_fields

        missing = set(missing_stock_in_fields(target.params))
    if not parameters or not set(parameters) <= missing:
        raise ClarificationAnswerError("答案只能补充当前目标缺失的必填参数")
    candidate = {**deepcopy(target.params), **deepcopy(parameters)}
    if target.tool_id == "sales" and target.action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import quote_answer_candidate

        candidate = quote_answer_candidate(target.params, parameters)
    validation = validate_tool_call(target.tool_id, target.action, candidate)
    if not validation.ok:
        raise ClarificationAnswerError(validation.message)
    # Validate everything before changing either step. Invalid answers must leave
    # the pending request usable, and may never mutate unrelated plan nodes.
    target.params = candidate
    step.status = "completed"
    step.output = {**step.output, "answer_confirmed": True, "requires_confirmation": False}
    for other in run.steps:
        detail = other.params.get("clarification") or {}
        if (
            other.status == "pending"
            and (other.tool_id, other.action) == ("clarify", "ask")
            and other.params.get("target_node_id") == target.node_id
            and isinstance(detail, dict)
            and detail.get("reason") == "missing_required"
        ):
            other.status = "completed"
            other.output = {"answer_confirmed": True, "resolved_by_step_id": step.step_id}
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
    target = next(
        (item for item in run.steps if item.node_id == step.params.get("target_node_id")), None
    )
    spec = get_tool_action_spec(target.tool_id, target.action) if target else None
    labels = {
        "unit_name": "客户单位",
        "name_or_model": "产品名称或型号",
        "quantity": "数量",
        "warehouse_id": "仓库编号",
        "product_id": "产品编号",
        "customer_id": "客户编号",
        "amount": "金额",
        "transaction_type": "收支类型",
    }
    properties = spec.input_schema.get("properties", {}) if spec else {}
    required_fields = spec.required_params if spec else []
    if target and target.tool_id == "sales" and target.action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import missing_quote_fields

        required_fields = missing_quote_fields(target.params)
    if target and (target.tool_id, target.action) == ("inventory", "stock_in"):
        from app.application.inventory_inputs import missing_stock_in_fields

        required_fields = missing_stock_in_fields(target.params)
    step.output["fields"] = [
        {
            "key": key,
            "label": properties.get(key, {}).get("title") or labels.get(key, key),
            "type": properties.get(key, {}).get("type", "string"),
        }
        for key in required_fields
        if target is not None and target.params.get(key) in (None, "", [], {})
    ]
    if target and target.tool_id == "sales" and target.action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import quote_question_fields

        step.output["fields"] = quote_question_fields(target.params)
    run.final_output = {"clarification": {"step_id": step.step_id, **step.output}}
    run.add_event("step.clarification_required", step.output["question"], run.final_output)
    return True
