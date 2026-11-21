"""Represent unanswered planner clarification as an interaction, never a tool call."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.workflow.clarification_inputs import (
    apply_input_fields,
    input_field_schema,
    missing_tool_fields,
)


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


def is_planning_clarification(run: AgentRun, step: AgentStep) -> bool:
    """Only an unanswered, standalone planning question may replace its empty graph."""
    from app.application.workflow.workflow_types import plan_from_dict, validate_plan_graph

    plan = plan_from_dict(run.metadata.get("plan"))
    return bool(
        plan
        and not validate_plan_graph(plan)
        and plan.metadata.get("planning_clarification") is True
        and len(plan.nodes) == len(run.steps) == 1
        and run.steps[0].step_id == step.step_id
        and run.status == step.status == "waiting_user"
        and not run.tool_calls
        and (step.tool_id, step.action) == ("clarify", "ask")
        and step.params.get("clarification") == {"reason": "planning_scope"}
        and not step.params.get("target_node_id")
        and plan.nodes[0].node_id == step.node_id
        and plan.nodes[0].params == step.params
        and not plan.nodes[0].depends_on
        and not plan.nodes[0].branches
        and plan.nodes[0].next is None
    )


def is_plan_confirmation(step: AgentStep) -> bool:
    """计划级确认：澄清不绑定具体节点，只做「继续/取消」闸门。

    ``clarify.ask`` 有两种形态：绑定 ``target_node_id`` 的用于补参数；不绑定的
    只能是计划级确认。后者绝不能走「丢弃旧计划重新规划」的分支——旧计划可能已经
    执行过预览步骤，重规划既不安全也无法让用户继续。
    """
    if (step.tool_id, step.action) != ("clarify", "ask"):
        return False
    if str(step.params.get("target_node_id") or "").strip():
        return False
    detail = step.params.get("clarification")
    return not isinstance(detail, dict) or not detail


def apply_plan_confirmation(run: AgentRun, *, step_id: str, confirmed: bool) -> None:
    """把计划级确认的答复写回同一个持久化计划（不重建计划）。"""
    step = next((item for item in run.steps if item.step_id == step_id), None)
    if (
        run.status != "waiting_user"
        or step is None
        or step.status != "waiting_user"
        or not is_plan_confirmation(step)
    ):
        raise ClarificationAnswerError("当前没有等待确认的计划")
    step.status = "completed" if confirmed else "failed"
    step.output = {
        **step.output,
        "answer_confirmed": bool(confirmed),
        "requires_confirmation": False,
        "confirmed": bool(confirmed),
    }
    if not confirmed:
        step.error = "用户取消确认"
        run.status = "cancelled"
        run.error = "用户取消确认"
    else:
        run.status = "running"
        run.error = ""
    run.final_output = {}
    run.add_event(
        "step.plan_confirmation_answered",
        "计划级确认已答复",
        {"step_id": step.step_id, "confirmed": bool(confirmed)},
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
    missing = set(missing_tool_fields(target.tool_id, target.action, target.params))
    from app.application.shipment_inputs import shipment_call_payload

    shipment = shipment_call_payload(target.tool_id, target.action, target.params)
    detail = step.params.get("clarification")
    detail = detail if isinstance(detail, dict) else {}
    reason = str(detail.get("reason") or "")
    candidate = deepcopy(target.params)
    pending_fields: set[str] = set()
    for other in run.steps:
        if (
            other is step
            or other.status != "pending"
            or (other.tool_id, other.action) != ("clarify", "ask")
            or other.params.get("target_node_id") != target.node_id
        ):
            continue
        pending_detail = other.params.get("clarification") or {}
        if not isinstance(pending_detail, dict):
            continue
        if pending_detail.get("reason") == "missing_required":
            pending_fields.update(str(key) for key in pending_detail.get("missing_fields", []))
        elif pending_detail.get("reason") == "ambiguous_target":
            pending_fields.add(str(pending_detail.get("field") or "id"))
    allowed_missing: set[str] = set()
    if reason == "missing_required":
        allowed_missing = {str(value) for value in detail.get("missing_fields", [])}
        if not parameters or not set(parameters) <= (missing & allowed_missing):
            raise ClarificationAnswerError("请一次补齐当前问题列出的全部必填参数")
        payload = (
            shipment_call_payload(target.tool_id, target.action, candidate)
            if shipment is not None
            else candidate
        )
        assert payload is not None
        # Shipment aliases share the same question paths as canonical products.
        if (
            shipment is not None
            and "products" not in payload
            and isinstance(payload.get("items"), list)
        ):
            payload["products"] = payload.pop("items")
        try:
            apply_input_fields(payload, deepcopy(parameters))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ClarificationAnswerError("明细结构已变化，请重新规划任务") from exc
        remaining = set(missing_tool_fields(target.tool_id, target.action, candidate))
        if remaining & allowed_missing or remaining - pending_fields:
            raise ClarificationAnswerError("请一次补齐当前问题列出的有效必填参数")
        allowed_missing.clear()
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
        else:
            candidate_id = parameters.get("id")
            if candidate_id in (None, "") or set(parameters) != {"id"}:
                raise ClarificationAnswerError("答案只能指定一个唯一目标 ID")
        candidates = detail.get("candidates") or []
        selected = [
            item
            for item in candidates
            if isinstance(item, dict)
            and item.get("id") not in (None, "")
            and str(item["id"]) == str(candidate_id)
        ]
        if reason == "ambiguous_target" or candidates:
            if len(selected) != 1:
                raise ClarificationAnswerError(
                    "请选择当前问题列出的候选对象，目标范围不能在回答中更换"
                )
            candidate_id = selected[0]["id"]
        destination = detail.get("field_path")
        if destination:
            from app.application.agent_orchestrator.param_references import (
                UnresolvedReference,
                substitute_selected_reference,
            )

            try:
                parent: Any = candidate
                for key in destination[:-1]:
                    parent = parent[key]
                original = parent[destination[-1]]
                if not isinstance(original, str):
                    raise UnresolvedReference("澄清目标引用已变化")
                parent[destination[-1]] = substitute_selected_reference(
                    original, detail["reference"], selected[0]["source_value"]
                )
            except (KeyError, IndexError, TypeError, UnresolvedReference) as exc:
                raise ClarificationAnswerError("澄清目标引用已变化，请重新规划任务") from exc
        elif target.tool_id == "business_db" and target.action == "write":
            payload = dict(candidate.get("payload") or {})
            payload["id"] = candidate_id
            candidate["payload"] = payload
        else:
            candidate[str(detail.get("field") or "id")] = candidate_id
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
    allowed_missing.update(
        pending_fields & set(missing_tool_fields(target.tool_id, target.action, candidate))
    )
    if spec is not None:
        allowed_missing.update(
            key
            for key in ("user_id", "tenant_id")
            if key in (spec.input_schema.get("required") or []) and candidate.get(key) in (None, "")
        )
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
            unresolved = fields & set(
                missing_tool_fields(target.tool_id, target.action, target.params)
            )
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
    required_fields = (
        missing_tool_fields(target.tool_id, target.action, target.params) if target else []
    )
    detail = step.params.get("clarification") or {}
    detail = detail if isinstance(detail, dict) else {}
    if detail.get("reason") == "missing_required":
        required_fields = [
            key for key in required_fields if key in detail.get("missing_fields", [])
        ]
    elif detail.get("reason") == "ambiguous_target":
        required_fields = [
            key for key in required_fields if key == str(detail.get("field") or "id")
        ]
    step.output["fields"] = [
        {
            "key": key,
            "label": field.get("title") or field.get("description") or labels.get(key, key),
            "type": field.get("type", "string"),
        }
        for key in required_fields
        for field in [input_field_schema(spec.input_schema if spec else {}, key)]
    ]
    if target and target.tool_id == "sales" and target.action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import quote_question_fields

        step.output["fields"] = [
            field
            for field in quote_question_fields(target.params)
            if field["key"] in required_fields
        ]
    run.final_output = {"clarification": {"step_id": step.step_id, **step.output}}
    run.add_event("step.clarification_required", step.output["question"], run.final_output)
    return True


def _candidate_rows(rows: list[Any], projections: list[Any] | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:20]):
        source = {"source_value": deepcopy(projections[index])} if projections is not None else {}
        if not isinstance(row, dict):
            if row not in (None, ""):
                candidates.append({"id": row, **source})
            continue
        candidate_id = next(
            (
                row[key]
                for key in ("id", "product_id", "customer_id", "material_id", "record_id")
                if row.get(key) not in (None, "")
            ),
            None,
        )
        if candidate_id in (None, ""):
            continue
        name = next(
            (
                str(row[key]).strip()
                for key in (
                    "name",
                    "product_name",
                    "unit_name",
                    "customer_name",
                    "material_name",
                    "model_number",
                )
                if str(row.get(key) or "").strip()
            ),
            "",
        )
        candidates.append({"id": candidate_id, **({"name": name} if name else {}), **source})
    return candidates


def _ambiguous_field(params: Any, path: str) -> list[str | int]:
    token = "{{" + path + "}}"

    def walk(value: Any, destination: list[str | int]) -> list[str | int]:
        if isinstance(value, dict):
            for child_key, child in value.items():
                found = walk(child, [*destination, str(child_key)])
                if found:
                    return found
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                found = walk(child, [*destination, index])
                if found:
                    return found
        elif isinstance(value, str) and token in value:
            return destination
        return []

    return walk(params, [])


def pause_for_ambiguous_target(
    run: AgentRun,
    step: AgentStep,
    rows: list[Any],
    *,
    field: str = "",
    field_path: list[str | int] | None = None,
    reference: str = "",
    projections: list[Any] | None = None,
) -> bool:
    """执行期把「多候选引用」转为澄清：插入 clarify 步骤并等待用户选择。"""
    from app.application.workflow.workflow_types import WorkflowNode, plan_from_dict, plan_to_dict

    candidates = _candidate_rows(rows, projections)
    if not candidates:
        return False
    target_field = str(field or "id")
    labels: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        name = str(candidate.get("name") or "").strip()
        cid = str(candidate.get("id") or "")
        labels.append(f"{index}. {name}（#{cid}）" if name else f"{index}. #{cid}")
    question = "检测到多个匹配目标，请选择要操作的对象：\n" + "\n".join(labels)
    detail: dict[str, Any] = {
        "reason": "ambiguous_target",
        "node_id": step.node_id,
        "field": target_field,
        "candidates": candidates,
        "question": question,
    }
    if field_path:
        detail.update(field_path=list(field_path), reference=reference)
    plan = plan_from_dict(run.metadata.get("plan")) if run.metadata.get("plan") else None
    used_ids = {item.node_id for item in run.steps}
    if plan is not None:
        used_ids.update(node.node_id for node in plan.nodes)
    base_id = f"{step.node_id}_clarify"
    clarify_node_id = next(
        node_id
        for index in range(len(used_ids) + 1)
        if (node_id := base_id if index == 0 else f"{base_id}_{index}") not in used_ids
    )
    params = {
        "question": question,
        "answer_key": "confirmed",
        "target_node_id": step.node_id,
        "clarification": detail,
    }
    clarify_node = WorkflowNode(
        node_id=clarify_node_id,
        tool_id="clarify",
        action="ask",
        params=params,
        risk="low",
        idempotent=True,
        description="多候选目标澄清",
    )
    clarify_step = AgentStep(
        node_id=clarify_node_id,
        tool_id="clarify",
        action="ask",
        params=dict(params),
        risk="low",
        idempotent=True,
        description="多候选目标澄清",
        status="waiting_user",
        output={
            "requires_confirmation": True,
            "question": question,
            "target_node_id": step.node_id,
            "candidates": candidates,
        },
    )
    index = next(
        (position for position, item in enumerate(run.steps) if item.step_id == step.step_id),
        len(run.steps),
    )
    run.steps.insert(index, clarify_step)
    step.status = "pending"
    step.error = ""
    step.output = {}
    if plan is not None:
        node_index = next(
            (position for position, node in enumerate(plan.nodes) if node.node_id == step.node_id),
            len(plan.nodes),
        )
        plan.nodes.insert(node_index, clarify_node)
        run.metadata["plan"] = plan_to_dict(plan)
    run.status = "waiting_user"
    run.error = ""
    run.final_output = {"clarification": {"step_id": clarify_step.step_id, **clarify_step.output}}
    run.add_event(
        "run.ambiguous_target_paused",
        "前序结果存在多个候选，已暂停并请求用户选择",
        {"node_id": step.node_id, "candidates": len(candidates), "field": target_field},
    )
    return True
