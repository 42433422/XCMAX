"""AIOPEN 开放平台应用服务。

来源：从 :mod:`app.fastapi_routes.ai_qclaw`（原 Qclaw龙虾生态）演进而来的 toA
开放平台核心。``AIOPEN_STATE`` 是运行时状态 SSOT，旧 ``/api/ai/qclaw/*`` 路由
保持 URL 契约不变并共享本状态（``_QCLOW_RUNTIME_STATE`` 即其别名）。

职责：
- 运行时状态（路由白名单 / openclaw_base / 远程操控开关 / 运行时 API Key）
- 工具注册表（MCP ``tools/list`` 与 REST ``/api/aiopen/invoke`` 共用同一份 manifest）
- API Key 鉴权（env ``AIOPEN_API_KEY`` + 面板运行时生成）
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any

from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

AIOPEN_PRODUCT_NAME = "AIOPEN"
AIOPEN_PRODUCT_TAGLINE = "我是 AI 的工具 — MCP / API 开放平台与虚拟光标操控"

# 运行时状态 SSOT（进程内，无持久化；与旧 qclaw 面板共享）。
AIOPEN_STATE: dict[str, Any] = {
    "wechat_open": True,
    "openclaw_base": "http://localhost:28789",
    "whitelist": {
        "/api/ai/chat": True,
        "/api/ai/unified_chat": True,
        "/api/wechat_contacts": True,
        "/api/shipment/orders": True,
        "/api/print/printers": True,
        "/api/products": True,
        "/api/customers": True,
        "/api/materials": True,
    },
    # 虚拟光标远程操控总开关（面板可改；默认开，前端 screen 端默认不连）
    "remote_control_enabled": True,
    # 面板运行时生成的 API Key：{key: {"label": str, "created_at": float}}
    "runtime_keys": {},
}


# ---------------------------------------------------------------------------
# API Key 鉴权
# ---------------------------------------------------------------------------


def _env_api_key() -> str:
    return (os.environ.get("AIOPEN_API_KEY") or "").strip()


def verify_api_key(provided: str | None) -> bool:
    """校验 ``X-AIOPEN-Key``。

    未配置任何 Key（env 与运行时均为空）时放行 —— 与
    :func:`app.fastapi_routes.business_api.require_fhd_business_key` 同策略，
    安全由 LAN 门禁兜底；生产务必配置 ``AIOPEN_API_KEY``。
    """
    env_key = _env_api_key()
    runtime_keys: dict[str, Any] = AIOPEN_STATE.get("runtime_keys", {})
    if not env_key and not runtime_keys:
        return True
    got = (provided or "").strip()
    if not got:
        return False
    if env_key and secrets.compare_digest(got, env_key):
        return True
    return got in runtime_keys


def generate_api_key(label: str = "") -> dict[str, Any]:
    key = "aiopen_" + secrets.token_urlsafe(24)
    entry = {"label": (label or "").strip() or "未命名", "created_at": time.time()}
    AIOPEN_STATE.setdefault("runtime_keys", {})[key] = entry
    return {"key": key, **entry}


def revoke_api_key(key: str) -> bool:
    return AIOPEN_STATE.setdefault("runtime_keys", {}).pop((key or "").strip(), None) is not None


def list_api_keys() -> list[dict[str, Any]]:
    """脱敏列出 Key（仅前 12 位 + label）。"""
    out: list[dict[str, Any]] = []
    if _env_api_key():
        out.append({"key_preview": "env:AIOPEN_API_KEY", "label": "环境变量", "created_at": None})
    for key, meta in AIOPEN_STATE.get("runtime_keys", {}).items():
        out.append(
            {
                "key_preview": key[:12] + "…",
                "label": meta.get("label", ""),
                "created_at": meta.get("created_at"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 工具注册表（MCP / REST 共用 manifest）
# ---------------------------------------------------------------------------

_UI_TOOL_TIMEOUT_SECONDS = 10.0

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "api_catalog",
        "description": "列出 AIOPEN 白名单内可调用的 XCAGI 业务 API 路由及其启用状态。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "api_call",
        "description": "调用白名单内的 XCAGI 业务 API（GET/POST）。path 必须在 api_catalog 中且已启用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API 路径，如 /api/products"},
                "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                "body": {"type": "object", "description": "POST 请求体（JSON）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "chat",
        "description": "向 XCAGI AI 助手发送一条消息（unified_chat，source=aiopen），返回助手回复。",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "要发送的消息"}},
            "required": ["message"],
        },
    },
    {
        "name": "ui_sessions",
        "description": "列出当前在线的虚拟光标 screen 会话（XCAGI 前端开启远程操控后出现）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ui_snapshot",
        "description": "采集 XCAGI 前端当前页面快照：URL、标题与可见可交互元素（selector/文本/位置）。",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "目标会话，缺省取第一个在线会话"}},
        },
    },
    {
        "name": "ui_navigate",
        "description": "让 XCAGI 前端跳转到指定路由路径（虚拟光标会话内 router.push）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "前端路由路径，如 /products"},
                "session_id": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "ui_click",
        "description": "虚拟光标移动到指定元素并真实点击（带可视化动画）。selector 来自 ui_snapshot。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS 选择器（来自 ui_snapshot）"},
                "text": {"type": "string", "description": "可选：按可见文本匹配元素（selector 缺省时使用）"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_type",
        "description": "在指定输入框中输入文本（聚焦 + 写值 + 派发 input/change 事件）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "输入框 CSS 选择器"},
                "text": {"type": "string", "description": "要输入的文本"},
                "session_id": {"type": "string"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "ui_scroll",
        "description": "滚动页面或将指定元素滚动到可见区域。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "可选：滚动到该元素"},
                "delta_y": {"type": "number", "description": "可选：垂直滚动像素（正值向下）"},
                "session_id": {"type": "string"},
            },
        },
    },
]

_UI_ACTIONS = {"ui_snapshot": "snapshot", "ui_navigate": "navigate", "ui_click": "click", "ui_type": "type", "ui_scroll": "scroll"}


def aiopen_manifest() -> dict[str, Any]:
    return {
        "name": AIOPEN_PRODUCT_NAME,
        "tagline": AIOPEN_PRODUCT_TAGLINE,
        "version": "10.0.0",
        "protocol": {
            "mcp": "/api/aiopen/mcp",
            "rest_invoke": "/api/aiopen/invoke",
            "ws_screen": "/api/aiopen/ws",
            "auth_header": "X-AIOPEN-Key",
        },
        "tools": [
            {k: v for k, v in tool.items() if k in ("name", "description", "inputSchema")}
            for tool in TOOL_DEFINITIONS
        ],
    }


# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------


def _tool_api_catalog() -> dict[str, Any]:
    whitelist: dict[str, bool] = AIOPEN_STATE.get("whitelist", {})
    return {
        "success": True,
        "routes": [{"path": p, "enabled": bool(e)} for p, e in whitelist.items()],
    }


def _tool_api_call(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    from starlette.testclient import TestClient

    path = str(args.get("path") or "").strip()
    method = str(args.get("method") or "GET").upper()
    body = args.get("body") if isinstance(args.get("body"), dict) else {}
    if not path:
        return {"success": False, "message": "path 不能为空"}
    whitelist: dict[str, bool] = AIOPEN_STATE.get("whitelist", {})
    if not bool(whitelist.get(path, False)):
        return {"success": False, "message": f"路由 {path} 未在 AIOPEN 白名单启用", "code": "ROUTE_NOT_WHITELISTED"}
    try:
        client = TestClient(app)
        if method == "POST":
            payload = dict(body)
            payload.setdefault("source", "aiopen")
            resp = client.post(path, json=payload)
        else:
            resp = client.get(path)
        try:
            data = resp.json()
        except (ValueError, TypeError):
            data = {"raw": resp.text[:2000]}
        return {
            "success": resp.status_code < 500,
            "path": path,
            "method": method,
            "status_code": resp.status_code,
            "data": data,
        }
    except OPERATIONAL_ERRORS as err:
        return {"success": False, "path": path, "method": method, "message": str(err)}


def _tool_chat(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        return {"success": False, "message": "message 不能为空"}
    return _tool_api_call(
        app,
        {"path": "/api/ai/unified_chat", "method": "POST", "body": {"message": message, "source": "aiopen"}},
    )


async def invoke_tool(name: str, args: dict[str, Any] | None, app: Any) -> dict[str, Any]:
    """统一工具执行入口（MCP tools/call 与 REST invoke 共用）。"""
    args = args if isinstance(args, dict) else {}
    name = str(name or "").strip()

    if name == "api_catalog":
        return _tool_api_catalog()
    if name == "api_call":
        return _tool_api_call(app, args)
    if name == "chat":
        return _tool_chat(app, args)
    if name == "ui_sessions":
        return {
            "success": True,
            "remote_control_enabled": bool(AIOPEN_STATE.get("remote_control_enabled", False)),
            "sessions": aiopen_cursor_hub.sessions_info(),
        }
    if name in _UI_ACTIONS:
        if not AIOPEN_STATE.get("remote_control_enabled", False):
            return {"success": False, "message": "远程操控总开关已关闭（AIOPEN 面板可开启）", "code": "REMOTE_CONTROL_DISABLED"}
        session_id = str(args.get("session_id") or "") or None
        params = {k: v for k, v in args.items() if k != "session_id"}
        return await aiopen_cursor_hub.dispatch(
            _UI_ACTIONS[name], params, session_id=session_id, timeout=_UI_TOOL_TIMEOUT_SECONDS
        )
    return {"success": False, "message": f"未知工具：{name}", "code": "UNKNOWN_TOOL"}


# ---------------------------------------------------------------------------
# OpenClaw 外部网关代理（从 ai_qclaw 收编，面板「外部网关联调」卡使用）
# ---------------------------------------------------------------------------


def openclaw_chat_proxy(message: str) -> tuple[dict[str, Any], int]:
    """转发消息到外部 OpenClaw 网关，返回 (payload, status_code)。"""
    base = str(AIOPEN_STATE.get("openclaw_base", "http://localhost:28789")).rstrip("/")
    target_url = f"{base}/api/chat"
    payload = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except OPERATIONAL_ERRORS:
                parsed = {"raw": raw}
            return {"success": True, "target": target_url, "data": parsed}, 200
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return (
            {"success": False, "target": target_url, "status_code": err.code, "message": body or str(err)},
            502,
        )
    except OPERATIONAL_ERRORS as err:
        return {"success": False, "target": target_url, "message": str(err)}, 502
