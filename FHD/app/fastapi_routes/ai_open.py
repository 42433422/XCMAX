"""AIOPEN 开放平台路由（toA：面向外部 AI Agent）。

由原 Qclaw龙虾生态（:mod:`app.fastapi_routes.ai_qclaw`）升级而来：

- ``GET  /api/aiopen/manifest`` — 工具目录（公开，无需 Key）
- ``GET  /api/aiopen/guide`` — 接入说明（公开；供其他 AI 阅读后自行配置 MCP）
- ``POST /api/aiopen/invoke`` — REST 通用工具调用 ``{tool, args}``（需 ``X-AIOPEN-Key``）
- ``POST /api/aiopen/mcp`` — MCP Streamable HTTP 端点（JSON-RPC 2.0：
  initialize / tools/list / tools/call / ping；无状态 application/json 应答）
- ``GET/POST/DELETE /api/aiopen/keys`` — 面板管理运行时 API Key
- ``GET  /api/aiopen/panel`` + ``POST /api/aiopen/whitelist|config|control`` — 控制台
- ``WS   /api/aiopen/ws`` — 前端 screen 端（虚拟光标）连接

旧 ``/api/ai/qclaw/*`` URL 全部保留（见 ai_qclaw.py），与本模块共享
``AIOPEN_STATE`` 运行时状态。
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    create_chat_trace_run,
)
from app.application.aiopen.service import (
    AIOPEN_STATE,
    MCP_DEFAULT_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSIONS,
    aiopen_manifest,
    build_aiopen_guide,
    build_mcp_install_bundle,
    format_tool_result_text,
    generate_api_key,
    invoke_tool,
    list_api_keys,
    openclaw_chat_proxy,
    revoke_api_key,
    verify_api_key,
)
from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["aiopen"])

AiOpenKeyHeader = Annotated[str | None, Header(alias="X-AIOPEN-Key")]


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": "invalid X-AIOPEN-Key", "code": "AIOPEN_KEY_INVALID"},
        status_code=401,
    )


def _trace_aiopen_tool_call(
    *,
    route: str,
    channel: str,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
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
        run = create_chat_trace_run(
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
        return run.run_id
    except Exception:  # noqa: BLE001 - tracing must not break external tool calls
        logger.exception("failed to attach AgentRun trace to AIOPEN tool call")
        return ""


def _safe_aiopen_control_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    raw_key = str(safe.pop("key", "") or "")
    if raw_key:
        safe["key_preview"] = raw_key[:16]
    return safe


def _trace_aiopen_control_result(
    payload: dict[str, Any],
    *,
    route: str,
    action: str,
    body: dict[str, Any] | None = None,
    channel: str = "aiopen_control",
    intent: str = "aiopen_control_update",
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        safe_payload = _safe_aiopen_control_payload(payload)
        safe_body = _safe_aiopen_control_payload(body or {})
        message = str(payload.get("message") or action)
        run = create_chat_trace_run(
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
    except Exception:  # noqa: BLE001 - tracing must not break control-plane writes
        logger.exception("failed to attach AgentRun trace to AIOPEN control action")
        return payload


# ---------------------------------------------------------------------------
# 公开：manifest
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/manifest")
def aiopen_manifest_route():
    return {"success": True, **aiopen_manifest()}


@router.get("/api/aiopen/guide")
def aiopen_guide_route(
    request: Request,
    format: str = Query(default="json", alias="format"),
):
    """公开接入说明：其他 AI Agent 读取后可自行完成 MCP 配置。

    - ``format=json``（默认）：JSON，含 ``markdown`` / ``mcp_config_template`` / ``prompt_for_user``
    - ``format=markdown`` 或 ``format=text``：纯 Markdown 文本，便于 AI 直接阅读
    """
    base = str(request.base_url).rstrip("/")
    payload = build_aiopen_guide(base)
    fmt = str(format or "json").strip().lower()
    if fmt in {"markdown", "text", "md"}:
        return PlainTextResponse(payload["markdown"], media_type="text/markdown; charset=utf-8")
    return payload


@router.get("/api/aiopen/install")
def aiopen_install_route(request: Request, key: str = Query(default="")):
    """公开：MCP 安装包（Cursor deep link / stdio / mcp-remote 多种方式）。"""
    base = str(request.base_url).rstrip("/")
    bundle = build_mcp_install_bundle(base, api_key=str(key or "").strip())
    manifest = aiopen_manifest()
    return {
        "success": True,
        "tool_count": len(manifest["tools"]),
        "protocol_versions": list(MCP_PROTOCOL_VERSIONS),
        **bundle,
    }


# ---------------------------------------------------------------------------
# REST 通用调用
# ---------------------------------------------------------------------------


@router.post("/api/aiopen/invoke")
async def aiopen_invoke(
    request: Request,
    x_aiopen_key: AiOpenKeyHeader = None,
    body: dict = Body(default_factory=dict),
):
    if not verify_api_key(x_aiopen_key):
        return _unauthorized()
    tool = str(body.get("tool") or "").strip()
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    if not tool:
        return JSONResponse({"success": False, "message": "tool 不能为空"}, status_code=400)
    result = await invoke_tool(tool, args, request.app)
    status = 200
    if result.get("code") == "ROUTE_NOT_WHITELISTED":
        status = 403
    elif result.get("code") == "UNKNOWN_TOOL":
        status = 404
    payload = {"tool": tool, **result}
    run_id = _trace_aiopen_tool_call(
        route="/api/aiopen/invoke",
        channel="aiopen_invoke",
        tool=tool,
        args=args,
        result=result,
        user_id=str(body.get("user_id") or body.get("userId") or ""),
    )
    if run_id:
        payload["run_id"] = run_id
        payload["agent_run_id"] = run_id
    return JSONResponse(payload, status_code=status)


# ---------------------------------------------------------------------------
# MCP Streamable HTTP（JSON-RPC 2.0）
# ---------------------------------------------------------------------------


def _resolve_mcp_protocol_version(params: dict[str, Any] | None) -> str:
    params = params if isinstance(params, dict) else {}
    requested = str(params.get("protocolVersion") or "").strip()
    if requested in MCP_PROTOCOL_VERSIONS:
        return requested
    return MCP_DEFAULT_PROTOCOL_VERSION


def _mcp_response_headers(
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


def _jsonrpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle_mcp_message(
    msg: dict[str, Any], app: Any, protocol_version: str
) -> dict[str, Any] | None:
    """处理单条 JSON-RPC 消息；notification（无 id）返回 None。"""
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    is_notification = "id" not in msg

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        negotiated = _resolve_mcp_protocol_version(params)
        manifest = aiopen_manifest()
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": manifest["name"], "version": manifest["version"]},
                "instructions": (
                    f"{manifest['tagline']}\n"
                    "操作流程：ui_sessions → ui_snapshot → ui_click/ui_type/ui_navigate。"
                    "业务数据用 api_catalog + api_call；对话用 chat。"
                ),
            },
        )
    if method == "ping":
        return _jsonrpc_result(req_id, {})
    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": aiopen_manifest()["tools"]})
    if method == "tools/call":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        tool = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = await invoke_tool(tool, args, app)
        except RECOVERABLE_ERRORS as err:
            return _jsonrpc_error(req_id, -32603, f"tool execution failed: {err}")
        is_error = not bool(result.get("success", False))
        text = format_tool_result_text(tool, result)
        run_id = _trace_aiopen_tool_call(
            route="/api/aiopen/mcp",
            channel="aiopen_mcp",
            tool=tool,
            args=args,
            result=result,
        )
        mcp_result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }
        if run_id:
            mcp_result["_meta"] = {"run_id": run_id, "agent_run_id": run_id}
        return _jsonrpc_result(
            req_id,
            mcp_result,
        )
    if is_notification:
        return None
    return _jsonrpc_error(req_id, -32601, f"method not found: {method}")


def _wrap_mcp_json(
    payload: dict[str, Any] | list[dict[str, Any]] | None,
    request: Request,
    *,
    status_code: int = 200,
    protocol_version: str = MCP_DEFAULT_PROTOCOL_VERSION,
    new_session: bool = False,
) -> Response:
    headers = _mcp_response_headers(request, protocol_version, new_session=new_session)
    if payload is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(payload, status_code=status_code, headers=headers)


@router.get("/api/aiopen/mcp")
async def aiopen_mcp_get(request: Request, x_aiopen_key: AiOpenKeyHeader = None):
    """Streamable HTTP GET：无 SSE 推送时返回服务说明（Cursor 探测用）。"""
    if not verify_api_key(x_aiopen_key):
        return _unauthorized()
    manifest = aiopen_manifest()
    return JSONResponse(
        {
            "success": True,
            "transport": "streamable-http",
            "mcp_endpoint": "/api/aiopen/mcp",
            "protocol_versions": list(MCP_PROTOCOL_VERSIONS),
            "server": manifest["name"],
            "tool_count": len(manifest["tools"]),
            "hint": "Send JSON-RPC via POST with Content-Type: application/json",
        },
        headers=_mcp_response_headers(request, MCP_DEFAULT_PROTOCOL_VERSION),
    )


@router.post("/api/aiopen/mcp")
async def aiopen_mcp(
    request: Request,
    x_aiopen_key: AiOpenKeyHeader = None,
    body: Any = Body(default=None),
):
    if not verify_api_key(x_aiopen_key):
        return _unauthorized()
    params = body.get("params") if isinstance(body, dict) else {}
    protocol_version = _resolve_mcp_protocol_version(params if isinstance(params, dict) else {})
    is_initialize = isinstance(body, dict) and body.get("method") == "initialize"

    if isinstance(body, list):
        responses = []
        for item in body:
            if isinstance(item, dict):
                item_params = item.get("params") if isinstance(item.get("params"), dict) else {}
                if item.get("method") == "initialize":
                    protocol_version = _resolve_mcp_protocol_version(item_params)
                    is_initialize = True
                resp = await _handle_mcp_message(item, request.app, protocol_version)
                if resp is not None:
                    responses.append(resp)
        if not responses:
            return _wrap_mcp_json(None, request, status_code=202, protocol_version=protocol_version)
        return _wrap_mcp_json(
            responses,
            request,
            protocol_version=protocol_version,
            new_session=is_initialize,
        )
    if not isinstance(body, dict):
        return _wrap_mcp_json(
            _jsonrpc_error(None, -32700, "parse error: body must be a JSON object"),
            request,
            status_code=400,
            protocol_version=protocol_version,
        )
    resp = await _handle_mcp_message(body, request.app, protocol_version)
    if resp is None:
        return _wrap_mcp_json(None, request, status_code=202, protocol_version=protocol_version)
    return _wrap_mcp_json(
        resp,
        request,
        protocol_version=protocol_version,
        new_session=is_initialize,
    )


# ---------------------------------------------------------------------------
# API Key 管理（面板）
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/keys")
def aiopen_keys_list():
    return {"success": True, "keys": list_api_keys()}


@router.post("/api/aiopen/keys")
def aiopen_keys_create(body: dict = Body(default_factory=dict)):
    created = generate_api_key(str(body.get("label") or ""))
    return _trace_aiopen_control_result(
        {"success": True, **created},
        route="/api/aiopen/keys",
        action="keys_create",
        body=body,
    )


@router.delete("/api/aiopen/keys")
def aiopen_keys_revoke(body: dict = Body(default_factory=dict)):
    key = str(body.get("key") or "").strip()
    if not key:
        return JSONResponse({"success": False, "message": "key 不能为空"}, status_code=400)
    ok = revoke_api_key(key)
    return _trace_aiopen_control_result(
        {"success": ok, "revoked": ok},
        route="/api/aiopen/keys",
        action="keys_revoke",
        body=body,
    )


# ---------------------------------------------------------------------------
# 控制台面板
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/panel")
def aiopen_panel(request: Request):
    whitelist = AIOPEN_STATE.get("whitelist", {})
    base = str(request.base_url).rstrip("/")
    manifest = aiopen_manifest()
    return {
        "success": True,
        "wechat_open": bool(AIOPEN_STATE.get("wechat_open", False)),
        "openclaw_base": str(AIOPEN_STATE.get("openclaw_base", "http://127.0.0.1:28789")),
        "remote_control_enabled": bool(AIOPEN_STATE.get("remote_control_enabled", False)),
        "routes": [{"path": p, "enabled": bool(e)} for p, e in whitelist.items()],
        "screen_sessions": aiopen_cursor_hub.sessions_info(),
        "recent_commands": aiopen_cursor_hub.recent_commands(30),
        "keys": list_api_keys(),
        "mcp": {
            "tool_count": len(manifest["tools"]),
            "endpoint": f"{base}/api/aiopen/mcp",
            "install_url": f"{base}/api/aiopen/install",
        },
    }


@router.post("/api/aiopen/whitelist")
def aiopen_whitelist(body: dict = Body(default_factory=dict)):
    path = str(body.get("path") or "").strip()
    enabled = bool(body.get("enabled", False))
    if not path:
        return JSONResponse({"success": False, "message": "path 不能为空"}, status_code=400)
    AIOPEN_STATE.setdefault("whitelist", {})[path] = enabled
    return _trace_aiopen_control_result(
        {"success": True, "path": path, "enabled": enabled},
        route="/api/aiopen/whitelist",
        action="whitelist_update",
        body=body,
    )


@router.post("/api/aiopen/config")
def aiopen_config(body: dict = Body(default_factory=dict)):
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return JSONResponse({"success": False, "message": "base_url 不能为空"}, status_code=400)
    AIOPEN_STATE["openclaw_base"] = base_url
    return _trace_aiopen_control_result(
        {"success": True, "openclaw_base": base_url},
        route="/api/aiopen/config",
        action="openclaw_config_update",
        body=body,
    )


@router.post("/api/aiopen/control")
def aiopen_control(body: dict = Body(default_factory=dict)):
    enabled = bool(body.get("enabled", False))
    AIOPEN_STATE["remote_control_enabled"] = enabled
    return _trace_aiopen_control_result(
        {"success": True, "remote_control_enabled": enabled},
        route="/api/aiopen/control",
        action="remote_control_update",
        body=body,
    )


@router.post("/api/aiopen/openclaw/chat")
def aiopen_openclaw_chat(body: dict = Body(default_factory=dict)):
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"success": False, "message": "message 不能为空"}, status_code=400)
    payload, status = openclaw_chat_proxy(message)
    payload = attach_chat_trace_run(
        payload,
        message=message,
        runtime_context={
            "route": "/api/aiopen/openclaw/chat",
            "source": "aiopen",
            "external_gateway": "openclaw",
        },
        user_id=str(body.get("user_id") or body.get("userId") or "").strip() or None,
        source="aiopen",
        channel="aiopen_openclaw",
        intent="external_openclaw_chat",
    )
    if status == 200:
        return payload
    return JSONResponse(payload, status_code=status)


# ---------------------------------------------------------------------------
# 虚拟光标 screen 端 WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/api/aiopen/ws")
async def aiopen_screen_ws(ws: WebSocket):
    await ws.accept()
    session_id = str(ws.query_params.get("session_id") or "").strip()
    if not session_id:
        import uuid

        session_id = "screen_" + uuid.uuid4().hex[:12]
    label = str(ws.query_params.get("label") or "").strip()
    await aiopen_cursor_hub.connect(session_id, ws, meta={"label": label or "XCAGI 前端"})
    try:
        await ws.send_json({"type": "hello", "session_id": session_id})
        while True:
            raw = await ws.receive_text()
            handled = aiopen_cursor_hub.handle_client_message(raw)
            if not handled:
                logger.debug("aiopen ws unhandled message: %s", raw[:200])
    except WebSocketDisconnect:
        pass
    except RECOVERABLE_ERRORS:
        logger.exception("aiopen screen ws error session=%s", session_id)
    finally:
        await aiopen_cursor_hub.disconnect(session_id)
