# AIOPEN 开放智控 — 接入指南

> 「我是 AI 的工具」。AIOPEN 由原「Qclaw龙虾生态」toA 升级而来：让任何外部
> AI Agent（Cursor、Claude、OpenClaw、自研程序…）通过 **MCP** 或 **REST API**
> 调用 XCAGI 的业务能力，并以 **虚拟光标** 真实操作 XCAGI 前端页面。
>
> 产品版本与发布身份以 [VERSION.md](../VERSION.md) 和实际部署回执为准。

## 端点总览

| 端点 | 说明 | 鉴权 |
|---|---|---|
| `GET /api/aiopen/guide` | **接入说明**（供其他 AI 阅读后自行配置 MCP；`?format=markdown` 纯文本） | 公开 |
| `GET /api/aiopen/install` | **MCP 安装包**（Cursor deep link / stdio / mcp-remote） | 公开 |
| `GET /api/aiopen/manifest` | 协议工具说明（业务能力须按账号另行发现） | 公开 |
| `POST /api/aiopen/mcp` | MCP Streamable HTTP（JSON-RPC 2.0） | `X-AIOPEN-Key` |
| `POST /api/aiopen/invoke` | REST 通用工具调用 `{tool, args}` | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/operations` | **系统地图**：运行时能力目录（关键字/风险/工具集过滤、分页） | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/operations/{operation_id}` | 单个 operation 的语义卡片 | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/schema/{entity}` | 实体字段字典（来自 OpenAPI） | `X-AIOPEN-Key` |
| `GET /api/aiopen/coverage` | 开放面覆盖度（规模、风险分布、语义覆盖率） | `X-AIOPEN-Key` |
| `GET /api/aiopen/panel` 等 | 控制台（Key / 会话 / 开关） | LAN 门禁及管理身份 |
| `WS /api/aiopen/ws` | 前端 screen 端（虚拟光标）连接 | 有效会话、来源及屏幕归属 |

旧 `/api/ai/qclaw/*` 路由、`api_call` 工具和 OpenClaw 独立聊天代理入口已删除；客户端须使用本页统一契约。

## API Key

- 在有效登录会话中，由管理员在 **AI生态应用 → AIOPEN 开放智控** 面板生成业务 Key；绑定真实账号、租户与当前会话授权，凭据记录沿用现有持久仓储。
- 环境变量 `AIOPEN_API_KEY` 和历史未绑定身份的 Key 只认证传输，不授予业务或屏幕权限。业务调用须重新签发身份绑定的 Key。
- 未配置 Key 时拒绝匿名调用。账号停用、会话过期/注销、权限变化和 Key 撤销都会在执行前重新检查。

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
`notifications/initialized`（notification 返回 202），以及只读资源
`resources/list`、`resources/templates/list`、`resources/read`。

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
  -d '{"tool": "chat", "args": {"message": "查询我有权查看的任务", "request_id": "client-turn-001"}}'
```

## 工具清单

| 工具 | 说明 |
|---|---|
| `api_catalog` | 列出当前账号真正可用的能力与员工 |
| `knowledge_search` | 在系统地图中按关键字检索 operation（含风险、scope、使用时机） |
| `operation_describe` | 读取单个 operation 的完整语义卡片 |
| `operation_call` | 按权威能力 ID 和 params 进入共享权限、审批、幂等与核验链 |
| `chat` | 用稳定请求 ID 登记自然语言任务，由同一编排器规划和执行 |
| `capability_loop` | 发现并抽样执行当前账号可用的明确只读能力，核对原执行回执；不证明写入或 UI 完整就绪 |
| `ui_sessions` | 列出在线虚拟光标 screen 会话 |
| `ui_snapshot` | 可访问性树快照：每个节点分配稳定 `ref`，附角色 / 可访问名称 / 状态 / 位置；`selector` 仅作兼容回退 |
| `ui_navigate` | 前端路由跳转（router.push） |
| `ui_click` | 虚拟光标移动并真实点击（`ref` 优先，兼容 selector / 可见文本） |
| `ui_type` | 输入框写值（原型 setter + input/change 事件，兼容 v-model） |
| `ui_select` | 下拉选择：原生 select 按 value/文本选中，自定义下拉点开后按 label 匹配 |
| `ui_upload` | 向 file input 投放文件（同源 Agent 产物 url / base64 / 纯文本），派发 input/change |
| `ui_wait` | 轮询等待元素出现/消失、页面文本或 URL 变化（最长 15s） |
| `ui_verify` | 校验元素存在、控件值、页面文本与 URL，逐项返回结论 |
| `ui_screenshot` | DOM 重绘截图（html-to-image，MIT），返回 data_url 与尺寸；不含跨域 iframe/视频 |
| `ui_scroll` | 滚动页面或将元素滚动到可见区域 |

`POST /api/aiopen/loop/verify` 运行与 `capability_loop` 相同的只读自检。历史白名单配置不会授予能力权限，也不会创建独立执行入口。

## 系统地图（知）

可执行目录在运行时投影权威 `ToolActionSpecV2`，按当前账号有效授权筛选。
每条能力带原始工具、动作、参数 schema、风险、幂等/只读属性与
`scope=capability.<tool_id>.<action>`。OpenAPI 只补 HTTP 资源和字段说明；
`app/application/aiopen/overlay/operations.yaml` 只补语义，不授予执行权限。
这里的系统能力地图不是企业业务数据地图。

MCP 只读资源：

| URI | 内容 |
|---|---|
| `xcmax://catalog/operations` | 当前账号可见的能力及非执行资源说明 |
| `xcmax://catalog/operation/{operation_id}` | 单个 operation 语义卡片 |
| `xcmax://catalog/schema/{entity}` | 实体字段字典（OpenAPI components.schemas） |

推荐顺序：`knowledge_search` → `operation_describe` → `operation_call`。

### 统一能力执行契约

ToolSpec 是工具、动作、Schema、权限与风险的唯一事实源。AIOPEN、Workflow 与小C读取同一目录；OpenAPI 路径只是 `http_resource` 元数据，不能据路径猜测能力或直接执行写入。

`api_catalog` / `knowledge_search` 按当前有效账号、租户、Mod、员工授权和 API Key scope 返回可用能力。执行用 `operation_call`：`operation_id=capability.<tool_id>.<action>`、`params`、稳定 `request_id`。REST 客户端使用 `POST /api/tools/execute` 的同一契约；原 `api_call` 工具与任意路径 HTTP 执行器已删除。

业务 Key 在已登录会话签发时绑定原身份，权限降级、注销、过期或撤销后不能继续执行。旧无身份 Key 和环境 Key 只认证传输，不授予企业业务权限；在有效登录下重新签发。查询目录不是授权，执行仍复核权限。Key scope 使用 `capability.<tool_id>.<action>`，限制同时进入审批摘要和持久任务。

原 AIOPEN 独立写开关、自动批准危险动作、审批消费实现和初始化脚本已删除。审批、幂等、队列与核验复用 AgentTask → AgentRun → AgentStep；同号改参数/授权范围冲突，审批通过只续原任务。REST/MCP 保留业务 run_id、task_id、approval_request_id，追踪不能覆盖它们。`chat` 同样要求 request_id，原子登记后由既有队列执行。

语义 overlay 仅补使用说明，不改变能力权限、Schema、风险或是否可执行。未取得独立业务证据的写入保持待核验；unknown 不自动重新提交。

OpenClaw 聊天使用 `openclaw.chat` 能力，经原任务审批后只调用批准的当前网关；网络响应不能代替最终业务证据。客来来能力同样绑定当前账号连接及授权范围，重新配对或撤销后原审批失效。对原运行的核验使用 `GET /api/agent/runs/{run_id}/verification` 与 `POST /api/agent/runs/{run_id}/verify`，只读核对原业务结果，不重新发送副作用。

## 虚拟光标（AI 模拟操作）

页面加载后自动静默待命，**不需要用户先点任何开关**：

1. 打开 XCAGI 页面即在后台连接 `WS /api/aiopen/ws` 并登记为受控屏幕
2. 待命期间不显示光标和徽标；外部 Agent 下发 `ui_*` 指令时才出现
3. 执行 `ui_click` / `ui_type` 时出现蓝色虚拟光标与「AI 点击/输入」标签，并短暂显示「AI 正在操作本页」徽标
4. 用户可在 **AIOPEN 开放智控 → 更多设置** 关闭「本页待命」，关闭状态会持久化（`localStorage`）

安全边界不变：仍需服务端「允许 AI 远程操控」总开关与有效 `X-AIOPEN-Key`，屏幕按用户与租户授权。

典型流程：`ui_snapshot` 取节点 `ref` → `ui_click {"ref": "e3"}` 或
`ui_click {"text": "员工商店"}` → `ui_wait` 等待结果 → `ui_verify` 校验 → 必要时
`ui_screenshot` 留证。`ref` 只在下一次 `ui_snapshot` 前有效，页面重渲染后会自动失效，
需重新快照；找不到时会明确提示。输入后可用 `ui_verify {"ref": "e5", "value": "..."}`
确认写值生效。

`ui_select` 对原生 `select` 直接按 `value`/文本选中；对 Element Plus / Ant 等自定义
下拉，会真实点开再按 `label` 匹配可见选项。`ui_upload` 的 `url` 仅支持同源
`/api/agent/runs/{run_id}/artifacts/{artifact_id}` 文件产物下载地址（不含查询或片段），沿用服务端用户、租户和文件摘要校验；其他文件使用 `base64` 或 `text`，由浏览器合成 `File` 后写入 `input.files`。

### 指令协议（screen 端 WS）

服务端 → 前端：

```json
{ "type": "command", "id": "<hex>", "action": "click", "params": { "selector": "#btn" } }
```

前端 → 服务端回执：

```json
{ "type": "result", "id": "<hex>", "result": { "success": true, "clicked": "保存" } }
```

`action ∈ snapshot | navigate | click | type | select | upload | wait | verify | screenshot | scroll`；
普通操作回执超时 10s，`wait`/`upload` 20s，`screenshot` 30s。

## 安全模型

- 公开 manifest 只描述协议；invoke/mcp 需要有效 Key，企业业务执行还要有仍有效的账号绑定、当前权限及契约 scope。
- 任意 URL、请求体身份或白名单不能替代能力授权；不同传输最终进入同一执行链。
- `ui_*` 受双重开关约束：服务端「远程操控总开关」+ 浏览器端「本页待命」开关
  （默认开启、静默待命；用户明确关闭后以 localStorage 持久化为准）
- 面板与 keys 管理端点同时核对管理身份；签发业务 Key 必须有真实会话。

## 技术方案

开放面的能力模型、权限矩阵与分期落地见
[`docs/architecture/AIOPEN_FULL_SURFACE.md`](architecture/AIOPEN_FULL_SURFACE.md)。

## 相关代码

- 后端：`app/application/capability_catalog.py` · `app/application/tools/registered_capabilities.py` ·
  `app/application/aiopen/service.py` · `app/fastapi_routes/ai_open.py` · `app/infrastructure/aiopen/cursor_hub.py`
- 前端：`src/components/aiopen/AIOpenPanel.vue` ·
  `src/components/aiopen/VirtualCursorOverlay.vue` · `src/composables/useAiOpenCursor.ts`
- 测试：`tests/test_aiopen.py`
