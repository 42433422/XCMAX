# AIOPEN 开放智控 — 接入指南

> 「我是 AI 的工具」。AIOPEN 由原「Qclaw龙虾生态」toA 升级而来：让任何外部
> AI Agent（Cursor、Claude、OpenClaw、自研程序…）通过 **MCP** 或 **REST API**
> 调用 XCAGI 的业务能力，并以 **虚拟光标** 真实操作 XCAGI 前端页面。
>
> 版本：v10 线内迭代（锚点恒 `10.0.0`）。

## 端点总览

| 端点 | 说明 | 鉴权 |
|---|---|---|
| `GET /api/aiopen/guide` | **接入说明**（供其他 AI 阅读后自行配置 MCP；`?format=markdown` 纯文本） | 公开 |
| `GET /api/aiopen/install` | **MCP 安装包**（Cursor deep link / stdio / mcp-remote） | 公开 |
| `GET /api/aiopen/manifest` | 工具目录（名称 / 描述 / inputSchema） | 公开 |
| `POST /api/aiopen/mcp` | MCP Streamable HTTP（JSON-RPC 2.0） | `X-AIOPEN-Key` |
| `POST /api/aiopen/invoke` | REST 通用工具调用 `{tool, args}` | `X-AIOPEN-Key` |
| `GET /api/aiopen/panel` 等 | 控制台（白名单 / Key / 会话 / 开关） | LAN 门禁内 |
| `WS /api/aiopen/ws` | 前端 screen 端（虚拟光标）连接 | LAN 门禁内 |

旧 `/api/ai/qclaw/*` 路由全部保留，与 AIOPEN 共享运行时状态。

## API Key

- 环境变量：`AIOPEN_API_KEY=<密钥>`（生产必配）
- 或在前端 **AI生态应用 → AIOPEN 开放智控** 面板「生成 Key」（运行时 Key，重启失效）
- 未配置任何 Key 时为开发直通模式（仅靠 LAN 门禁兜底）

请求头：`X-AIOPEN-Key: <你的 Key>`。

## 发给其他 AI（推荐小白用法）

在 AIOPEN 面板点 **「复制说明链接」** 或 **「复制给 AI 的提示语」**，粘贴给任意 AI。
对方会打开 `GET /api/aiopen/guide?format=markdown` 阅读完整步骤，并向你索取连接口令后自行写入 MCP 配置。

示例提示语（面板一键复制）：

```
请打开并阅读以下 XCAGI AIOPEN 接入说明，然后帮我完成 MCP 配置并验证连接：
http://<主机>/api/aiopen/guide?format=markdown
```

## MCP 接入（Cursor / Claude）

**推荐**：在 AIOPEN 面板 **选择 AI 软件**（Cursor / Claude / VS Code 等）一键安装或复制配置；
或 `GET /api/aiopen/install` 取 `clients[]` 完整安装包。

三种传输方式（install 端点均返回），**六种 AI 客户端**（`clients` 数组）：

| 客户端 | 方式 | 说明 |
|---|---|---|
| **Cursor** | 一键 deep link | `~/.cursor/mcp.json` |
| **Claude Desktop** | 复制 JSON | `claude_desktop_config.json` + npx mcp-remote |
| **VS Code** | 一键 / 复制 | MCP 扩展 |
| **Windsurf** | 复制 JSON | `mcp_config.json` |
| **Trae** | 复制 JSON | Trae MCP 设置 |
| **其他** | 复制 JSON | Cherry Studio / Chatbox 等 |

传输方式：

| 方式 | 适用 | 说明 |
|---|---|---|
| **url** | Cursor / Windsurf / Trae | 原生 HTTP MCP，`url` + `headers` |
| **mcp-remote** | Claude / VS Code / 通用 | `npx -y mcp-remote <mcp_url> --header X-AIOPEN-Key:...` |
| **stdio** | 无 npx 环境 | `python3 FHD/scripts/dev/aiopen_mcp_stdio.py` 本地桥接 |

