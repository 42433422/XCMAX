"""Unified-agent execution helpers for print routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.domain.task_lifecycle.results import agent_node_output as agent_node_output
from app.middleware.request_id import ensure_request_id


def print_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "print-route"
    ).strip()


def print_agent_status_code(result: dict[str, Any], *, failure_status: int = 400) -> int:
    if result.get("success"):
        return 200
    if str(result.get("error_code") or "") == "tool_exception":
        return 500
    return failure_status


def run_print_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("print") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 print 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"print_{action}"
    user_id = print_agent_user_id(request, params)
    risk = normalize_workflow_risk(str(action_meta.get("risk") or "medium"))
    plan = PlanGraph(
        plan_id=f"{node_id}:{ensure_request_id(request)}",
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 print.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="print",
                action=action,
                params=dict(params or {}),
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute print.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
        metadata={"source": "print_route", "route": route_path},
    )
    runtime_context = {
        "source": "print_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_print_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Print {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "print-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return agent_node_output(run, node_id)
