# XCAGI 企业 AI 桌面平台

XCAGI 位于 [XCMAX](https://github.com/42433422/XCMAX) 的 `FHD/` 子树。Windows 与 macOS 共用由 `main` 构建的宿主；客户定制通过版本化 Mod、账号权益和数据归属隔离交付。

本页只保留入口。功能、版本、架构和发布事实在既有 SSOT 中维护，避免重复说明漂移。

## 快速入口

| 内容 | 文档 |
|---|---|
| 日常工作与维护文档 | [START_HERE](docs/START_HERE.md)、[SSOT_INDEX](docs/SSOT_INDEX.md) |
| 开发环境与运行 | [QUICK_START](docs/QUICK_START.md) |
| 功能边界与目录职责 | [FEATURE_MAP](docs/FEATURE_MAP.md) |
| Mod 开发与权限 | [MOD_AUTHORING_GUIDE](docs/guides/MOD_AUTHORING_GUIDE.md) |
| AI 员工配置 | [AI_EMPLOYEE](docs/AI_EMPLOYEE.md) |
| 迁移与历史入口 | [MIGRATION_REGISTRY](docs/MIGRATION_REGISTRY.md) |
| 更新内容 | [CHANGELOG](CHANGELOG.md) |

## 客来来模块

企业客户端的“数据来源”入口现统一为“客来来”，主路径 `/kellai`，标题为“智能生态 / 客来来”。普通模块 `mods/tools/kellai` 随企业包交付，五个工作区为连接与账号、消息中心、联系人、数据接入、自动化。原 `/data-sources` 和 ERP Mod 旧链接保留查询参数与定位片段并转到新入口；内部导航键保持兼容已有角色和移动菜单。

模块复用已有 `KellaiCustomerInbox`、本机文件授权、ELT、AI 模型和跟进任务，Pinia 中共享绑定、客户、会话及回执。渠道目录、实际收发能力与连接状态直接读取客来来；没有渠道能力就不显示可用发送，未实现的静态 planned 来源不再充当产品能力。每类渠道当前只有客来来配置的主实例，渠道凭据、回调和自动回复规则在客来来管理。

默认旧配对仍只申请 `customer_profiles.read`、`customer_conversations.read`。模块入口另申请 `channels.read`；`messages.send` 需用户主动选择并在客来来确认，保存当前 XCMAX 登录账号与企业范围，原只读绑定不自动升级。新代理固定访问本机 `127.0.0.1:8793`，复用客来来 `integrations/xcmax/channels`、`messages/send`、`messages/requests/{client_request_id}`。令牌不交给前端，不接受浏览器提供的渠道密钥或任意发送地址。

手动发送只使用已授权客户会话中的渠道联系人编号。每条发送按请求号保留独立回执，同一联系人的后一次发送不会覆盖前一次查询入口；任何未决请求仍阻止对该目标重复发送。超时和未知结果只查询原回执；同一账号与连接在关闭窗口或重启后仍恢复所有已保存请求编号，内容与令牌不进入该恢复存储。恢复或持久保存失败时拒绝发送；用户清除应用数据不在恢复保证内，多窗口存储也不提供原子互斥。账本 `accepted` 表示渠道受理，界面和小 C 按真实 `provider_state` 显示已发送、送达、已读或失败；未知请求不会因附带状态被升级为成功。桌面执行型渠道明确返回 `requires_desktop_execution`，不冒充服务端已发送。解除绑定不能撤回已受理的消息。

小 C 通过既有 `execute_erp_capability` 注册表调用 `kellai.channels/customers/conversations/send/receipt`，没有第二套 Agent 运行时。发送属于 high 风险、必须写审批、不自动重试；执行前复核封存的登录身份、客来来 scope、已持久化审批的精确收件人和正文，再以运行与步骤生成稳定请求编号。自动化页复用客来来配置入口；本模块人工发送授权不会自动开启自动发送规则。

摘要与草稿沿现有 `chat_completion_openai_format(profile="customer_copilot", request=request)` 使用宿主账户模型。独立客来来可配置现有 OpenAI 兼容账户网关 `/v1/models` 与 `/v1/chat/completions`（`xcauto-account`、`stream=false`）；需已有账户 JWT，或明确配置了钱包签名和 `llm:use` 的 PAT。渠道配对令牌不等于模型授权，LiteLLM 服务端主密钥不下发给模块，不建立另一套供应商密钥池。

验证边界：单元与本机契约测试只证明代码边界；真实外部渠道仍需要有效账号、凭据、可达回调和原始供应商回执，候选代码不能作为已发布或真实送达证据。

## 开源组件选型

企业 Agent 的可选本地执行器复用 [OpenAI Codex Python SDK / App Server](https://github.com/openai/codex) `0.171.0`（Apache-2.0）；`uv.lock` 同时固定 `openai-codex-cli-bin`。SDK 负责进程协议和事件，XCMAX 只负责身份、额度、工具权限、持久任务与结果核验。受控工具使用已锁定的 MCP Python SDK `2.3.0`（MIT）；模型流解析复用 [httpx-sse](https://github.com/florimondmanca/httpx-sse) `0.4.3`（MIT），私有回环服务使用现有 Uvicorn。安装可选 `codex-runtime` extra 才下载运行时；Native 安装和原业务路径保持默认。

管理端手机导航及智能对话的任务／会话抽屉复用锁文件中的 [Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）Drawer，沿用其遮罩、焦点管理与 Escape 关闭；产品侧仅接入原侧栏、路由、任务事件及移动视口样式，不新增导航或聊天执行链。

客来来工作区复用前端 lockfile 已固定的 [Vue 3.5.45](https://github.com/vuejs/core/tree/v3.5.45)、[Pinia 4.1.0](https://github.com/vuejs/pinia/tree/v4.1.0)、[Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（均为 MIT）。采用现有 tabs、table、switch、状态 store 和请求工具，不搬入 React/Tauri 页面或新增渠道 SDK；渠道协议仍由客来来统一负责。


自主编程继续调用已集成的 [OpenAI Codex `rust-v0.153.4`](https://github.com/openai/codex/tree/rust-v0.153.4)（Apache-2.0），GitHub worker 的版本由既有 manifest/lock 固定；本机设备记录实际探测到的 CLI 版本，不能用云端锁版代替本机身份。`cli_output_stream.mjs` 依据同版原生 JSONL 事件与进程退出共同形成回执；`turn.completed`、退出码 0、完整事件流须同时成立，单条工具完成或文本不是整轮成功。保留可内部重试的错误事件，最终仍核对原生终态。旧安装入口转发同一 Para 执行器，真实执行开始后不因配额或工具失败重放；失败补丁保留用于核对，不能进入发布。版本、thread、usage 和执行回执沿原任务报告/outbox 回传。

Para 首次派工先核对 `/api/health` 的 `task_request_recovery_version=1`，冻结全部设备计划和每次原请求正文。`POST /api/tasks` 与 `GET /api/tasks/by-request/:client_request_id` 都核对服务端计算的正文 SHA-256、原 task/subtask/device；消息轮询只读恢复，获授权的原调用续接只派发尚未发送的设备。配套服务 `42433422/devfleet-private` 沿用 SQLite 原生事务、唯一约束和既有重连调度，不能只升级客户端。客户端复用已固定的 [filelock 4.2.4](https://github.com/tox-dev/py-filelock/tree/4.2.4)（MIT）单例可重入文件锁，保留跨进程原请求互斥；未知结果不切换 webhook/CLI 重做。新任务须配置原 Para 地址、账号令牌、仓库与在线设备，旧服务在创建前停止；历史已知 task 仍可读取。

工具回执复用现有 `app/domain/task_lifecycle/results.py`、SQL 幂等账本及 LangGraph，统一首次执行、已观察工具记录、后继节点与历史恢复的 unknown 语义；普通业务 `data.status` 不冒充执行状态。LangGraph 检查点包使用仓库带回补的版本，源码基线与补丁见 `packages/xcagi_langgraph_*/PROVENANCE.json`，不是声明上游发行了同名 fork 版本。[MCP Python SDK 2.3.0](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0)（MIT）沿用原适配器及 `isError` 语义。账号、审批、原任务身份和副作用核对属于产品适配，不重建通用代理或编排引擎。完整缺口及验收边界见 [自治手册](../docs/autonomy.md#自主编程与工具执行)。

浏览器执行复用 [Playwright Python 1.65.1](https://github.com/microsoft/playwright-python/tree/v1.65.1)（Apache-2.0，`browser` extra 与 `uv.lock` 固定版本，与现有前端版本一致）的 BrowserContext、严格 locator、自动等待、断言、上传与下载。内部页面沿用 AIOPEN 光标；任务、模型路由、审批、租约、幂等和文件存储均复用现有 Agent。未引入另一套 Agent 循环：[Playwright MCP](https://github.com/microsoft/playwright-mcp) 可作外部客户端接入，普通 MCP 通道保留逐调用语义，多步 AI 浏览器另由同一任务绑定的持久 MCP 会话维持页面状态，页面丢失后仍不重放操作，直接浏览器和 MCP 共用来源、定位与证据脱敏政策，各自保留原会话、审批和执行账本；[Browser Use](https://github.com/browser-use/browser-use) 与 [Stagehand](https://github.com/browserbase/stagehand)（均 MIT）提供更高层模型编排，本次选择更薄的 Playwright 原语适配。配置、代码边界与剩余缺口见 [浏览器执行接入](docs/aiopen.md#agent-浏览器执行闭环)。

浏览器进程预算复用既有 [psutil 7.2.2](https://github.com/giampaolo/psutil)（BSD-3-Clause，`uv.lock` 与部署锁均已固定）和 Agent 子进程握手、截止及回收器。真实 Chromium 对照确认 2 GiB 虚拟地址上限会阻止启动，浏览器任务因而使用整棵已观测进程树的 RSS 预算，默认仍为 2 GiB；CPU、句柄和 Chromium sandbox 保留。RSS 轮询是运行预算监督，严格内核内存隔离需部署侧 cgroup 等机制，不能把前者当成后者。
Computer Use 在现有 `desktop_automation` 工具内复用 [Playwright Python 1.65.1](https://github.com/microsoft/playwright-python/tree/v1.65.1)（Apache-2.0）、[PyAutoGUI 0.9.54](https://pypi.org/project/PyAutoGUI/0.9.54/)（[BSD-3-Clause 源码](https://github.com/asweigart/pyautogui)）及 [Pyperclip 1.9.0](https://pypi.org/project/pyperclip/1.9.0/)（[BSD-3-Clause 源码](https://github.com/asweigart/pyperclip)），版本与传递依赖锁于 `pyproject.toml` 的 `computer-use` extra 和 `uv.lock`。 Unicode 剪贴板输入仅接受可确认的纯文本格式；Linux 需 `xclip` 枚举格式，图片、富文本及未知格式均拒绝覆盖。浏览器使用独立 Context，桌面使用主屏截图、鼠标键盘与剪贴板；沿用 Agent 审批、租户归属与 `run_id`，不另建 Agent。启用条件、安装及核验边界见 [AIOPEN 的 Computer Use 说明](docs/aiopen.md#computer-use桌面与浏览器执行器)；源码回归不代表安装包或 Windows/macOS 真机验收通过。

小 C 桌面浮窗复用已锁定的 [Electron 45.3.4](https://github.com/electron/electron/tree/v45.3.4)（MIT）`BrowserWindow` 和 `Tray`，沿用现有小 C 对话组件和同一登录会话。


开发自动化继续使用 [LangGraph 1.2.10](https://github.com/langchain-ai/langgraph)（MIT；checkpoint 4.3.0、SQLite 3.1.2 与已吸收的 PostgreSQL 适配版本见 `packages/retort_engine/pyproject.toml`）保存审批、中断和交付等待，不增加另一套任务引擎。GitHub 执行迁移到官方 Actions 独立 job：执行候选、受信发布、恢复原验证、独立验收；[checkout 4.4.0](https://github.com/actions/checkout/tree/11d5960a326750d5838078e36cf38b85af677262)、[upload-artifact 4.6.2](https://github.com/actions/upload-artifact/tree/ea165f8d65b6e75b540449e92b4886f43607fa02)、[setup-node 4.4.0](https://github.com/actions/setup-node/tree/49933ea5288caeca8642d1e84afbd3f7d6820020)、[setup-python 7.1.0](https://github.com/actions/setup-python/tree/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0) 均为 MIT，并在相关源 workflow 固定完整提交。候选用 Git 原生 bundle 传递，发布任务只导入对象，不执行候选代码；原共享身份发布入口保持禁用。

GitHub 业务适配复用 [HTTPX 0.28.1](https://github.com/encode/httpx/tree/0.28.1)（BSD-3-Clause）及 GitHub REST `2022-11-28` 的 merge SHA 并发守卫、dispatch run ID、Issues/Actions 持久回执；配置使用 PyYAML 6.0.3（MIT）。只保留任务归属、风险门禁、可信回执和最终版本校验等产品胶水。已知 Para 控制任务优先恢复；未知外部写入结果保留待核对，不能保证跨 GitHub/Para 的恰好一次。正式完成需受保护主干合入、同提交 CI/安全扫描、已有发布审批、部署证据及线上 SHA/制品摘要一致；分支验收不会提前归档为上线成功。共享宿主交付不替代桌面安装包及客户 Mod 的原有验收。操作入口见根仓 [CI SSOT](../docs/CI_SSOT.md#自治闭环autonomy)。

Retort 复用 Git 原生归档与 [GitHub Compare REST 2022-11-28](https://docs.github.com/en/rest/commits/commits?apiVersion=2022-11-28#compare-two-commits) 核对修复提交与实际发布的祖先关系。MODstore 通过 [GitHub artifact attestations](https://github.com/actions/attest-build-provenance/tree/e8998f949152b193b063cb0ec769d69d929409be)（MIT，锁定提交 `e8998f949152b193b063cb0ec769d69d929409be`）签署原生 Git tar（Git GPL-2.0），由 GitHub CLI 验证签名和签名工作流身份。部署回执绑定签名制品摘要、版本、实际发布 SHA 与公共运行读回。策展员沿用已审查执行包、Python 标准库 `zipfile` 和 Retort 已有加密证据存储，核对批准和原包后生成私有候选 `.xcemp`，读回包与执行凭证后登记完成。

客户反馈改进接入已有 Retort 的 LangGraph 和正式发布核验。管理端复用已锁定的 [Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）表格、步骤和抽屉；审批仍显示准确脱敏复现并绑定摘要，公开计划不含客户原文。客户复现是不可信输入，管理员审批不授权其访问执行器凭据。原 Retort 反馈/训练工作单仅在固定 OpenCode/SRT 的 `srt-0.0.83-header-only-platform-v1` 准入、原派工审批和公司/组合预算绑定全部有效时继续；隔离 worker 只有占位符，模型 grant 由原 event/task/subtask/attempt 核验后领取。原候选发布、独立验证、main 和交付验收仍逐步核对。原 PR repair 沿同一隔离与发布组件，使用自身 MacControlTask、原请求摘要、独立预算 UUID 和 `control_task_id` grant，禁止借用 Retort event 身份；候选经受信消费者核对后 CAS 快进原分支，再核对原候选 CI。缺少原批准、隔离或可信用量时保持相应 waiting/blocked，未知执行只核对原回执；普通非修复任务沿用原路径。群体效果按 [GrowthBook 5.2.0](https://github.com/growthbook/growthbook/tree/0bd125f5a1df8dcde5b1dd1996bc0bc7e1b1e73d)（开源核心 MIT，企业目录另行许可）的 REST v1 读取原统计，真实付费复用客户价值账本的支付源与退款排除规则。

已有 `MODSTORE_RETORT_PROTOCOLS` 的冻结验收方案可选配 `customer_feedback`。其中 `domain` 为 `platform` 或 `software`，`surface` 固定为 `shared_web`，`goal` 为适合公开派工的目标。若同时配置 `MODSTORE_RETORT_FEEDBACK_ACTOR_ID` 和 `MODSTORE_RETORT_FEEDBACK_TEMPLATE`，现有调度器每天自动选题一次；审批不能代替上述隔离身份和预算准入。可选的 `growthbook` 指定 `project`、`metric`、`minimum_users`，由 `MODSTORE_RETORT_GROWTHBOOK_URL` 和服务端只读 API 密钥连接实验。实验 `trackingKey` 使用 `xcagi-retort-<运行 ID>`，标签使用 `xcagi-release-<正式提交>`。`track_paid_outcome` 启用同一账号、订单、目标与制品的商业对账。实验或付费证据缺失时保持待核对。

演化信号的时间与数值护栏复用 Python 标准库 `datetime` / `math`：`generated_at` 按既有信号回看窗口判断新鲜度，`window` 仅表示统计范围，缺测和证据不足沿用原 `needs_human` 账本回执。

智能对话执行流复用现有 AI SDK / Vue 栈，选型和许可证如下：

| 层 | 固定来源 | 复用边界 |
|---|---|---|
| 桌面更新 | [electron-updater 6.8.11](https://github.com/electron-userland/electron-builder/tree/electron-updater%406.8.11/packages/electron-updater)，MIT | 沿用上游频道、灰度、制品哈希校验与安装。产品 provider 在同一次清单请求上验 Ed25519。Windows 未签名候选沿用 NSIS 安装包和临时手动下载流程。 |
| 执行卡片 | [shadcn-vue v2.9.0](https://github.com/unovue/shadcn-vue/tree/39cb0b277f009e47de2dc62c4217755fb9a27eec/apps/v4/registry/bases/reka/ui/trace)，MIT | `frontend/src/components/ui/trace/` 保留上游 Trace / Collapsible 结构及许可；仅替换样式、图标和 Vue getter，使用已有 Reka UI 2.11.0，无额外 CSS 框架。 |
| 消息状态 | [Vercel AI SDK 7.0.173](https://github.com/vercel/ai)，Apache-2.0，版本由前端 lockfile 固定 | `readUIMessageStream` 组装文本和工具事件，`ChatStatus` 提供会话状态。参考 [Open WebUI 的会话任务事件](https://docs.openwebui.com/features/extensibility/plugin/development/events/) 按会话分发，产品层只绑定账号、Mod、会话和审批回执。 |
| SSE 解析 | [eventsource-parser 4.1.3](https://github.com/rexxars/eventsource-parser)，MIT | 从现有传递依赖提升为直接锁定依赖，代替手写 SSE 分隔解析，支持碎片、CRLF、多行 data。 |
| 执行链观测 | [OpenTelemetry Python v1.45.2](https://github.com/open-telemetry/opentelemetry-python/tree/v1.45.2)，Apache-2.0，现有 `uv.lock` 固定 | 复用 W3C Trace Context、SDK span 和 OTLP exporter；产品薄适配绑定原任务账本、工具尝试和既有执行卡片，无新增采集服务。 |

| 员工办公室 | [Pixel Agents v1.6.0](https://github.com/pixel-agents-hq/pixel-agents/tree/4dd14d612fd37d89ffbbc977959f572395c4eec8)，MIT | 固定提交 `4dd14d612fd37d89ffbbc977959f572395c4eec8` 的 Canvas 2D 渲染、工位、精灵与动画核心；仅加 Vue/部门/任务胶水，异步加载，无新增运行时依赖。角色来源为 MetroCity CC0，原许可、源文件校验和可复现导入脚本见 [third_party/pixel-agents](third_party/pixel-agents/README.md)。 |
| 员工任务与图谱 | [Vue Flow 1.48.2](https://github.com/bcakmakoglu/vue-flow) / [Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)，MIT，已有 lockfile 固定 | 复用现有流程图、表单、对话框、执行记录与产物面板；空间、工作台和图谱共同读取原任务账本及认证事件流，不引入上游独立执行器。 |
| 子进程观测 | Python 标准库 `multiprocessing.Pipe` | 只增加隔离工具与现有 StreamLifetime 的 JSON 进度适配，保留业务回执、绝对截止、进程回收、租户和审批控制。 |
| ELT 预演续租 | [CPython 3.12.13 threading](https://github.com/python/cpython/blob/v3.12.13/Lib/threading.py)，PSF-2.0 | 阻塞解析和字段映射期间使用线程及 Event，在独立短事务校验原租户和租约令牌。 |
| ELT 台账证据 | [openpyxl 3.1.5](https://openpyxl.readthedocs.io/en/3.1.5/)，MIT | 复用只读行列坐标。现有结构化模型只判断客户归属，入库校验逐行核对原件。 |

对话执行卡复用同一套 Trace 组件展示规划、附件读取、工具节点、确认和回执。规划占用状态栏，步骤数来自真实工具事件或运行回执。ELT 进度直接读取已持久化的阶段数据；流结束且缺少工具回执时显示“待核对”。正文和执行进度独立更新。

执行链统一传递 `trace_id/span_id/parent_span_id`，保留独立 `request_id/task_id/run_id/call_id/attempt`。HTTP/SSE、后台恢复、工具子进程、结构化日志和模型 OTLP 使用原关联；历史回放不重新生成 ID。错误使用 `error_code/error_type`，业务失败回执也标记失败，重试恢复后保留各次尝试而不污染成功终态。`duration_ms` 使用单调时钟：HTTP 记录完整响应，`run.observed` 的 `duration_scope=active` 累计规划和执行段，审批等待不计入；工具累计与任务执行耗时分开，缺失测量不写零。流结束只表示传输结束。旧任务在观测增量中只派生稳定关联，不改原账本快照或放宽恢复 CAS。

员工办公室遵循 `config/duty_roster.json` 的企业四部门和管理六部门，安装包显式 `enterprise_layer` 优先，部门 ID 与原成员关系保持一致。当前任务和多员工步骤由服务端投影身份、步骤状态及待核对回执；断流保留上次结果并标为过期，慢请求不覆盖较新事件，账号切换丢弃旧响应。派发、审批、暂停、恢复、取消和结果查看沿用原 API；托管开关只控制自动接单。完成数只统计当前可见服务端任务并按任务 ID 去重；地图动画不产生任务、交接或完成回执。

员工办公室遵循 `config/duty_roster.json` 的企业四部门和管理六部门，安装包显式 `enterprise_layer` 优先，部门 ID 与原成员关系保持一致。当前任务和多员工步骤由服务端投影身份、步骤状态及待核对回执；断流保留上次结果并标为过期，慢请求不覆盖较新事件，账号切换丢弃旧响应。派发、审批、暂停、恢复、取消和结果查看沿用原 API；托管开关只控制自动接单。完成数只统计当前可见服务端任务并按任务 ID 去重；地图动画不产生任务、交接或完成回执。

AIOPEN、Workflow、员工与小 C 的可执行能力统一投影现有 `ToolActionSpecV2`，内置动作仍在 `risk_actions.registry.json` 定义，MCP 动态动作沿用现有注册器；重复身份直接拒绝。FastAPI OpenAPI 只提供非执行 HTTP 资源和字段元数据。目录检索复用已锁定依赖 [scikit-learn](https://github.com/scikit-learn/scikit-learn)（BSD-3-Clause）的 TF-IDF 向量化与余弦相似度，语义 overlay 由已有 PyYAML（MIT）读取，不改变契约授权。MCP 协议层沿用官方 Python SDK（`mcp==2.3.0`，MIT）同一生态的 JSON-RPC 约定，未替换现有传输实现。

统一执行继续复用已有 LangGraph、SQLAlchemy 任务仓储、审批工作台和工具幂等账本。产品胶水只负责有效账号/租户/Mod/凭据绑定、同一能力契约投影、原任务回执和独立业务读回，不增加第二个调度器、权限引擎或企业数据存储。客来来适配使用已有 HTTPX 0.28.1 固定本机连接，供应方 gitlink 保留已整合的 `d680714fae8917f692e261c67856e5d266cafb05`，包含原 PR #2 后续修复；已受理不等于送达，核验必须读取原消息与回执。实现、回归入口与尚未取得的供应方/部署证据见 [流程 SSOT §2.4](docs/architecture/PROCESS_FLOW_SSOT.md#24-能力契约与调用方迁移t03t12)。

桌面语音沿用 [HTTPX 0.28.1](https://github.com/encode/httpx/tree/0.28.1)（BSD-3-Clause）和 websockets 16.1（BSD-3-Clause），由 XCAGI 绑定配置的出站地址。通话断句使用 [Pipecat Smart Turn v3.2 CPU](https://huggingface.co/pipecat-ai/smart-turn-v3/commit/f766f81d3cfdf7737ac64aad813d91bbfd56bf93)（BSD-2-Clause），桌面后端构建校验并打包固定权重。

扫描件与图片兜底复用 [RapidOCR](https://github.com/RapidAI/RapidOCR) `rapidocr-onnxruntime` `1.4.4`（Apache-2.0，ONNX，无 torch）：仅在 pdfplumber 提取不到文本的页面渲染后识别，`XCAGI_PDF_OCR=off` 可关闭，默认最多处理 30 个空页；同时支持直接导入 png/jpg/webp/bmp 图片。文本版 PDF 仍走 pdfplumber 的文本与表格。

知识库网页导入复用 [trafilatura](https://github.com/adbar/trafilatura) `2.3.1`（Apache-2.0，纯 Python）提取正文与标题，URL 导入与本地 `.html/.htm` 文件共用同一实现；联网复用锁定的 [urllib3](https://github.com/urllib3/urllib3/tree/2.8.0) `2.8.0`（MIT）连接池，把经全部 DNS 结果校验的数字 IP 作为连接目标，保留原域名的 Host、TLS SNI 与证书校验，不继承环境代理。产品侧只保留 SSRF 防护（拒绝内网/回环/保留地址、逐跳校验重定向、5MB/15s 限制）与租户隔离胶水；真实传输层回归确认路径中的地址不能更改连接目标。`XCAGI_KB_ALLOW_PRIVATE_URLS=1` 仅用于受控内网调试。

知识库对象存储导入复用 [boto3](https://github.com/boto/boto3) `1.44.4`（Apache-2.0）读取 `s3://bucket/key`：产品侧只做 URI 校验、可选桶白名单 `XCAGI_S3_ALLOWED_BUCKETS`、大小上限 `XCAGI_KB_MAX_OBJECT_BYTES`（默认 25MB）与错误归一化；S3 兼容存储用 `XCAGI_S3_ENDPOINT_URL` / `XCAGI_S3_REGION` 指向，凭证沿用标准 AWS 环境。

知识库 Confluence 导入直接调用站点 REST API（`GET /rest/api/content/{id}?expand=body.storage`），产品侧只保留配置校验、5MB/15s 限制与正文抽取；站点用 `XCAGI_CONFLUENCE_BASE_URL` 指定，凭据用 `XCAGI_CONFLUENCE_API_TOKEN`（可选 `XCAGI_CONFLUENCE_EMAIL` 启用 Basic Auth，否则 Bearer Token）。

知识库飞书文档导入调用开放平台 `tenant_access_token` 鉴权与 docx `raw_content` 接口，产品侧只做凭据校验、token 缓存、5MB/15s 限制与纯文本落库；应用凭据用 `XCAGI_FEISHU_APP_ID` / `XCAGI_FEISHU_APP_SECRET`，私有化域名用 `XCAGI_FEISHU_BASE_URL`。

知识库 Notion 导入调用官方 REST API 读取页面标题与块树（递归子块、分页、最多 500 块 / 3 层），扁平化为纯文本；集成 token 用 `XCAGI_NOTION_TOKEN`，自建代理域名用 `XCAGI_NOTION_BASE_URL`。

知识库语雀导入直接调用官方 REST `GET /api/v2/repos/{namespace}/docs/{slug}`（`X-Auth-Token`），正文取 Markdown（缺失时从 `body_html` 抽纯文本）；token 用 `XCAGI_YUQUE_TOKEN`，私有化域名用 `XCAGI_YUQUE_BASE_URL`，文档引用写成 `namespace/repo/doc`。

外部来源入库时记录 `source_kind` / `source_ref`（url、Confluence、飞书、Notion、语雀），`POST /datasets/{dataset_id}/documents/{document_id}/refresh` 可按坐标重新抓取：内容未变不产生新版本，变化则沿用原 source 与分块配置生成下一版本，供 diff / rollback 治理；`POST /datasets/{dataset_id}/documents/refresh` 批量同步当前租户可见来源并返回 changed/unchanged/failed/skipped 汇总；每次刷新记录 `last_source_sync_at`，批量同步传 `max_age_hours` 可只处理超时未同步的来源（返回 `fresh` 计数），适合定时任务反复调用。设置 `XCAGI_KB_AUTO_REFRESH_HOURS>0` 后应用会启动进程内定时同步线程（首次延迟 120 秒、最小间隔 5 分钟，随应用关闭退出），默认关闭。

知识库语义检索复用 [fastembed](https://github.com/qdrant/fastembed) `0.9.1`（Apache-2.0，ONNX Runtime，不依赖 torch）：`FHD_EMBEDDING_MODE=fastembed` 时默认中文模型 `BAAI/bge-small-zh-v1.5`，精排复用其 `TextCrossEncoder`（默认 `BAAI/bge-reranker-v2-m3-int8`，多语言 int8，约 0.57GB，需显式开启或 `FHD_RERANK_AUTO=1` 在 hash 降级时自动启用）。未安装或未启用时回退到 192 维「中英二元组带符号哈希」向量与词法重排（BM25 中文按字、剔除高频功能字），状态接口会如实报告 `semantic_embedding_available=false`。检索质量用 `scripts/dev/knowledge_retrieval_eval.py` 的 recall@k/MRR 评测，`--multi` 可把语料拆到 3 个知识库验证跨库检索。入库可带 `tags`（≤20 个、每个 ≤32 字），查询与跨库检索支持 `tags` 任一命中过滤（也可用 `metadata_filter` 做同样收窄）。纯文本/外部抓取入库时，同一租户下不同来源的正文完全一致时，入库直接复用已有文档（返回 `duplicate=true`/`duplicate_of`），需要保留副本可传 `allow_duplicate=true`；文件上传仍走指纹幂等。问答默认带低置信拒答：证据覆盖率低于 `XCAGI_KB_MIN_RELEVANCE`（默认 0.1，单次请求可用 `min_relevance` 覆盖）时明确回复「没有找到相关内容」，`--ood` 可验证域外问题拒答率；送入模型的证据默认限制 6000 字（`XCAGI_KB_MAX_CONTEXT_CHARS` 或请求 `max_context_chars` 调整），返回 `context_chars/context_truncated`。`XCAGI_KB_AUTO_QUESTIONS=1` 可在入库时为片段生成检索问题（写入 `metadata.auto_questions`，参与 BM25 与证据覆盖；每片 3 个、单次 20 片可调），默认关闭。检索支持可选的 MMR 多样性重排：查询与跨库检索传 `mmr_lambda`（0–1，0 关闭，也可用 `XCAGI_KB_MMR_LAMBDA` 设服务端默认），按「相关性 − 与已选结果的相似度」挑选片段，避免同一段内容的多份切片占满 top-k；有向量用余弦、hash 降级用查询词 Jaccard，`--diversity 0.7` 可对照评测。检索模式用 `retrieval_mode` 选择 `hybrid`（默认，向量 + BM25 + RRF）/ `vector`（仅语义）/ `keyword`（仅关键词，适合精确编号与型号），单库查询、跨库检索与问答都支持，`--mode` 可对照评测；混合模式还可用 `vector_weight` / `keyword_weight`（0–10，默认 1:1）调两路 RRF 权重。本语料 hash 下 keyword-only 0.8696/1.0/1.0、MRR 0.9348，BM25S 修复后默认混合 0.8551/0.9710/1.0、MRR 0.9147（69 题 hash 小语料，不代表生产语义验收）。需要整章证据时传 `expand_section=true`：命中块扩展为同一 Markdown 章节的完整正文（默认 4000 字预算、从命中块向两侧扩，不跨文档/版本/章节，结果标 `metadata.context_mode="section"`），即成熟的 small-to-big 检索。知识库问答框下方可直接切换「模式 / 整章扩展 / 多样性」，默认混合、关闭、关闭。PDF 表格入库会保留 `[table N]` 标记的 Markdown 表格，查询命中表格附近时结果附带 `metadata.table_context`（完整表头与各行，4000 字上限）。状态接口返回 `source_sync`（可刷新文档数、从未同步数、最近同步时间），检索质量由 `tests/test_application/test_knowledge_retrieval_baseline.py` 在 CI 中锁定基线。问答另提供 SSE 流式端点 `POST /datasets/{dataset_id}/query/stream`（`meta` / `delta` / `done` 事件，无平台模型时回退确定性答案），前端默认使用流式、失败自动回退普通查询；问答框下的「跨库」开关（存在多个知识空间时显示）改为调用 `POST /datasets/multi-query` 一次检索全部可见库。答案可点「有帮助 / 没帮助」提交反馈（`POST /datasets/{dataset_id}/feedback`，按租户隔离，`GET .../feedback` 汇总满意度），反馈独立存于 `dataset_feedback.json`，不触碰查询快照。术语表（同义词）用 `PUT /datasets/{dataset_id}/synonyms` 维护（`{退款: [退货, 退钱]}`），查询命中口语词时自动追加语料写法参与召回，前端问答「术语」按钮可编辑。未命中问题会记入知识缺口（`GET/DELETE /datasets/{dataset_id}/query-gaps`，同问题合并计数、租户隔离），前端空召回时可直接查看与清空。问答引用带 `document_id`/`char_range`，召回面板证据行可点「原文」直接打开该文档分块。知识空间可整体导出为 JSON（`GET /datasets/{id}/export`，含文档/分块/术语，已剔除内部向量字段）并导入恢复（`POST .../import`，需写权限、非空需 `overwrite=true`、强制操作者租户），前端工具栏提供导出/导入按钮。外部只读访问用数据集 API Key：`POST /datasets/{id}/api-keys` 生成（明文只显示一次、仅存哈希、可回收），外部调用 `POST /api/knowledge/v1/public/query` 携带 `X-KB-Key`，密钥绑定单一数据集与创建者租户并按 ACL 过滤。查询结果 `metadata.highlights` 给出命中词区间，前端召回证据行高亮显示。问答对（FAQ）用 `GET/PUT/DELETE /datasets/{dataset_id}/qa-pairs` 维护：`PUT` 接受 `{question, answer}` 列表或「问题,答案」CSV/TSV 文本（默认覆盖当前租户、`replace=false` 追加，按问题+答案去重，单库 2000 对），问答对随数据集持久化并和文档块一起进混合召回与引用（`metadata.type="qa"`），无文档也能直接命中答案；前端问答框的「问答」面板可粘贴导入并预览。

AIOPEN 虚拟光标的蓝色星尘拖尾复用 [cursor-effects](https://github.com/tholman/cursor-effects) `1.0.18`（MIT，已锁定版本）的 `fairyDustCursor`，通过合成 `mousemove/mousedown` 驱动；光标本体、方向倾斜与点击动效仍由产品侧 CSS/薄胶水控制，库仅在首次操作时懒加载。
模板库前端采用 [VueFinder](https://github.com/n1crack/vuefinder) `4.8.0`（MIT，已锁定版本）作为文件管理页面；文档预览沿用 `@vue-office/docx` `^1.6.3` 与 `@vue-office/pptx` `^1.0.1`。业务数据、权限与审批仍由宿主承担，组件仅做只读浏览与交互。

智能生态「AI 市场」复用锁文件中的 [Element Plus 2.14.8](https://github.com/element-plus/element-plus/tree/2.14.8)（MIT）分段选择器呈现「模块 / 员工」。分类复用现有目录身份与 `catalogStoreCollection`，业务模块和员工均沿用原有查询、安装、卸载、更新及授权流程；产品侧只补充分类、路由和界面衔接，无需新增市场引擎或依赖。

前端测试的原生 Canvas 后端复用 [@napi-rs/canvas](https://github.com/Brooooooklyn/canvas) `1.0.13`（MIT，仅开发依赖），满足已锁定 jsdom `31.0.1` 的可选 peer 要求；像素回归使用真实绘制结果，依赖及平台二进制均由锁文件安装，不依赖宿主共享模块。

## AI 浏览器执行（可选）

浏览器自动化复用 [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) `@playwright/mcp==0.0.86`（Apache-2.0）、已锁定的官方 Python MCP SDK `2.3.0`（MIT）与原有 AgentRun / LangGraph。浏览器依赖单独锁在 [browser_mcp_deps](scripts/autonomy/runtime_tools/browser_mcp_deps/package.json)，保持官方发行包的 Playwright `1.66.0-alpha-2026-11-18` 精确依赖及 integrity；这是官方 MCP 包的依赖选择，不把 alpha 浏览器引擎描述成稳定版，也不更改前端 Playwright 版本。

决策继续调用 `planner_llm_gateway` 和已有模型池，使用原任务的预算、模型调用记录、工具契约、逐步审批、租户权限与检查点。产品适配只补任务身份、原执行器进程生命周期和观察回路；纯动作策略与决策/页面证据契约分别位于 `domain/autonomy/browser_policy.py`、`browser_evidence.py`，本地服务信任与执行图入口合同留在原 MCP registry。已调研 [Browser Use](https://github.com/browser-use/browser-use)（MIT）与 [Stagehand](https://github.com/browserbase/stagehand)（MIT）；它们带有另外的 Agent / 模型控制面，本实现直接使用 Playwright MCP 的浏览器能力，保留仓库已存在的执行控制面。AIOPEN 的宿主 DOM 导航与光标仍负责自身页面；Codex CLI 的编码执行、模型路由与超时能力不等同于这个第三方网页回路。

| 已定位的缺口 | 当前代码处理与证据入口 |
|---|---|
| MCP 每调用一次就关闭连接，执行器每步又销毁进程 | 有状态连接与隔离 worker 都按服务器、租户、账号、原 run 复用；普通工具仍用原路径。见 `persistent_sessions.py`、`browser_tool_process.py`。 |
| SDK 2.3 字段变化丢失错误、Schema、分页及结构化结果 | 同时识别新 snake_case 与旧别名；显式结构化 `success=false`、非法成功标记及未完成外层回执不报成功，空的合法 MCP 结果和普通资源正文仍兼容。 |
| 工具发现后只剩必填字段，模型缺少参数类型和枚举 | 原始 JSON Schema 保留至规划、ToolActionSpec 与执行前校验。 |
| 模型预先猜测页面目标，静态计划执行完就宣称完成 | 只接受一个导航/快照起始节点；每步重新观察后仅追加一个节点，仍由原 LangGraph 执行。 |
| 外部动作绕过原权限或复用旧审批 | 工具继续走真实 actor、Mod、allowlist、审批凭据与幂等回执；每个新写动作重新绑定自己的 step。 |
| 页面文字或模型回复被当作成功凭证 | 必须实际等待指定文字，再获取同代会话的新内联快照；拒绝仅出现在工具代码回显中的文字及操作前已存在的静态文字。最终只证明指定页面文字已读回。 |
| 超时、断连、重启后可能重做未知写操作 | 输出持久化 session generation；旧进程/会话丢失、身份或配置变化时明确阻断，未知写结果须核对，不能自动创建新浏览器继续。 |
| 取消可打断 SDK 的受保护清理 | 会话 owner 与 deadline 使用官方 SDK 同体系的 AnyIO 取消域；真实 stdio 回归同时检查进程退出与 transport 关闭，不忽略资源告警。 |
| 模型凭据随 worker 请求进入临时文件 | 请求通过有大小、deadline 与清理边界的匿名 Pipe 传输；模型 scope 与任务输入不写入请求文件。 |
| 无界循环和等待任务占用资源 | 最多 12 次模型决策、32 个步骤，原始 300 秒调度期限不因续跑重置；每步仍受原执行 deadline 约束，终态主动回收，空闲会话默认 300 秒回收。 |
| 目标审核把观察起始节点误判成遗漏后续任务 | 仅对本地配置认可的合法入口补充浏览器控制合同，独立模型仍须审核完整目标、约束和可验证范围；普通计划不获得该合同。后续决策保留原任务内已持久化的用户澄清答案，用户更正优先于原请求，提问文字本身不构成授权。 |
| 原隔离内存上限无法启动现代 V8 | 浏览器单独设置虚拟地址上限并采样整个子进程树 RSS，超限回收；保留原 CPU、文件描述符和进程树清理。 |
| 只有受控 transport 测试，没有真实浏览器验收入口 | CI `Browser Agent real MCP integration` 安装精确 runtime 与 Chromium，经真实隔离执行器验证跨步页面、任务隔离、审批消费、单次提交、读回失败和会话丢失。测试代码存在不等于该提交的 CI 已通过。 |
| Codex 的 CLI、验证或发布失败被文字结果标记完成 | 原同步、派发回退与流式调用保留阶段失败、部分输出和已启动事实；验证失败不提交，失败工作区保留供核对，持久工作区有改动或状态未知时停止。历史消息读取不再重放明确的失败回执；已接收任务不等于执行成功。 |

启用前按 [QUICK_START](docs/QUICK_START.md) 安装现有服务端依赖，并在 `FHD/` 中安装独立浏览器 runtime（Node 20 以上）：

```bash
npm --prefix scripts/autonomy/runtime_tools/browser_mcp_deps ci --ignore-scripts
cd scripts/autonomy/runtime_tools/browser_mcp_deps
npx --no-install playwright install --with-deps chromium
```

从 [mcp_browser.example.json](resources/config/mcp_browser.example.json) 创建本机私有配置，把 `args[0]` 改为安装后 `@playwright/mcp/cli.js` 的绝对路径，设置 `XCAGI_MCP_SERVERS_FILE` 指向该文件，再启动原后端。配置不存在或 `XCAGI_MCP_ENABLED=0` 时不启用。`--isolated` 不复用个人浏览器 profile；本地 `browser: true` 与 `session_mode: persistent` 才会启用观察回路，远端名称或注解不能自行开启。明确写出原任务目标和可读回的页面完成条件，初始规划只含 `mcp__browser.browser_navigate` 或 `browser_snapshot`。

浏览器动作仅开放导航、快照、点击、填写、选择、按键、等待、标签页、返回和截图；最终执行边界也检查相同策略。导航只接受不含凭据的 HTTP(S) 地址，禁止直接执行 JS、安装代码、上传本地文件和指定本地输出路径。非白名单动作、登录、验证码或模型不可用进入原澄清/等待流程；等待不会替用户完成登录。需要人工操作时必须在可见桌面配置同一浏览器实例，默认 headless 模式没有远程接管 UI。

`session_idle_seconds` 默认 300，`max_sessions` 默认 8（每服务最多 32），另有 worker 总量上限。浏览器虚拟地址配置为 `XCAGI_BROWSER_ADDRESS_MB`（默认 1.5 TiB，仅为 V8 地址预留，非物理内存配额）；`XCAGI_BROWSER_MEMORY_MB` 默认 4096 MiB，由生命周期监测器采样 RSS 并回收超限进程树，不等同于内核 cgroup 的无超调硬限制。`XCAGI_TOOL_CPU_SECONDS` 默认 60，长寿 worker 不为每步重置 CPU 额度。300 秒为调度期限，已开始的单次模型/工具调用仍使用原调用超时，期限后不再发起新动作。

Computer、原生浏览器、AIOPEN 与持久 MCP 已在本轮集成候选中适配原执行器和独立核验；固定来源见[流程 SSOT §9.3](docs/architecture/PROCESS_FLOW_SSOT.md#93-候选身份快照与整合约束)。两个直接浏览器共用目标、定位和快照政策，MCP 会话生命周期仍独立保留；源码接入不代表 main 合入、真实业务验收或发布。

| 剩余缺口 | 已有资源、候选组件与当前边界 |
|---|---|
| AIOPEN 内部 Agent 到宿主屏幕的可信桥接 | workflow router 已接入 [#3434](https://github.com/42433422/XCMAX/pull/3434) 的短效单动作桥，按原 actor / tenant / screen、审批及后续核验绑定请求，再访问持屏宿主 HTTP 入口。宿主 WebSocket 池不会自动进入工具子进程；多 worker 的部署和真实屏幕归属仍须验收。 |
| 按租户约束网络目标与页面隐私 | 两个直接浏览器已共用 origin 约束、字段脱敏和截图遮罩；这些页面隐私政策尚未接入本持久 MCP 回路。浏览器进程隔离和动作白名单不代替网络出口边界。 |
| 登录、SSO、验证码与人工接管 | 可复用 [Playwright authenticated state](https://playwright.dev/docs/auth) 和 [noVNC](https://github.com/novnc/noVNC)（主体 MPL-2.0）的可见会话接管；尚未接入账号凭据保险库或远程接管 UI，当前沿用澄清等待，默认 headless 不提供人工登录窗口。 |
| 跨宿主恢复浏览器 | 可评估 Playwright 远程连接及 [Steel Browser](https://github.com/steel-dev/steel-browser)（Apache-2.0）的会话设施；Steel 当前仍标 public beta，仅作候选。已有检查点只能恢复任务控制状态，原浏览器丢失后明确停止，不宣称网页状态已恢复。 |
| 授权上传、下载与持久制品 | 直接浏览器已接入 [Playwright download](https://playwright.dev/docs/downloads) 和 #3434 的制品桥，复用原文件归属、哈希与下载接口；持久 MCP 白名单仍不开放本地文件操作，完整上传下载场景须真实验收。 |
| Canvas 与桌面视觉定位 | [#3430](https://github.com/42433422/XCMAX/pull/3430) 的 PyAutoGUI 桌面适配已纳入候选，尚未接入本持久 MCP 回路；像素状态不证明后台业务完成。 |
| 超长页面、混合工具和多个浏览器 | 继续复用原 LangGraph 与 MCP 定位快照能力；当前每次观察最多 24,000 字符，入口仅接受单一浏览器服务的连续任务，不宣称整页覆盖，混合或多浏览器初始计划会被拒绝。 |
| 业务数据库、付款或外发结果核验 | 须复用对应业务服务的独立查询和实际交易回执；本回路终态仅证明指定页面文本已读回。 |
| 生产模型、客户站点和各平台交付 | 复用原模型池、客户测试环境与原发布流水线逐项验收；Linux fixture 不代替真实模型决策质量、客户 SSO、Windows/macOS 安装包或同 SHA 部署证据。 |
| Codex 的完整产品验收与任务凭据隔离 | 继续复用现有 CLI、工作区和 CI；本次验证了失败状态与禁止重放，默认验证仍是已配置命令或 Python 编译，未调用真实 Codex 账户完成产品验收。反馈修复链的 `waiting_credential_isolation` 仍须独立解决，不因普通 CLI 回执修复而解除。 |
| CI 宿主后续升级 | 浏览器专项暂固定为保持 Chromium 沙箱的 `ubuntu-22.04`，避免 24.04 缓存内 Chromium 的 user-namespace/AppArmor 不兼容；该镜像已进入弃用期，须在官方 [2027-04-17 退休](https://github.com/actions/runner-images/issues/14254)前迁移到验证过沙箱兼容的新宿主。 |
### Verification Engine：任务结果独立核验

入口为 [result_verification.py](app/application/agent_orchestrator/result_verification.py)、[verification_readback.py](app/application/agent_orchestrator/verification_readback.py) 和 [verification_recovery.py](app/application/agent_orchestrator/verification_recovery.py)，接入现有 `StepExecution`、AgentRun/ToolCall 账本和 LangGraph。宿主在执行前冻结账号、租户、Mod、任务/步骤/调用、attempt、参数摘要及注册工具契约；先保存原始执行回执，再独立读取事实。核验记录另存，不覆盖执行器原输出；模型或工具自报 `verified=true` 不构成证据。

`failed`、`inconclusive`、`pending` 阻止任务报告成功和自动重放。已完成步骤跳过前仍核对契约、原回执、步骤投影与核验摘要；已有成功回执不能被后续保存改写。重新核验沿用原权限和原调用，只更新读回观察，以原任务 CAS 防止并发覆盖；崩溃后先按权威队列租约收敛为 `unknown/needs_verification`，不因缺少核验结果重新出库、入账或发送。已验证产物从原回执幂等恢复下载投影；只有全部动作原本已完成或跳过时才可终结任务。

持久化任务的 dispatcher 在原结果回流线程中分批发现待核验回执，租约和退避存于原 AgentRun，不建立新队列。后台核验同时检查原队列身份、状态、计数、时间及已释放租约，再与任务 CAS 一起保存观察。仅当全部原步骤已完成或跳过、核验通过、原会话仍有效且没有未结清副作用时，原重试事务才重新核对条件并安排原图完成收尾；不续期授权、不重做未完成步骤。`unknown` 队列和未结清副作用只能更新观察。客来来丢失发送回执时可按原请求 ID 精确读回送达证据，执行未知仍保留，不能据此自动重发或改成成功。

任务详情展示核验状态、独立通过/仅契约检查步数和证据，并提供“重新核验结果”。接口为 `GET /api/agent/runs/{run_id}/verification` 和 `POST /api/agent/runs/{run_id}/verify`。`not_required` 仅用于注册为只读且输出契约通过、未声明待核验文件的动作，表示**只读契约检查**；旧记录为 `not_verified`，混合新旧步骤不能省略未覆盖步骤后宣称整任务已核验。员工结果包检查只拦截显式失败和身份不符，不能代替此独立读回。

只读资格只接受宿主在 [原工具登记](config/risk_actions.registry.json) 显式登记的 `read_only=True`。核验适配以宿主 `verify_independent_result` 的实际分派为准，不再维护会随合并失效的第二份动作数量清单。旧 `query/list` 等动作若既无此标记也无独立适配器，即使执行及输出契约通过，仍会进入 `inconclusive` 并阻止完成；需逐动作审查实际实现，不能凭名称、低风险或幂等性放行。尚未补齐的范围包括部分报表汇总、库存流水、客户地址和账龄分析。Excel 读取、结构、查询与统计已按实际只读实现登记；自然语言查询只执行经过校验的有界 JSON 计划，与受限筛选表达式互斥，不再执行模型生成的任意代码。这里说明限定链路的实现与核验范围，不能据此认定全系统达到生产 L6。

| 核验范围 | 已接入的独立事实 | 尚未覆盖的条件 |
|---|---|---|
| `customers.create` | 原事务幂等回执、原参数摘要、租户、客户 ID/字段与当前版本 | 无可信原事务回执、对象已变化或读取权限不足时不放行 |
| `catalog_products_v1.append_price/correct_price` | 原操作、来源绑定和价格账本读回；要求当前状态吻合 | 历史修改成功但当前已变化仍待核对；不重新发布修改 |
| `reports.export`、`excel_analysis.export`、五类文档生成员工 | 运行归属、文件哈希/字节数、格式与可读结构；报表/Excel 导出的显式表格输入可逐项对照 | 证据标记 `artifact_integrity`；不证明任意文档的业务语义或客户验收，已有生产者标识不得冲突 |
| `sales.confirm/cancel/deliver/invoice/payment/credit_note` | 执行前冻结原订单观察，执行后按原租户/Mod 读取订单状态、出库流水、收款分配及平衡分录；非原幂等键的新动作不能借用旧流水 | 需当前订单/账簿读取权限；缺失记录、并发歧义、金额/数量不符仍待核验；证明请求后置状态，不推断因果 |
| `enterprise_cognition.bind_goal/plan/evaluate` | 原目标哈希、原父子任务准入及冻结观察对应的 MemoryV2 记录 | 方案准入不等于业务完成，待审批子任务不可被核验终结；记忆仍按原确认、拒绝、纠正流程治理 |
| `employee.execute` 的 clerk 显式 start | 原员工账本中的服务端任务、账号、租户、工作区与创建事件；只核验准入，业务结果保持 pending/success=False | 准入回执不证明后续执行；子任务实际执行与业务完成需要各自原始回执 |
| `employee.execute` 的 `run_tools/child_return/chain` 收尾 | 原任务与全部必需子任务集合、父子关系、账号/租户/工作区、原计划与执行回执逐项核对，继续读取原独立核验与文件证据 | 任一必需子任务未完成、原账本/来源/权限变化或原回执缺失均不放行；不把其它 continuity 操作自动视为已核验 |
| `purchase.create_order/update_order/approve_order/cancel_order/create_inbound` | 原租户和审批订单、价格/数量/供应商范围，以及收货、库存和应付关联按原事务与独立 SQL 读回核验；创建单号绑定原 run/step/tenant | 缺原订单、额度或归属不符时拒绝；受理与材料回执不能替代真实业务记录，结果未知时禁止重放 |
| `elt_import.execute` 的六类 SQL 目标 | 执行前冻结原预演、审批计划及来源摘要；执行后独立回读原行级账本及 `dynamic_table`、客户、产品、客户产品、采购单、发货记录的真实字段、归属与关联 | 同内容去重仍须核对真实目标；计划、来源、租户或数据不符时不放行。考勤、导出、知识库、Webhook 等其他目标尚无本适配器，保持待核验；未知执行不能因读回成功而重放 |
| `browser.observe/execute`、`computer_execute`、具备后置条件的 AIOPEN/MCP 写动作 | 原调用冻结断言；原制品/效果记录的实际观察与文件字节，或同一屏幕/浏览器代次的新只读观察 | 明确 DOM、像素、页面或文件范围及 `business_effect_verified=false`；历史记录不证明当前状态，缺条件、丢失会话或权限不足仍待核对 |
| 注册只读动作 | 原输出契约检查，明确标为 `not_required` | 不宣称已证明外部业务副作用；声明文件却没有适配器仍阻断 |
| 其他销售/出库/会计、未覆盖的 ELT 目标及尚未接入适配器的外部动作 | 保留已有专用执行回执与门禁 | 尚未全部接通本引擎的可信原回执和独立适配器；未覆盖的副作用返回 `inconclusive` |
| 旧任务、legacy 管理端路径 | 保留历史原回执；员工台账的新 `verified` 为 false，旧值只作为 `legacy_result_valid` 展示 | 执行包检查明确标为 `execution_envelope`；无冻结契约不能补造独立通过，仍需逐入口迁移和真实业务验收 |

`kellai.send` 的原渠道回执完整保存在 `data.delivery_receipt`；受理与送达分开。独立核验只读取当前账号授权的原请求回执和原客户消息，并核对请求、渠道、收件人、内容与供应商消息 ID。仅 `delivered/read` 可通过，发送受理、投影缺失、读取范围不足和权限撤销保持待核验，不能自动重发；具体外部渠道回执仍取决于已配对客来来实例。

企业结果回流复用原 AgentRun 和 SQLAlchemy CAS。调度器在启动及周期检查中发现已完成但尚未记录的经营结果，在独立线程只读核验，按原观察和记忆键恢复 MemoryV2 候选及聊天投影。租约、退避与停止状态均在原任务元数据内，不建立第二个任务账本。权限过期停止读取；结果改善也不等于因果已证实，记忆候选仍遵循原审核、拒绝和更正流程。

复用现有成熟组件，产品侧仅补业务身份、证据适配和完成门禁；通用编排或评测库不掌握 XCMax 的原事务事实，不能直接替代这些适配。

| 来源与固定版本 | 许可证 | 复用决策 |
|---|---|---|
| 现仓 LangGraph 1.2.10、checkpoint 4.3.0、SQLite 3.1.2 | MIT | 沿用持久化/恢复；遵循[至少一次执行与回执未知语义](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)，本次不升级运行时 |
| [jsonschema 4.26.0](https://github.com/python-jsonschema/jsonschema)，版本见 [requirements.txt](requirements.txt) | [MIT](https://github.com/python-jsonschema/jsonschema/blob/main/COPYING) | 实际用于冻结输出契约和读回结构校验，禁止远程 schema 取数 |
| openpyxl 3.1.5、python-docx 1.2.0、python-pptx 1.0.2；pypdf 6.21.4；pandas 服务端 2.3.3/桌面 3.0.2 | 前三者 MIT；后两者 BSD-3-Clause | 沿用[服务端锁文件](ops/deploy/requirements-server-api.lock.txt)和[桌面锁文件](XCAGI/requirements.lock.txt)解析真实字节；[docx](https://github.com/python-openxml/python-docx/blob/master/LICENSE)、[pptx](https://github.com/scanny/python-pptx/blob/master/LICENSE)、[pypdf](https://github.com/py-pdf/pypdf/blob/main/LICENSE)、[pandas](https://github.com/pandas-dev/pandas/blob/main/LICENSE) 许可保留 |
| [Codex rust-v0.171.0](https://github.com/openai/codex/tree/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e) | Apache-2.0 | 参考结构化执行事件和[确定性检查后只读评测](https://developers.openai.com/blog/eval-skills)，未复制执行器；`item.completed` 可包含失败，轮次完成不等于业务核验通过 |
| [Promptfoo 0.126.0 快照](https://github.com/promptfoo/promptfoo/tree/1b7e4e54ae5a35587babf705000c2a034eb5091f)、[Temporal Python 1.36.1 快照](https://github.com/temporalio/sdk-python/tree/5c925a41b36b34d9ce32d03f1d1f07faa35b348a) | MIT | 分别参考[确定性断言](https://www.promptfoo.dev/docs/configuration/expected-outputs/deterministic/)与[Activity 幂等恢复](https://docs.temporal.io/activity-definition)，不新增运行时依赖或第二套任务引擎 |

本轮针对成功包装掩盖失败、旧证据/身份漂移、读取故障、回执保存前后崩溃、重复核验、CAS 冲突和产物恢复增加回归。代码与本地测试通过只证明这些路径已实现；生产成熟度仍须同一主线 SHA 的 CI/安全扫描、实际部署身份、真实业务对账及长时故障恢复证据，不据此给 Codex 或 XCMax 虚构评分。

## 独立 Agent 运行时

`XCAGI_AGENT_RUNTIME_CONFIG` 指向部署方维护的 JSON 文件。请求不能选择供应商、凭据或引擎。Codex 路径使用独立私有目录、短期模型/工具令牌和本地 MCP/Responses 代理；不继承个人 Codex 配置、ChatGPT 登录或额外插件。仅开启受控业务工具，禁止 shell、文件修改、托管搜索及默认 OpenAI 回落。管理员强制策略仍然生效。该路径不改变已有开发超级员工的 Codex CLI 调度。

配置示例（路径和容量必须替换成实际部署值，示例不构成验收）：

```json
{
  "engine": "codex",
  "surfaces": ["chat", "employee"],
  "runtime_root": "/var/lib/xcmax/agent-runtime",
  "qualification_file": "/etc/xcmax/runtime-qualification.json",
  "turn_timeout_seconds": 300,
  "route": {
    "base_url": "https://your-enterprise-gateway.example/v1",
    "model": "your-verified-model",
    "provider_id": "enterprise-gateway",
    "upstream_vendor": "your-non-openai-provider",
    "api_key_env": "XCMAX_RUNTIME_GATEWAY_KEY",
    "context_window": 32768,
    "max_output_tokens": 4096,
    "max_model_calls": 24
  }
}
```

仅支持网关真实提供的 Responses 多轮工具协议，不自行将 Chat Completions 拼装成 Responses。企业现有网关必须实际暴露该协议；平台聊天接口健康不代表已兼容。独立配置拒绝 OpenAI/ChatGPT/Azure OpenAI 地址和 OpenAI 上游声明，禁止重定向和通过 `previous_response_id` 借用其他任务的上游会话。任意代理域名本身不能证明上游独立，必须核对网关路由记录和网络隔离证据。

启用凭据采用 `xcmax.runtime-qualification.v1`，必须匹配 `ModelRoute.identity`、`codex_version=0.171.0`、`model_kind=real`，并带实际 `evidence_refs`。`checks` 中 `responses_stream`、`multi_turn_tools`、`openai_network_denied`、`business_receipt_verified` 均需真实 PASS。缺凭据、模型/容量/版本变化、合成模型或缺证据均拒绝启动；不能手填 PASS 代替验收。未配置时继续 Native，已启动 Codex 的任务出错不改走 Native。

所有模型请求先经过现有调用准入和用量账本预留额度，再按真实 usage 结算并释放余量；断流或用量未知保留待核对。工具调用创建受控子任务，权限、审批与冻结参数保持原语义。等待审批/补充信息和进程重启均保留原任务；取消先撤销运行授权，已发生的业务效果仍需回读。完成一个工具动作仅表示该动作有回执；完整业务目标必须有服务端冻结的目标契约及全部证据，模型轮次结束不代表业务完成。

预算由根任务统一累计模型和子任务费用，未结算调用继续占用预留额度；`turn_timeout_seconds` 是同一任务跨轮累计的活跃运行时间（1–3570 秒），审批等待不计入。聊天历史保存原任务续跑指针，审批卡只指向实际冻结的子任务；Codex 子任务不能经普通重试入口绕开父任务预算。当前业务完成契约仅接受宿主传入的一项完整规范工作流（`expected_operations`）；任意自然语言多目标、动态多动作尚不能证明整体覆盖，只报告已核验动作并保留待核对，不能据此将全部员工任务切换到新引擎。

验证分层：固定 SDK + 本地协议替身测试只证明接口/资源/隔离契约；SQL/LangGraph 回归证明权限、幂等与账本状态；真实非 OpenAI 模型、多轮工具与禁止 OpenAI 出网测试证明独立路径；Windows/macOS/Linux 安装与业务回归分别记录。没有客户原件时，ELT 原件到最终 Excel 的验收仍为 BLOCKED。发布不得用合成测试替代任何真实验收，也不得提前切换生产默认引擎。

<a id="version-policy"></a>

## 版本与发布约定

产品版本与工具链映射以 [VERSION.md](VERSION.md) 为准；仓根 [GitHub workflows](../.github/workflows/) 是执行入口，生成的子树副本不独立调度。发布流程见 [CI_SSOT](../docs/CI_SSOT.md)。

产品修复通过审查和必需检查后合入 `main`。交付包须来自明确的主线 SHA；包内身份、运行后台与业务验收记录必须一致。分支测试、demo 和历史包不证明新候选通过。

| 验收 | 入口 |
|---|---|
| 同版双端发布原则 | [desktop_platform_parity_ssot](docs/desktop_platform_parity_ssot.md) |
| Windows 包、签名与实机门禁 | [WINDOWS_RELEASE_SSOT](docs/WINDOWS_RELEASE_SSOT.md) |
| Mac 双架构、签名公证与实机门禁 | [MACOS_RELEASE_SSOT](docs/MACOS_RELEASE_SSOT.md) |
| 客服工单与客户确认 | [CUSTOMER_TICKET_BUS_SSOT](docs/architecture/CUSTOMER_TICKET_BUS_SSOT.md) |

正式下载指针和 stable 更新通道只在既有发布门禁及真实客户闭环通过后推进。历史变更保留在 CHANGELOG，已外置文档的恢复位置见 [ARCHIVE_POINTER](../ARCHIVE_POINTER.md)。

## 🧠 Neuro-DDD 与代码落点（必读）

分层和运行入口见 [ARCHITECTURE](docs/ARCHITECTURE.md)、[TECH_STACK](docs/TECH_STACK.md) 与 [XCAGI 子树说明](XCAGI/README.md)。应用用例在 `app/application/`，业务规则在 `app/domain/`，数据库及外部能力在 `app/infrastructure/`；HTTP 路由经应用层调用。

桌面壳在 `desktop/`，共享前端在 `frontend/`。Mod 的编辑源、镜像及发布约束见作者指南；不要维护客户分叉宿主或重复编辑镜像。真实业务数据、密钥与大体积私有资源不提交源码。

## 参与开发

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX/FHD
```

依赖安装、启动和最小验证按快速开始与 [贡献指南](.github/CONTRIBUTING.md) 执行。修改前检查工作区及历史主线提交，保留其他人的改动；本地定向测试不能替代发布级实机验收。

## 对话上下文与技能的来源

记忆与检索优先复用以下固定组件。个人记忆表单参考 [Hermes Agent v0.23.2 的写入策略](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/user-guide/features/memory.md#controlling-memory-writes)（MIT），用户主动保存时复用 MemoryV2 的候选和确认接口。记忆写入遵循现有权限和来源校验。

| 能力 | 来源与版本 | 产品适配 |
|---|---|---|
| 长期记忆抽取、向量存储 | [Mem0](https://github.com/mem0ai/mem0) `mem0ai==2.2.1`，Apache-2.0 | 复用官方 additive extraction 和 SDK。本人明确陈述的个人记忆从已授权对话自动生效，企业及跨空间候选保留审核。写入体验参考 [Hermes Agent v0.23.2](https://github.com/NousResearch/hermes-agent/blob/v0.23.2/website/docs/user-guide/features/memory.md#controlling-memory-writes)（MIT）。召回按来源 ID 和版本回查 MemoryV2。 |
| 结构化候选、历史预算 | [LangChain Core](https://github.com/langchain-ai/langchain) `1.5.3`，MIT | 复用 PydanticOutputParser 与 trim_messages；移除规则自动确认为事实和不完整摘录摘要，完整消息按预算保留并报告实际丢弃范围。 |
| 关键词召回 | [BM25S](https://github.com/xhluca/bm25s) `0.3.16`，MIT | FHD 与 MODstore 共用成熟 BM25 计算；完整授权语料的关键词候选独立于 dense 候选，随后 RRF 融合。 |
| 多进程历史写入 | [filelock](https://github.com/tox-dev/py-filelock) `4.2.4`，MIT | 共享本地目录中的会话和轮次文件锁，保护跨进程读改写及执行归属；不提供跨节点锁或业务 ExactlyOnce。 |

用户业务记忆按 tenant/user/Mod 隔离，企业记忆按 tenant/Mod 隔离；跨企业复用仅接受显式确认的本人 `global_preference`。旧裸账号、缺少来源版本的索引和原始聊天仍保留供审计，但不自动转为可信事实。员工任务历史独立保留真实运行来源和成功/失败状态，不标记为已核实业务事实。撤销/更正先持久化权威状态，投影故障返回 `retry_required`，过期副本立即失去召回资格；后续召回按退避重放已生效记录和撤销记录。未配置模型时，只处理现有回退能识别的明确陈述；模型明确返回空结果时不使用规则补写。

`EmbeddingService` 为 mode/model/endpoint/revision 生成不含密钥的指纹。数据集指纹变化即重建，即使维度相同；Mem0 使用新指纹集合并从当前已确认记录重放。供应方更新同名模型权重时设置新的 `FHD_EMBEDDING_MODEL_REVISION` 并重启，该值只标识索引版本。自定义 embedder 应暴露 `embedding_fingerprint`，否则只能检查维度。hash 模式仍报告非语义；小语料回归和关系查询测试不代表真实模型、生产 pgvector 或大规模延迟验收。

上下文能力优先来自当前账号、凭据和实际选中路由的 `model_capabilities`，沿原模型目录与 `resolve-chat-default` 传至桌面；网关别名仍用于原计费路由，不替换为底层模型。总上下文、最大输入、最大输出分别计量；只预留一次本次输出、外置工具 Schema 和安全余量，真实容量之外不再固定折半或默认截为 32K。未知容量保留有来源的保守默认值；固定必需输入无法容纳时返回配置来源与分项预算，不截掉工具约束、当前输入或假报成功。`config/model_context_windows.json` 是离线兼容目录，继续保留 [LiteLLM 固定来源](https://github.com/BerriAI/litellm/blob/736b05716593347fa51b92afa9526a2397af312c/model_prices_and_context_window.json)（MIT）和 [MiMo 官方规格](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)。

| 本次复用边界 | 固定来源与许可 | 运行位置 |
|---|---|---|
| 直接复用 | [LiteLLM](https://github.com/BerriAI/litellm) `1.109.3`，MIT | MODstore 原 Router、`get_model_info`/能力目录及部署 `model_info`；同凭据读取网关 `/model/info`，别名多部署采用共同已知的较小限制。 |
| 适配复用 | [OpenHands Condenser](https://github.com/OpenHands/software-agent-sdk/tree/885242b563b1d2695d6c7b3d4bfe642f1c8838a3/openhands-sdk/openhands/sdk/context)，MIT | `app/infrastructure/llm/_vendor/openhands_condenser` 保留安全消息边界和 Token 前缀搜索组件、许可证及来源清单；将 SDK 事件适配为现有消息，摘要继续使用原 LangChain provider/计量接口。SDK 要求 Python 3.12，宿主支持 3.11，因此只移植所需组件。 |
| 参考移植 | [Codex 上下文压缩](https://github.com/openai/codex/blob/1145028ae47e8119955323d38ce34122d418f951/codex-rs/core/src/compact.rs)，Apache-2.0 | 参考完整请求硬预算、独立摘要请求、压后复算及失败保留原文；保留原 AgentRun、审批、LangGraph 检查点和业务记忆。 |

文字与图片按本次操作选路，预算、摘要与最终请求共用同一份账号路由快照；兼容 OpenAI SDK 请求作用域，换号或改绑客户端后拒绝沿用旧预算。规划器与普通对话的系统默认输出适配已选模型上限，调用者显式值仍接受严格检查；修复与目标审查入口保留未指定值直到实际选路。公开能力只含数值和模型身份，内部凭据快照不进入 HTTP 负载或预算日志。摘要是模型输入的派生视图，不能更新业务执行事实。首次系统与工具本身超限不触发历史摘要；压缩保留完整最新轮与工具调用/回执组。已有调用、审批与恢复仍走原入口。能力缺失、真实供应商回复、生产部署及桌面实机恢复需分别取得回执。

对话响应参照 [OpenHands 响应分流](https://github.com/OpenHands/software-agent-sdk/blob/3a893a1b26de7ec02cc0dd2427906eea6aea3fc7/openhands-sdk/openhands/sdk/agent/response_dispatch.py)（MIT），复用现有 LangChain/Pydantic 解析器与 `conversation.reply`：关键词不触发索引或强制索要文件；原生工具协议的可见文本可进入普通回复，混合或未知工具调用仍须校验。普通答复使用只检查答题、证据和澄清必要性的窄格式核验，业务图保持完整目标覆盖审核。两者读取候选生成时相同的授权历史与条件快照，经原 Condenser 和模型网关控制预算；摘要不保证事实无损，需要精确原文时仍调用原会话读取能力。

澄清、预演与审批等待复用原 typed `turn_kind`、LangGraph 检查点和 SQL 任务：澄清回答更新原任务，插问交当前轮规划且保留原等待状态；审批仍走原确认与批准流程，模型分类不产生授权。合法不明确输入与模型错误分别处理。轮次/动作绑定参照 [Codex 公开协议](https://github.com/openai/codex/tree/a0436d69ffd9a6d943d9b56175ba2968c5e698af/codex-rs/protocol)（Apache-2.0）；产品只适配既有 run、step、会话与批准范围，不再维护第二套任务状态。传输错误沿用 `MarketModelError`，规划、澄清抽取、修复与核验共用现有 `InvocationBudget`，`XCAGI_PLANNER_TIMEOUT_SECONDS` 默认 90 秒；达到期限结束模型阶段，不重放业务写入。上述接线属于本产品的任务语义与证据约束，通用组件不自动判断所有话题切换或业务完成。

仓库技能以 [OpenHands Software Agent SDK 的 `SKILL.md` 解析格式](https://github.com/OpenHands/software-agent-sdk/blob/ae4fd87f9b86a9362943d29771192816877646a9/openhands-sdk/openhands/sdk/skills/skill.py)（参考提交 `ae4fd87f9b86a9362943d29771192816877646a9`，[MIT](https://github.com/OpenHands/software-agent-sdk/blob/ae4fd87f9b86a9362943d29771192816877646a9/LICENSE)）为协议参考；使用锁定的 [PyYAML 6.0.3](https://github.com/yaml/pyyaml/tree/6.0.3)（MIT）解析元数据。宿主仅适配 `name`、`description`、`triggers` 和 Markdown 正文，不引入另一套 Agent 运行时；仅命中的技能参与本轮规划，受服务端开关、路径和输入总量限制，不能用客户端 `active_skills` 冒充技能规则。此适配不宣称支持上游完整技能发现、资源调用或插件协议。

## 许可证与安全

### 工具调用、权限与重试

公共工具和技能 API、Planner bridge、已登记 ERP 能力统一经过原 `AgentOrchestrator` / `AgentToolExecutor`，沿用风险动作目录、会话 RBAC、审批事务、LangGraph 检查点和工具回执。员工子工具从宿主显式接收可信身份；模型参数不能注入授权。MODstore 是独立服务，继续使用原员工执行器，通过既有结果契约遵守同样的未知结果禁重放规则。AIOPEN 的 API Key 配额、屏幕身份与主进程会话仍由原授权入口和 ToolDispatcher 执行；通用工具入口没有该 adapter，明确返回 not_started，不能因为目录里有 ToolSpec 就宣称可执行。

| 对应缺口 | 成熟来源及固定版本 | 本仓复用方式 |
|---|---|---|
| 路由、审批与扩大权限后的重试边界 | [OpenAI Codex](https://github.com/openai/codex/tree/1145028ae47e8119955323d38ce34122d418f951)，参考提交 `1145028ae47e8119955323d38ce34122d418f951`，Apache-2.0 | 对照上游 router / registry / orchestrator / approvals；本仓只补可信上下文、执行契约摘要和原审批回执的逐次核验，不复制 Rust 执行器或另建权限服务。 |
| 持久暂停与原任务恢复 | 已吸收 LangGraph 1.2.10、checkpoint 4.3.0、SQLite 3.1.2、Postgres 3.1.1+xcagi.1，MIT | 复用原图与检查点；审批、修复、恢复仍保留同一 run/step、计费与轨迹。[上游故障语义](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)不承诺外部副作用恰好一次。 |
| 安全传输重试与共享截止时间 | [Tenacity](https://github.com/jd/tenacity/tree/aac059c906170ee7b6ce1aa086a226f3aded5c99)，运行时 `uv.lock` 固定 9.1.4，Apache-2.0 | 替换 MCP 手写重连；最多两次明确安全的传输尝试，共享绝对截止、原参数和 ContextVar，不在业务写外再包自动重试。 |
| MCP 输入输出与只读提示信任 | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/77001c96f9507be0f4d009b83210a384a5e08bda)，本仓锁定 2.3.0，MIT | 继续用原 SDK / adapter；只有本地配置允许且远端声明只读的工具才进入安全读重试，远端注解不能授予写权限。 |
| 派发前持久化及并发请求互斥 | 现有 [filelock 4.2.4](https://github.com/tox-dev/filelock/tree/22f0776dd499690d71d2e6d2f95e1662a76db75d)（MIT）、SQLAlchemy 2.0.51（MIT，`uv.lock`）及 Python `os.replace` / `fsync` | 复用已有 outbox、文件锁、SQL 事务和声明账本；保留请求 ID、任务 ID、原发送范围及部分成功回执。 |

已核对的代码断点与处理位置如下；这是实现边界，不是线上验收或完整安全证明。

| 断点 | 处理后的行为 | 原组件 / 回归入口 |
|---|---|---|
| HTTP 未登记动作落入旧执行器，bridge 直接调 Planner | 先核对登录，再由同一动作目录建原生执行计划；未登记动作未执行 | `fastapi_routes/tools_execute.py`、`test_unified_tool_entry.py` |
| 插件异常后继续找其他实现；TypeError 后丢上下文再调用 | 调用前检查签名；选中的实现只调用一次，执行后异常保留未知结果 | `planner_native_tools.py`、`workflow_tools/dispatch.py` |
| 业务库 / 模板别名绕过原审批运行；旧 CRUD 用模型 confirm 代替授权 | 业务库和模板别名进入原能力运行；无 ToolSpec 的旧模型别名拒绝执行，原显式业务 API 保留 | `workflow_business_db.py`、`workflow_tools/adapters.py` |
| 工具生命周期只做参数校验就报告执行成功 | 无实际 adapter 的定义只返回 validated / not_started，不能作为业务完成证据 | `agent_tool_lifecycle.py`、原生命周期验收 |
| 员工调用丢失可信身份、显式白名单越过只读配置、宽泛路径匹配越出工作区 | 宿主上下文逐层传递；风险目录动态读取；只读和工作区边界持续核对 | `employee_runtime`、原 tool_scope / workspace_guard / agent_loop 回归 |
| 审批后租户、actor、Mod、员工权限或工具安全契约发生变化 | 审批摘要绑定执行范围及 ToolSpec；排队恢复和每次尝试重新核对，变化后重新审批 | `approval_grant.py`、`approval_transaction.py`、`test_approval_scope_binding.py` |
| 换登录会话只更新 Mod 证明，旧 actor 会话仍过期 | 同身份续期同时核验及更新两份服务端证明；身份、权限范围改变不能续用审批 | `session_renewal.py`、真实双会话路由回归 |
| 可信 mutation_policy / 批量预演摘要被清洗丢失，后台批量删除落入默认租户 | 仅从可信宿主保留策略与原预演摘要；受控批量动作恢复原租户，客户端同名字段继续剥离 | 原 guarded_batch_delete、真实零删除 / 批准删除回归 |
| 同键重放跨执行主体、Mod 或已撤销权限 | 旧键继续保留，授权范围不匹配拒绝读取旧回执；不换键重发旧未知写入 | 原工具声明、运行复用与统一任务恢复 |
| 已派发写返回 429/5xx、普通 false 或合法 schema 假成功后释放声明 | 执行可信 I/O 状态优先于 handler 自述；未知结果和账本一致，写声明不释放 | `tool_executor.py`、`tool_execution_deadline.py`、SQLite 实际副作用回归 |
| 修复入口遗漏未知状态、无限放大次数、ToolSpec 重试配置未消费 | 复用原结果分类器；显式修复与模型修复共用最多四次修复，保留原审计计费 | `run_repair.py`、`test_tool_idempotency.py` |
| MCP 每次重连重置超时、线程丢上下文、请求参数被修改 | 一份绝对预算；复制可信上下文及原参数；权限和配置错误不重试，写调用仅一次 | `infrastructure/mcp/client.py`、`test_mcp_tools.py` |
| Codex / 超级员工丢 ACK 后切换 webhook / CLI、多设备部分成功后整单重发 | 先保存发送意图；同请求只恢复原回执或只读查询已知任务，未知和部分成功不自动重发；Para 首次 ACK 丢失且无任务 ID 时明确需要人工核对 | `super_employee/dispatch.py`、`test_super_employee_dispatch_recovery.py` |
| 消息历史回填及 MODstore fallback / maintenance 消费端忽略 unknown | 沿用结果契约，保留原 task_id，未知、已接收及明确不可重试结果不再触发另一执行通道 | `super_employee/messages.py`、MODstore `employee_executor_policies.py` |
| AIOPEN 审计脱敏时丢掉未知结果标记 | 脱敏继续保留类型正确的 outcome、retryable 与核对状态，业务私密数据不进入轨迹 | `aiopen_route_support.py`、原 trace privacy 回归 |
| 红线变更执行失败仍发布 approved / rejected 成功事件 | 只在原变更事务返回真实成功后记录及发布对应事件 | MODstore `redline_approval_gate.py`、`test_autonomy_decision_audit.py` |
| 脚本代理及快速运行在超时、未知 SDK 或员工动作后再次执行；模型回答或摘要文件代替真实成功 | V1 / V2 / Vibe / 快速入口共用原沙箱结果核验与禁止重放分类；最终代码绑定真实执行与验收，消费端独立复核，诊断文件不能改写超时和失败；员工业务回执仅保留必要控制字段 | 原 `script_agent`、`workbench_script_agent_job.py`、`workbench_script_job.py` 与真实沙箱 / RPC 副作用回归 |

`ToolSpec.retry.max_attempts` 的正整数是同一步总调用上限，`1` 表示不重试；历史默认 `0` 保留原修复策略。它只能收窄次数，不能覆盖权限、未知结果和截止时间。模型请求重试、只读传输重试与业务步骤重放保持各自的原计数，不把三者套成嵌套通用重试。只读元数据仅在核实实际 handler 后加入原风险目录；低风险、idempotent、名字包含 query 均不能代替无副作用证明，已审计查询的空结果仍是有效完成。

MODstore `VIBE_AGENT_V2` 保持默认关闭。脚本循环沿用原 AgentLoop 和 judge，循环与快速入口共用 sandbox runner 和结果分类器；快速入口仍按原静态检查及沙箱产物契约验收，纯文件脚本可安全修复。`employee_run` 的 RPC 日志与业务回执分别核对，已接收、运行中或无法核对的业务结果保持未验证；已有员工动作不能因后续脚本验收失败而整段自动重放。这里没有增加任意供应商的独立回读适配器。

仍有明确边界：通用工具声明默认使用本机 SQLite，已有同机多进程与崩溃恢复测试，但不能代替多主机共享的事务账本；现有 SQL BusinessActionLedger 尚未覆盖所有外部工具。没有供应商独立查单接口的外部写保持待核对，不能由模型或成功布尔值补结。Para 首次创建响应丢失且没有任务 ID 时，当前未接通按请求键查询的服务端契约，须人工核对，不能以标题或提示词相似度匹配任务；已核对 [Para 源码 2d9a15d](https://github.com/42433422/devfleet-private/tree/2d9a15d6b249ee3eab086a68e4f10c0e803adb19) 的任务路由、存储和表结构，没有请求键持久化或精确查询，运行实例版本仍须现场核验。尚未登记的旧别名和只有 Schema 的自定义工具须接入真实 adapter / ToolSpec 后才能执行；其他旧工具的只读元数据仍需逐项核实。超级员工服务沿用生产调用方的逐请求实例，文件锁保证同 user/request 的存储互斥，不承诺同一可变 service 实例跨身份并发使用。真实 PostgreSQL、多设备、操作系统沙箱和部署后的同 SHA 验证需对应环境证据；本地回归不能替代这些验收。这里复用 Codex 的授权边界设计，不声称已实现 Codex 全部沙箱、插件协议或任意供应商的恰好一次副作用。

多轮澄清复用 [LangChain Core 1.5.3](https://github.com/langchain-ai/langchain/tree/01d8481ae3d457ec3751cbb0331ea3a4b720fa90/libs/core)（MIT）：`trim_messages` 保留有序会话窗口，`PydanticOutputParser` 解析字段与候选对象回答；暂停与续跑沿用已吸收的 LangGraph 1.2.10。完整业务计划也复用其 `convert_to_openai_tool` 与 `PydanticOutputParser`，由 [Pydantic](https://github.com/pydantic/pydantic)（MIT，服务端锁定 2.13.5）生成同一份原生调用/JSON Schema；一次提交含全部 `depends_on` 的图，替代逐个原生动作手写适配。嵌套必填字段复用 [python-jsonschema](https://github.com/python-jsonschema/jsonschema) 4.26.0 与 [referencing](https://github.com/python-jsonschema/referencing) 0.37.0（均为 MIT），规划与澄清续跑共用工具契约和本地 Schema 引用解析；服务端 tarball 复用 `ops/deploy/requirements-langgraph-runtime.txt` 清单，通过已有运行时 bootstrap 固定安装两者，`FHD_SKIP_PIP=1` 时仍执行。已停用的直接导入工具由同一服务端规则在规划、执行与恢复前拒绝，导入沿用 ELT 预演与执行。产品侧仅绑定原话、节点、权限和会话；独立模型调用核对目标覆盖、否定与顺序，失败最多重新规划一次，仍失败则不执行。该语义核对不是正确性证明，真实模型准确率由评测报告另行记录。版本固定在依赖清单，不另建对话或执行引擎。

会话连续性复用 [LangChain 1.3.14 SummarizationMiddleware](https://github.com/langchain-ai/langchain/tree/01d8481ae3d457ec3751cbb0331ea3a4b720fa90/libs/langchain_v1)（MIT）及上述 Core 1.5.3，压缩入口同时覆盖普通/流式规划，预留输出和工具 schema，保存完整原文的已覆盖游标；摘要失败不伪造覆盖。跨进程文件互斥使用 [filelock 4.2.4](https://github.com/tox-dev/filelock/tree/4.2.4)（MIT，统一跨进程锁依赖版本）。SQLAlchemy 事务管理会话 revision、删除标记和整轮回执，JSON 只作为可重建投影；历史通过授权游标分页读取，保存失败仅重试原回执。

任务恢复使用 [LangGraph 原生检查点](https://docs.langchain.com/oss/python/langgraph/checkpointers)（核心 1.2.10、checkpoint 4.3.0、SQLite 3.1.2、Postgres 3.1.1+xcagi.1，MIT，源码与许可见 `packages/xcagi_langgraph_*`）。安全步骤在原 run 内恢复。独立规划澄清复用 AgentRun、WorkflowPlanStore 和运行快照 CAS 保存原目标、问题与答复，只有尚未执行业务的单一提问图可以重新规划，并再次经过目标、风险与审批校验；参数澄清和已有业务图继续在原图恢复。这里的执行元数据不提供跨进程租约，持久队列使用现有条件更新和租约归属校验。知识答复沿用 DatasetRag 的答案、证据和查询范围。聊天批量导入按 ELT 文件回执核对已写入项，将剩余原附件绑定到同一任务的下一次审批执行，继续用原有 StateGraph 调度。未知写结果保留待核对。

统一执行入口与任务状态继续复用上述 LangGraph 和现有 task/run/step、审批、轮次回执组件，新增部分限于本产品的授权范围、原子准入和状态投影；不增加第二套调度服务。复用与对照来源如下，具体缺口和未完成的验收见 [流程 SSOT §2.2](docs/architecture/PROCESS_FLOW_SSOT.md#22-统一执行入口与任务状态实现与证据边界)。

| 缺口对应能力 | 固定来源与许可 | 本次使用方式 |
|---|---|---|
| 持久执行、原步骤恢复与审批中断 | 上述 LangGraph 1.2.10 / checkpoint 4.3.0，MIT | 使用仓库内已吸收实现，接通原 run；不把检查点解释为外部写入恰好一次。 |
| 并发准入、版本比较和原子回滚 | [SQLAlchemy 2.0.51](https://github.com/sqlalchemy/sqlalchemy)，MIT，`uv.lock` | 复用事务、唯一键和条件更新；owner/tenant/Mod 与原 task 身份是产品侧必须保留的适配。 |
| thread/turn/item 状态和只读恢复语义 | [OpenAI Codex](https://github.com/openai/codex/tree/1145028ae47e8119955323d38ce34122d418f951)，Apache-2.0，固定提交 `1145028ae47e8119955323d38ce34122d418f951` | 对照 SDK 事件及 app-server 原 thread/turn 恢复与审批测试；本次没有引入整个 Codex runtime，item 结束不等于 turn 成功。 |
| 外部副作用重试与未知结果边界 | [Temporal Python SDK 1.36.1](https://github.com/temporalio/sdk-python/tree/1.36.1)，MIT | 参考持久活动和幂等约束，继续使用现有执行队列；不引入 Temporal 服务或声称复用了其完整服务端能力。 |
| Web 流式解析和原回执展示 | [eventsource-parser 4.1.3](https://github.com/rexxars/eventsource-parser)，MIT，`frontend/package-lock.json` | 继续使用现有 SSE 组件；修正消费侧的受理、等待、未知和完成判断。 |
| 手机离线队列和请求身份恢复 | [Drift 2.35.4](https://github.com/simolus3/drift)，MIT，`mobile-flutter-poc/pubspec.lock` | 复用现有 SQLite/outbox 及迁移机制保存原 turn；已发送任务只能读取原回执。 |

通用开源运行时不能替本仓决定授权主体、审批计划指纹、父子任务归属或业务写回凭证，因此这些校验保留在现有接缝中。缺少原回执时保留 `unknown`；本地测试不代表真实模型、移动端构建、生产 PostgreSQL 或已部署产品验收。

企业认知继续复用上述 SQLAlchemy 2.0.51（MIT）的事务、提交事件、唯一键和条件更新，Pydantic 2.13.5（MIT）的共享接口契约，以及 LangGraph 1.2.10（MIT）的原任务审批执行；版本以既有锁文件为准，没有新增通用状态机、消息总线或记忆数据库。NeuroBus、strategic plan、goal coverage、Business Harness 与 MemoryV2 都从现有入口接入。产品适配仅处理原业务 ID/权威来源、tenant/actor/Mod 权限、投影过期、目标与动作绑定和证据引用；通用组件无法决定这些本产品业务语义，因此保留这些适配。接口、实体清单与验收边界见[流程 SSOT §2.3](docs/architecture/PROCESS_FLOW_SSOT.md#23-企业认知权威状态--经营目标--原任务执行--指标证据)。
普通 Conversation API 与规划器共享授权 SQL 历史，当前输入按 `turn_id` 排除，不重复混入内存副本；缓存读取、每批摘要与最终模型调用前重核会话 revision，拒绝已撤回的旧快照。澄清保留原任务中的完整已接受问答，将其作为必须完整保留的当前规划输入；窗口不足则停止本轮并保留原等待任务，不截掉早期范围，也不删除业务工具。行为对照 [Codex `1145028` 的 retained answers](https://github.com/openai/codex/blob/1145028ae47e8119955323d38ce34122d418f951/codex-rs/core/src/tools/handlers/request_user_input.rs)（Apache-2.0，其 Guardian 功能启用时独立持久化答案）；未移植 Rust 运行时。规划目录只省略与完整 JSON Schema `required` 完全相同的重复说明，保留本地引用、条件、嵌套约束及全部动作。

任务恢复使用 [LangGraph 原生检查点](https://docs.langchain.com/oss/python/langgraph/checkpointers)（核心 1.2.10、checkpoint 4.3.0、SQLite 3.1.2、Postgres 3.1.1+xcagi.1，MIT，源码与许可见 `packages/xcagi_langgraph_*`）。安全步骤在原 run 内恢复。独立规划澄清复用 AgentRun、WorkflowPlanStore 和执行租约保存原目标、问题与答复，只有尚未执行业务的单一提问图可以重新规划，并再次经过目标、风险与审批校验；参数澄清和已有业务图继续在原图恢复。知识答复沿用 DatasetRag 的答案、证据和查询范围。聊天批量导入按 ELT 文件回执核对已写入项，将剩余原附件绑定到同一任务的下一次审批执行，继续用原有 StateGraph 调度。未知写结果保留待核对。

企业认知继续复用上述 SQLAlchemy 2.0.51（MIT）的事务、提交事件、唯一键和条件更新，Pydantic 2.13.5（MIT）的共享接口契约，以及 LangGraph 1.2.10（MIT）的原任务审批执行；版本以既有锁文件为准，没有新增通用状态机、消息总线或记忆数据库。NeuroBus、strategic plan、goal coverage、Business Harness 与 MemoryV2 都从现有入口接入。产品适配仅处理原业务 ID/权威来源、tenant/actor/Mod 权限、投影过期、目标与动作绑定和证据引用；通用组件无法决定这些本产品业务语义，因此保留这些适配。接口、实体清单与验收边界见[流程 SSOT §2.3](docs/architecture/PROCESS_FLOW_SSOT.md#23-企业认知权威状态--经营目标--原任务执行--指标证据)。

计划投影缺失或滞后时，从当前授权 owner、tenant、mod、session、revision 下的持久等待任务恢复，查询状态在 SQL 层筛选；多个等待任务须绑定具体任务卡，读失败或计划损坏不会转成新任务，重启不延长澄清时限。暂停恢复与重试共用持久化 `SessionBook.effects` 核对：只有真实成功步骤回执能结清未确认写入；队列状态和恢复账本仅在执行租约 CAS 成功后共同提交。队列已停止而业务记录尚未同步时，任务与运行 API/SSE 快照统一投影为待核对或失败，已完成业务回执保持不变。测试覆盖本地 SQLite 崩溃恢复及确定性长会话，真实模型语义保真、PostgreSQL 多 worker、Windows/macOS 与长时运行另行验收，不由源码或模拟模型测试推定。

对话撤回参考 [Temporal Saga v1.40.0](https://github.com/temporalio/sdk-java/blob/v1.40.0/temporal-sdk/src/main/java/io/temporal/workflow/Saga.java)（[Apache-2.0](https://github.com/temporalio/sdk-java/blob/v1.40.0/LICENSE)），复用现有 ELT 行级回滚和回执。服务端先核对写入归属及补偿范围，按倒序撤销，收齐回执后再按会话版本截断历史。

企业专属客服复用 [APScheduler 3.11.3](https://github.com/agronholm/apscheduler/tree/3.11.3)（MIT，版本见 `uv.lock`）触发 IM 待处理消息恢复，沿用现有数据库记录和 MODstore 账号授权。产品知识复用 BM25S 0.3.16（MIT）与现有引用组件，内置公开指南。扩展资料使用专用只读密钥 `XCAGI_ENTERPRISE_CS_KB_KEY` 及公开元数据过滤。

主动提醒的外发适配复用 [Apprise 1.13.1](https://github.com/caronc/apprise/tree/v1.13.1)（BSD-2-Clause，确切版本见 `uv.lock` 的可选 `proactive-push` 依赖），记录与渠道结果复用 SQLite 事务及既有跨进程锁。当前交付仅为服务和 `scripts/ops/publish_proactive_event.py`：必须指定租户；本地事件记录不等于站内通知已送达，业务事件生产、站内 UI 与真实渠道验收尚未完成。已成功渠道不重复投递，失败渠道可重试；进程中断留下的未知投递结果需人工核对，不能宣称外发恰好一次。

[Apache-2.0](LICENSE)；商业约定见 [COMMERCIAL_LICENSE](COMMERCIAL_LICENSE.md) 与 [LICENSING](docs/guides/LICENSING.md)。安全反馈和配置规则见 [SECURITY](SECURITY.md)。
