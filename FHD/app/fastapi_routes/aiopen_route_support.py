"""Protocol and tracing helpers shared by the AIOPEN route module."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.application.aiopen.definitions import (
    MCP_DEFAULT_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSIONS,
    TOOL_DEFINITIONS,
)
from app.application.aiopen.runtime import ClientKeyLimitReached
from app.application.aiopen.service import (
    AIOPEN_STATE,
    has_active_client_key,
    issue_client_key,
    revoke_client_key,
)
from app.application.employee_runtime.result_verifier import (
    execution_result_requires_reconciliation,
)
from app.domain.aiopen.principal import ScreenPrincipal
from app.utils.operational_errors import RECOVERABLE_ERRORS

_TRACE_FLAGS = (
    "success",
    "pending_approval",
    "requires_token",
    "enabled",
    "merge",
    "revoked",
    "wechat_open",
    "remote_control_enabled",
    "retryable",
    "reconciliation_required",
    "requires_reconciliation",
)
_TRACE_TOOL_NAMES = frozenset(item["name"] for item in TOOL_DEFINITIONS)


def retired_openclaw_chat_response() -> JSONResponse:
    """Legacy raw gateway URLs must not dispatch outside the approved task runtime."""
    return JSONResponse(
        {
            "success": False,
            "error_code": "openclaw_legacy_route_retired",
            "execution_state": "not_started",
            "retryable": False,
            "message": "旧网关直连入口已停用，请通过统一任务入口申请执行。",
        },
        status_code=410,
    )


def safe_control_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only typed operational metadata, never business values or key prefixes."""
    safe: dict[str, Any] = {"payload_redacted": True}
    for name in _TRACE_FLAGS:
        value = payload.get(name)
        if isinstance(value, bool):
            safe[name] = value
    outcome = payload.get("outcome")
    if isinstance(outcome, str) and outcome in {
        "unknown",
        "succeeded",
        "failed",
        "not_started",
        "not_executed",
        "partial",
    }:
        safe["outcome"] = outcome
    if execution_result_requires_reconciliation(payload):
        safe.update(success=False, outcome="unknown", retryable=False, reconciliation_required=True)
    status = payload.get("status_code")
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        safe["status_code"] = status
    if payload.get("key"):
        safe["key_preview"] = "[REDACTED]"
    return safe


def trace_tool_call(
    *,
    route: str,
    channel: str,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
    create_trace_run: Callable[..., Any],
    logger: logging.Logger,
    user_id: str = "",
) -> str:
    try:
        tool = tool if tool in _TRACE_TOOL_NAMES else "unknown_tool"
        message = f"AIOPEN {tool} executed"
        safe_result = safe_control_payload(result or {})
        trace_payload = {
            "success": bool(safe_result.get("success", False)),
            "response": message,
            "data": {
                "text": message,
                "legacy_tool_records": [
                    {
                        "tool_id": "aiopen",
                        "tool_name": "aiopen",
                        "action": tool,
                        "params": {"payload_redacted": True, "argument_count": len(args or {})},
                        "output": safe_result,
                        "tool_call_id": f"aiopen:{tool}",
                    }
                ],
            },
        }
        run = create_trace_run(
            trace_payload,
            message=f"AIOPEN {tool}",
            runtime_context={
                "route": route,
                "source": "aiopen",
                "tool": tool,
                "protocol": "mcp" if channel == "aiopen_mcp" else "rest",
            },
            user_id=user_id or "aiopen-api-key",
            source="aiopen",
            channel=channel,
            intent="aiopen_tool_call",
        )
        return str(run.run_id)
    except RECOVERABLE_ERRORS as error:
        logger.warning("AIOPEN tool trace failed (%s)", type(error).__name__)
        return ""


