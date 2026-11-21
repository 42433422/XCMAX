"""Always-on tool execution routes.

``/api/tools/execute`` and ``/api/skills/execute`` must stay registered even when
``XCAGI_REGISTER_LEGACY_ROUTES`` is off. Otherwise the SPA ``GET /{fallback:path}``
matches the path and POST returns 405 Method Not Allowed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application.workflow.workflow_types import normalize_workflow_risk

router = APIRouter(tags=["tools-execute"])


def _resolve_tool_request(body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Resolve HTTP and model envelopes against the existing action catalog."""
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2
    from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME
    from app.application.workflow_registry_app import _normalize_action

    payload = dict(body)
    name = str(payload.get("tool_name") or payload.get("name") or "").strip()
    params = payload.get("params", payload.get("arguments", payload.get("args", {})))
    if not isinstance(params, dict):
        raise ValueError("工具参数必须是 JSON 对象")
    if name == ERP_CAPABILITY_TOOL_NAME:
        payload = params
        params = payload.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("工具参数必须是 JSON 对象")
    tool_id = str(payload.get("tool_id") or payload.get("skill_id") or "").strip()
    action = str(payload.get("action") or params.get("action") or "").strip()
    if not tool_id and name:
        specs = build_tool_specs_v2()
        matches = [(tool, verb) for tool, verb in specs if name == f"{tool}_{verb}"]
        if len(matches) == 1:
            tool_id, action = matches[0]
        elif any(tool == name for tool, _ in specs):
            tool_id = name
            if not action and (tool_id, "execute") in specs:
                action = "execute"
    return tool_id, _normalize_action(action or "view", params), dict(params)


def user_id_from_tool_request(request: Request, body: dict[str, Any]) -> str:
    from app.infrastructure.auth.agent_principal import require_agent_principal

    return require_agent_principal(request, x_user_id=None).user_id


def _authenticated_tool_body(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    from app.fastapi_routes.domains.agent.route_support import (
        request_runtime_context,
        without_runtime_identity,
    )

    trusted = request_runtime_context(request)
    raw_params = body.get("params", body.get("arguments", body.get("args", {})))
    if not isinstance(raw_params, dict):
        # Authenticate first, then let the shared contract reject the original
        # malformed value instead of silently converting it to an empty call.
        return {**body, "user_id": trusted["user_id"], "params": raw_params}
    params = without_runtime_identity(raw_params)
    params["_runtime_context"] = trusted
    return {**body, "user_id": trusted["user_id"], "params": params}


def tool_route_agent_payload(run: Any, node_id: str) -> dict[str, Any]:
    from app.domain.task_lifecycle.results import (
        execution_result_requires_reconciliation,
    )

    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                if not output and str(getattr(step, "status", "")) == "waiting_user":
                    output = {
                        "success": False,
                        "error_code": "approval_required",
                        "message": "工具执行需要用户确认",
                        "waiting_step_id": getattr(step, "step_id", ""),
                    }
                break
    if not output:
        if getattr(run, "status", "") == "waiting_user":
            output = {
                "success": False,
                "error_code": "approval_required",
                "message": "工具执行需要用户确认",
            }
        else:
            output = {"success": getattr(run, "status", "") == "completed"}
    unknown = execution_result_requires_reconciliation(output)
    if unknown:
        output = {**output, "success": False}
    if not output.get("success"):
        # Tool implementations historically returned ``str(exc)`` and persisted
        # tracebacks in their failure payload.  Rebuild the public failure shape
        # from stable fields so neither can cross the HTTP boundary.  Preserve
        # only a validated HTTP status because route adapters need to distinguish
        # validation/not-found/unavailable failures without exposing raw details.
        raw_error_code = str(output.get("error_code") or "tool_failed")[:64]
        if raw_error_code in {
            "tool_permission_denied",
            "tool_identity_required",
            "approval_required",
        }:
            return {
                "success": False,
                "message": (
                    "工具执行需要用户确认"
                    if raw_error_code == "approval_required"
                    else "权限不足，已拒绝执行工具"
                ),
                "error_code": raw_error_code,
                "reason": str(output.get("reason") or raw_error_code)[:80],
                "user_id": str(output.get("user_id") or ""),
                "tool_id": str(output.get("tool_id") or "")[:80],
                "task_id": str(output.get("task_id") or getattr(run, "run_id", "") or ""),
                "run_id": str(getattr(run, "run_id", "") or ""),
                "agent_run_id": str(getattr(run, "run_id", "") or ""),
                "agent_status": str(getattr(run, "status", "") or ""),
            }
        try:
            raw_http_status = int(output.get("http_status_code") or 0)
        except (TypeError, ValueError):
            raw_http_status = 0
        original = output
        output = {
            "success": False,
            "message": "工具结果待核对，请勿重复提交" if unknown else "工具执行未完成",
            "error_code": raw_error_code,
        }
        for key in ("retryable", "reconciliation_required"):
            if type(original.get(key)) is bool:
                output[key] = original[key]
        for key in ("outcome", "execution_status"):
            if isinstance(original.get(key), str):
                output[key] = original[key][:64]
        if unknown:
            output.update(outcome="unknown", retryable=False, reconciliation_required=True)
        if 400 <= raw_http_status <= 599:
            output["http_status_code"] = raw_http_status
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
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.fastapi_routes.domains.agent.route_support import (
        request_runtime_context,
        without_runtime_identity,
    )

    trusted = request_runtime_context(request)
    try:
        tool_id, action, params = _resolve_tool_request(body)
    except ValueError as exc:
        return {
            "success": False,
            "error_code": "invalid_tool_arguments",
            "message": str(exc),
        }, 400
    params = without_runtime_identity(params)
    params.pop("_runtime_context", None)
    spec = get_tool_action_spec(tool_id, action)
    if spec is None:
        return {
            "success": False,
            "error_code": "tool_contract_unavailable",
            "message": "工具或动作未登记，未执行",
            "retryable": False,
            "execution_status": "not_started",
        }, 400
    if spec.availability == "aiopen":
        return {
            "success": False,
            "error_code": "tool_entry_unsupported",
            "message": "该工具需要原 AIOPEN 授权及会话入口，本次未执行",
            "retryable": False,
            "execution_status": "not_started",
        }, 400

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
                risk=normalize_workflow_risk(spec.risk),
                idempotent=spec.idempotent,
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=normalize_workflow_risk(spec.risk),
        metadata={"source": "tools_execute_route", "route": route_path},
    )
    user_id = trusted["user_id"]
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=str(body.get("message") or f"Execute {tool_id}.{action}"),
        plan=plan,
        runtime_context={
            **trusted,
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
    body = _authenticated_tool_body(request, body or {})
    agent_result = run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/skills/execute",
    )
    return JSONResponse(agent_result[0], status_code=agent_result[1])


@router.post("/api/tools/execute")
def tools_execute_route(request: Request, body: dict = Body(default_factory=dict)):
    body = _authenticated_tool_body(request, body or {})
    agent_result = run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/tools/execute",
    )
    return JSONResponse(agent_result[0], status_code=agent_result[1])
