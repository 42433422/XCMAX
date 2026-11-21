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
{ "type": "command", "id": "<hex>", "action": "click", "timeout_ms": 10000, "params": { "selector": "#btn" } }
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
同一连接按 FIFO 串行执行。超时或调用取消时，服务端发送 `{"type":"cancel","id":"<hex>"}`；前端在下一次副作用前检查取消与截止时间，上传取文件使用可取消请求。已经发出的点击或网络请求不能撤销，超时必须先核对，不能自动重放。回执必须包含布尔 `success`；缺失或类型错误不能当成功。`ref` 失效时拒绝调用，不回退到 `selector`/`text` 猜另一个控件。输入值、口令、验证码与私密字段不进入光标操作日志。

## Agent 浏览器执行闭环

### 入口与复用边界

现有 Agent 的工具目录提供三条入口，继续使用现有模型网关和规划器：

| 入口 | 执行位置 | 完成依据 |
|---|---|---|
| `aiopen.ui_*` | 当前账号和租户的 XCAGI 页面 | 写操作只说明动作已执行；批准计划必须包含同屏幕、依赖于写操作的 `ui_verify` 回读 |
| `browser.observe` / `browser.execute` | 每任务新建的 Playwright Chromium context | observe 返回未信任页面快照；execute 必须执行 `verify`，核验全通过才能 `verified=true` |
| 本地已配置的 Playwright MCP | 原账号、租户、任务所属的持久 worker 与浏览器代次 | 写前冻结具体后置条件，写后只读新快照；整体目标仍由原循环末端等待与快照核验 |

三条入口均从 `AgentToolExecutor` 到现有 dispatcher，验证签名会话、运行归属、完整存储计划、当前步骤、标准幂等键、租约与审批记录。spawn 通过独立服务端参数传递租约代次，并恢复调用方 workflow 数据库，模型字段不能冒充租约。写操作先落现有幂等账本，未知结果保留原任务待核对；手工调用 dispatcher、模型自带身份字段或页面文字都不能授权。内部光标由 HTTP 进程持有，因此隔离 Agent 子进程通过仅限 loopback 的 HTTP 桥接调用原有 `/api/aiopen/invoke`，使用按账号/租户、单动作、单次配额、短期有效的临时 Key，调用结束撤销。原任务编号不被 HTTP 子轨迹覆盖。

独立核验接入原 `result_verification`：执行前冻结原调用身份、参数和具体断言，执行后先持久化原回执再回查。原生浏览器与 `computer_execute` 读取原制品或效果记录，核对观察摘要、时间及文件字节，只证明记录时的 DOM、像素或文件完整性，不宣称当前页面仍相同。AIOPEN 通过原屏幕的 `ui_verify`、MCP 通过原 worker 的只读快照核对新状态；会话丢失不新建浏览器。点击等动作没有可区分的后置条件、权限已撤销或回查失败时保持 `inconclusive`。所有这些证据均明确 `business_effect_verified=false`，业务交易仍需原业务来源核验；重新核验不会重放输入。

内部 Agent 的 `ui_*` 写操作 Schema 要求非空白 `session_id`，计划只接受不含 `branches` 的依赖图；后续同屏幕 `ui_verify` 必须同时存在于尚可执行的持久化步骤中。外部 REST/MCP 原有定义不受这项 Agent 约束修改。

`browser.execute` 一次包含最多 30 步。支持 role/name、label、text、selector 与 frame 定位，动作包括 click、fill、select、check、press、upload、download；locator 不唯一时拒绝。每步可附 `verify` 等待业务回执，再执行下一步；任务末尾 `verify` 必填，支持 text、value、visible、url。页面 DOM 成功不替代业务事实，调用方应核验订单号、明确状态或下载内容等与目标有关的证据。

### 安装与配置

在运行 Agent 子进程的宿主安装锁定依赖和官方浏览器：

```bash
cd FHD
uv sync --frozen --extra server-api --extra browser
.venv/bin/python -m playwright install --with-deps chromium
export XCAGI_BROWSER_ALLOWED_ORIGINS='{"7":["https://erp.example.com"]}'
export XCAGI_AIOPEN_INTERNAL_URL='http://127.0.0.1:5000'
```

`7` 是示例租户，域名应替换为实际授权站点。配置没有对应租户时拒绝执行；不接受通配符、路径、账号口令或模型传入白名单。资源域名、登录跳转域名必须逐项显式批准。可通过宿主配置 `XCAGI_BROWSER_EXECUTABLE` 指定受维护的 Chromium；模型不能指定二进制、启动参数、本地文件路径、任意 JavaScript 或共享浏览器 profile。Chromium sandbox 保持开启，无法启动时失败。

