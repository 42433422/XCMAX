"""Agent-runtime adapter for Memory v2 HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.workflow.workflow_types import normalize_workflow_risk


def agent_output(run: Any, node_id: str) -> dict[str, Any]:
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
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def user_id_from_request(request: Request, params: dict[str, Any]) -> str:
    from app.infrastructure.auth.dependencies import get_logged_in_user

    user = get_logged_in_user(request)
    owner = str(user.id)
    aliases = {owner}
    # A numeric legacy username may be another account's canonical id.
    if not str(user.username).isdecimal():
        aliases.add(str(user.username))
    claims = [
        str(value).strip()
        for value in (request.headers.get("X-User-Id"), params.get("user_id"), params.get("userId"))
        if value is not None and str(value).strip() not in {"", "default"}
    ]
    if any(value not in aliases for value in claims):
        raise HTTPException(status_code=403, detail="只能访问当前账户的记忆")
    return claims[0] if claims else owner


def run_memory_v2_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
    failure_status: int,
) -> JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.tool_spec import validate_tool_call
    from app.application.memory_v2_facade import get_memory_v2_action_meta
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    data = dict(params or {})
    user_id = user_id_from_request(request, data)
    data["user_id"] = user_id
    action_meta = get_memory_v2_action_meta(action)
    if action_meta is None:
        return JSONResponse(
            {"success": False, "message": f"未注册的 Memory v2 动作: {action}"},
            status_code=400,
        )
    validation = validate_tool_call("memory_v2", action, data)
    if not validation.ok:
        return JSONResponse(
            {"success": False, "error_code": validation.error_code, "message": validation.message},
            status_code=400,
        )
    node_id = f"memory_v2_{action}"
    risk = normalize_workflow_risk(str(action_meta.get("risk") or "medium"))
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 memory_v2.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="memory_v2",
                action=action,
                params=data,
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute memory_v2.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
        metadata={"source": "memory_v2_route", "route": route_path},
    )
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal

    principal = require_agent_principal(request)
    runtime_context = {
        **authenticated_runtime_context({}, principal),
        "source": "memory_v2_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "route_confirmed": True,
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=principal.user_id,
        message=str(data.get("message") or f"Memory v2 {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "memory-v2-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    payload = agent_output(run, node_id)
    status_code = 200 if payload.get("success") else failure_status
    if payload.get("error_code") == "tool_exception":
        status_code = 500
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return JSONResponse(payload, status_code=status_code)
