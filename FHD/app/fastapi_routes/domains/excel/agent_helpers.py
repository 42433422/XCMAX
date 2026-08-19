"""Unified Agent-run helpers used by the legacy Excel route facade."""

from __future__ import annotations

import logging
from typing import Any, TypeVar, cast

from fastapi import Request

from app.application.workflow.types import normalize_workflow_risk
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
PayloadT = TypeVar("PayloadT")


def trace_excel_route(
    payload: PayloadT,
    *,
    route: str,
    message: str,
    user_id: str = "",
    intent: str = "excel_ai_route",
    runtime_context: dict[str, Any] | None = None,
) -> PayloadT:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context={"route": route, "source": "legacy_excel_route", **(runtime_context or {})},
            user_id=user_id or "legacy-excel-route",
            source="legacy_excel_route",
            channel="excel_ai_route",
            intent=intent,
        )
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - tracing must not break legacy AI routes
        logger.exception("failed to attach AgentRun trace to excel route response")
        return payload
    traced = dict(payload)
    traced["run_id"] = run.run_id
    traced["agent_run_id"] = run.run_id
    return cast(PayloadT, traced)


def agent_node_payload(run: Any, node_id: str) -> dict[str, Any]:
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
    if not output.get("success") and getattr(run, "error", False) and not output.get("message"):
        output["message"] = getattr(run, "error", False)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output.update({"run_id": run_id, "agent_run_id": run_id})
    output["agent_status"] = str(getattr(run, "status", "") or "")
    if isinstance(output.get("data"), dict):
        output["data"].setdefault("run_id", run_id)
        output["data"].setdefault("agent_run_id", run_id)
    return output


def user_id_from_excel_skill_request(request: Request, body: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or body.get("user_id")
        or body.get("userId")
        or "excel-skill-route"
    ).strip()


def run_excel_skill_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    intent: str,
    message: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get(tool_id) or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的工具动作: {tool_id}.{action}"}
    node_id = f"{intent}_{tool_id}_{action}".replace(".", "_").replace("-", "_")
    risk = normalize_workflow_risk(str(action_meta.get("risk") or "low"))
    plan = PlanGraph(
        plan_id=intent,
        intent=intent,
        todo_steps=[f"通过 AgentOrchestrator 执行 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=tool_id,
                action=action,
                params=dict(params),
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
        metadata={"source": "excel_skill_route", "route": route_path},
    )
    user_id = user_id_from_excel_skill_request(request, body)
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=message,
        plan=plan,
        runtime_context={
            "source": "excel_skill_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
        },
    )
    return agent_node_payload(run, node_id)


__all__ = ["agent_node_payload", "run_excel_skill_agent", "trace_excel_route", "user_id_from_excel_skill_request"]
