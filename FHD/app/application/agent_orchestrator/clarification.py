"""Represent unanswered planner clarification as an interaction, never a tool call."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call


class ClarificationAnswerError(ValueError):
    """The answer does not resolve the currently pending input request."""


def find_waiting_step(run: AgentRun, *, approved_step_id: str = "") -> AgentStep | None:
    """Select the pending interaction, optionally constrained to an approved step."""
    wanted = str(approved_step_id or "").strip()
    return next(
        (
            step
            for step in run.steps
            if step.status == "waiting_user"
            and (not wanted or wanted in {step.step_id, step.node_id})
        ),
        None,
    )


def apply_clarification_answer(
    run: AgentRun,
    *,
    step_id: str,
    parameters: dict[str, Any],
    confirmed: bool = False,
    allowed_fields: set[str] | None = None,
) -> None:
    """Apply a bounded answer to the exact clarification node in the durable plan."""
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
        from app.domain.app_pure.inventory_inputs import missing_stock_in_fields

        missing = set(missing_stock_in_fields(target.params))
    from app.application.shipment_inputs import missing_shipment_call_fields, shipment_call_payload

    shipment = shipment_call_payload(target.tool_id, target.action, target.params)
    if shipment is not None:
        missing = set(missing_shipment_call_fields(target.tool_id, target.action, target.params))
    detail = step.params.get("clarification")
    detail = detail if isinstance(detail, dict) else {}
    reason = str(detail.get("reason") or "")
    candidate = deepcopy(target.params)
    allowed_missing: set[str] = set()
    if reason == "missing_required":
        allowed_missing = {str(value) for value in detail.get("missing_fields", [])}
        if not missing <= allowed_missing or set(parameters) != missing:
            raise ClarificationAnswerError("请一次补齐当前问题列出的全部必填参数")
        if shipment is None:
            candidate.update(deepcopy(parameters))
        else:
            payload = shipment_call_payload(target.tool_id, target.action, candidate)
            assert payload is not None
            for key, value in parameters.items():
                parts = key.split(".")
                if len(parts) == 1:
                    payload[key] = deepcopy(value)
                elif len(parts) == 3 and parts[0] == "products" and parts[1].isdigit():
                    products = payload.get("products") or payload.get("items")
                    index = int(parts[1])
                    if (
                        not isinstance(products, list)
                        or index >= len(products)
                        or not isinstance(products[index], dict)
                    ):
                        raise ClarificationAnswerError("商品明细已变化，请重新规划任务")
                    products[index][parts[2]] = deepcopy(value)
                else:
                    raise ClarificationAnswerError("商品明细格式无效，请重新规划任务")
            if missing_shipment_call_fields(target.tool_id, target.action, candidate):
                raise ClarificationAnswerError("请提供有效的发货信息")
    elif reason in {"ambiguous_target", "missing_target"}:
        if target.tool_id == "business_db" and target.action == "write":
            if set(parameters) == {"id"}:
                candidate_id = parameters.get("id")
            elif set(parameters) == {"payload"} and isinstance(parameters.get("payload"), dict):
                payload_patch = parameters["payload"]
                if set(payload_patch) != {"id"}:
                    raise ClarificationAnswerError("答案只能指定一个唯一目标 ID")
                candidate_id = payload_patch.get("id")
            else:
                raise ClarificationAnswerError("答案只能指定一个唯一目标 ID")
            if candidate_id in (None, ""):
                raise ClarificationAnswerError("请提供唯一目标 ID")
            payload = dict(candidate.get("payload") or {})
            payload["id"] = candidate_id
            candidate["payload"] = payload
        else:
            candidate_id = parameters.get("id")
            if candidate_id in (None, "") or set(parameters) != {"id"}:
                raise ClarificationAnswerError("答案只能指定一个唯一目标 ID")
            candidate["id"] = candidate_id
    elif reason in {
        "multi_unit",
        "report_scope",
        "reversal_confirm",
        "inventory_count_diff",
        "journal_entry_reverse",
        "batch_scope",
        "credit_limit_exceed",
    }:
        allowed = set(allowed_fields or ())
        if parameters and (not allowed or set(parameters) - allowed):
            raise ClarificationAnswerError("答案包含当前澄清步骤未授权的参数")
        if parameters:
            candidate.update(deepcopy(parameters))
        if not confirmed and detail.get("requires_confirmation", True):
            raise ClarificationAnswerError("请明确回答该操作的澄清问题")
    else:
        field_rows = step.output.get("fields") if isinstance(step.output, dict) else []
        allowed = {
            str(item.get("key"))
            for item in field_rows or []
            if isinstance(item, dict) and item.get("key")
        }
        allowed.update(allowed_fields or ())
        if parameters:
            if not allowed or set(parameters) - allowed:
                raise ClarificationAnswerError("答案参数与当前澄清字段不匹配")
            candidate.update(deepcopy(parameters))
        if not confirmed and detail.get("requires_confirmation", True):
            raise ClarificationAnswerError("请明确回答该操作的澄清问题")
    if confirmed and spec is not None and isinstance(spec.input_schema, dict):
        properties = spec.input_schema.get("properties") or {}
        if "confirmed" in properties:
            candidate["confirmed"] = True
    candidate.pop("candidates", None)
    candidate.pop("_candidates", None)
    if target.tool_id == "sales" and target.action in {"quote", "create_order"} and parameters:
        from app.application.sales_quote_inputs import quote_answer_candidate

        candidate = quote_answer_candidate(target.params, parameters)
    validation = validate_tool_call(
        target.tool_id,
        target.action,
        candidate,
        allow_references_from=set(target.depends_on),
        allow_missing_fields=allowed_missing,
    )
    if not validation.ok:
        raise ClarificationAnswerError(validation.message)
    # Validate and update a candidate full graph before changing live state. The
    # durable plan and its AgentSteps must never diverge across clarification.
    from app.application.workflow.workflow_types import (
        plan_fingerprint,
        plan_from_dict,
        plan_to_dict,
        validate_plan_graph,
    )

    persisted_plan = plan_from_dict(run.metadata.get("plan"))
    if persisted_plan is None:
        raise ClarificationAnswerError("持久化计划缺失，请重新规划后补充信息")
    plan_target = next(
        (node for node in persisted_plan.nodes if node.node_id == target.node_id),
        None,
    )
    plan_clarification = next(
        (node for node in persisted_plan.nodes if node.node_id == step.node_id),
        None,
    )
    if plan_target is None or (
        plan_target.tool_id,
        plan_target.action,
        plan_target.params,
        plan_target.depends_on,
    ) != (target.tool_id, target.action, target.params, target.depends_on):
        raise ClarificationAnswerError("澄清目标与持久化计划不一致，请重新规划")
    candidate_plan = deepcopy(persisted_plan)
    candidate_target = next(node for node in candidate_plan.nodes if node.node_id == target.node_id)
    candidate_target.params = candidate
    candidate_clarification = next(
        (node for node in candidate_plan.nodes if node.node_id == step.node_id),
        None,
    )
    if (
        plan_clarification is None
        or plan_clarification.tool_id != "clarify"
        or plan_clarification.action != "ask"
        or plan_clarification.params != step.params
        or candidate_clarification is None
    ):
        raise ClarificationAnswerError("澄清步骤与持久化计划不一致，请重新规划")
    # Remove the temporary incomplete-input exception before the graph can resume.
    candidate_clarification.params = {
        **candidate_clarification.params,
        "target_node_id": "",
        "clarification": {},
    }
    graph_error = validate_plan_graph(candidate_plan)
    if graph_error:
        raise ClarificationAnswerError(f"补充信息后计划校验失败：{graph_error}")
    from app.application.workflow.planning_graph_policy import validate_required_params
    from app.application.workflow_registry_app import get_workflow_tool_registry

    plan_error = validate_required_params(candidate_plan, get_workflow_tool_registry())
    if plan_error:
        raise ClarificationAnswerError(f"补充信息后计划校验失败：{plan_error}")
    # Invalid answers leave both the pending request and full plan untouched.
    target.params = candidate
    step.params = deepcopy(candidate_clarification.params)
    run.metadata["plan"] = plan_to_dict(candidate_plan)
    step.status = "completed"
    step.output = {
        **step.output,
        "answer_confirmed": True,
        "requires_confirmation": False,
        "confirmed": bool(confirmed),
    }
    for other in run.steps:
        detail = other.params.get("clarification") or {}
        if (
            other.status == "pending"
            and (other.tool_id, other.action) == ("clarify", "ask")
            and other.params.get("target_node_id") == target.node_id
            and isinstance(detail, dict)
            and detail.get("reason") == "missing_required"
        ):
            fields = {
                str(value)
                for value in detail.get("missing_fields", [])
                if isinstance(value, (str, int))
            }
            if target.tool_id == "sales" and target.action in {"quote", "create_order"}:
                from app.application.sales_quote_inputs import missing_quote_fields

                unresolved = fields & set(missing_quote_fields(target.params))
            elif (target.tool_id, target.action) == ("inventory", "stock_in"):
                from app.domain.app_pure.inventory_inputs import missing_stock_in_fields

                unresolved = fields & set(missing_stock_in_fields(target.params))
            else:
                unresolved = {key for key in fields if target.params.get(key) in (None, "", [], {})}
            if not unresolved:
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
            "plan_sha256": plan_fingerprint(candidate_plan),
        },
    )


def pause_for_clarification(run: AgentRun, step: AgentStep, outputs: dict | None = None) -> bool:
    from app.application.shipment_inputs import (
        missing_shipment_fields,
        resolve_shipment_product_source,
        shipment_call_payload,
    )

    payload = shipment_call_payload(step.tool_id, step.action, step.params)
    if payload is not None and step.tool_id == "business_db":
        if payload.get("product_source_node"):
            payload = step.params["payload"] = resolve_shipment_product_source(
                payload, outputs or {}
            )
        missing = missing_shipment_fields(payload)
        if missing:
            run.status = "blocked"
            step.error = run.error = "请补充有效出货参数：" + "、".join(missing)
            return True
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
        from app.domain.app_pure.inventory_inputs import missing_stock_in_fields

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
