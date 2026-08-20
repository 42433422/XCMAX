"""Always-on tool execution routes.

``/api/tools/execute`` and ``/api/skills/execute`` must stay registered even when
``XCAGI_REGISTER_LEGACY_ROUTES`` is off. Otherwise the SPA ``GET /{fallback:path}``
matches the path and POST returns 405 Method Not Allowed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application.workflow.types import normalize_workflow_risk

router = APIRouter(tags=["tools-execute"])


def user_id_from_tool_request(request: Request, body: dict[str, Any]) -> str:
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    if not isinstance(params, dict):
        params = {}
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or body.get("user_id")
        or body.get("userId")
        or params.get("user_id")
        or "tools-route"
    ).strip()


def tool_route_agent_payload(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                if not output and str(getattr(step, "status", "")) == "waiting_user":
                    output = {
                        "success": True,
                        "message": "工具执行需要用户确认",
                        "waiting_step_id": getattr(step, "step_id", ""),
                    }
                break
    if not output:
        output = {"success": getattr(run, "status", "") in {"completed", "waiting_user"}}
    if not output.get("success"):
        # Tool implementations historically returned ``str(exc)`` and persisted
        # tracebacks in their failure payload.  Rebuild the public failure shape
        # from stable fields so neither can cross the HTTP boundary.
        raw_error_code = str(output.get("error_code") or "tool_failed")[:64]
        output = {
            "success": False,
            "message": "工具执行失败，请稍后重试",
            "error_code": raw_error_code,
        }
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    output.setdefault("data", {})
    if isinstance(output.get("data"), dict):
        output["data"].setdefault("agent_run_id", run_id)
        output["data"].setdefault("run_id", run_id)
    return output


def run_tools_execute_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int] | None:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import _normalize_action, get_workflow_tool_registry

    raw_tool_id = body.get("tool_id") or body.get("skill_id")
    tool_id = str(raw_tool_id or "").strip()
    if not tool_id:
        return None
    params = body.get("params")
    if not isinstance(params, dict):
        params = {}
    action = _normalize_action(str(body.get("action") or "view"), params)
    registry = get_workflow_tool_registry()
    if tool_id not in registry or action not in dict(registry[tool_id].get("actions") or {}):
        return None

    node_id = f"tools_execute_{tool_id}_{action}".replace(".", "_").replace("-", "_")
    plan = PlanGraph(
        plan_id=f"tools_execute_{tool_id}_{action}",
        intent=f"tools_execute_{tool_id}_{action}",
        todo_steps=[f"通过 AgentOrchestrator 执行 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=tool_id,
                action=action,
                params=dict(params),
                risk=normalize_workflow_risk(
                    str(registry[tool_id]["actions"][action].get("risk") or "low")
                ),
                idempotent=bool(registry[tool_id]["actions"][action].get("idempotent", False)),
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=normalize_workflow_risk(
            str(registry[tool_id]["actions"][action].get("risk") or "low")
        ),
        metadata={"source": "tools_execute_route", "route": route_path},
    )
    user_id = user_id_from_tool_request(request, body)
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=str(body.get("message") or f"Execute {tool_id}.{action}"),
        plan=plan,
        runtime_context={
            "source": "tools_execute_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
        },
    )
    payload = tool_route_agent_payload(run, node_id)
    if run.status in {"waiting_user", "blocked"}:
        return payload, 202
    return payload, 200 if payload.get("success") else 400


@router.post("/api/skills/execute")
def skills_execute(request: Request, body: dict = Body(default_factory=dict)):
    agent_result = run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/skills/execute",
    )
    if agent_result is not None:
        return JSONResponse(agent_result[0], status_code=agent_result[1])
    from app.application.facades.tools_facade import run_archive_tools_execute

    data, code = run_archive_tools_execute(body)
    return JSONResponse(data, status_code=code)


@router.post("/api/tools/execute")
def tools_execute_route(request: Request, body: dict = Body(default_factory=dict)):
    agent_result = run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/tools/execute",
    )
    if agent_result is not None:
        return JSONResponse(agent_result[0], status_code=agent_result[1])
    from app.application.facades.tools_facade import run_archive_tools_execute

    data, code = run_archive_tools_execute(body)
    return JSONResponse(data, status_code=code)
