"""Protocol and tracing helpers shared by the AIOPEN route module."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.application.aiopen.service import (
    MCP_DEFAULT_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSIONS,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def safe_control_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    raw_key = str(safe.pop("key", "") or "")
    if raw_key:
        safe["key_preview"] = raw_key[:16]
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
        message = str(result.get("message") or result.get("code") or f"AIOPEN tool {tool} executed")
        trace_payload = {
            "success": bool(result.get("success", False)),
            "response": message,
            "data": {
                "text": message,
                "legacy_tool_records": [
                    {
                        "tool_id": "aiopen",
                        "tool_name": "aiopen",
                        "action": tool,
                        "params": dict(args or {}),
                        "output": dict(result or {}),
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
            user_id=user_id or str(args.get("user_id") or args.get("userId") or "aiopen"),
            source="aiopen",
            channel=channel,
            intent="aiopen_tool_call",
        )
        return str(run.run_id)
    except RECOVERABLE_ERRORS:
        logger.exception("failed to attach AgentRun trace to AIOPEN tool call")
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
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        safe_payload = safe_control_payload(payload)
        safe_body = safe_control_payload(body or {})
        message = str(payload.get("message") or action)
        run = create_trace_run(
            {
                "success": bool(payload.get("success", False)),
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
            user_id=str(
                (body or {}).get("user_id") or (body or {}).get("userId") or "aiopen-control"
            ),
            source="aiopen",
            channel=channel,
            intent=intent,
        )
        traced = dict(payload)
        traced["run_id"] = run.run_id
        traced["agent_run_id"] = run.run_id
        return traced
    except RECOVERABLE_ERRORS:
        logger.exception("failed to attach AgentRun trace to AIOPEN control action")
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
        return jsonrpc_result(
            request_id,
            {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": manifest_payload["name"],
                    "version": manifest_payload["version"],
                },
                "instructions": (
                    f"{manifest_payload['tagline']}\n"
                    "操作流程：ui_sessions → ui_snapshot → ui_click/ui_type/ui_navigate。"
                    "业务数据用 api_catalog + api_call；对话用 chat。"
                ),
            },
        )
    if method == "ping":
        return jsonrpc_result(request_id, {})
    if method == "tools/list":
        return jsonrpc_result(request_id, {"tools": manifest()["tools"]})
    if method == "tools/call":
        raw_params = message.get("params")
        call_params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
        tool = str(call_params.get("name") or "")
        raw_args = call_params.get("arguments")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        try:
            result = await invoke(tool, args, app)
        except RECOVERABLE_ERRORS as error:
            return jsonrpc_error(request_id, -32603, f"tool execution failed: {error}")
        trace_id = trace_call(
            route="/api/aiopen/mcp",
            channel="aiopen_mcp",
            tool=tool,
            args=args,
            result=result,
        )
        mcp_result: dict[str, Any] = {
            "content": [{"type": "text", "text": format_result(tool, result)}],
            "isError": not bool(result.get("success", False)),
        }
        if trace_id:
            mcp_result["_meta"] = {"run_id": trace_id, "agent_run_id": trace_id}
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
