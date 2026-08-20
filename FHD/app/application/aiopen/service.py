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

import base64
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

AIOPEN_PRODUCT_NAME = "AIOPEN"
AIOPEN_PRODUCT_TAGLINE = "我是 AI 的工具 — MCP / API 开放平台与虚拟光标操控"
MCP_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26")
MCP_DEFAULT_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "xcagi-aiopen"

# 运行时状态 SSOT（进程内，无持久化；与旧 qclaw 面板共享）。
# 白名单默认覆盖侧栏能力闭环主前缀；api_call 按「精确或子路径前缀」匹配。
CAPABILITY_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/ai/chat",
    "/api/ai/unified_chat",
    "/api/chat/send",
    "/api/conversations",
    "/api/planner",
    "/api/im",
    "/api/mobile/v1/ai-groups",
    "/api/platform-shell",
    "/api/mods",
    "/api/knowledge",
    "/api/persy/knowledge",
    "/api/system/workflow-employee-catalog",
    "/api/workflow-employee-space",
    "/api/mod",
    "/api/products",
    "/api/customers",
    "/api/materials",
    "/api/orders",
    "/api/shipment",
    "/api/print",
    "/api/wechat_contacts",
    "/api/templates",
    "/api/excel",
    "/api/document-templates",
    "/api/data-sources",
    "/api/auth/me",
)


from app.application.aiopen.service_part01 import (
    _default_capability_whitelist as _default_capability_whitelist,
)
from app.application.aiopen.service_part01 import (
    _env_api_key as _env_api_key,
)
from app.application.aiopen.service_part01 import (
    _pick_probe_path as _pick_probe_path,
)
from app.application.aiopen.service_part01 import (
    _repo_stdio_bridge_path as _repo_stdio_bridge_path,
)
from app.application.aiopen.service_part01 import (
    _tool_api_call as _tool_api_call,
)
from app.application.aiopen.service_part01 import (
    _tool_api_catalog as _tool_api_catalog,
)
from app.application.aiopen.service_part01 import (
    _tool_capability_loop as _tool_capability_loop,
)
from app.application.aiopen.service_part01 import (
    _tool_chat as _tool_chat,
)
from app.application.aiopen.service_part01 import (
    aiopen_manifest as aiopen_manifest,
)
from app.application.aiopen.service_part01 import (
    build_aiopen_guide as build_aiopen_guide,
)
from app.application.aiopen.service_part01 import (
    build_cursor_deeplink as build_cursor_deeplink,
)
from app.application.aiopen.service_part01 import (
    build_mcp_install_bundle as build_mcp_install_bundle,
)
from app.application.aiopen.service_part01 import (
    build_mcp_remote_config as build_mcp_remote_config,
)
from app.application.aiopen.service_part01 import (
    build_mcp_stdio_config as build_mcp_stdio_config,
)
from app.application.aiopen.service_part01 import (
    build_mcp_url_config as build_mcp_url_config,
)
from app.application.aiopen.service_part01 import (
    format_tool_result_text as format_tool_result_text,
)
from app.application.aiopen.service_part01 import (
    generate_api_key as generate_api_key,
)
from app.application.aiopen.service_part01 import (
    invoke_tool as invoke_tool,
)
from app.application.aiopen.service_part01 import (
    is_path_whitelisted as is_path_whitelisted,
)
from app.application.aiopen.service_part01 import (
    list_api_keys as list_api_keys,
)
from app.application.aiopen.service_part01 import (
    normalize_api_path as normalize_api_path,
)
from app.application.aiopen.service_part01 import (
    revoke_api_key as revoke_api_key,
)
from app.application.aiopen.service_part01 import (
    seed_capability_whitelist as seed_capability_whitelist,
)
from app.application.aiopen.service_part01 import (
    verify_api_key as verify_api_key,
)

# ---------------------------------------------------------------------------
# OpenClaw 外部网关代理（从 ai_qclaw 收编，面板「外部网关联调」卡使用）
# ---------------------------------------------------------------------------
from app.application.aiopen.service_part02 import (
    openclaw_chat_proxy as openclaw_chat_proxy,
)

# ruff: noqa: F401

AIOPEN_STATE: dict[str, Any] = {
    "wechat_open": True,
    "openclaw_base": "http://localhost:28789",
    "whitelist": _default_capability_whitelist(),
    "remote_control_enabled": True,
    "runtime_keys": {},
}

_UI_TOOL_TIMEOUT_SECONDS = 10.0

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "api_catalog",
        "description": "列出 AIOPEN 白名单内可调用的 XCAGI 业务 API 路由及其启用状态。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "api_call",
        "description": "调用白名单内的 XCAGI 业务 API。path 支持精确匹配或已启用前缀的子路径（如启用 /api/products 则可调 /api/products/list）。method 支持 GET/POST/PUT/PATCH/DELETE。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "API 路径，如 /api/products/list；可带 query",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET",
                },
                "body": {"type": "object", "description": "请求体（JSON，非 GET/DELETE 时使用）"},
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
        "name": "capability_loop",
        "description": "全调用闭环自检：api_catalog → 抽样 api_call(GET) → chat → ui_sessions，返回各步成败，供外部 Agent 确认 MCP 已打通。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_path": {
                    "type": "string",
                    "description": "可选抽样 API，默认自动选已启用白名单路径",
                },
                "message": {"type": "string", "description": "可选 chat 探测文案"},
            },
            "additionalProperties": False,
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
            "properties": {
                "session_id": {"type": "string", "description": "目标会话，缺省取第一个在线会话"}
            },
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
                "text": {
                    "type": "string",
                    "description": "可选：按可见文本匹配元素（selector 缺省时使用）",
                },
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

_UI_ACTIONS = {
    "ui_snapshot": "snapshot",
    "ui_navigate": "navigate",
    "ui_click": "click",
    "ui_type": "type",
    "ui_scroll": "scroll",
}

_API_CALL_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
