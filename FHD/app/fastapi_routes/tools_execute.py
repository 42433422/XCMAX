"""Authenticated HTTP projection of the canonical capability execution chain."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

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
    action = action or "view"
    return (
        tool_id,
        action if tool_id.startswith("mcp__") else _normalize_action(action, params),
        dict(params),
    )


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


def _capability_http_receipt(receipt: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Project a canonical receipt; the executor alone decides its outcome."""
    from app.domain.task_lifecycle.results import (
        execution_result_outcome_unknown,
    )

    result = receipt.get("result")
    output = {**(result if isinstance(result, dict) else {}), **receipt}
    try:
        failure_status = int(output.get("http_status_code") or 0)
    except (TypeError, ValueError):
        failure_status = 0
    state = str(receipt.get("execution_state") or "")
    output["agent_status"] = str(receipt.get("run_status") or receipt.get("agent_status") or state)
    unknown = execution_result_outcome_unknown(receipt)
    if unknown:
        output.update(success=False, retryable=False, reconciliation_required=True)
    if receipt.get("pending_approval"):
        output["error_code"] = "approval_required"
        output["agent_status"] = str(receipt.get("run_status") or "waiting_user")
    if output.get("success") is not True:
        # A plugin failure can contain business values or an internal exception.
        # Keep the stable receipt fields without copying its raw failure details.
        safe_keys = {
            "success",
            "error_code",
            "task_id",
            "request_id",
            "root_task_id",
            "attempt",
            "run_id",
            "agent_run_id",
            "agent_status",
            "execution_state",
            "execution_status",
            "outcome",
            "retryable",
            "reconciliation_required",
            "requires_reconciliation",
            "pending_approval",
            "approval_request_id",
            "plan_id",
            "deduplicated",
            "execution_accepted",
            "requires_confirmation",
            "capability",
            "idempotency_scope",
        }
        output = {key: value for key, value in output.items() if key in safe_keys}
        output["success"] = False
        output["message"] = (
            "工具结果待核对，请查询原任务，勿重复提交"
            if unknown
            else (
                "工具执行需要审批"
                if receipt.get("pending_approval")
                else "工具执行尚未完成，请查看任务状态"
            )
        )
    error = str(output.get("error_code") or "")
    if error == "approval_scope_required":
        output["message"] = "当前账号没有可用的企业审批范围，本次操作尚未开始"
        return output, 403
    if error == "task_identity_required":
        output["message"] = "本次写操作需要稳定请求标识，本次操作尚未开始"
    if error == "task_idempotency_conflict":
        return output, 409
    if error in {"tool_permission_denied", "tool_identity_required"}:
        return output, 403
    if (
        unknown
        or receipt.get("pending_approval")
        or state
        in {
            "pending",
            "accepted",
            "queued",
            "planning",
            "running",
            "processing",
            "retrying",
            "waiting_user",
            "waiting_input",
            "waiting_approval",
            "waiting_auth",
            "paused",
        }
    ):
        return output, 202
    if output.get("success") is True:
        return output, 200
    return output, failure_status if 400 <= failure_status <= 599 else 400


def run_tools_execute_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.tools.registered_capabilities import (
        execute_registered_capability,
    )
    from app.fastapi_routes.domains.agent.route_support import (
        request_runtime_context,
        without_runtime_identity,
    )

    trusted = request_runtime_context(request)
    try:
        tool_id, action, params = _resolve_tool_request(body)
    except ValueError:
        return {
            "success": False,
            "error_code": "invalid_tool_arguments",
            "message": "工具请求格式无效，请检查工具名称与参数。",
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
    keys = [
        str(value).strip()
        for value in (
            request.headers.get("Idempotency-Key"),
            body.get("idempotency_key"),
            body.get("request_id"),
        )
        if value is not None and str(value).strip()
    ]
    if any(len(key) > 160 for key in keys) or len(set(keys)) > 1:
        return {
            "success": False,
            "error_code": "invalid_idempotency_key",
            "message": "请求标识必须一致且不能超过 160 字符",
            "execution_status": "not_started",
        }, 400
    context = {
        **trusted,
        "source": "tools_execute_route",
        "route": route_path,
        "request_path": str(request.url.path),
    }
    if keys:
        context["idempotency_key"] = keys[0]
    try:
        receipt = json.loads(
            execute_registered_capability(
                {"tool_id": tool_id, "action": action, "params": params},
                runtime_context=context,
                workspace_root=trusted.get("workspace_root"),
            )
        )
        if not isinstance(receipt, dict):
            raise ValueError("invalid capability receipt")
    except RECOVERABLE_ERRORS:
        receipt = {
            "success": False,
            "error_code": "capability_receipt_unavailable",
            "execution_state": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
    return _capability_http_receipt(receipt)


@router.post("/api/tools/execute")
def tools_execute_route(request: Request, body: dict = Body(default_factory=dict)):
    body = _authenticated_tool_body(request, body or {})
    agent_result = run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/tools/execute",
    )
    return JSONResponse(agent_result[0], status_code=agent_result[1])