浏览器任务复用 psutil 7.2.2 对 worker、驱动和已观测浏览器后代合计 RSS，预算取 `XCAGI_TOOL_MEMORY_MB`，默认 2048 MiB。父进程在启动放行、运行等待、流式排空和接受回执前检查；不可观察或超额均停止，已放行的任务标记结果未知并禁止自动重放。子进程放行前仍用原地址空间限制，确认受监督后仅恢复继承的地址空间上限；默认 CPU 60 秒、句柄 256 及 Chromium sandbox 保留。其他工具沿用原地址空间限制。采样 RSS 会重复计共享页，也有采样间短时超额和未观测后代的边界；需要内核硬限制的部署应使用 [cgroup v2 memory controller](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory)，不将轮询当作内核隔离。

以下仅为进入现有审批流程的计划参数示例，不是直接执行端点：

```json
{
  "tool_id": "browser",
  "action": "execute",
  "params": {
    "url": "https://erp.example.com/orders/new",
    "steps": [
      {"action": "fill", "locator": {"label": "客户名称"}, "value": "示例客户"},
      {"action": "click", "locator": {"role": "button", "name": "保存"},
       "verify": [{"kind": "text", "locator": {"selector": "#receipt"}, "expected": "保存成功"}]},
      {"action": "download", "locator": {"role": "link", "name": "下载回执"}}
    ],
    "verify": [{"kind": "text", "locator": {"selector": "#receipt"}, "expected": "保存成功"}],
    "screenshot": true
  }
}
```

上传只接受已有 Agent 文件产物的 `run_id` / `artifact_id`，服务端复验所属账号、租户、摘要和 25 MiB 总大小后读取。下载在点击前注册监听，关闭 context 前保存，产物总接受大小最多 25 MiB；文件名由系统生成并保留安全后缀，随后写入现有不可变产物存储，返回原有账号/租户受控下载 URI。支持现有 xls/xlsm/xlsx/csv/pdf/docx/pptx 与新增 png/json/txt，格式清单复用同一产物存储契约。不支持或保存失败的附件逐项标记 `not_saved`，已观察的执行结果、步骤及核验仍写入回执；整体交付不报告成功、不自动重放。公共执行器保留已保存附件和原失败信息，供任务关联与受控下载；回执本身无法保存时明确报告失败。截图遮罩表单输入区域，JSON 回执避免重复保存输入值；任意页面正文与下载内容仍按用户业务数据处理。

### 已发现缺口与当前处理

此表覆盖本次实际审查的内部页面、Agent 执行器、MCP 适配和 Codex 接入，不表示已对全仓所有业务或任意网站做完生产验收。

