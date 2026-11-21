# AIOPEN 开放智控 — 接入指南

> 「我是 AI 的工具」。AIOPEN 由原「Qclaw龙虾生态」toA 升级而来：让任何外部
> AI Agent（Cursor、Claude、OpenClaw、自研程序…）通过 **MCP** 或 **REST API**
> 调用 XCAGI 的业务能力，并以 **虚拟光标** 真实操作 XCAGI 前端页面。
>
> 稳定产品版本：`1.0.0.0`。

## 端点总览

| 端点 | 说明 | 鉴权 |
|---|---|---|
| `GET /api/aiopen/guide` | **接入说明**（供其他 AI 阅读后自行配置 MCP；`?format=markdown` 纯文本） | 公开 |
| `GET /api/aiopen/install` | **MCP 安装包**（Cursor deep link / stdio / mcp-remote） | 公开 |
| `GET /api/aiopen/manifest` | 工具目录（名称 / 描述 / inputSchema） | 公开 |
| `POST /api/aiopen/mcp` | MCP Streamable HTTP（JSON-RPC 2.0） | `X-AIOPEN-Key` |
| `POST /api/aiopen/invoke` | REST 通用工具调用 `{tool, args}` | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/operations` | **系统地图**：运行时能力目录（关键字/风险/工具集过滤、分页） | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/operations/{operation_id}` | 单个 operation 的语义卡片 | `X-AIOPEN-Key` |
| `GET /api/aiopen/catalog/schema/{entity}` | 实体字段字典（来自 OpenAPI） | `X-AIOPEN-Key` |
| `GET /api/aiopen/coverage` | 开放面覆盖度（规模、风险分布、语义覆盖率） | `X-AIOPEN-Key` |
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
  -d '{"tool": "chat", "args": {"message": "你好"}}'
```

## 工具清单

| 工具 | 说明 |
|---|---|
| `api_catalog` | 列出白名单内可调用的业务 API 路由（精确 + 前缀子路径） |
| `knowledge_search` | 在系统地图中按关键字检索 operation（含风险、scope、使用时机） |
| `operation_describe` | 读取单个 operation 的完整语义卡片 |
| `operation_call` | 按 operation_id 执行接口；危险操作拒绝执行，写操作需服务端开启 |
| `api_call` | 调用白名单业务 API（GET/POST/PUT/PATCH/DELETE） |
| `chat` | 发消息给 XCAGI AI 助手（unified_chat，source=`aiopen`） |
| `capability_loop` | 全调用闭环自检：catalog → 抽样 api_call → chat → ui_sessions |
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

面板还可：`POST /api/aiopen/whitelist/seed` 一键开启侧栏全业务白名单；
`POST /api/aiopen/loop/verify` 跑与 `capability_loop` 相同的闭环自检。

## 系统地图（知）

能力目录在运行时从应用 OpenAPI 生成，不手工维护；内部管理端、运行时通道与
AIOPEN 自身路由不进入目录。每条 operation 带 `risk`（read/write/danger）与
`scope`（如 `read:products`），语义说明来自 `app/application/aiopen/overlay/operations.yaml`。

MCP 只读资源：

| URI | 内容 |
|---|---|
| `xcmax://catalog/operations` | 全部可开放 operation |
| `xcmax://catalog/operation/{operation_id}` | 单个 operation 语义卡片 |
| `xcmax://catalog/schema/{entity}` | 实体字段字典（OpenAPI components.schemas） |

推荐顺序：`knowledge_search` → `operation_describe` → `api_call`。

### 执行闸门（P1）

`operation_call` 按目录中的风险等级执行，不靠 AI 自觉：

| 风险 | 行为 |
|---|---|
| `read` | 直接执行，Key 需具备 `read:<domain>` 或以 `*` 全量授权 |
| `write` | 默认返回 `WRITE_DISABLED`；服务端设置 `AIOPEN_ENABLE_WRITES=1` 后才执行 |
| `danger` | 发起审批（复用审批中心）；通过后携带 `approval_id` 重试，审批单只能执行一次 |

