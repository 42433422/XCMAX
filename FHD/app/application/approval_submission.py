"""Approval Workspace submission bridge for pending chat workflows."""

from __future__ import annotations

from typing import Any


def submit_pending_approval(
    *,
    pending: dict[str, Any],
    approval_service: Any,
    user_id: str,
) -> tuple[str, list[str], bool]:
    """Persist formal approvals, including workflows created before AgentRun existed."""
    plan = pending.get("plan")
    runtime_context = pending.get("runtime_context", {})
    approval_nodes = pending.get("approval_nodes", [])
    agent_run_id = str(pending.get("agent_run_id") or "").strip()
    if agent_run_id:
        from app.application.agent_orchestrator import AgentOrchestrator

        agent_run, request_ids = AgentOrchestrator().submit_run_for_approval(
            agent_run_id, requested_by=user_id
        )
        return agent_run_id, request_ids, bool(agent_run and request_ids)

    request_ids: list[str] = []
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
        if not bool(getattr(request, "persistence_confirmed", True)):
            continue
        request_id = str(getattr(request, "request_id", "") or "").strip()
        if request_id:
            request_ids.append(request_id)
    return "", request_ids, bool(request_ids)


def approval_pending_response(
    *,
    plan_id: str,
    agent_run_id: str,
    approval_nodes: list[Any],
    approval_request_ids: list[str],
    submitted: bool,
    enrich_confirmation: Any,
) -> dict[str, Any]:
    response_text = (
        "已提交审批请求，请在审批中心处理；审批通过后任务会从当前步骤继续。"
        if submitted
        else "审批请求提交失败，持久化任务仍保留，可稍后重试。"
    )
    inner = {
        "plan_id": plan_id,
        "run_id": agent_run_id,
        "agent_run_id": agent_run_id,
        "approval_required": True,
        "approval_nodes": approval_nodes,
        "approval_request_ids": approval_request_ids,
    }
    return {
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
            "data": enrich_confirmation(inner, action="approval_pending"),
        },
    }


def workflow_confirmation_response(
    *,
    plan: Any,
    thinking_steps: str,
    blocking_nodes: list[str],
    reason: str,
    approval_required: bool,
    approval_nodes: list[Any],
    approval_info: str,
    agent_run_id: str,
    enrich_confirmation: Any,
) -> dict[str, Any]:
    todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
    response_text = (
        "我已根据语义生成动态工作流计划：\n"
        f"{thinking_steps}\n\n{todo_text}\n\n"
        f"检测到中高风险步骤（{', '.join(blocking_nodes)}），回复「确认」继续执行，回复「取消」终止。"
        f"{approval_info if approval_required else ''}"
    )
    inner = {
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "thinking_steps": thinking_steps,
        "todo": plan.todo_steps,
        "blocking_nodes": blocking_nodes,
        "reason": reason,
        "approval_required": approval_required,
        "approval_nodes": [
            {"node_id": node.node_id, "tool_id": node.tool_id, "action": node.action}
            for node in approval_nodes
        ],
    }
    payload: dict[str, Any] = {
        "success": True,
        "message": "处理完成",
        "response": response_text,
        "data": {
            "text": response_text,
            "action": "workflow_confirmation_required",
            "data": enrich_confirmation(inner, action="workflow_confirmation_required"),
        },
    }
    if agent_run_id:
        payload.update({"run_id": agent_run_id, "agent_run_id": agent_run_id})
        payload["data"].update({"run_id": agent_run_id, "agent_run_id": agent_run_id})
        payload["data"]["data"].update({"run_id": agent_run_id, "agent_run_id": agent_run_id})
    return payload
