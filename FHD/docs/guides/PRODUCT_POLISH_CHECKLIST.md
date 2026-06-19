# XCAGI 产品级打磨清单

状态日期：2026-06-19

这份清单用于把当前零散修复收敛成产品路径验收。后续不要按单个报错乱修，每个问题都必须归到下面的用户路径里，并用同一套验收标准关闭。

## 产品关系

| 端 | 用户理解 | 产品职责 | 不能再混淆的点 |
|---|---|---|---|
| 管理端 | 服务器后台 | 管理企业账号、员工编制、Mod、系统配置、运维状态 | 管理端不是客户客服，它是后台控制台 |
| 企业端/桌面端 | 电脑执行端 | 执行必须在电脑上跑的员工、文件、数据库、Codex、自动化任务 | 不是手机的附属端，和手机同级 |
| 手机端 | 移动控制端 | 查看消息、联系员工、派发任务、远程控制电脑执行端 | 不在局域网时必须走服务器中继 |
| 服务器中继 | 长期连接层 | 保存绑定关系、会话、任务队列、状态回写 | 不能把局域网直连当成唯一链路 |

核心产品叙事：用户在手机或管理端找到 AI 员工，像找同事一样发消息或派任务；需要电脑能力的任务由桌面端执行；需要多设备协作的任务由超级员工 Codex 统一调度。

## P0 路径一：登录和绑定稳定性

### 用户路径

1. 用户打开手机端。
2. 选择服务器后台或企业工作台登录。
3. 扫描管理端/桌面端二维码，或输入设备码绑定。
4. 同一局域网时走本地直连，不同网络时走服务器中继。
5. 重启手机端、重启桌面端、网络切换 5G/Wi-Fi 后，仍能看到账号、绑定设备、员工列表和消息。

### 当前风险

- 扫码显示成功，但后续接口仍然 401。
- 手机端拿到的是局域网地址，离开局域网后继续请求 `192.168.x.x` 导致超时。
- 绑定成功后仍显示“账号生态待同步”。
- 登录失败、绑定失败、推送未配置等错误以原始 HTTP/SDK 文案展示，产品质感差。
- 手机端闪退后没有可定位的崩溃路径。

### 验收标准

- 登录成功后，`/api/mobile/v1/*` 常规接口 0 个非预期 401/403。
- 绑定成功后，手机端本地至少持久化：`accountId`、`tenantId`、`deviceId`、`relayBaseUrl`、`localBaseUrl`、`sessionToken`、`pairedAt`。
- 手机端请求选择规则明确：优先可达局域网；不可达时自动切换服务器中继；不要在 5G 下死请求局域网 IP。
- 绑定二维码和设备码都可用，二维码过期时提示“二维码已过期，请刷新”，不是 HTTP 401。
- 登录页、扫码页、我的页和 AI 员工页使用同一份会话状态，不允许一个页面显示已登录，另一个页面 401。
- 推送 SDK 未配置时降级为“消息提醒未开启”，不能阻断员工同步和会话。
- 闪退必须能在本地日志或 Android logcat 中定位到页面、接口或序列化字段。

### 代码落点