| 缺口 | 对应组件与当前处理 | 保留边界 |
|---|---|---|
| 工具目录有 ui_*，统一 dispatcher 没有 aiopen 路由 | 接入现有 Agent dispatcher 与 HTTP 桥接 | 只接受受信任务上下文 |
| spawn 子进程读不到内存 WebSocket hub | 复用现有 REST/Key 注册表抵达持屏进程 | 当前要求单持屏服务实例；跨 worker 路由未实现 |
| 子进程丢失队列代次与审批数据库绑定 | 复用受信租约传递/恢复及调用方 workflow 会话 | 租约失效后拒绝新动作；已经发出的外站请求不能撤销 |
| 缺失 success 被当成功、MCP 错误字段漏读 | 严格布尔回执；兼容固定 MCP SDK 的 snake_case/camelCase | 外部服务器的语义仍是不可信声明 |
| MCP schema 在注册时丢失 | 保留完整嵌套 input_schema；工具契约透传 | readonly 需本地配置与服务器标注同时满足 |
| 指令并发、失效 ref 退回模糊定位 | FIFO、不可复用引用、失效拒绝 | 动态页面应重新 snapshot |
| 超时后动作继续排队、上传阻塞后续任务 | 截止时间、cancel 协议、AbortController；前端命令预算最多 30 秒，非法时长立即过期 | 已发生的事件不能撤销 |
| 账号/租户/审批与任务未完整绑定 | 复用签名会话、持久化审批、步骤与计划、标准幂等键 | 页面不能提升权限 |
| 已执行写入在失败后可能重放 | 任务写前占用；异常回执 unknown 且不重试 | 外部站点不提供原子事务，不能宣称恰好一次 |
| 点击完成等同业务成功 | 当前页面要求依赖回读；外站必填 verify 与可选步骤断言 | 断言内容需要与业务目标相关 |
| 无外站浏览器执行层 | 薄适配复用 Playwright 1.65.1 | 操作限批准来源和固定动作，不支持任意脚本 |
| 逐调用 MCP 会话丢失页面状态 | Playwright MCP 按原账号、租户和任务保留同一 worker/会话代次；原生 browser.execute 在一次 context 内执行 | 原浏览器丢失后禁止替换会话继续，未实现跨宿主页面恢复 |
| 上传路径与下载临时文件缺乏归属，附件失败丢失原核验 | 复用现有摘要校验与产物下载权限；逐附件保存并保留原执行证据，公共执行器传递可下载回执 | 未支持格式标记未保存；交付不完整时保留待核对并禁止重放 |
| Cookie/profile 跨任务污染 | 每任务独立 context，禁止共享 profile | 登录持久化、MFA/验证码及人工接管尚未实现 |
| 脱敏仅覆盖日志，快照/截图仍可泄露输入 | 内部光标与外站表单快照/截图分别处理 | 任意网页文本不能自动证明无敏感信息 |
| iframe 内输入未被顶层截图遮罩 | 截图保守遮罩整个 iframe/frame/object/embed 区域 | frame 内核验沿用 locator，截图不展示嵌入页面正文 |
| 站点跳转/子资源可越过初始 URL 限制 | 每跳 exact-origin 校验，阻断 WebSocket/Service Worker；observe 仅 GET/HEAD | 来源限制不是 OS 网络沙箱；未实现 DNS/IP 钉住与流式传输配额 |
| 外部 AIOPEN 客户端只有事后轨迹 | 本次受控 Agent 入口复用写前账本 | 直接外部 REST/MCP 多次调用不具备端到端幂等保证 |
| Codex CLI 错误可能被直接回复/流式链路当完成 | 非零/未知退出、超时或缺终态保留部分输出并显式失败；直答、fallback、消息回填和开发循环不再提升为完成 | 已验证真实子进程协议边界；Codex 原生 JSONL 全部事件、实际模型及业务任务仍需分别验收 |
| 生产 2 GiB 虚拟地址上限阻止 Chromium 启动 | 真实 CPU/FD 与 AS-only 对照定位，复用 psutil 的整树 RSS 预算与已有握手、截止和回收器 | RSS 采样不是内核硬限制；保留外部继承的限制，严格隔离依赖宿主 cgroup 等机制 |
| 单测可通过但没有真实浏览器验收 | 专项 CI 强制真实 Chromium，缺依赖/启动失败/skip 均失败 | CI 成功只证明合成站点集成，实际模型、业务站点与生产仍需验收 |

### 验证与回滚

`tests/test_application/test_aiopen_agent_bridge.py` 使用真实 SQLite、会话签名、审批消耗、Agent executor 与 FastAPI route 验证身份和幂等；只替换 HTTP 传输与 screen。`test_browser_tool.py` 核对授权与实际产物存储；`test_surface_worker.py` 经真实 spawn 验证租约、原 workflow 数据库和默认资源限制下的 Playwright 驱动，页面效果仍为替身。`test_mcp_tools.py` 使用固定 SDK 的真实 stdio 子进程。`tests/test_infrastructure/test_browser_runtime.py` 在合成 HTTP 站点上验证表单、上传、提交、下载、回读、隔离、超时、iframe 截图遮罩和默认资源限制下的真实 Chromium。

`test_browser_agent_e2e.py` 复用真实会话、审批和产物夹具，经原 AgentToolExecutor 启动真实 Chromium，完成表单、归属文件上传、提交及下载回执，再以新子进程读取同一幂等结果并断言网站只收到一次提交。专项 CI 为此使用独立 JUnit，缺报告或跳过均失败，并记录服务器依赖锁摘要及实际版本。

真实浏览器门禁设置 `XCMAX_BROWSER_REQUIRE_REAL=1`，本地依赖缺失或 sandbox 启动失败时的 skip 不算通过。线上启用需另外核对安装版本、租户站点、真实模型任务、实际业务回执与生产 SHA；可先移除对应租户的站点配置以停止新外站任务，未知旧任务仍须回读核对。

`test_codex_cli_receipts.py` 用实际子进程验证非零退出、stdout/输出文件部分内容、硬截止和流结束；失败只记录一次，不进入开发循环的验证、修复或发布。与既有 Codex/Claude/Cursor 和权限用例合计 916 项本地通过；这证明 Python CLI 适配的失败传播，不代表已连接真实模型或完成 Codex 原生 JSONL 工具事件的验收。

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
