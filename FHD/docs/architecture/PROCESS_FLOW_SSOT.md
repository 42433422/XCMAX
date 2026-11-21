# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 与任何业务文档冲突时，以本文件为准。
> 最后更新：2026-11-21（本次核对执行入口与回执，§2.2；新增企业认知候选契约，§2.3；其他业务域未重新验收） · 登记：`docs/SSOT_INDEX.md`（领域 `process-flow`）

---

## 1. 目的与范围

本文档定义 XCMAX（FHD 企业桌面 ERP + AI 员工平台）的**业务工作流程**与**对外交付流程**，作为 AGI 主导编排时的流程基线。目标是让每一段业务链路上升为可触发的 `WorkflowDefinition`，并使 AGI 能回答三个问题：

1. **观察**：某张单据/某个业务对象当前处于哪个环节？
2. **决策**：下一步有哪些合法动作、各自风险等级、是否需要人签核？
3. **执行**：动作由谁触发（LLM 编排 / 事件驱动 / 人工），落库何张单据？

范围：**业务域里程碑状态机 + 跨域编排链 + 自动化就绪度**。不覆盖覆盖率和 CI/CD（见 `../../docs/CI_SSOT.md`）。

## 2. 基础设施盘点（编排底座已就位）

| 组件 | 现状 | 代码位置 |
|------|------|---------|
| 工作流模型 | ✅ Definition / Run / RunStep 三表 + 状态机 | `../../app/db/models/workflow.py` |
| 审批流 | ✅ Flow / Node / Request / Record / Delegation（含委托） | `../../app/db/models/approval.py` |
| 领域事件总线 | ✅ NeuroBus 域事件（ocr.completed 等） | `../../app/neuro_bus/bus.py` |
| 风险门禁 | ✅ 节点级 risk（low / medium） | `../../app/application/workflow/risk_gate.py` |
| 单据状态机 | ⚠️ 各域自建，未统一（见 §4） | 各 `app/db/models/*.py` |

**结论**：编排引擎已就位，但尚无内置 WorkflowDefinition；发票→入库→审批→月报 由 NeuroBus 域处理器直接编排（`../../app/neuro_bus/domains/inventory_domain_handlers.py`、`finance_domain_handlers.py`，月报由 `../../app/application/monthly_report_scheduler.py` 触发）。

### 2.1 智能对话与业务工作流的唯一执行链

在线聊天流式、非流式及语音命令入口共用 `AIChatApplicationService`；compat 端点只做鉴权、格式适配和调用该主服务。每条消息都交给账户配置的平台模型，由模型选择生成普通回复或完整业务计划；不再用本地对话分类分流，也不保留独立直回复路径。两种输出都进入同一个 `LangGraph StateGraph`：普通回复作为内部无副作用节点运行，业务计划则在图执行前经独立于模型的确定性审核，核对图结构、工具动作、参数引用、服务端风险/幂等属性、当前权限和计划节点绑定。模型输出缺失、无效或被拒绝时明确失败，不回退到规则计划或未核验的业务回答。会话历史、跨会话个人记忆及本轮授权知识随请求提供；个人记忆按当前用户、租户和 Mod 授权独立注入，不依赖企业知识库权限。审批快照绑定完整计划和当前工具契约摘要；恢复时复核请求归属、租户、参数、整张计划、步骤清单及当前工具契约。代码在副作用后读取工具回执及业务状态；模型回复和运行状态不能代替业务核验。语音命令不再本地分类后直接调用工具。旧 workflow engine、旧普通聊天意图执行器和 shadow/canary 执行分支已退役。

LangGraph 处理 AND 依赖、条件分支、未选分支、澄清/审批暂停、失败终止与死端。工具错误、超时、权限拒绝、限流和熔断保留结构化结果及恢复提示；安全的短暂故障可自动重试，配额/并发拒绝标为未执行并等待后续重试，副作用结果未知则转人工核对，禁止自动重放。审批驳回会取消挂起计划。只有工具自带明确补偿契约的动作才可回滚，系统不猜测通用回滚。