审批流程：服务端设置 `AIOPEN_APPROVAL_FLOW_KEY`（默认 `aiopen_danger_operation`），
并先在审批中心创建同名 `flow_key` 且配置启用节点；未配置时危险操作一律拒绝。
幂等创建用 `python scripts/dev/ensure_aiopen_approval_flow.py --approver-id <用户ID>`
（缺省自动取 admin/superadmin；找不到审批人时退出码 2，不会创建无人可批的空流程）。
审批单记录 operation、参数指纹与申请人，执行时校验三者一致并写入消费时间防重放。

生产前置顺序：先确保审批流程与启用节点存在，再设置 `AIOPEN_ENABLE_WRITES=1` 放行写操作；
两者都完成前，写操作返回 `WRITE_DISABLED`，危险操作返回 `APPROVAL_FLOW_NOT_CONFIGURED`。

`params` 传路径与查询参数（键名见 operation 卡片），`body` 传 JSON 请求体。
`api_call` 命中目录条目时套用同一套读写/危险闸门，未命中目录的自定义路径保持原白名单行为。

语义草稿由 `scripts/dev/aiopen_overlay_draft.py` 批量生成到 `overlay/drafts/`（运行时不加载），
人工审核后移入 `overlay/generated/*.yaml|*.jsonl` 生效；大规模语义用 jsonl（每行一条）存储。

默认白名单覆盖对话 / IM / 群聊 / 知识库 / 员工台 / 产品组织订单 / 出货打印 / Mod 等前缀；
`api_call` 对已启用前缀的子路径自动放行（例如启用 `/api/products` 即可调 `/api/products/list`）。

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

## Computer Use：桌面与浏览器执行器

智能聊天的既有 `desktop_automation` 工具增加 `computer_status`、`computer_observe`、`computer_execute`、`computer_stop`、`computer_result` 动作。执行沿用统一 Agent 的身份、审批和 `run_id`；本节不为外部 AIOPEN Key 增加直接桌面控制权限。先观察、再执行、再读回检查，回执区分动作执行与结果核验。写动作结果未知时不自动重放。

在 `FHD/` 的运行环境安装锁定的可选执行器：

```bash
uv sync --frozen --extra server-api --extra computer-use
uv run --frozen --extra server-api --extra computer-use python -m playwright install chromium
```

| 服务端配置 | 作用 |
|---|---|
| `XCAGI_COMPUTER_USE_ENABLED=1` | 显式开启 Computer Use；默认关闭 |
| `XCAGI_COMPUTER_USE_USER_ID`、`XCAGI_COMPUTER_USE_TENANT_ID` | 将桌面与浏览器执行器绑定到一个用户和租户；桌面操作还必须处于 `desktop_mode` |
| `XCAGI_COMPUTER_USE_ALLOWED_ORIGINS` | 浏览器允许访问的 origin JSON 数组，例如 `["https://example.com"]`；按实际目标配置 |
| `XCAGI_COMPUTER_USE_BROWSER_EXECUTABLE` | 可选：受控、已安装 Chromium 的可执行文件路径；不读取已有用户 profile |
| `XCAGI_COMPUTER_USE_HEADFUL=1` | 可选：浏览器显示窗口，与桌面输入/观察共用设备锁；默认无界面，需要浏览器沙箱可用 |

例如，提交 `desktop_automation.computer_execute` 的参数如下；必须由既有 Agent 审批后执行，不能把 `approved` 或身份字段加进参数自行放行。服务端允许的 origin 需包含示例站点。

```json
{
  "request_id": "browser-check-001",
  "target": "browser",
  "steps": [{"action": "navigate", "url": "https://example.com/"}],
  "verification": {"kind": "url", "expected": "https://example.com/"}
}
```