手动 `mcp.json` 示例（Cursor：`~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "xcagi-aiopen": {
      "url": "http://<XCAGI主机>:5100/api/aiopen/mcp",
      "headers": { "X-AIOPEN-Key": "<你的 API Key>" }
    }
  }
}
```

支持的 JSON-RPC 方法：`initialize`、`tools/list`、`tools/call`、`ping`、
`notifications/initialized`（notification 返回 202）。

响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`（initialize 时下发）。
`tools/call` 返回人类可读文本（非原始 JSON  dump）。

## REST 接入

```bash
# 列出工具
curl http://localhost:5000/api/aiopen/manifest

# 调用工具
curl -X POST http://localhost:5000/api/aiopen/invoke \
  -H 'Content-Type: application/json' \
  -H 'X-AIOPEN-Key: <你的 API Key>' \
  -d '{"tool": "chat", "args": {"message": "你好"}}'
```

## 工具清单

| 工具 | 说明 |
|---|---|
| `api_catalog` | 列出白名单内可调用的业务 API 路由 |
| `api_call` | 调用白名单内业务 API（GET/POST；白名单在面板可视化开关） |
| `chat` | 发消息给 XCAGI AI 助手（unified_chat，source=`aiopen`） |
| `ui_sessions` | 列出在线虚拟光标 screen 会话 |
| `ui_snapshot` | 页面快照：URL / 标题 / 可交互元素（selector / 文本 / 位置） |
| `ui_navigate` | 前端路由跳转（router.push） |
| `ui_click` | 虚拟光标移动并真实点击（selector 或按可见文本匹配） |
| `ui_type` | 输入框写值（原型 setter + input/change 事件，兼容 v-model） |
| `ui_scroll` | 滚动页面或将元素滚动到可见区域 |

## 虚拟光标（AI 模拟操作）

1. 在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**
2. 开启「远程操控总开关」（服务端）与「本浏览器作为受控屏幕」
3. 页面右下角出现「AI 操控通道已连接」徽标，外部 Agent 即可经 `ui_*` 工具操作
4. 执行 `ui_click` / `ui_type` 时页面会出现蓝色虚拟光标动画与「AI 点击/输入」标签

典型流程：`ui_snapshot` 取元素 → `ui_click {"selector": "..."} ` 或
`ui_click {"text": "员工商店"}` → 再次 `ui_snapshot` 验证结果。

### 指令协议（screen 端 WS）

服务端 → 前端：

```json
{ "type": "command", "id": "<hex>", "action": "click", "params": { "selector": "#btn" } }
```

前端 → 服务端回执：

```json
{ "type": "result", "id": "<hex>", "result": { "success": true, "clicked": "保存" } }
```

`action ∈ snapshot | navigate | click | type | scroll`；回执超时 10s。

## 安全模型

- 对外三端点（manifest/invoke/mcp）越过 LAN 门禁与订阅门禁，**安全完全由
  `X-AIOPEN-Key` 承担**——生产必须配置 `AIOPEN_API_KEY`
- `api_call` 仅放行白名单路由（面板可视化管理）
- `ui_*` 受双重开关约束：服务端「远程操控总开关」+ 浏览器端「受控屏幕」开关
  （localStorage 持久化，默认关闭）
- 面板与 keys 管理端点仍在 LAN 门禁内

## 相关代码

- 后端：`app/application/aiopen/service.py` · `app/fastapi_routes/ai_open.py` ·
  `app/infrastructure/aiopen/cursor_hub.py` · 兼容层 `app/fastapi_routes/ai_qclaw.py`
- 前端：`src/components/aiopen/AIOpenPanel.vue` ·
  `src/components/aiopen/VirtualCursorOverlay.vue` · `src/composables/useAiOpenCursor.ts`
- 测试：`tests/test_aiopen.py`