模型入口按认证账户限 60 次/分钟、租户限 600 次/分钟（可用 `XCAGI_MODEL_CALLS_PER_MINUTE` 与 `XCAGI_TENANT_MODEL_CALLS_PER_MINUTE` 覆盖），进程并发上限默认 32，单账户/供应商连续 5 次瞬时失败后熔断 30 秒；工具入口按租户/动作限 120 次/分钟，单进程并发上限 32、单租户上限 16、单租户动作上限 8，连续 5 次瞬时故障后按租户动作熔断 30 秒。生产/预发布要求 Redis 分布式速率限流；Redis 不可用时限流门禁 fail-closed；并发闸门和熔断在每个应用进程内生效。平台余额与套餐仍由模型平台核算。

短期会话历史按用户、租户、Mod 与会话隔离；可召回个人记忆跨会话共享，但仍按用户、租户和 Mod 隔离。向量记忆最多保留 90 天/400 个片段，并在写入或召回时物理清理过期/超额片段，单次模型上下文最多 120 条、48,000 字符。凭据在记忆存储与模型上下文中脱敏；附件记忆只保留名称、类型和大小。线上业务查询不再由旧 slot 路由或直达处理器短路，模型没有生成有效计划时不执行。离线模式只开放原有受限本地业务处理，不提供普通离线大模型问答。代码、模型回复或 checkpoint 状态都不是业务成功证据；验收须以原始场景核对业务读回。

### 2.2 统一执行入口与任务状态：实现与证据边界

