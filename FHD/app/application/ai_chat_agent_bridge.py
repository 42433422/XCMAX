from __future__ import annotations

from collections.abc import Callable
from typing import Any


def try_customer_mutation(
    message: str,
    *,
    runtime_context: dict[str, Any],
    user_id: str,
    source: str | None,
) -> dict[str, Any] | None:
    from app.application.customer_mutation_agent import try_start_customer_mutation_agent_run

    return try_start_customer_mutation_agent_run(
        message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
    )


def submit_pending_agent_approval(
    pending: dict[str, Any],
    *,
    user_id: str,
    approval_service: Any,
    enrich_confirmation_inner: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    from app.application.agent_orchestrator import AgentOrchestrator

    plan = pending.get("plan")
    runtime_context = pending.get("runtime_context", {})
    approval_nodes = pending.get("approval_nodes", [])
    agent_run_id = str(pending.get("agent_run_id") or "").strip()
    if agent_run_id:
        agent_run, request_ids = AgentOrchestrator().submit_run_for_approval(
            agent_run_id,
            requested_by=user_id,
        )
    else:
        request_ids = []
        for node_info in approval_nodes:
            node = next(
                (item for item in plan.nodes if item.node_id == node_info.get("node_id")),
                None,
            )
            if node is None:
                continue
            request = approval_service.create_approval_request(
                plan_id=plan.plan_id,
                node=node,
                runtime_context=runtime_context,
                plan=plan,
            )
            request_id = str(getattr(request, "request_id", "") or "").strip()
            if bool(getattr(request, "persistence_confirmed", True)) and request_id:
                request_ids.append(request_id)
        agent_run = object() if request_ids else None
    submitted = bool(agent_run and request_ids)
    response_text = (
        "已提交审批请求，请在审批中心处理；审批通过后任务会从当前步骤继续。"
        if submitted
        else "审批请求提交失败，持久化任务仍保留，可稍后重试。"
    )
    approval_inner = {
        "plan_id": plan.plan_id,
        "run_id": agent_run_id,
        "agent_run_id": agent_run_id,
        "approval_required": True,
        "approval_nodes": approval_nodes,
        "approval_request_ids": request_ids,
    }
    payload = {
        "success": submitted,
        "message": "处理完成",
        "run_id": agent_run_id,
        "agent_run_id": agent_run_id,
        "response": response_text,
        "data": {
            "text": response_text,
            "action": "approval_pending",
            "run_id": agent_run_id,
            "agent_run_id": agent_run_id,
            "data": enrich_confirmation_inner(approval_inner, action="approval_pending"),
        },
    }
    return payload, bool(agent_run_id)
