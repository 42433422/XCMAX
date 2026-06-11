"""AIOPEN 开放平台路由（toA：面向外部 AI Agent）。

由原 Qclaw龙虾生态（:mod:`app.fastapi_routes.ai_qclaw`）升级而来：

- ``GET  /api/aiopen/manifest`` — 工具目录（公开，无需 Key）
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
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.application.aiopen.service import (
    AIOPEN_STATE,
    aiopen_manifest,
    generate_api_key,
    invoke_tool,
    list_api_keys,
    openclaw_chat_proxy,
    revoke_api_key,
    verify_api_key,
)
from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["aiopen"])

AiOpenKeyHeader = Annotated[str | None, Header(alias="X-AIOPEN-Key")]


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": "invalid X-AIOPEN-Key", "code": "AIOPEN_KEY_INVALID"},
        status_code=401,
    )


# ---------------------------------------------------------------------------
# 公开：manifest
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/manifest")
def aiopen_manifest_route():
    return {"success": True, **aiopen_manifest()}


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
    return JSONResponse({"tool": tool, **result}, status_code=status)


# ---------------------------------------------------------------------------
# MCP Streamable HTTP（JSON-RPC 2.0，无状态）
# ---------------------------------------------------------------------------

_MCP_PROTOCOL_VERSION = "2025-03-26"


def _jsonrpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle_mcp_message(msg: dict[str, Any], app: Any) -> dict[str, Any] | None:
    """处理单条 JSON-RPC 消息；notification（无 id）返回 None。"""
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    is_notification = "id" not in msg

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        manifest = aiopen_manifest()
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": manifest["name"], "version": manifest["version"]},
                "instructions": manifest["tagline"],
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
        except OPERATIONAL_ERRORS as err:
            return _jsonrpc_error(req_id, -32603, f"tool execution failed: {err}")
        import json as _json

        is_error = not bool(result.get("success", False))
        return _jsonrpc_result(
            req_id,
            {
                "content": [{"type": "text", "text": _json.dumps(result, ensure_ascii=False, default=str)}],
                "isError": is_error,
            },
        )
    if is_notification:
        return None
    return _jsonrpc_error(req_id, -32601, f"method not found: {method}")


@router.post("/api/aiopen/mcp")
async def aiopen_mcp(
    request: Request,
    x_aiopen_key: AiOpenKeyHeader = None,
    body: Any = Body(default=None),
):
    if not verify_api_key(x_aiopen_key):
        return _unauthorized()
    if isinstance(body, list):
        responses = []
        for item in body:
            if isinstance(item, dict):
                resp = await _handle_mcp_message(item, request.app)
                if resp is not None:
                    responses.append(resp)
        if not responses:
            return JSONResponse(None, status_code=202)
        return JSONResponse(responses)
    if not isinstance(body, dict):
        return JSONResponse(_jsonrpc_error(None, -32700, "parse error: body must be a JSON object"), status_code=400)
    resp = await _handle_mcp_message(body, request.app)
    if resp is None:
        return JSONResponse(None, status_code=202)
    return JSONResponse(resp)


# ---------------------------------------------------------------------------
# API Key 管理（面板）
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/keys")
def aiopen_keys_list():
    return {"success": True, "keys": list_api_keys()}


@router.post("/api/aiopen/keys")
def aiopen_keys_create(body: dict = Body(default_factory=dict)):
    created = generate_api_key(str(body.get("label") or ""))
    return {"success": True, **created}


@router.delete("/api/aiopen/keys")
def aiopen_keys_revoke(body: dict = Body(default_factory=dict)):
    key = str(body.get("key") or "").strip()
    if not key:
        return JSONResponse({"success": False, "message": "key 不能为空"}, status_code=400)
    ok = revoke_api_key(key)
    return {"success": ok, "revoked": ok}


# ---------------------------------------------------------------------------
# 控制台面板
# ---------------------------------------------------------------------------


@router.get("/api/aiopen/panel")
def aiopen_panel():
    whitelist = AIOPEN_STATE.get("whitelist", {})
    return {
        "success": True,
        "wechat_open": bool(AIOPEN_STATE.get("wechat_open", False)),
        "openclaw_base": str(AIOPEN_STATE.get("openclaw_base", "http://127.0.0.1:28789")),
        "remote_control_enabled": bool(AIOPEN_STATE.get("remote_control_enabled", False)),
        "routes": [{"path": p, "enabled": bool(e)} for p, e in whitelist.items()],
        "screen_sessions": aiopen_cursor_hub.sessions_info(),
        "recent_commands": aiopen_cursor_hub.recent_commands(30),
        "keys": list_api_keys(),
    }


@router.post("/api/aiopen/whitelist")
def aiopen_whitelist(body: dict = Body(default_factory=dict)):
    path = str(body.get("path") or "").strip()
    enabled = bool(body.get("enabled", False))
    if not path:
        return JSONResponse({"success": False, "message": "path 不能为空"}, status_code=400)
    AIOPEN_STATE.setdefault("whitelist", {})[path] = enabled
    return {"success": True, "path": path, "enabled": enabled}


@router.post("/api/aiopen/config")
def aiopen_config(body: dict = Body(default_factory=dict)):
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return JSONResponse({"success": False, "message": "base_url 不能为空"}, status_code=400)
    AIOPEN_STATE["openclaw_base"] = base_url
    return {"success": True, "openclaw_base": base_url}


@router.post("/api/aiopen/control")
def aiopen_control(body: dict = Body(default_factory=dict)):
    enabled = bool(body.get("enabled", False))
    AIOPEN_STATE["remote_control_enabled"] = enabled
    return {"success": True, "remote_control_enabled": enabled}


@router.post("/api/aiopen/openclaw/chat")
def aiopen_openclaw_chat(body: dict = Body(default_factory=dict)):
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"success": False, "message": "message 不能为空"}, status_code=400)
    payload, status = openclaw_chat_proxy(message)
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
    except OPERATIONAL_ERRORS:
        logger.exception("aiopen screen ws error session=%s", session_id)
    finally:
        await aiopen_cursor_hub.disconnect(session_id)
