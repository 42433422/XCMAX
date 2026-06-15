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


def _repo_stdio_bridge_path() -> str:
    """stdio 桥脚本绝对路径（供 Cursor command/args 配置）。"""
    here = Path(__file__).resolve()
    bridge = here.parents[3] / "scripts" / "dev" / "aiopen_mcp_stdio.py"
    return str(bridge)


def build_mcp_url_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    """Cursor 原生 HTTP MCP 配置（url + headers）。"""
    root = str(base_url or "").rstrip("/")
    cfg: dict[str, Any] = {"url": f"{root}/api/aiopen/mcp"}
    key = str(api_key or "").strip()
    if key:
        cfg["headers"] = {"X-AIOPEN-Key": key}
    return cfg


def build_mcp_stdio_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    """Python stdio 桥配置（无需 npx，适合 Claude Desktop）。"""
    env: dict[str, str] = {"AIOPEN_BASE_URL": str(base_url or "").rstrip("/")}
    key = str(api_key or "").strip()
    if key:
        env["AIOPEN_API_KEY"] = key
    return {
        "command": "python3",
        "args": [_repo_stdio_bridge_path()],
        "env": env,
    }


def build_mcp_remote_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    """npx mcp-remote 配置（业界常用，Cursor / Claude 均支持）。"""
    root = str(base_url or "").rstrip("/")
    args = ["-y", "mcp-remote", f"{root}/api/aiopen/mcp"]
    key = str(api_key or "").strip()
    if key:
        args.extend(["--header", f"X-AIOPEN-Key:{key}"])
    return {"command": "npx", "args": args}


