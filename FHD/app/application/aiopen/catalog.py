"""Tool manifest and installation guide from the same live catalog."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .definitions import AIOPEN_PRODUCT_NAME, AIOPEN_PRODUCT_TAGLINE, MCP_SERVER_NAME
from .ports import CursorHub
from .runtime import RuntimeState


class CatalogGuide:
    def __init__(
        self,
        state: RuntimeState,
        tools: Callable[[], list[dict[str, Any]]],
        install: Callable[[str], dict[str, Any]],
        cursor: Callable[[], CursorHub],
        version: Callable[[], str],
    ) -> None:
        self._state = state
        self._tools = tools
        self._install = install
        self._cursor = cursor
        self._version = version

    def manifest(self) -> dict[str, Any]:
        tools = self._tools()
        return {
            "name": AIOPEN_PRODUCT_NAME,
            "tagline": AIOPEN_PRODUCT_TAGLINE,
            "version": self._version(),
            "protocol": {
                "guide": "/api/aiopen/guide",
                "mcp": "/api/aiopen/mcp",
                "rest_invoke": "/api/aiopen/invoke",
                "ws_screen": "/api/aiopen/ws",
                "auth_header": "X-AIOPEN-Key",
            },
            "tools": [
                {k: v for k, v in tool.items() if k in ("name", "description", "inputSchema")}
                for tool in tools
            ],
        }

    def guide(self, base_url: str) -> dict[str, Any]:
        """生成可供外部 AI 自行阅读的接入说明（``GET /api/aiopen/guide`` SSOT）。"""
        tools = self._tools()
        session_count = len(self._cursor().session_ids())
        root = str(base_url or "").rstrip("/")
        mcp_url = f"{root}/api/aiopen/mcp"
        invoke_url = f"{root}/api/aiopen/invoke"
        manifest_url = f"{root}/api/aiopen/manifest"
        guide_url = f"{root}/api/aiopen/guide"
        keys_url = f"{root}/api/aiopen/keys"
        install_url = f"{root}/api/aiopen/install"
        install = self._install(root)
        mcp_template = install["mcp_config_template"]
        url_deeplink = install["methods"]["url"]["cursor_deeplink"]
        remote_cfg = install["methods"]["mcp_remote"]["config"]
        remote_template = json.dumps(
            {"mcpServers": {MCP_SERVER_NAME: remote_cfg}}, ensure_ascii=False, indent=2
        )
        tool_lines = "\n".join(f"- **{t['name']}**：{t['description']}" for t in tools)
        markdown = f"""# XCAGI AIOPEN 接入说明（给 AI 阅读）\n\n你是即将接入 XCAGI 的 AI Agent。请阅读本文并完成 MCP 配置，然后告知用户配置结果。\n\n## 产品\n\n- 名称：**{AIOPEN_PRODUCT_NAME}** — {AIOPEN_PRODUCT_TAGLINE}\n- 版本：{self._version()}（稳定版）\n\n## 前置条件（请提醒用户）\n\n1. 用户在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**\n2. 用户点击 **「一键开启 AI 操控」**（或手动开启远程操控 + 本浏览器受控屏幕）\n3. 用户在本面板 **「获取连接口令」** 后将口令提供给你（开发模式无 Key 时可留空）\n\n当前服务端远程操控：{("已开启" if self._state.remote_control_enabled else "未开启")}\n在线虚拟光标会话数：{session_count}\n\n## 端点（基于请求来源 `{root}`）\n\n| 用途 | URL |\n|------|-----|\n| **本说明（你正在读的）** | `{guide_url}` |\n| 工具目录 JSON | `{manifest_url}` |\n| MCP 接入（推荐） | `{mcp_url}` |\n| REST 通用调用 | `{invoke_url}` |\n| 生成运行时 Key（POST） | `{keys_url}` |\n\n鉴权请求头：`X-AIOPEN-Key: <连接口令>`（未配置任何 Key 时开发模式可省略）\n\n## 你的配置任务（MCP）\n\n**方式 A（推荐 · Cursor 一键）**：让用户在 AIOPEN 面板点「在 Cursor 中安装」，或打开 deep link：\n\n`{url_deeplink}`\n\n**方式 B（手动 JSON）**：写入 `~/.cursor/mcp.json`：\n\n```json\n{json.dumps(mcp_template, ensure_ascii=False, indent=2)}\n```\n\n将连接口令填入 `X-AIOPEN-Key`（向用户索取或在面板生成）。\n\n**方式 C（npx mcp-remote · 与 Notion/Asana 同款）**：\n\n```json\n{remote_template}\n```\n\n完整安装选项：`GET {install_url}`\n\n### MCP 协议\n\n- 传输：Streamable HTTP — POST JSON-RPC 2.0 到 `{mcp_url}`\n- 支持方法：`initialize`、`tools/list`、`tools/call`、`ping`、`notifications/initialized`\n- 响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`\n- 请求头：`Content-Type: application/json`，以及 `X-AIOPEN-Key`（若已配置）\n\n### 验证步骤\n\n1. `initialize` → 应返回 serverInfo.name = AIOPEN\n2. `tools/list` → 应返回 {len(tools)} 个工具（含 ui_snapshot、ui_click、chat 等）\n3. `tools/call` name=`ui_sessions` → 确认有在线 screen 会话（用户须保持浏览器打开）\n4. `tools/call` name=`ui_snapshot` → 读取当前页面可交互元素\n5. 按需 `ui_click` / `ui_type` / `ui_navigate` 操作页面\n\n## REST 备选\n\n```bash\ncurl -X POST '{invoke_url}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AIOPEN-Key: <连接口令>' \\\n  -d '{{"tool": "chat", "args": {{"message": "你好"}}}}'\n```\n\n## 可用工具\n\n{tool_lines}\n\n## 虚拟光标操作流程\n\n1. `ui_sessions` — 确认有在线会话\n2. `ui_snapshot` — 获取 selector / 可见文本\n3. `ui_click` — 点击（参数 selector 或 text）\n4. `ui_type` — 输入（selector + text）\n5. `ui_navigate` — 跳转路由 path\n6. `ui_scroll` — 滚动\n\n## 完成后请告诉用户\n\n- MCP 是否配置成功\n- tools/list 工具数量\n- 是否检测到在线 screen 会话\n- 若失败：是否缺少连接口令、用户是否已一键开启、后端是否已重启\n\n---\n文档 URL：{guide_url} · 重新获取最新说明请再次 GET 此链接\n"""
        prompt_for_user = f"请打开并阅读以下 XCAGI AIOPEN 接入说明，然后帮我完成 MCP 配置并验证连接：\n{guide_url}"
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
            "remote_control_enabled": bool(self._state.remote_control_enabled),
            "screen_sessions_online": session_count,
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