- 后端：`app/fastapi_routes/mobile_api.py`
- 后端：`app/fastapi_routes/mobile_api_extensions.py`
- 后端：`app/services/mobile_relay_service.py`
- 后端：`app/services/mobile_relay_desktop_client.py`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/datastore/SessionStore.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/AuthInterceptor.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt`

### 必测证据

- 密码登录、扫码绑定、设备码绑定三条路径都要跑。
- 绑定后立刻请求员工列表、消息列表、个人页同步。
- 手机切 5G 后再次请求同一组接口，确认走服务器中继。
- 杀掉 App 重开后，账号和绑定关系仍存在。

## P0 路径二：员工同步真实一致

### 用户路径

1. 管理端进入员工编制图谱，看到本机编制员工、安装状态、可执行状态。
2. 管理端进入信息页，看到可联系的固定员工。
3. 手机端进入 AI 员工和消息列表，看到同一批可联系员工。
4. 用户点击任意员工，可以进入对话或派发任务。

### 当前风险

- 图谱展示的是编制员工，信息页展示的是另一套联系人，手机端又是第三套假数据。
- `mods/_employees` 未安装时，图谱有员工但实际不能执行，用户不知道差别。
- 员工身份、头像、联系方式、是否可运行、最近任务没有统一来源。
- 超级员工 Codex 没有稳定置顶。

### 员工身份契约

所有端都应消费同一份员工联系人模型：

```json
{
  "employee_id": "daily-orchestrator",
  "display_name": "每日编排员",
  "surface_name": "每日编排员",
  "department": "platform-core",
  "source": "planned | installed | builtin | codex",
  "installed": true,
  "runnable": true,
  "online": true,
  "pinned": false,
  "avatar_key": "daily",
  "contact_route": "/api/admin/employees/chat/daily-orchestrator",
  "mobile_contact_route": "/api/mobile/v1/employees/daily-orchestrator/messages",
  "capabilities": ["schedule", "repair", "report"],
  "last_task_status": "idle | running | failed | blocked"
}
```

### 验收标准

- 管理端信息页、手机端消息页、手机端 AI 员工页使用同一批 `employee_id`。
- 图谱可以展示未安装编制，但必须标清“编制中/未安装/不可执行”，不能假装在线。
- 信息页列表第一位固定为“超级员工-Codex”，后面是已安装或可联系员工，再后面是未安装编制员工。
- 小C助理、企业专属客服、超级员工 Codex 的关系明确：
  - 小C助理：移动端通用助手。
  - 企业专属客服：企业端/桌面端面向企业客户的客服。
  - 超级员工-Codex：跨设备协作开发员工，负责调度真实 Codex/MCP/电脑执行端。
  - 管理端信息页不重复塞“小C助理”，但要能看到员工通讯录。
- 员工列表刷新后，管理端和手机端数量、名称、在线状态一致。

### 代码落点

- 后端：`app/application/local_duty_graph_health.py`
- 后端：`app/fastapi_routes/im_routes.py`
- 后端：`app/fastapi_routes/mobile_api_extensions.py`
- 前端：`frontend/src/views/ImMessengerView.vue`
- 前端：`frontend/src/domain/yuangonDutyRoster.ts`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/model/ConversationItem.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt`

### 必测证据

- 同一个账号下，管理端信息页和手机端 AI 员工页截图对齐。
- 本机缺少员工包时，UI 明确显示“未安装”，并提供安装入口或说明。
- 后端返回员工列表的接口有单元测试覆盖 installed/runnable/source 三类状态。

## P1 路径三：信息页和手机端通讯录统一

### 用户路径

1. 管理员打开管理端“信息”。
2. 左侧看到固定员工列表和普通联系人。
3. 选择员工后，右侧显示员工身份、状态、最近任务、对话记录。
4. 手机端消息列表展示同一批员工，可以继续对话。

### 当前风险

- 管理端信息页像一个单独聊天 Demo，手机端像另一个产品。
- 管理端“信息”、手机端“消息”、手机端“AI 员工”边界不清。
- 员工可以展示但不能对话，或者能对话但调用的是假回复。

### 验收标准

- 管理端信息页是员工通讯录和对话工作台，不是装饰页。
- 手机端消息页显示最近会话，AI 员工页显示员工名录；两者点击后进入同一个聊天能力。
- 员工卡片必须展示：身份、部门、状态、最近任务、能否派工、联系入口。
- 发送消息后，管理端和手机端能看到同一条会话记录，至少保证同账号同设备绑定下可同步。
- 接口不可用时显示“正在通过中继重连/电脑端离线/员工未安装”，不显示原始 HTTP 错误。

### 代码落点

- 前端：`frontend/src/views/ImMessengerView.vue`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt`
- 后端：`app/application/im_app_service.py`
- 后端：`app/fastapi_routes/im_routes.py`

### 必测证据

- 管理端发给任意员工一条消息，手机端刷新后能看到。
- 手机端发给同一员工一条消息，管理端信息页能看到。
- 离线、未登录、员工不可执行三类状态都有可读文案。

## P1 路径四：超级员工 Codex 真调用链

### 用户路径

1. 用户在管理端或手机端选择“超级员工-Codex”。
2. 输入任务，例如“修复手机端 401 并打包 APK”。
3. 系统把任务派发到真实 Codex/MCP 多设备调度器。
4. Codex 以流式方式直接回复过程和结果。
5. 如果需要电脑执行端，本机或远程电脑接任务，完成后回写状态、日志、产物。

### 当前风险

- UI 上叫 Codex，但实际回复像调度器占位文案。
- 消息不流式，用户认为卡死。
- 只能排队，不能看到真实 Codex 执行、设备分派、日志和结果。
- 任务失败时缺少可恢复动作。

### 验收标准

- 用户看到的发言人只叫“Codex”，不暴露“调度器”中间层。
- 前端使用流式消息，至少包括：已接收、正在分派、执行中 token、完成/失败。
- 后端有真实调用边界：`CodexSuperEmployeeService -> relay/desktop client -> Codex/MCP runner -> event stream`。
- 任务状态必须能查询：`queued`、`assigned`、`running`、`blocked`、`completed`、`failed`。
- 失败时返回可执行原因，例如“电脑端离线”“MCP 未连接”“需要确认权限”“仓库未打开”。
- 手机端和管理端看到同一个 Codex 任务进度。

### 代码落点

- 后端：`app/application/codex_super_employee_service.py`
- 后端：`app/fastapi_routes/im_routes.py`
- 后端：`app/services/mobile_relay_service.py`
- 前端：`frontend/src/views/ImMessengerView.vue`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt`
- Android：`mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt`

