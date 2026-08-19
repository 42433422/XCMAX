"""Shared AgentOrchestrator bridge for shipment compatibility routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.workflow.types import normalize_workflow_risk


def agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success"):
        output["message"] = "出货单操作失败"
        output.pop("error", None)
        output.pop("traceback", None)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def shipment_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "shipment-route"
    ).strip()


def _run_shipment_agent(
    *,
    request: Request,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    route_path: str,
    default_risk: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get(tool_id) or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 {tool_id} 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"{tool_id}_{action}"
    user_id = shipment_agent_user_id(request, params)
    risk = normalize_workflow_risk(str(action_meta.get("risk") or default_risk))
    source = f"{tool_id}_route"
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=tool_id,
                action=action,
                params=dict(params or {}),
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
        metadata={"source": source, "route": route_path},
    )
    runtime_context = {
        "source": source,
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": f"fastapi_{source}",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"{tool_id.replace('_', ' ').title()} {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "shipment-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return agent_node_output(run, node_id)


def run_shipment_records_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    return _run_shipment_agent(
        request=request,
        tool_id="shipment_records",
        action=action,
        params=params,
        route_path=route_path,
        default_risk="medium",
    )


def run_shipment_orders_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    return _run_shipment_agent(
        request=request,
        tool_id="shipment_orders",
        action=action,
        params=params,
        route_path=route_path,
        default_risk="high",
    )