浏览器每次调用使用新的隔离 Context，首步必须为 `navigate`，不接管已有登录浏览器。支持按角色、标签、测试 ID 或 CSS 定位后点击、填值、按键、选择和勾选；使用 Playwright 的可操作性等待与后置断言。当前拦截全部 HTTP 重定向、WebSocket、Service Worker、弹窗和下载，因此依赖登录跳转或流式长连接的网站不在本版已验证范围内。单次最多 20 步、浏览器总时限 60 秒，执行后返回截图与标记为不可信外部内容的 ARIA 快照。

桌面通过 PyAutoGUI 操作主显示器，保留四角 FailSafe 与任务停止；当前不提供多显示器、操作系统控件树或锁屏控制。先执行 `computer_observe`，将返回的 `snapshot_id` 传入桌面执行参数；快照 120 秒有效、只使用一次，执行前画面或尺寸变化会拒绝原坐标动作，需重新观察和审批。输入坐标使用 `input_width/input_height`，像素核验使用截图的物理尺寸。macOS 需要本机录屏和辅助功能授权；Linux 需要可用的 X11 会话与截图系统依赖。ASCII 使用键盘输入，Unicode 借助经格式检查的纯文本剪贴板；图片、文件、富文本或格式无法可靠确定时拒绝这一路径，不覆盖原内容。Linux Unicode 输入需 `xclip` 能枚举 `TARGETS`。批次前、每次复制及恢复前均重查格式；检测到剪贴板被其他程序替换时不强行恢复。

`verification` 缺失或不成立时，动作即使已发出也不返回成功；桌面像素条件仅证明视觉状态，不能代替业务结果核验。发生中断或回执未知时保留原 `request_id`，用 `computer_result {"request_id":"..."}` 读取回执并核对实际效果，不生成新请求重放原输入。`computer_stop` 记录停止请求，在执行检查点生效，返回 `stop_requested` 不代表操作系统已经停止。额外防重放回执只保存摘要和效果元数据；完整工具输出仍遵循既有 Agent 任务审计存储规则，可能包含截图和页面内容。

可选包缺失、权限未满足或没有活动桌面时应报告能力不可用。桌面构建前设置 `XCAGI_BUNDLE_COMPUTER_USE=1`，既有 `build-backend.sh` / `.ps1` 才会安装 `computer-use` extra，并由 PyInstaller 收集 Playwright driver 和桌面依赖；默认构建保持原有依赖。此开关不下载或内嵌 Chromium：运行时使用已部署的匹配浏览器，或通过上述可执行文件路径配置受控 Chromium。源码回归和打包配置检查不代表 Windows/macOS 安装包真机验收通过。组件来源、固定版本和许可见 [README 开源组件选型](../README.md#开源组件选型)。

## 安全模型

- 对外三端点（manifest/invoke/mcp）越过 LAN 门禁与订阅门禁，**安全完全由
  `X-AIOPEN-Key` 承担**——生产必须配置 `AIOPEN_API_KEY`
- `api_call` 仅放行白名单路由（面板可视化管理）
- `ui_*` 受双重开关约束：服务端「远程操控总开关」+ 浏览器端「本页待命」开关
  （默认开启、静默待命；用户明确关闭后以 localStorage 持久化为准）
- 面板与 keys 管理端点仍在 LAN 门禁内

## 技术方案

开放面的能力模型、权限矩阵与分期落地见
[`docs/architecture/AIOPEN_FULL_SURFACE.md`](architecture/AIOPEN_FULL_SURFACE.md)。

## 相关代码

- 后端：`app/application/aiopen/service.py` · `app/fastapi_routes/ai_open.py` ·
  `app/infrastructure/aiopen/cursor_hub.py` · 兼容层 `app/fastapi_routes/ai_qclaw.py`
- 前端：`src/components/aiopen/AIOpenPanel.vue` ·
  `src/components/aiopen/VirtualCursorOverlay.vue` · `src/composables/useAiOpenCursor.ts`
- 测试：`tests/test_aiopen.py`
