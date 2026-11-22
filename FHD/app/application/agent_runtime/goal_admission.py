"""Compile host-owned goals through the task's existing metered model gateway.

The established planner, schema admission, risk gate and independent goal review
produce a frozen business graph. They never execute it. Codex owns the only
autonomous tool loop; the host owns the graph, approvals and receipt validation.
"""

from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

from app.application.workflow.workflow_types import PlanGraph, plan_to_dict, validate_plan_graph
from app.infrastructure.codex.binding import CodexBindingError


@dataclass(frozen=True)
class RuntimeGoal:
    mode: str
    plan: dict[str, Any] | None = None
    question: str = ""
    reply: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)


def compile_runtime_goal(binding: Any, config: Any) -> RuntimeGoal:
    """Use only the bound route/token; no provider fallback or direct business I/O."""
    started = time.monotonic()
    from openai import APIError, DefaultHttpxClient, OpenAI
    from openai.types.responses import ResponseInputParam

    from app.application.agent_orchestrator.attachment_inputs import (
        AttachmentInputError,
        resolve_attachment_context,
    )
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.agent_orchestrator.tool_spec import (
        get_tool_action_spec,
        validate_tool_call,
    )
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.application.tool_execution_deadline import (
        invocation_deadline,
        remaining_invocation_seconds,
    )
    from app.application.workflow.goal_coverage import (
        GoalCoverage,
        coverage_error,
        review_goal_coverage,
    )
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.risk_gate import HybridRiskGate

    deadline = started + float(config.turn_timeout_seconds)

    def remaining() -> float:
        seconds = remaining_invocation_seconds(deadline - time.monotonic())
        if not math.isfinite(seconds) or seconds <= 0:
            raise CodexBindingError("goal_admission_timeout", "目标规划已超时，未冻结业务目标")
        return seconds

    request_limit = float(config.timeout_seconds)
    if not math.isfinite(request_limit) or request_limit <= 0:
        raise CodexBindingError("goal_admission_failed", "目标规划模型请求时限无效")
    remaining()
    context = binding.context
    # User data is quoted input, never a source of authority or a supplied goal.
    answered = [
        event for event in binding.run.events if event.event_type == "runtime.input_answered"
    ]
    file_context = {}
    for value in (context.get("file_analysis"), context.get("file_context")):
        if isinstance(value, dict):
            file_context.update(copy.deepcopy(value))
    for attached in [
        binding.run.metadata.get("_codex_input_data"),
        *(event.data.get("input_data") for event in answered),
    ]:
        if isinstance(attached, dict):
            if isinstance(attached.get("file_context"), dict):
                file_context.update(copy.deepcopy(attached["file_context"]))
            if "attachment_upload_ids" in attached:
                # Upload IDs are untrusted references, never authorization.
                # The resolver verifies current ownership, expiry and content.
                context["attachment_upload_ids"] = copy.deepcopy(attached["attachment_upload_ids"])
    if file_context:
        context["file_context"] = file_context
    try:
        context, attachments = resolve_attachment_context(context)
    except AttachmentInputError as exc:
        return RuntimeGoal(mode="business", question=str(exc))
    exchanges = [
        {"question": event.data.get("question"), "answer": event.data.get("answer")}
        for event in answered
    ]
    message = binding.run.message
    if exchanges:
        context["planning_clarification"] = {
            "original_request": message,
            "exchanges": exchanges,
        }
        message = json.dumps(context["planning_clarification"], ensure_ascii=False)
    registry = copy.deepcopy(get_workflow_tool_registry())
    actions = binding.metadata.get("allowed_actions")
    for tool_id, tool in list(registry.items()):
        permitted = {}
        for action, details in (tool.get("actions") or {}).items():
            spec = get_tool_action_spec(tool_id, action)
            if (
                spec is not None
                and tool_id not in {"aiopen", "conversation", "clarify"}
                and (actions is None or f"{tool_id}.{spec.action}" in actions)
                and actor_tool_denial(tool_id, spec.action, context) is None
            ):
                permitted[action] = details
        if permitted:
            tool["actions"] = permitted
        else:
            registry.pop(tool_id)

    output_limit = config.context_window - (config.auto_compact_token_limit or 0)
    if output_limit <= 0:
        raise CodexBindingError("goal_admission_failed", "模型输出预算无效，未冻结业务目标")

    with (
        invocation_deadline(deadline),
        OpenAI(
            api_key=config.provider_token,
            base_url=config.provider_url,
            max_retries=0,
            timeout=min(request_limit, remaining()),
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False),
        ) as client,
    ):

        def complete(*, messages: list[dict[str, Any]], max_tokens=None, **_kwargs):
            # The planner's optional native submit-plan schema is represented by
            # the JSON output contract already in its prompt, never remote tools.
            try:
                response = client.responses.create(
                    model=config.model,
                    input=cast(ResponseInputParam, messages),
                    tools=[],
                    store=False,
                    max_output_tokens=min(max_tokens or output_limit, output_limit),
                    timeout=min(request_limit, remaining()),
                )
            except APIError as exc:
                raise CodexBindingError(
                    "goal_admission_failed", "目标规划模型请求未完成，请核对原任务计量回执"
                ) from exc
            remaining()
            raw = response.model_dump()
            if (
                not isinstance(raw, dict)
                or raw.get("status") != "completed"
                or not isinstance(raw.get("output"), list)
                or any(
                    not isinstance(item, dict) or item.get("type") not in {"message", "reasoning"}
                    for item in raw["output"]
                )
            ):
                raise CodexBindingError("goal_admission_failed", "目标规划未返回完整的无工具结果")
            text = response.output_text
            if not isinstance(text, str) or not text.strip():
                raise CodexBindingError("goal_admission_failed", "目标规划没有返回可核对的内容")
            return {
                "model": config.model,
                "choices": [{"message": {"content": text}}],
            }

        planner = LLMWorkflowPlanner(
            ai_service=SimpleNamespace(get_context=lambda _owner: None), completion=complete
        )
        plan = planner.plan(binding.run.user_id, message, registry, context)
        remaining()
        if not isinstance(plan, PlanGraph) or plan.metadata.get("planning_rejected"):
            raise CodexBindingError(
                "goal_admission_failed", "目标、条件或参数尚未核对完整，本轮未执行"
            )
        if error := validate_plan_graph(plan):
            raise CodexBindingError("goal_admission_failed", error)
        questions = [
            str(node.params.get("question") or node.description or "请补充任务信息")
            for node in plan.nodes
            if (node.tool_id, node.action) == ("clarify", "ask")
        ]
        if questions:
            # Freeze only after required scope is known. All business effects
            # remain absent; the same parent retains the exact questions/answers.
            return RuntimeGoal(mode="business", question="\n".join(dict.fromkeys(questions)))
        # Bind identity and owned uploads before authorization/review/risk. The
        # frozen graph must contain the exact targets those gates checked.
        plan.plan_id = f"plan_{binding.run_id}"
        reviewed_nodes = plan_to_dict(plan)["nodes"]
        is_reply = len(plan.nodes) == 1 and (plan.nodes[0].tool_id, plan.nodes[0].action) == (
            "conversation",
            "reply",
        )
        if not is_reply:
            from app.application.elt.batch_continuation import bind_durable_batch

            bind_durable_batch(plan, context)
            remaining()
            for node in plan.nodes:
                validation = validate_tool_call(
                    node.tool_id,
                    node.action,
                    node.params,
                    allow_references_from=set(node.depends_on),
                )
                if (
                    not validation.ok
                    or validation.spec is None
                    or node.tool_id not in registry
                    or node.action not in registry[node.tool_id]["actions"]
                    or actor_tool_denial(node.tool_id, node.action, context, node.params)
                ):
                    raise CodexBindingError(
                        "goal_permission_denied", "计划含未获授权或无效的业务动作"
                    )
                node.risk, node.idempotent = validation.spec.risk, validation.spec.idempotent
        review_data = (
            plan.metadata.get("goal_coverage")
            if reviewed_nodes == plan_to_dict(plan)["nodes"]
            else None
        )
        review: GoalCoverage | None
        if isinstance(review_data, dict):
            review = GoalCoverage.model_validate(review_data)
            error = coverage_error(review, plan, message)
        else:
            review, error = review_goal_coverage(plan, message, context, complete)
        remaining()
        if review is None or error:
            if review is not None and review.clarification_question:
                return RuntimeGoal(mode="business", question=review.clarification_question)
            raise CodexBindingError("goal_coverage_rejected", error or "任务目标尚未核对完整")
        plan.metadata["goal_coverage"] = review.model_dump()
        if is_reply:
            reply = plan.nodes[0].params.get("response")
            if not isinstance(reply, str) or not reply.strip():
                raise CodexBindingError("goal_admission_failed", "普通回复内容无效")
            return RuntimeGoal(mode="reply", reply=reply, artifacts=attachments)
        decision = HybridRiskGate().evaluate(plan, context)
        remaining()
        blocking = set(decision.blocking_nodes or [])
        if (
            decision.denied_nodes
            or (not decision.allowed and not decision.requires_confirmation)
            or (decision.requires_confirmation and not blocking)
            or not blocking <= {node.node_id for node in plan.nodes}
        ):
            raise CodexBindingError("goal_risk_denied", "计划未通过宿主风险审核")
        if blocking:
            plan.metadata["approval_required_node_ids"] = sorted(blocking)
            for node in plan.nodes:
                if node.node_id in blocking:
                    node.risk = "high"
        if attachments:
            plan.metadata["artifacts"] = attachments
        return RuntimeGoal(mode="business", plan=plan_to_dict(plan), artifacts=attachments)