def build_cursor_deeplink(server_name: str, server_config: dict[str, Any]) -> str:
    """生成 Cursor 一键安装 deep link（base64(JSON)）。"""
    config_b64 = base64.b64encode(
        json.dumps(server_config, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={quote(server_name, safe='')}&config={quote(config_b64, safe='')}"


def build_mcp_install_bundle(base_url: str, api_key: str = "") -> dict[str, Any]:
    """面板 / guide 共用的 MCP 安装包（多种 AI 客户端 + 传输方式）。"""
    root = str(base_url or "").rstrip("/")
    url_cfg = build_mcp_url_config(root, api_key)
    stdio_cfg = build_mcp_stdio_config(root, api_key)
    remote_cfg = build_mcp_remote_config(root, api_key)
    script_path = _repo_stdio_bridge_path()

    def _client_entry(
        cid: str,
        name: str,
        icon: str,
        config_path: str,
        hint: str,
        transport: str,
        server_cfg: dict[str, Any],
        *,
        install_mode: str = "copy",
        cursor_deeplink: str | None = None,
        web_install_url: str | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": cid,
            "name": name,
            "icon": icon,
            "config_path": config_path,
            "hint": hint,
            "transport": transport,
            "install_mode": install_mode,
            "mcp_json": json.dumps(
                {"mcpServers": {MCP_SERVER_NAME: server_cfg}}, ensure_ascii=False, indent=2
            ),
            "config": server_cfg,
        }
        if cursor_deeplink:
            entry["cursor_deeplink"] = cursor_deeplink
        if web_install_url:
            entry["web_install_url"] = web_install_url
        return entry

    cursor_dl = build_cursor_deeplink(MCP_SERVER_NAME, url_cfg)
    cursor_web = (
        f"https://cursor.com/en/install-mcp?name={quote(MCP_SERVER_NAME, safe='')}"
        f"&config={quote(base64.b64encode(json.dumps(url_cfg, ensure_ascii=False).encode()).decode(), safe='')}"
    )

    clients = [
        _client_entry(
            "cursor",
            "Cursor",
            "◆",
            "~/.cursor/mcp.json",
            "点一下自动写入 MCP 配置",
            "url",
            url_cfg,
            install_mode="deeplink",
            cursor_deeplink=cursor_dl,
            web_install_url=cursor_web,
        ),
        _client_entry(
            "claude",
            "Claude",
            "✳",
            "claude_desktop_config.json",
            "复制后粘贴到 Claude Desktop → 设置 → MCP",
            "mcp_remote",
            remote_cfg,
        ),
        _client_entry(
            "vscode",
            "VS Code",
            "▣",
            "MCP 扩展 · 用户 settings",
            "需安装 MCP 扩展；也可复制 JSON 手动添加",
            "mcp_remote",
            remote_cfg,
            install_mode="vscode",
        ),
        _client_entry(
            "windsurf",
            "Windsurf",
            "≋",
            "~/.codeium/windsurf/mcp_config.json",
            "与 Cursor 相同 url 格式，复制后写入配置文件",
            "url",
            url_cfg,
        ),
        _client_entry(
            "trae",
            "Trae",
            "◎",
            "Trae → MCP 服务器设置",
            "字节 Trae IDE，粘贴 mcpServers JSON",
            "url",
            url_cfg,
        ),
        _client_entry(
            "generic",
            "其他",
            "⋯",
            "任意支持 MCP 的 AI 客户端",
            "Cherry Studio / Chatbox / Open WebUI 等通用 JSON",
            "mcp_remote",
            remote_cfg,
        ),
    ]

    return {
        "server_name": MCP_SERVER_NAME,
        "mcp_url": f"{root}/api/aiopen/mcp",
        "recommended": "url",
        "clients": clients,
        "methods": {
            "url": {
                "label": "Cursor 直连（推荐）",
                "description": "写入 ~/.cursor/mcp.json 的 url 字段，Cursor 2025+ 原生支持",
                "config": url_cfg,
                "cursor_deeplink": cursor_dl,
                "web_install_url": cursor_web,
            },
            "mcp_remote": {
                "label": "npx mcp-remote（通用）",
                "description": "与 Notion、Asana 等远程 MCP 相同模式，适合 Claude Desktop",
                "config": remote_cfg,
                "cursor_deeplink": build_cursor_deeplink(MCP_SERVER_NAME, remote_cfg),
            },
            "stdio": {
                "label": "Python stdio 桥",
                "description": "无需 npx，本地 Python 转发到 HTTP",
                "config": stdio_cfg,
                "script_path": script_path,
                "cursor_deeplink": build_cursor_deeplink(MCP_SERVER_NAME, stdio_cfg),
            },
        },
        "mcp_config_template": {"mcpServers": {MCP_SERVER_NAME: url_cfg}},
    }


def format_tool_result_text(tool_name: str, result: dict[str, Any]) -> str:
    """将工具执行结果格式化为 Agent 易读文本（MCP tools/call content）。"""
    name = str(tool_name or "").strip()
    ok = bool(result.get("success", False))

    if name == "api_catalog":
        routes = result.get("routes") if isinstance(result.get("routes"), list) else []
        enabled = [r for r in routes if isinstance(r, dict) and r.get("enabled")]
        lines = [f"AIOPEN 白名单 API（{len(enabled)}/{len(routes)} 已启用）："]
        for r in routes:
            if not isinstance(r, dict):
                continue
            mark = "✓" if r.get("enabled") else "·"
            lines.append(f"  {mark} {r.get('path', '')}")
        return "\n".join(lines)

    if name == "api_call":
        path = result.get("path", "")
        method = result.get("method", "GET")
        status = result.get("status_code", "?")
        if not ok:
            return f"API 调用失败：{method} {path}\n{result.get('message', '')}"
        data = result.get("data")
        body = (
            json.dumps(data, ensure_ascii=False, indent=2, default=str)
            if data is not None
            else "(empty)"
        )
        if len(body) > 4000:
            body = body[:4000] + "\n…(truncated)"
        return f"API 调用成功：{method} {path} → HTTP {status}\n\n{body}"

    if name == "chat":
        if not ok:
            return f"对话失败：{result.get('message', '')}"
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        reply = ""
        if isinstance(data, dict):
            reply = str(data.get("reply") or data.get("message") or data.get("content") or "")
        if not reply:
            reply = json.dumps(data, ensure_ascii=False, default=str)[:2000]
        return f"XCAGI 助手回复：\n{reply}"

    if name == "ui_sessions":
        sessions = result.get("sessions") if isinstance(result.get("sessions"), list) else []
        if not sessions:
            return "当前无在线虚拟光标会话。\n请让用户在 XCAGI 打开 AIOPEN 面板并开启「本页待命」。"
        lines = [f"在线 screen 会话 {len(sessions)} 个："]
        for s in sessions:
            if not isinstance(s, dict):
                continue
            lines.append(f"  · {s.get('session_id', '?')} — {s.get('label', 'XCAGI 前端')}")
        return "\n".join(lines)

    if name == "ui_snapshot":
        if not ok:
            return f"页面快照失败：{result.get('message', '')}"
        url = result.get("url") or result.get("page_url") or ""
        title = result.get("title") or result.get("page_title") or ""
        elements = result.get("elements") if isinstance(result.get("elements"), list) else []
        lines = [
            f"页面：{title or '(无标题)'}",
            f"URL：{url or '(未知)'}",
            f"可交互元素 {len(elements)} 个：",
        ]
        for el in elements[:40]:
            if not isinstance(el, dict):
                continue
            sel = el.get("selector") or el.get("ref") or "?"
            text = str(el.get("text") or el.get("label") or "")[:60]
            role = el.get("role") or el.get("tag") or ""
            lines.append(f"  · [{role}] {text!r} → {sel}")
        if len(elements) > 40:
            lines.append(f"  … 另有 {len(elements) - 40} 个元素")
        return "\n".join(lines)

    if name in {"ui_click", "ui_type", "ui_navigate", "ui_scroll"}:
        if not ok:
            return f"{name} 失败：{result.get('message', '')}"
        detail = result.get("message") or result.get("detail") or "操作已执行"
        extra = {k: v for k, v in result.items() if k not in {"success", "message", "detail"}}
        if extra:
            return f"{detail}\n{json.dumps(extra, ensure_ascii=False, default=str)}"
        return str(detail)

    if not ok:
        return f"工具 {name} 失败：{result.get('message', result.get('code', 'unknown error'))}"
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def aiopen_manifest() -> dict[str, Any]:
    return {
        "name": AIOPEN_PRODUCT_NAME,
        "tagline": AIOPEN_PRODUCT_TAGLINE,
        "version": "10.0.0",
        "protocol": {
            "guide": "/api/aiopen/guide",
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


def build_aiopen_guide(base_url: str) -> dict[str, Any]:
    """生成可供外部 AI 自行阅读的接入说明（``GET /api/aiopen/guide`` SSOT）。"""
    root = str(base_url or "").rstrip("/")
    mcp_url = f"{root}/api/aiopen/mcp"
    invoke_url = f"{root}/api/aiopen/invoke"
    manifest_url = f"{root}/api/aiopen/manifest"
    guide_url = f"{root}/api/aiopen/guide"
    keys_url = f"{root}/api/aiopen/keys"
    install_url = f"{root}/api/aiopen/install"

    install = build_mcp_install_bundle(root)
    mcp_template = install["mcp_config_template"]
    url_deeplink = install["methods"]["url"]["cursor_deeplink"]
    remote_cfg = install["methods"]["mcp_remote"]["config"]
    remote_template = json.dumps(
        {"mcpServers": {MCP_SERVER_NAME: remote_cfg}}, ensure_ascii=False, indent=2
    )

    tool_lines = "\n".join(f"- **{t['name']}**：{t['description']}" for t in TOOL_DEFINITIONS)

    markdown = f"""# XCAGI AIOPEN 接入说明（给 AI 阅读）

你是即将接入 XCAGI 的 AI Agent。请阅读本文并完成 MCP 配置，然后告知用户配置结果。

## 产品

- 名称：**{AIOPEN_PRODUCT_NAME}** — {AIOPEN_PRODUCT_TAGLINE}
- 版本：10.0.0（v10 线内迭代）

## 前置条件（请提醒用户）

1. 用户在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**
2. 用户点击 **「一键开启 AI 操控」**（或手动开启远程操控 + 本浏览器受控屏幕）
3. 用户在本面板 **「获取连接口令」** 后将口令提供给你（开发模式无 Key 时可留空）

当前服务端远程操控：{"已开启" if AIOPEN_STATE.get("remote_control_enabled") else "未开启"}
在线虚拟光标会话数：{len(aiopen_cursor_hub.session_ids())}

## 端点（基于请求来源 `{root}`）

| 用途 | URL |
|------|-----|
| **本说明（你正在读的）** | `{guide_url}` |
| 工具目录 JSON | `{manifest_url}` |
| MCP 接入（推荐） | `{mcp_url}` |
| REST 通用调用 | `{invoke_url}` |
| 生成运行时 Key（POST） | `{keys_url}` |

鉴权请求头：`X-AIOPEN-Key: <连接口令>`（未配置任何 Key 时开发模式可省略）

## 你的配置任务（MCP）

**方式 A（推荐 · Cursor 一键）**：让用户在 AIOPEN 面板点「在 Cursor 中安装」，或打开 deep link：

`{url_deeplink}`

**方式 B（手动 JSON）**：写入 `~/.cursor/mcp.json`：

```json
{json.dumps(mcp_template, ensure_ascii=False, indent=2)}
```

将连接口令填入 `X-AIOPEN-Key`（向用户索取或在面板生成）。

**方式 C（npx mcp-remote · 与 Notion/Asana 同款）**：

```json
{remote_template}
```

完整安装选项：`GET {install_url}`

### MCP 协议

- 传输：Streamable HTTP — POST JSON-RPC 2.0 到 `{mcp_url}`
- 支持方法：`initialize`、`tools/list`、`tools/call`、`ping`、`notifications/initialized`
- 响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`
- 请求头：`Content-Type: application/json`，以及 `X-AIOPEN-Key`（若已配置）

### 验证步骤

1. `initialize` → 应返回 serverInfo.name = AIOPEN
2. `tools/list` → 应返回 9 个工具（含 ui_snapshot、ui_click、chat 等）
3. `tools/call` name=`ui_sessions` → 确认有在线 screen 会话（用户须保持浏览器打开）
4. `tools/call` name=`ui_snapshot` → 读取当前页面可交互元素
5. 按需 `ui_click` / `ui_type` / `ui_navigate` 操作页面

## REST 备选

```bash
curl -X POST '{invoke_url}' \\
  -H 'Content-Type: application/json' \\
  -H 'X-AIOPEN-Key: <连接口令>' \\
  -d '{{"tool": "chat", "args": {{"message": "你好"}}}}'
```

## 可用工具

{tool_lines}

## 虚拟光标操作流程

1. `ui_sessions` — 确认有在线会话
2. `ui_snapshot` — 获取 selector / 可见文本
3. `ui_click` — 点击（参数 selector 或 text）
4. `ui_type` — 输入（selector + text）
5. `ui_navigate` — 跳转路由 path
6. `ui_scroll` — 滚动

## 完成后请告诉用户

- MCP 是否配置成功
- tools/list 工具数量
- 是否检测到在线 screen 会话
- 若失败：是否缺少连接口令、用户是否已一键开启、后端是否已重启

---
文档 URL：{guide_url} · 重新获取最新说明请再次 GET 此链接
"""

    prompt_for_user = (
        f"请打开并阅读以下 XCAGI AIOPEN 接入说明，然后帮我完成 MCP 配置并验证连接：\n{guide_url}"
    )

    return {
        "success": True,
        "guide_url": guide_url,
        "base_url": root,
        "endpoints": {
            "guide": guide_url,
            "manifest": manifest_url,
            "mcp": mcp_url,
            "invoke": invoke_url,
            "keys": keys_url,
        },
        "mcp_config_template": mcp_template,
        "install": install,
        "install_url": install_url,
        "cursor_deeplink": url_deeplink,
        "auth_header": "X-AIOPEN-Key",
        "remote_control_enabled": bool(AIOPEN_STATE.get("remote_control_enabled", False)),
        "screen_sessions_online": len(aiopen_cursor_hub.session_ids()),
        "prompt_for_user": prompt_for_user,
        "markdown": markdown,
        "instructions_for_ai": [
            "读取本文 markdown 字段或 format=markdown 纯文本",
            "向用户索取连接口令（或确认开发模式无 Key）",
            "将 mcp_config_template 写入用户 MCP 配置并替换 Key",
            "调用 initialize → tools/list 验证",
            "调用 ui_sessions 确认用户浏览器已开启受控屏幕",
            "告知用户配置结果",
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
        return {
            "success": False,
            "message": f"路由 {path} 未在 AIOPEN 白名单启用",
            "code": "ROUTE_NOT_WHITELISTED",
        }
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
    except RECOVERABLE_ERRORS as err:
        return {"success": False, "path": path, "method": method, "message": str(err)}


def _tool_chat(app: Any, args: dict[str, Any]) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        return {"success": False, "message": "message 不能为空"}
    return _tool_api_call(
        app,
        {
            "path": "/api/ai/unified_chat",
            "method": "POST",
            "body": {"message": message, "source": "aiopen"},
        },
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
            return {
                "success": False,
                "message": "远程操控总开关已关闭（AIOPEN 面板可开启）",
                "code": "REMOTE_CONTROL_DISABLED",
            }
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
            except RECOVERABLE_ERRORS:
                parsed = {"raw": raw}
            return {"success": True, "target": target_url, "data": parsed}, 200
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return (
            {
                "success": False,
                "target": target_url,
                "status_code": err.code,
                "message": body or str(err),
            },
            502,
        )
    except RECOVERABLE_ERRORS as err:
        return {"success": False, "target": target_url, "message": str(err)}, 502