### 必测证据

- 管理端发一条 Codex 任务，浏览器能看到流式增量。
- 手机端发一条 Codex 任务，桌面端收到并回写。
- 断开桌面端后再发任务，状态显示为等待电脑端，而不是假成功。
- 完成任务后，UI 能展示 commit、push、安装包路径或测试结果这类真实产物。

## P1 路径五：流程可视化解释每个员工

### 用户路径

1. 管理员打开“流程可视化”。
2. 看到每个员工在流程里的位置、职责、输入、输出、触发方式。
3. 点击员工，能跳到信息页对话，或跳到员工空间查看执行状态。
4. 如果员工未安装或不可执行，页面解释原因和下一步动作。

### 当前风险

- 页面看起来像流程图装饰，用户不知道每个员工是干什么的。
- “流程全景”和“流程可视化”边界混乱。
- 员工节点没有和通讯录、执行状态、安装状态打通。

### 验收标准

- 流程可视化不是六部门全景图；它要解释“员工如何参与工作流”。
- 每个员工节点至少展示：
  - 员工名
  - 所属部门
  - 负责环节
  - 输入
  - 输出
  - 触发方式
  - 依赖工具
  - 风险/审批要求
  - 当前安装/运行状态
  - 联系员工按钮
- 未安装员工要展示“安装本地员工包/从 Catalog 安装/仅查看编制”的下一步。
- 节点详情必须复用员工身份契约，不能手写另一份静态文案。

### 代码落点

- 前端：`frontend/src/utils/workflowEmployeeDocs.ts`
- 前端：`frontend/src/components/workflow/WorkflowEmployeeSelectPanel.vue`
- 前端：`frontend/src/components/workflow/EmployeeWorkspaceScene.vue`
- 前端：`frontend/src/router/index.ts`
- Mod：`mods/xcagi-workflow-visualization-bridge/frontend/views/WorkflowVisualizationView.vue`
- Admin runtime：`mods-admin-runtime/xcagi-workflow-visualization-bridge/frontend/views/WorkflowVisualizationView.vue`

### 必测证据

- 从流程可视化点一个员工，能进入信息页对应员工会话。
- 未安装员工和已安装员工视觉状态不同。
- 页面不再只靠大图表达；每个节点有可读说明和下一步动作。

## P2 路径六：产品质感和发布闭环

### 用户路径

1. 用户下载手机 APK 或桌面安装包。
2. 首次打开能稳定登录、绑定、同步。
3. 错误提示像产品，不像调试日志。
4. 每次发包都有可追溯版本、测试证据和回滚方式。

### 验收标准

- 登录页、扫码页、员工空状态、错误 toast 使用统一文案。
- 提示音默认克制，支持关闭；推送未配置不弹长英文错误。
- Android 打包产物路径、版本号、commit、服务端地址写入 release note。
- 发布前必须跑：
  - 后端移动接口 smoke。
  - 前端管理端 type-check/test。
  - Android assemble。
  - 手机端登录、扫码、员工列表、Codex 对话手测。

## 首轮实施顺序

1. 先修 P0 登录和绑定：解决 401/403、局域网地址误用、绑定后不同步、闪退。
2. 再修 P0 员工同步：建立统一员工联系人模型，管理端和手机端同源。
3. 再修 P1 信息页和通讯录：管理端信息页、手机消息页、AI 员工页统一。
4. 再修 P1 Codex：真实调用链、流式回复、任务状态和失败恢复。
5. 最后修 P1 流程可视化：从装饰图改成每个员工的流程说明和操作入口。

## 不接受的完成标准

- 只改页面名字，不打通数据。
- 只添加卡片，不提供真实联系人和对话入口。
- 只显示“设备绑定成功”，但员工列表、消息、个人页仍 401。
- 只把 Codex 任务放入队列，没有真实 Codex/MCP/电脑端执行回写。
- 只做流程图，不解释员工职责、输入、输出和状态。

