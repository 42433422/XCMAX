"""Tool manifest and installation guide from the same live catalog."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .definitions import AIOPEN_PRODUCT_NAME, AIOPEN_PRODUCT_TAGLINE, MCP_SERVER_NAME
from .protocols import CursorHub
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
        markdown = f"""# XCAGI AIOPEN 接入说明（给 AI 阅读）\n\n你是即将接入 XCAGI 的 AI Agent。请阅读本文并完成 MCP 配置，然后告知用户配置结果。\n\n## 产品\n\n- 名称：**{AIOPEN_PRODUCT_NAME}** — {AIOPEN_PRODUCT_TAGLINE}\n- 版本：{self._version()}（稳定版）\n\n## 前置条件（请提醒用户）\n\n1. 用户在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**；管理端用户打开 **管理端 → 智能生态 → AIOPEN 开放智控**（`/admin/ai-ecosystem`）并先登录管理端\n2. 页面加载后会默认静默待命，不需要再点「一键开启」或「本页待命」；待命期间不显示光标\n3. 登录后点 AIOPEN 面板的 **「复制一句话」**，把包含连接口令和 MCP JSON 的内容粘贴给本机 AI 助手。\n\n当前服务端远程操控：{("已开启" if self._state.remote_control_enabled else "未开启")}\n在线虚拟光标会话数：{session_count}\n\n## 端点（基于请求来源 `{root}`）\n\n| 用途 | URL |\n|------|-----|\n| **本说明（你正在读的）** | `{guide_url}` |\n| 工具目录 JSON | `{manifest_url}` |\n| MCP 接入（推荐） | `{mcp_url}` |\n| REST 通用调用 | `{invoke_url}` |\n| 生成运行时 Key（POST） | `{keys_url}` |\n\n鉴权请求头：`X-AIOPEN-Key: <连接口令>`（包括开发环境）\n\n## MCP 配置\n\n**推荐**：将「复制一句话」附带的 JSON 合并到本地 MCP 配置，再验证连接。\n\n**手动配置 Cursor**：写入 `~/.cursor/mcp.json`：\n\n```json\n{json.dumps(mcp_template, ensure_ascii=False, indent=2)}\n```\n\n在本地配置 `headers.X-AIOPEN-Key`。客户端口令只授权该账号自己的虚拟屏幕工具。\n\n**使用 npx mcp-remote**：\n\n```json\n{remote_template}\n```\n\n完整安装选项：`GET {install_url}`\n\n### MCP 协议\n\n- 传输：Streamable HTTP — POST JSON-RPC 2.0 到 `{mcp_url}`\n- 支持方法：`initialize`、`tools/list`、`tools/call`、`ping`、`notifications/initialized`\n- 响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`\n- 请求头：`Content-Type: application/json`，以及 `X-AIOPEN-Key`\n\n### 验证步骤\n\n1. `initialize` → 应返回 serverInfo.name = AIOPEN\n2. `tools/list` → 应返回 {len(tools)} 个工具（含 ui_snapshot、ui_click、chat 等）\n3. `tools/call` name=`ui_sessions` → 确认有在线 screen 会话（用户须保持浏览器打开）\n4. `tools/call` name=`ui_snapshot` → 读取页面可访问性节点与 `ref`\n5. 按需 `ui_click` / `ui_type` / `ui_select` / `ui_upload` 操作，`ui_wait` / `ui_verify` 确认结果\n\n## REST 备选\n\n```bash\ncurl -X POST '{invoke_url}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AIOPEN-Key: <连接口令>' \\\n  -d '{{"tool": "chat", "args": {{"message": "你好"}}}}'\n```\n\n## 可用工具\n\n{tool_lines}\n\n## 虚拟光标操作流程\n\n1. `ui_sessions` — 确认有在线会话\n2. `ui_snapshot` — 获取可访问性节点：`ref`、角色、名称、状态；`selector` 仅作回退\n3. `ui_click` — 点击（`ref` 优先，也支持 selector / 可见文本）\n4. `ui_type` — 输入（`ref` + text）\n5. `ui_select` — 下拉选择（`ref` + value / label）\n6. `ui_upload` — 上传文件（`ref` + files：同源 Agent 文件产物 url（/api/agent/runs/{{run_id}}/artifacts/{{artifact_id}}，不含查询或片段）/ base64 / text）\n7. `ui_wait` — 等待元素、文本或 URL 变化\n8. `ui_verify` — 校验元素、控件值、文本或 URL\n9. `ui_screenshot` — 截图留证（返回 data_url 与尺寸）\n10. `ui_navigate` / `ui_scroll` — 跳转路由或滚动\n\n`ref` 只在最近一次 `ui_snapshot` 内有效；页面重渲染后失效，重新快照即可。\n\n## 完成后请告诉用户\n\n- MCP 是否配置成功\n- tools/list 工具数量（当前应为 {len(tools)}）\n- `ui_sessions` 是否检测到在线 screen 会话\n- 若失败：是否缺少连接口令、用户是否在对应端（主应用或管理端）登录并保持页面打开、后端是否已重启\n\n---\n文档 URL：{guide_url} · 重新获取最新说明请再次 GET 此链接\n"""
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
                "将「复制一句话」附带的 MCP JSON 合并到本地配置",
                "调用 initialize → tools/list 验证",
                "调用 ui_sessions 确认用户浏览器已开启受控屏幕",
                "告知用户配置结果",
            ],
        }