def trace_control_result(
    payload: dict[str, Any],
    *,
    route: str,
    action: str,
    create_trace_run: Callable[..., Any],
    logger: logging.Logger,
    body: dict[str, Any] | None = None,
    channel: str = "aiopen_control",
    intent: str = "aiopen_control_update",
    user_id: str = "",
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        safe_payload = safe_control_payload(payload)
        safe_body = safe_control_payload(body or {})
        message = f"AIOPEN {action}"
        run = create_trace_run(
            {
                "success": bool(safe_payload.get("success", False)),
                "response": message,
                "data": {"text": message, "control_result": safe_payload},
            },
            message=f"AIOPEN {action}",
            runtime_context={
                "route": route,
                "source": "aiopen",
                "action": action,
                "request": safe_body,
            },
            user_id=user_id or "aiopen-control",
            source="aiopen",
            channel=channel,
            intent=intent,
        )
        traced = dict(payload)
        traced["run_id"] = run.run_id
        traced["agent_run_id"] = run.run_id
        return traced
    except RECOVERABLE_ERRORS as error:
        logger.warning("AIOPEN control trace failed (%s)", type(error).__name__)
        return payload


def resolve_mcp_protocol_version(params: dict[str, Any] | None) -> str:
    params = params if isinstance(params, dict) else {}
    requested = str(params.get("protocolVersion") or "").strip()
    if requested in MCP_PROTOCOL_VERSIONS:
        return requested
    return MCP_DEFAULT_PROTOCOL_VERSION


def mcp_response_headers(
    request: Request, protocol_version: str, *, new_session: bool = False
) -> dict[str, str]:
    headers = {"MCP-Protocol-Version": protocol_version}
    incoming = str(
        request.headers.get("mcp-session-id") or request.headers.get("Mcp-Session-Id") or ""
    ).strip()
    if incoming:
        headers["Mcp-Session-Id"] = incoming
    elif new_session:
        headers["Mcp-Session-Id"] = secrets.token_hex(16)
    return headers


def jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def handle_mcp_message(
    message: dict[str, Any],
    app: Any,
    protocol_version: str,
    *,
    manifest: Callable[[], dict[str, Any]],
    invoke: Callable[..., Any],
    format_result: Callable[[str, dict[str, Any]], str],
    trace_call: Callable[..., str],
    resources: dict[str, Callable[..., Any]] | None = None,
) -> dict[str, Any] | None:
    """Handle one stateless MCP JSON-RPC request or notification."""
    method = str(message.get("method") or "")
    request_id = message.get("id")
    is_notification = "id" not in message
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        negotiated = resolve_mcp_protocol_version(params)
        manifest_payload = manifest()
        capabilities: dict[str, Any] = {"tools": {"listChanged": False}}
        if resources is not None:
            capabilities["resources"] = {"listChanged": False, "subscribe": False}
        return jsonrpc_result(
            request_id,
            {
                "protocolVersion": negotiated,
                "capabilities": capabilities,
                "serverInfo": {
                    "name": manifest_payload["name"],
                    "version": manifest_payload["version"],
                },
                "instructions": (
                    f"{manifest_payload['tagline']}\n"
                    "先知后做：knowledge_search 检索能力 → operation_describe 读语义卡片 → "
                    "operation_call 使用稳定 request_id 执行业务；页面操作用 ui_sessions → ui_snapshot → ui_click/ui_type。"
                ),
            },
        )
    if method == "ping":
        return jsonrpc_result(request_id, {})
    if method == "tools/list":
        return jsonrpc_result(request_id, {"tools": manifest()["tools"]})
    if resources is not None and method == "resources/list":
        return jsonrpc_result(request_id, {"resources": resources["list"](app)})
    if resources is not None and method == "resources/templates/list":
        return jsonrpc_result(request_id, {"resourceTemplates": resources["templates"]()})
    if resources is not None and method == "resources/read":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        uri = str((params or {}).get("uri") or "").strip()
        if not uri:
            return jsonrpc_error(request_id, -32602, "resources/read 需要 uri")
        try:
            payload = resources["read"](app, uri)
        except ValueError as error:
            return jsonrpc_error(request_id, -32602, str(error))
        return jsonrpc_result(request_id, payload)
    if method == "tools/call":
        raw_params = message.get("params")
        call_params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
        tool = str(call_params.get("name") or "")
        raw_args = call_params.get("arguments")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        try:
            result = await invoke(tool, args, app)
        except RECOVERABLE_ERRORS:
            return jsonrpc_error(request_id, -32603, "tool execution failed")
        trace_id = str(result.get("run_id") or result.get("agent_run_id") or "") or trace_call(
            route="/api/aiopen/mcp",
            channel="aiopen_mcp",
            tool=tool,
            args=args,
            result=result,
        )
        mcp_result: dict[str, Any] = {
            "content": [{"type": "text", "text": format_result(tool, result)}],
            "structuredContent": result,
            "isError": safe_control_payload(result).get("success") is not True,
        }
        if trace_id:
            mcp_result["_meta"] = {"run_id": trace_id, "agent_run_id": trace_id}
            for key in ("task_id", "request_id", "approval_request_id"):
                if result.get(key):
                    mcp_result["_meta"][key] = result[key]
        return jsonrpc_result(request_id, mcp_result)
    if is_notification:
        return None
    return jsonrpc_error(request_id, -32601, f"method not found: {method}")


def wrap_mcp_json(
    payload: dict[str, Any] | list[dict[str, Any]] | None,
    request: Request,
    *,
    status_code: int = 200,
    protocol_version: str = MCP_DEFAULT_PROTOCOL_VERSION,
    new_session: bool = False,
) -> Response:
    headers = mcp_response_headers(request, protocol_version, new_session=new_session)
    if payload is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(payload, status_code=status_code, headers=headers)


def create_client_router(trace_result, get_logged_in_user):
    router = APIRouter()

    def _client_principal(user: Any = Depends(get_logged_in_user)) -> ScreenPrincipal:
        principal = ScreenPrincipal.from_user(user)
        if principal is None:
            raise HTTPException(status_code=403, detail="当前账号没有有效的租户归属")
        return principal

    @router.get("/api/aiopen/client")
    def aiopen_client_panel(principal: ScreenPrincipal = Depends(_client_principal)):
        return {
            "success": True,
            "client_mode": True,
            "has_active_key": has_active_client_key(principal),
            "keys": [],
            "remote_control_enabled": bool(AIOPEN_STATE.get("remote_control_enabled")),
        }

    @router.post("/api/aiopen/client/key")
    def aiopen_client_key_create(
        principal: ScreenPrincipal = Depends(_client_principal), keep_existing: bool = False
    ):
        try:
            issued = issue_client_key(principal, keep_existing=keep_existing)
        except ClientKeyLimitReached as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="口令存储暂不可用") from exc
        result = trace_result(
            {"success": True, "key": issued["key"], "expires_at": issued["expires_at"]},
            route="/api/aiopen/client/key",
            action="client_key_create",
            user_id=principal.principal_id,
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @router.delete("/api/aiopen/client/key")
    def aiopen_client_key_revoke(principal: ScreenPrincipal = Depends(_client_principal)):
        try:
            revoked = revoke_client_key(principal)
        except OSError as exc:
            raise HTTPException(status_code=503, detail="口令撤销尚未保存") from exc
        return trace_result(
            {"success": True, "revoked": revoked},
            route="/api/aiopen/client/key",
            action="client_key_revoke",
            user_id=principal.principal_id,
        )

    return router