任务复用现有 `AgentTask → AgentRun → AgentStep`、LangGraph 检查点、SQLAlchemy 仓储、审批工作台和聊天轮次回执。`create_unified_task` 与注册能力共用 `publish_task_run`；旧 `start_run_from_plan` 也先原子登记原 run，再由唯一创建者执行。相同键和内容读取原回执，参数、动作或授权范围改变则拒绝复用。显式续接仍可生成下一 attempt，子任务不能抢占父任务的活动 run。具体开源版本、许可和参考协议见 [README](../../README.md#许可证与安全)。

状态按语义投影，保留等待原因：`accepted/queued/running/retrying` 表示已受理或进行中；`waiting_approval/waiting_input/waiting_auth/paused/blocked` 表示尚未完成；`unknown` 表示结果待核对。只有权威完成回执才能展示成功，外层 `success=true` 不能覆盖内层未完成或未知结果。确认的 `completed/failed/cancelled` 不受迟到状态覆盖。失去租约、回执丢失或副作用未核对不能通过重新提交“恢复”。

本次以代码和可重复回归核对以下缺口；这是入口与状态的审计范围，不是全仓业务域成熟度评分。

| 缺口 | 当前实现 | 验证入口 |
|---|---|---|
| 同一 task 的并发创建和旧 plan 先查后写导致重复执行 | 现有 SQL 事务原子登记 task/run；败选者只读；失败整体回滚 | `test_agent_task_admission.py`：独立 session、真实副作用计数、普通/续接/子任务 |
| 迟到保存抢占 active_run 或复活终态 | task 投影检查 attempt/run/version；规划澄清换代须通过原快照 CAS，普通迟到保存不能替换新代或终态 | 同上及 `test_planning_clarification_roundtrip.py`，内存与独立 SQLite 仓储 |
| 失效 worker 写入副作用账本、过期租约把未知写入重试 | 认领、状态及副作用登记使用同一 owner/版本条件；未知写结果保留 `unknown` | `test_task_execution_repository.py`、`test_native_task_recovery.py` |
| paused/blocked/input 被压成失败或审批，接受回执被当完成 | 共用 `domain/task_lifecycle` 归一化与嵌套回执判定，等待态没有 finished_at | `test_task_dispatcher.py`、`test_task_lifecycle_acceptance.py` |
| 注册能力绕开统一登记，重复模型调用创建新 run | 复用统一发布和可信 turn/call 身份；只有原子赢家调用原执行器 | `test_registered_capabilities.py` |
| 员工写审批只有提示文本，没有可恢复原 run | 从现有工具契约准备计划，登记原 run 并绑定审批；不同 call 使用不同审批身份，旧审批先只读核验；gate 回执进入同一结果管道 | `test_employee_runtime_write_approval.py`、`test_agent_loop.py` |
| 审批通过后 queued/unknown 被误报取消或新建审批 | 读取原 plan/run/审批；等待和待核对保持原身份 | `test_approval_persistence.py`、`test_approval_workspace_components.py` |
| 执行回执保存失败后提前清理 pending plan | 完成回执持久化后再清理；恢复读取原 run，不重执行 | `test_workflow_plan_store.py`、`test_chat_component_boundaries.py` |
| 模型继续解释待审批/未知结果，并记作员工成功或失败 | 未完成回执立即退出工具循环；指标单列 pending，账本不填完成时间 | `test_agent_loop.py`、`test_employee_runtime_metrics.py` |
| 扩展调用异常或内部 TypeError 后回退再次执行 | 调用前识别签名；已调用异常返回待核对，只有明确未注册才选下一适配器 | `test_workflow_tool_components.py` |
| 手机员工及 LAN 超级员工没有持久 turn，断线后可能重新调用 | 复用聊天轮次准入、保存和结算；相同 turn 返回原回执；服务端绑定实际工具与执行上下文，断线继续保存原调用结果 | `test_mobile_component_boundaries.py`、`test_mobile_super_employee_receipts.py` |
| 普通回复/员工历史不能恢复，SQL 历史范围混用 | 保存只读 turn 回执；带 run 的记录读取原运行并复核 owner/tenant/Mod/conversation/revision | `test_conversation_turn_receipts.py`、`test_conversation_lifecycle.py` |
| Web 暂存任务重复创建、JSON/SSE 断线错标失败 | 复用原 task/run；断线只查原 turn；未知和等待保留原因 | `useCanonicalChatTaskBridge.test.ts`、聊天编排回归 |
| 手机 EOF、自动切服、离线 outbox 导致第二次 POST | 持久 turn/请求键；已发送记录只查原服务器；未完成气泡按自身身份核对 | `mobile_turn_receipt_test.dart`、`offline_store_test.dart` |
| Codex 中继首次响应丢失、超时重排、认领败选仍派发、晚回执覆盖终态 | 原表按授权 owner/relay/客户端请求键唯一准入并支持只读查询；CAS 认领；超时 unknown 不重放；运行中取消等待原回执；密文过期仍保留带键任务的最小身份与状态 | `test_mobile_relay_queue_components.py`、中继 HTTP 回归 |
| 父子回执使用过时快照或跨 owner/Mod 绑定 | 绑定核对完整授权范围；读取已绑定原 child 的当前回执，丢失或越界显示 unknown | `test_employee_handoff_durability.py`、任务路由投影回归 |
| 管理端员工独立 POST 缺少请求身份，重试建立新审计 run | 新请求键接入同一 `publish_task_run`；仅赢家调用原员工执行器，同键冲突拒绝，查询按原键只读回执；Web 保留原键恢复 | `test_admin_employee_admission.py`、管理端员工 Web 回归 |
| 超级员工的已受理回执长期停在 queued，消息列表读取隐含补回复执行 | 精确读取原 turn，并按原 owner/request/task 读取原派工结果；普通消息查询也不再启动 CLI 补回复，只允许静态展示重建和原派工结果查询 | `test_mobile_super_employee_receipts.py`、超级员工组件回归 |

剩余边界必须继续公开：

- 普通聊天、手机员工和新 LAN 超级员工请求可按原 turn 查询；新中继请求可按原 relay 与客户端请求键查询。旧客户端未携带稳定键、旧 outbox 未保存原身份、或历史回执已按旧策略删除时，不能凭空找回或自动重建任务；只能停止重发并保留待核对。
- 管理端员工仅在提供稳定请求键时保证跨 POST 幂等；旧无键调用保留兼容语义。注册能力及管理端同步路径的原子准入不冒充后台 SQL 队列租约；`_execute_with_durable_lease` 的 metadata 也不是分布式锁。
- Web 管理端不再自动切换到缺少原键回读契约的 market 或旧 Mod HTTP 执行口；新本机入口不可用时明确阻断。已有员工执行器和 Mod 组件仍由新本机入口调用，部署须保持前后端同版。
- 通用 unknown 状态仍需要原工具/执行端的确定回执或人工核对。没有业务供应方的幂等接口和读回凭证，LangGraph 检查点、数据库事务及客户端去重不能证明外部副作用恰好一次。
- Codex 的 thread/turn/item 协议是本次状态对照来源；本仓既有超级员工与中继适配不因此自动获得完整 app-server 协议、所有模型能力或生产成熟度。
- 本地 SQLite/内存并发和 Web 定向测试属于代码、自动测试证据。真实 PostgreSQL、多进程长时间故障演练、项目固定 Flutter 工具链、真实模型/设备及部署同版验收须分别取得证据；未执行项不能记作通过。合入、部署和运行身份以 PR/CI/发布回执为准。

### 2.3 企业认知：权威状态 → 经营目标 → 原任务执行 → 指标证据

本节记录企业认知第二阶段的**候选实现与验收契约**。认知层读取原业务权威源，只维护派生状态、事件游标和目标绑定；业务动作仍由 §2.2 的统一任务链执行。实现依赖 [PR #3441](https://github.com/42433422/XCMAX/pull/3441) 的原子任务准入，核对提交为 `910babadc74559628ae3713b11b686e2dcd50c6c`。该依赖提交、分支代码和本地测试均不代表已合入 `main`、已部署或已通过真实客户验收；合入与运行身份须按最终 PR / CI / 发布证据确认。

#### 企业实体清单与权威来源

以下路径以 `FHD/` 为根。统一引用保留 `entity_type + entity_id`，缓存和访问再绑定 `tenant_id + actor_id + mod_id`；显示编号、员工名称和对话标题均不替代原主键。目录由 `app/domain/enterprise_cognition/catalog.py` 提供，不给原业务对象重新编号。

| 实体类型 | 原唯一 ID 与权威来源 | 可读范围与权限 | 状态含义 |
|---|---|---|---|
| `order` | `sales_orders.id`；`app/db/models/sales.py::SalesOrder`，明细为 `SalesOrderItem` | 本企业；`tool.sales.query` | 保留 `state`、`invoice_status`、`payment_state` 与原履约派生；`order_no` 为业务显示编号，旧 `status` 不替代正交状态 |
| `customer` | `customers.id`；`app/db/models/customer.py::Customer` | 本企业；`customer.view` | 销售订单 `customer_id` 对应的客户；不把购买单位 `PurchaseUnit` 的同号记录当成该客户 |
| `employee` | `ai_employee_profiles.employee_id`；`app/db/models/ai_employee.py::AiEmployeeProfile` | owner 为当前主体，owner 用户属于本企业；`employee.list`；有活动 Mod 时校验其 `mod_id` | AI 员工身份与归属，不把全局 `duty_roster` 编制名单当成当前账号已获授权的员工 |
| `task` | `agent_tasks` 的原组合键 `(tenant_id, user_id, task_id)`；`app/db/models/agent.py::AgentTaskRecord` | 当前主体、本企业；带 active run 时复核该 run 的原主体、租户和 Mod 绑定 | `task_id` 为稳定任务身份，`active_run_id` 为执行尝试；无运行绑定的旧任务仅在宿主范围读取 |
| `fund` | `financial_transactions.id`；`app/db/models/finance.py::FinancialTransaction` | 本企业；`tool.finance.ledger_query` | 一条财务流水的金额、币种和状态；不是银行余额、钱包余额或可支配资金 |

`app/infrastructure/enterprise_cognition_sources.py` 只执行原模型的查询。主体、企业和 Mod 来自服务端认证上下文，不接受模型或 HTTP 参数替换；命中缓存仍重新检查当前 RBAC 和记录归属。缺少资金读取权限时拒绝查询，不能借用写权限或报表导出权限放行。

#### 企业事件订阅与只读状态投影

订阅清单位于原 `config/neuro_bus_events.yaml::enterprise_subscriptions`，由 `app/application/enterprise_cognition/projection.py` 读取；`app/neuro_bus/register_runtime.py` 在真实 NeuroBus 启动路径注册。当前订阅 `enterprise.entity_changed`，以及有完整企业 / Mod 身份的 `order.status_changed`、`order.item_updated`、`customer.updated`、`customer.deactivated`。事件 payload 中的金额、状态或原因均不作为事实写入投影。

原目录中的部分领域事件只有定义，且 `application.customer.changed` 实际指向购买单位，不能直接借其名称证明客户事件已经接通。因此 `app/infrastructure/enterprise_cognition_events.py` 以现有 SQLAlchemy session 事件观察上述五类模型及销售订单明细：仅在外层事务提交后向原 NeuroBus 发布企业、Mod、类型、原 ID 和源表；嵌套事务不提前发布，回滚丢弃对应待发身份。事件失败保留日志，不能把已提交业务改报为失败。观察器不改原业务字段，也不执行任务。

`app/application/enterprise_cognition/projection.py` 将事件转为投影失效标记，再查询权威来源。`EnterpriseStateProjection` 存一张供调用方只读的当前状态视图；`EnterpriseEventCursor` 保存该引用的事件进度和最后事件 ID。两者均在 `app/db/models/enterprise_cognition.py`，并通过现有 ORM bootstrap 与 `alembic/versions/2026_11_21_enterprise_cognition.py` 建表；不迁移原业务数据。

| 投影规则 | 契约 |
|---|---|
| 新鲜度 | 当前目录 TTL 为 30 秒。事件使缓存失效；过期或 `force_refresh=true` 必须回权威系统。读不到权威源、找不到可见记录或存储失败时返回 `freshness=unknown`、空 `state` 与原因，不把旧快照当作当前事实 |
| 证据字段 | `source`、`source_version`、`version_kind`、`source_last_changed`、UTC `observed_at / expires_at`、`last_event_id` 和 `evidence`。证据包含原表、原行 ID、租户、主体、Mod、观测时间和内容哈希 |
| 版本含义 | `source_version=sha256:…` 是读回内容的指纹，不冒充业务数据库的并发版本。订单指纹覆盖子明细及单位，不能只依赖父订单 `updated_at` 判断明细是否变化 |
| 数量与金额 | 金额保留币种并以十进制字符串传递；只有明细单位相同时才聚合数量并给出 `quantity_unit`。不同单位、缺失度量或非有限数字不参加经营指标比较 |
| 重复与乱序 | 事件只负责失效；重复 / 迟到事件不得用旧 payload 覆盖新状态。缓存按租户、主体、Mod 和原实体隔离；读取任务时还检查原运行的 Mod 授权 |
| 覆盖边界 | 无原 ID 的查询仅列当前主体可见的最近有限条，HTTP 默认 10 条、最多 20 条，并返回范围及 `has_more`。它不声称已经扫描全企业。原系统的 bulk SQL、外部写入或 NeuroBus 未启用时不能保证即时通知，依赖 TTL 或强制回查 |

派生状态、事件游标和目标绑定统一保存于宿主库（Host），按上述完整范围隔离。订单、客户、财务流水仍通过原动态 SessionLocal 查询当前授权 Mod 的业务库；员工与原任务从宿主权威库读取，任务额外核对 active run 的 Mod。已有客户 Mod 业务库不需要新增认知表。领域目录、数值/单位规则和证据校验保持纯函数，存储、模型、审批与记忆编排位于应用层。

#### 七步接线与验收证据入口

下表中的认知模块文件均位于 `app/application/enterprise_cognition/`；规划与目标覆盖复用 `app/application/workflow/`，战略读取复用 `app/application/autonomy/`。测试名是核验入口，实际运行范围与结果须另附回执。

| 步骤 | 当前接线 | 核验入口与仍需证明的事实 |
|---|---|---|
| 1. 实体清单 | `catalog.py` → 原五类 ORM 模型 | `tests/test_application/test_enterprise_projection.py`：原 ID、权限、owner / tenant / Mod 范围 |
| 2. 只读事件订阅 | 原 `neuro_bus_events.yaml` → `source_events.py` → 原 NeuroBus → `subscriptions.py` | 同上：真实总线消费、仅提交后发布、嵌套回滚、重复 / 乱序、发布失败；bulk SQL 边界单列 |
| 3. 状态投影 | `sources.py` → `projection.py` → 两张派生表 | 同上：五类详情 / 列表、缓存权限重验、TTL、子明细指纹、故障时 `unknown`，原业务数据不因查询而改变 |
| 4. 经营目标 | `domain/enterprise_cognition/goal_contract.py` 与 `application/enterprise_cognition/goals.py` 绑定原实体、指标、单位、方向、目标值及可选期限；只读引用 `autonomy/strategic_plan_app_service.latest_plan` 的精确内容指纹和条目 | `tests/test_application/test_enterprise_goals.py`：租户 / 主体 / Mod 隔离、单位可比、策略来源校验；目标变更用新 ID，旧绑定不覆盖。研发战略条目不自动成为企业经营事实 |
| 5. 规划与任务 | `execution.py` 复用 `workflow/planner.py`、`workflow/goal_coverage.py` 与原 `AgentOrchestrator` 原子任务准入 | `tests/test_application/test_enterprise_execution.py`：完整目标覆盖、当前工具权限、规划前后实体版本、稳定请求键、原任务回读、审批前无副作用。首批业务写动作仅接与同一 `order_id` 绑定的原 `sales` 生命周期动作；其他实体的写动作仍需各自审核过的选择器契约 |
| 6. 指标与记忆 | `outcomes.py` 读取原 Business Harness 终态及动作回执，强制回查同一权威实体，冻结前后观测；`memory.py` 复用 MemoryV2 追加带证据的经历候选 | `tests/test_application/test_enterprise_outcomes.py`：原任务 / 审批 / 动作绑定、同来源同单位、观测窗口、重复评估、未知回执与记忆失败恢复。观察到变化不证明因果，保留 `attribution=unproven`；记忆候选沿原确认治理，不覆盖原始事实 |
| 7. 同一订单场景 | 同一实体引用串联状态、目标、计划、审批、原任务、工具回执、指标观测和记忆证据 | 组合验收须保留原订单 ID、目标 ID、请求键、task / run / node ID、审批凭证及前后源版本；代码测试、真实模型、真实客户数据、发布身份分别记录，未取得证据的层级不能记为通过 |

该候选的只读回答明确区分：已观察到的未履约数量、用户目标是否达到、用户目标期限是否错过，以及仍未知的订单承诺交期和延期原因。**当前 `SalesOrder` 没有权威交期字段，用户目标的 `deadline` 不是订单的承诺交期。** 因此不得仅凭未交数量或目标过期给出“订单已延期若干天”或断言原因。完整订单延期验收还需要可追溯的原承诺交期和原因证据；不能用固定样例或模型解释补成事实。

2026-11-21 候选本地组合验证：上述八个企业认知测试文件，加原 Business Harness、dispatcher、runtime context、approval consumption/transaction、工具契约/注册和 Agent HTTP 路由，共 **443 项通过、无跳过**。真实 SQLite 场景只控制 planner 输出，原 `sales.confirm → sales.deliver` 两个步骤各自审批；待交数量 `10 → 0 件`、库存 `20 → 10 件`，有唯一库存流水和原回执。重复规划、审批与评估不重复业务副作用、观察或记忆；记忆仍为 pending、归因仍为 unproven。双库同 ID 不同值、Mod 库无派生表和真实 NeuroBus 提交失效均有反例测试。这不替代真实模型、PostgreSQL、原客户延期原因与部署同版验收。

#### 小C入口与审批归属

HTTP 入口为 `POST /api/enterprise/cognition`，请求体为 `{"action": "…", "params": {…}}`。动作包括 `catalog`（实体目录）、`query`（当前状态）、`goals`（原目标绑定）、`bind_goal`（保存目标元数据）、`plan`（生成并登记待审批原任务）、`evaluate`（按原 run 回查结果）。HTTP 入口复用 `app/fastapi_routes/domains/agent/task_routes.py`，编排位于 `app/application/enterprise_cognition/service.py`，参数契约在 `app/domain/enterprise_cognition/contracts.py`。模型工具名为 `enterprise_cognition`，从现有工具注册 / 派发链调用 `app/application/tools/enterprise_cognition.py`，与 HTTP 共用同一应用服务。

`plan` 接收 `goal_id / request_id / message`，不接受 `approved=true`、审批人或替换主体；相同请求读取原任务，不创建另一条执行链。审批、拒绝、继续、取消和回执查询继续使用原 agent / 审批工作台路由（`app/fastapi_routes/domains/agent/agent_routes.py`）；认知层不自批、不直接调用业务执行器。任务终态由原 `app/application/agent_orchestrator/task_dispatcher.py` 调用结果观测；`evaluate` 提供同一回执的显式核对入口。任何外层 `success=true` 都不能替代投影 `freshness`、任务状态和独立观测结论。

## 3. 工作流程（企业内部业务）

### 3.1 采购线（相对完整）
```
供应商 Supplier → 采购订单 PurchaseOrder(draft → 审批 approve) 
→ 采购入库 PurchaseInbound(draft → 入库) → 库存 Inventory
```
- ✅ 已自动化：OCR 识别发票 → 自动建采购入库单 → 推财务审批
- ⚠️ 半自动：PO / Inbound 停留 `draft`，审批后回写状态

### 3.2 发运 / 发货线（核心特色）
```
ShipmentRecord(quantity_kg / quantity_tins / 单价 / 金额, status=pending)
→ 解析(raw_text → parsed_data) → 生成发货单 → 打印(printed_at / printer)
```
- ✅ 已自动化：发运数据解析 → 生成发货单 → 打印标签

### 3.3 服务请求线（状态机完整）
```
ServiceRequest: pending → processing → resolved → closed
```

### 3.4 财务线
```
Finance: pending → (…) 审批 / 月报汇总
```

### 3.5 审批线（跨域通用）
```
ApprovalFlow → ApprovalRequest(pending / …) → ApprovalRecord 留痕 → 委托 Delegation
```

## 4. 交付流程（对外交付，⚠️ 存在结构性断点）

| 交付环节 | 模型 | 现状 |
|---------|------|------|
| 客户 | `customer.py` | ✅ 有 |
| 销售订单 Order / Sale | `sales.py::SalesOrder / SalesOrderItem` | 有原模型及销售生命周期；本次认知层只读复用，真实交付验收另计 |
| 发货单 | `shipment.py` | ✅ 有 + 打印 |
| 交付回执 / 客户签收 | — | ❌ **无** |

**本次更正**：原系统已有销售订单和明细，不能继续记为“无订单模块”。订单状态、原任务回执与前后指标的认知接线见 §2.3；它们不自动证明真实客户签收、约定交期或完整对外交付闭环，仍须原场景证据。

## 5. 统一单据生命周期规范（AGI 编排契约）

当前各域状态值不统一（`draft` / `pending` / `processing`…），AGI 编排需收敛为统一生命周期。建议：

```
draft(草稿) → pending(待审/待处理) → processing(处理中) → completed/succeeded(完成)
   → closed(关闭)   · 异常：failed / rejected / cancelled
审批挂起：awaiting_approval   · 委托：delegated
```

> 落地前需各域模型迁移对齐；未对齐前 AGI 编排一律以"白名单状态映射"读取，禁止跨域直接假设状态语义一致。

## 6. 流程自动化与 AGI 编排就绪度矩阵

| 流程 | 状态机 | 事件触发 | 自动编排 | AGI 闭环 | 就绪度 |
|------|--------|---------|---------|---------|--------|
| 采购线 | ⚠️ draft | ✅ | ⚠️ 1 条 | ❌ 停在审批 | 🟡 |
| 发运线 | ⚠️ pending | ⚠️ | ❌ | ❌ | 🟠 |
| 服务线 | ✅ | ❌ | ❌ | ❌ | 🟠 |
| 财务线 | ⚠️ | ⚠️ | ⚠️ 月报 | ❌ | 🟠 |
| 交付线 | 有销售订单与明细 | §2.3 已接只读提交观察 | 候选规划接原任务审批 | 真实交期 / 签收待验 | 待验 |

图例：🟢 可自主闭环 · 🟡 半自动（需人签核）· 🟠 未编排 · 🔴 域缺失

## 7. 断点与行动项（AGI 主导落地序）

P0（域补齐，先做）：
1. 沿现有**销售订单 → 履约 → 交付回执**核对真实闭环，补齐原承诺交期、客户签收和结果证据；复用现有订单模型，不另建订单权威源。
2. 收敛**统一单据生命周期**（§5），为编排契约定基。

P1（编排提级）：
3. 将采购 / 发运 / 服务 / 财务各线提为可触发的 `WorkflowDefinition`，从"1 条样板"扩为"流程库"。
4. 为发运线增加事件触发（`shipment.parsed` → 自动生成发货单 → 打印）。

P2（AGI 自主闭环）：
5. 在风险门禁（`risk_gate.py`）之上定义"低风险环节 AGI 自主执行、中高风险人签核"的决策边界。
6. 打通"观察 → 决策 → 执行 → 记录 → 学习"闭环，审计留痕由 `ApprovalRecord` + NeuroBus trace 承载。

## 8. 维护约定

- 业务域新增 / 状态机变更：**必须同步本文档 §3–§5**，并在此登记（`# PROCESS_FLOW_SSOT`）。
- 新增 WorkflowDefinition seed：同步 §6 就绪度矩阵。
- 本文档为纯文档 SSOT，不改动 `config/ssot.yaml` 机器注册表；由 `docs/SSOT_INDEX.md` 的 `docs-ssot` 域 lint 守护。
