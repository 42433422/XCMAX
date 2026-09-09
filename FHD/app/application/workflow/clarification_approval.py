"""Recheck approval after clarification resolves the operation target."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .types import PlanGraph


def require_approval_after_clarification(
    service: Any,
    user_id: str,
    plan: PlanGraph,
    runtime_context: dict[str, Any],
    thinking_steps: str,
) -> dict[str, Any] | None:
    nodes = service.approval_service.get_approval_required_nodes(plan)
    if not nodes:
        return None
    approval_nodes = [
        {"node_id": n.node_id, "tool_id": n.tool_id, "action": n.action, "params": dict(n.params)}
        for n in nodes
    ]
    service._pending_workflows[user_id] = {
        "plan": plan,
        "runtime_context": runtime_context,
        "pending_id": uuid4().hex,
        "agent_run_id": "",
        "thinking_steps": thinking_steps,
        "approval_required": True,
        "approval_nodes": approval_nodes,
    }
    service._persist_plan_state(plan, runtime_context, status="pending_awaiting")
    response = "已确定操作对象。该操作仍需审批，请确认提交审批，或取消本次操作。"
    return {
        "success": True,
        "message": "等待审批确认",
        "response": response,
        "data": {
            "text": response,
            "action": "workflow_confirmation_required",
            "data": {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "approval_required": True,
                "approval_nodes": [
                    {k: n[k] for k in ("node_id", "tool_id", "action")} for n in approval_nodes
                ],
            },
        },
    }
