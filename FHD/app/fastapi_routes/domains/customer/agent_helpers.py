"""Unified-agent execution helpers used by customer compatibility routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.domain.task_lifecycle.results import agent_node_output as agent_node_output


def customers_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "customers-route"
    ).strip()


def run_customers_agent(
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
    action_meta = dict((registry.get("customers") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 customers 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"customers_{action}"
    principal = None
    if action in {"delete", "batch_delete"}:
        from app.infrastructure.auth.agent_principal import require_agent_principal

        principal = require_agent_principal(request, x_user_id=None)
    user_id = principal.user_id if principal else customers_agent_user_id(request, params)
    from app.middleware.request_id import ensure_request_id

    risk = normalize_workflow_risk(str(action_meta.get("risk") or "medium"))
    plan = PlanGraph(
        plan_id=f"{node_id}:{ensure_request_id(request)}",
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 customers.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="customers",
                action=action,
                params=dict(params or {}),
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute customers.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
        metadata={"source": "customers_route", "route": route_path},
    )
    runtime_context = {
        "source": "customers_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_customer_route",
    }
    if principal is not None:
        from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context

        runtime_context = authenticated_runtime_context(runtime_context, principal)
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Customers {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "customers-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return agent_node_output(run, node_id)
