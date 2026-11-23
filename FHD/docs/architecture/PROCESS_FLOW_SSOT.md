# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 本文件约束跨组件职责与迁移验收；账号授权、事件、版本和发布仍分别服从已登记领域的规范。实现现状以指定提交的源码与实际回执为证，文档不能覆盖运行事实。
> 最后更新：2026-11-23 · 登记：[SSOT_INDEX.md](../SSOT_INDEX.md)（领域 `process-flow`）。§2.2 保留集成候选的执行入口与回执契约，§2.3 保留企业认知候选；其他业务域未重新验收。§9 的 2026-11-21 源码核查基线为 [main@171418352d24667a7123b6556c55bad445ef3440](https://github.com/42433422/XCMAX/commit/171418352d24667a7123b6556c55bad445ef3440)，当时的开放候选身份见 §9.3。

---

## 1. 目的与范围

本文档定义 XCMAX（FHD 企业桌面 ERP + AI 员工平台）的**业务工作流程**与**对外交付流程**，作为 AGI 主导编排时的流程基线。目标是让每一段业务链路上升为可触发的 `WorkflowDefinition`，并使 AGI 能回答三个问题：

1. **观察**：某张单据/某个业务对象当前处于哪个环节？
2. **决策**：下一步有哪些合法动作、各自风险等级、是否需要人签核？
3. **执行**：动作由谁触发（LLM 编排 / 事件驱动 / 人工），落库何张单据？

范围：**业务域状态、跨域编排、组件权威归属及迁移验收**。CI/CD 与合入顺序见 [CI_SSOT.md](../../../docs/CI_SSOT.md)，自治运营见 [autonomy.md](../../../docs/autonomy.md)。§9 的历史核查仅核对源码与规范，未执行真实业务或重跑候选 PR 的测试；§2.2–2.3 的候选实现与分支回归分列记录，不替代 main 合入或生产验收。

## 2. 基础设施盘点（基线可定位的实现）

| 组件 | 现状 | 代码位置 |
|------|------|---------|
| 工作流模型 | ✅ Definition / Run / RunStep 三表 + 状态机 | `../../app/db/models/workflow.py` |
| 审批流 | ✅ Flow / Node / Request / Record / Delegation（含委托） | `../../app/db/models/approval.py` |
| 领域事件总线 | ✅ NeuroBus 域事件（ocr.completed 等） | `../../app/neuro_bus/bus.py` |
| 风险门禁 | 服务端风险策略、硬边界与审批证据；不能简化成仅 low / medium | [AutonomyGuard](../../app/domain/autonomy/autonomy_guard.py)、[风险注册表](../../config/risk_actions.registry.json) |
| 单据状态机 | 各域保留独立生命周期，跨域投影按 §5 核对 | 各 `app/db/models/*.py` |

已有 [WorkflowDefinitionAppService](../../app/application/workflow_definition_app_service.py)、[库存事件处理器](../../app/neuro_bus/domains/inventory_domain_handlers.py)、[财务事件处理器](../../app/neuro_bus/domains/finance_domain_handlers.py) 和 [月报调度](../../app/application/monthly_report_scheduler.py)。定义、事件触发和任务执行属于不同层；可定位这些实现不等于任意业务流程已经贯通或已验收。

### 2.1 智能对话与业务工作流的唯一执行链

新聊天、语音/compat 聊天、agent 型员工和自然语言 `/api/agent/runs` 由固定本地 Codex `0.171.0` 执行。独立路由同时绑定已验收的请求别名、实际响应模型和网关协议；禁止故障转移与响应身份纳入资格，LiteLLM 路径逐次核对原始零重试/零换模计数，标准 Responses 不盲发非标准参数。新任务的配置或独立模型资格证缺失时明确阻断；已经持久化的旧计划、审批和澄清仍在原任务恢复。显式业务工具、人工操作和开发超级员工保留各自已授权的入口；本节不代表 §9 的全部消费者已完成统一。

宿主首次保存原请求、约束、授权附件及来源摘要，不先生成完整计划。Codex `0.171.0` 是唯一通用模型工具循环：发现能力、取得完整 ToolSpec 与 `schema_digest`、执行当前动作、观察原回执、继续或纠正。原 SQL 任务和 AgentOrchestrator 为动作登记子任务，审批绑定原参数与工具合同；正式业务图继续由 LangGraph 处理依赖、分支和检查点。通用 Planner、整图修复、执行前覆盖审核、员工/浏览器第二模型循环与 `execute_plan` 均已移除。

每轮动作结束后，独立业务核验先回读 SQL、文件或同会话页面事实；无工具的目标审计再核对原始请求、全部持久补答和当前证据。报告与原目标及证据摘要绑定，缺口返回同一 thread 继续，执行—核验最多三轮。审计按规模分配输出预算，格式错误或截断只重试一次，并受原任务剩余时限/模型调用数/费用控制。等待输入、审批、活动调用、未知效果或用量不明优先暂停；动作成功、模型结束或最终回复丢失都不自动完成原目标。

令牌、记忆召回、工作簿产物和浏览器会话绑定原父任务、主体、租户、Mod 与员工范围。记忆/历史只提供可追溯上下文，不能改变授权；补答累积进原账本而不覆盖目标。浏览器/AIOPEN 写动作必须具有原观察与后置条件，同会话只读回查才可验证；单动作子任务不能提前关闭父浏览器会话。Excel 读写、公式存储及数值重算采用各自真实证据，不推断未运行的计算。

确定未发送的连接故障与明确拒绝的限流可有限退避，未知写入与未知计量仅核对原回执。审批通过后，后台 dispatcher 从原子任务的确定回执登记一次父任务续接，恢复同一 thread；GET 只更新可读投影，不触发执行。正式工作流的确定性重试仍遵守原工具契约，补偿只按工具已声明的回滚能力执行。

保留的宿主公共模型入口按认证账户限 60 次/分钟、租户限 600 次/分钟（可用 `XCAGI_MODEL_CALLS_PER_MINUTE` 与 `XCAGI_TENANT_MODEL_CALLS_PER_MINUTE` 覆盖），进程并发上限默认 32，单账户/供应商连续 5 次瞬时失败后熔断 30 秒；工具入口按租户/动作限 120 次/分钟，单进程并发上限 32、单租户上限 16、单租户动作上限 8，连续 5 次瞬时故障后按租户动作熔断 30 秒。生产/预发布要求 Redis 分布式速率限流；Redis 不可用时限流门禁 fail-closed；并发闸门和熔断在每个应用进程内生效。固定 Codex 路径的模型预留、usage 结算、未知计量和Codex 跨轮累计活跃时限（不含审批等待及独立后台业务 worker；后者保留原工具超时与租约）服从 [运行时合同](../../README.md#固定本地-agent-执行器)，不借用旧入口的成功状态。

短期会话历史按用户、租户、Mod 与会话隔离；可召回个人记忆跨会话共享，但仍按用户、租户和 Mod 隔离。向量记忆最多保留 90 天/400 个片段，并在写入或召回时物理清理过期/超额片段，单次模型上下文最多 120 条、48,000 字符。凭据在记忆存储与模型上下文中脱敏；附件记忆只保留名称、类型和大小。线上业务查询不再由旧 slot 路由或直达处理器短路，没有已授权的动作契约时不执行。离线模式只开放原有受限本地业务处理，不提供普通离线大模型问答。代码、模型回复或 checkpoint 状态都不是业务成功证据；验收须以原始场景核对业务读回。

### 2.2 统一执行入口与任务状态：实现与证据边界

任务复用现有 `AgentTask → AgentRun → AgentStep`、LangGraph 检查点、SQLAlchemy 仓储、审批工作台和聊天轮次回执。`create_unified_task` 与注册能力共用 `publish_task_run`；旧 `start_run_from_plan` 也先原子登记原 run，再由唯一创建者执行。相同键和内容读取原回执，参数、动作或授权范围改变则拒绝复用。显式续接仍可生成下一 attempt，子任务不能抢占父任务的活动 run。具体开源版本、许可和参考协议见 [README](../../README.md#许可证与安全)。

状态按语义投影，保留等待原因：`accepted/queued/running/retrying` 表示已受理或进行中；`waiting_approval/waiting_input/waiting_auth/paused/blocked` 表示尚未完成；`unknown` 表示结果待核对。只有权威完成回执才能展示成功，外层 `success=true` 不能覆盖内层未完成或未知结果。确认的 `completed/failed/cancelled` 不受迟到状态覆盖。失去租约、回执丢失或副作用未核对不能通过重新提交“恢复”。

本次以代码和可重复回归核对以下缺口；这是入口与状态的审计范围，不是全仓业务域成熟度评分。

| 缺口 | 当前实现 | 验证入口 |
|---|---|---|
| 同一 task 的并发创建和旧 plan 先查后写导致重复执行 | 现有 SQL 事务原子登记 task/run；败选者只读；失败整体回滚 | `test_agent_task_admission.py`：独立 session、真实副作用计数、普通/续接/子任务 |
| 迟到保存抢占 active_run 或复活终态 | task 投影检查 attempt/run/version；持久补答与原任务续接须通过原快照 CAS，普通迟到保存不能替换新代或终态 | 同上及 `test_codex_goal_lifecycle.py`，内存与独立 SQLite 仓储 |
| 失效 worker 写入副作用账本、过期租约把未知写入重试 | 认领、状态及副作用登记使用同一 owner/版本条件；未知写结果保留 `unknown` | `test_task_execution_repository.py`、`test_native_task_recovery.py` |
| paused/blocked/input 被压成失败或审批，接受回执被当完成 | 共用 `domain/task_lifecycle` 归一化与嵌套回执判定，等待态没有 finished_at | `test_task_dispatcher.py`、`test_task_lifecycle_acceptance.py` |
| 注册能力绕开统一登记，重复模型调用创建新 run | 复用统一发布和可信 turn/call 身份；只有原子赢家调用原执行器 | `test_registered_capabilities.py` |
| 员工写审批只有提示文本，没有可恢复原 run | 从现有工具契约准备计划，登记原 run 并绑定审批；不同 call 使用不同审批身份，旧审批先只读核验；gate 回执进入同一结果管道 | `test_employee_runtime_write_approval.py`、`test_codex_employee_entry.py` |
| 审批通过后 queued/unknown 被误报取消或新建审批 | 读取原 plan/run/审批；等待和待核对保持原身份 | `test_approval_persistence.py`、`test_approval_workspace_components.py` |
| 执行回执保存失败后提前清理 pending plan | 完成回执持久化后再清理；恢复读取原 run，不重执行 | `test_workflow_plan_store.py`、`test_chat_component_boundaries.py` |
| 模型继续解释待审批/未知结果，并记作员工成功或失败 | 未完成回执立即退出工具循环；指标单列 pending，账本不填完成时间 | `test_codex_employee_entry.py`、`test_employee_runtime_metrics.py` |
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

下表中的认知模块文件均位于 `app/application/enterprise_cognition/`；通用执行与目标核验复用 `app/application/agent_runtime/`，战略读取复用 `app/application/autonomy/`。测试名是核验入口，实际运行范围与结果须另附回执。

| 步骤 | 当前接线 | 核验入口与仍需证明的事实 |
|---|---|---|
| 1. 实体清单 | `catalog.py` → 原五类 ORM 模型 | `tests/test_application/test_enterprise_projection.py`：原 ID、权限、owner / tenant / Mod 范围 |
| 2. 只读事件订阅 | 原 `neuro_bus_events.yaml` → `source_events.py` → 原 NeuroBus → `subscriptions.py` | 同上：真实总线消费、仅提交后发布、嵌套回滚、重复 / 乱序、发布失败；bulk SQL 边界单列 |
| 3. 状态投影 | `sources.py` → `projection.py` → 两张派生表 | 同上：五类详情 / 列表、缓存权限重验、TTL、子明细指纹、故障时 `unknown`，原业务数据不因查询而改变 |
| 4. 经营目标 | `domain/enterprise_cognition/goal_contract.py` 与 `application/enterprise_cognition/goals.py` 绑定原实体、指标、单位、方向、目标值及可选期限；只读引用 `autonomy/strategic_plan_app_service.latest_plan` 的精确内容指纹和条目 | `tests/test_application/test_enterprise_goals.py`：租户 / 主体 / Mod 隔离、单位可比、策略来源校验；目标变更用新 ID，旧绑定不覆盖。研发战略条目不自动成为企业经营事实 |
| 5. 规划与任务 | `execution.py` 将原 goal、order、task/request 身份交给唯一 Codex 入口；原 `AgentOrchestrator` 原子准入实际业务子动作 | `tests/test_application/test_enterprise_execution.py`：完整目标覆盖、当前工具权限、规划前后实体版本、稳定请求键、原任务回读、审批前无副作用。首批业务写动作仅接与同一 `order_id` 绑定的原 `sales` 生命周期动作；其他实体的写动作仍需各自审核过的选择器契约 |
| 6. 指标与记忆 | `outcomes.py` 只接受原父目标核验终态及对应动作回执，强制回查同一权威实体，冻结前后观测；单动作子任务不得提前结算整体目标；`memory.py` 复用 MemoryV2 追加带证据的经历候选 | `tests/test_application/test_enterprise_outcomes.py`：原任务 / 审批 / 动作绑定、同来源同单位、观测窗口、重复评估、未知回执与记忆失败恢复。观察到变化不证明因果，保留 `attribution=unproven`；记忆候选沿原确认治理，不覆盖原始事实 |
| 7. 同一订单场景 | 同一实体引用串联状态、目标、计划、审批、原任务、工具回执、指标观测和记忆证据 | 组合验收须保留原订单 ID、目标 ID、请求键、task / run / node ID、审批凭证及前后源版本；代码测试、真实模型、真实客户数据、发布身份分别记录，未取得证据的层级不能记为通过 |

该候选的只读回答明确区分：已观察到的未履约数量、用户目标是否达到、用户目标期限是否错过，以及仍未知的订单承诺交期和延期原因。**当前 `SalesOrder` 没有权威交期字段，用户目标的 `deadline` 不是订单的承诺交期。** 因此不得仅凭未交数量或目标过期给出“订单已延期若干天”或断言原因。完整订单延期验收还需要可追溯的原承诺交期和原因证据；不能用固定样例或模型解释补成事实。

2026-11-21 候选本地组合验证：上述八个企业认知测试文件，加原 Business Harness、dispatcher、runtime context、approval consumption/transaction、工具契约/注册和 Agent HTTP 路由，共 **443 项通过、无跳过**。真实 SQLite 场景只控制 planner 输出，原 `sales.confirm → sales.deliver` 两个步骤各自审批；待交数量 `10 → 0 件`、库存 `20 → 10 件`，有唯一库存流水和原回执。重复规划、审批与评估不重复业务副作用、观察或记忆；记忆仍为 pending、归因仍为 unproven。双库同 ID 不同值、Mod 库无派生表和真实 NeuroBus 提交失效均有反例测试。这不替代真实模型、PostgreSQL、原客户延期原因与部署同版验收。

#### 小C入口与审批归属

HTTP 入口为 `POST /api/enterprise/cognition`，请求体为 `{"action": "…", "params": {…}}`。动作包括 `catalog`（实体目录）、`query`（当前状态）、`goals`（原目标绑定）、`bind_goal`（保存目标元数据）、`plan`（生成并登记待审批原任务）、`evaluate`（按原 run 回查结果）。HTTP 入口复用 `app/fastapi_routes/domains/agent/task_routes.py`，编排位于 `app/application/enterprise_cognition/service.py`，参数契约在 `app/domain/enterprise_cognition/contracts.py`。模型工具名为 `enterprise_cognition`，从现有工具注册 / 派发链调用 `app/application/tools/enterprise_cognition.py`，与 HTTP 共用同一应用服务。

`plan` 接收 `goal_id / request_id / message`，不接受 `approved=true`、审批人或替换主体；相同请求读取原任务，不创建另一条执行链。审批、拒绝、继续、取消和回执查询继续使用原 agent / 审批工作台路由（`app/fastapi_routes/domains/agent/agent_routes.py`）；认知层不自批、不直接调用业务执行器。任务终态由原 `app/application/agent_orchestrator/task_dispatcher.py` 调用结果观测；`evaluate` 提供同一回执的显式核对入口。任何外层 `success=true` 都不能替代投影 `freshness`、任务状态和独立观测结论。

## 3. 工作流程（企业内部业务）

| 流程 | 现有业务拥有方 | 编排必须核对的结果 |
|---|---|---|
| 采购与入库 | [PurchaseOrder / PurchaseInbound](../../app/db/models/purchase.py)、库存事件处理器 | 原审批、入库单与库存读回，不用 OCR 完成事件替代入库 |
| 发运与打印 | [ShipmentRecord](../../app/db/models/shipment.py) | 原单据、解析结果和实际打印回执分别核对 |
| 服务请求 | [ServiceRequest](../../app/db/models/service_request.py) | 原请求的处理/解决/关闭事实，不用聊天结束代替解决 |
| 财务与月报 | 财务事件处理器、月报调度 | 原业务凭证、统计范围和产物，调度成功不代替报表正确 |
| 审批 | [ApprovalFlow / Request / Record / Delegation](../../app/db/models/approval.py) | 当前有权审批人的决定、原计划和后续执行回执，批准不等于执行完成 |

## 4. 交付流程（对外交付）

| 交付环节 | 基线源码证据 | 本轮结论 |
|---|---|---|
| 客户与销售订单 | [SalesOrder / SalesOrderItem](../../app/db/models/sales.py) 关联客户、订单与明细 | 已有模型，撤销旧版“无销售订单模块”判断 |
| 订单到履约/开票/收款 | [SalesAppService.execute_closed_loop](../../app/application/sales_app_service.py) 在事务中组合既有领域服务 | 已有执行入口；本轮未运行原聊天、审批、出库、会计与导出全链，不能记为验收通过 |
| 发货与客户确认 | 发货单、各交付系统的原业务记录 | 发货、文件下载、渠道送达与客户签收/确认是不同事实；没有原主体、原对象和独立回执时保持待核验 |

后续补齐的是原订单、批准计划、实际履约和客户确认之间的可追溯关联；应先核对现有领域服务，不能再新建一套订单域或依据字段存在宣称交付完成。§2.3 的认知接线、原任务回执与前后指标不自动证明真实客户签收、约定交期或完整对外交付闭环，仍须原场景证据。

## 5. 统一单据生命周期规范（AGI 编排契约）

统一跨域读取与结果解释，保留领域状态的含义。销售订单已有商业 `state`、`invoice_status`、`payment_state` 和按明细数量派生的履约维度；旧线性 `status` 是兼容读取，不能覆盖这些正交维度。
跨域投影应携带原对象 ID、所属账号/租户、来源、版本/观测时间和核验状态；过期或来源不可读时回查原系统并保留未知。任务控制态、审批决定和业务完成态分别读取，不把所有业务表迁成同一套 `pending/completed` 枚举。

## 6. 流程自动化与 AGI 编排就绪度矩阵

| 范围 | 已定位的源码与候选证据 | 后续验收证据 |
|---|---|---|
| 采购、发运、服务、财务 | §3 的模型/处理器/调度源码可定位 | 同账号原始输入、批准、业务写入与独立读回；源码定位不代表全链通过 |
| 销售与客户交付 | §4 的订单模型和事务执行入口可定位；§2.3 另列只读提交观察与原任务审批的候选回归 | 原计划确认后不中途换计划；履约/会计/导出/原承诺交期/客户确认逐项回读；候选 SQLite 证据不代替完整交付验收 |
| 跨入口统一 | §9 的来源关系与具体静态缺口 | 同一集成提交的原子准入、恢复、权限、核验及各客户端回归；开放 PR 不计为 main 已完成 |

## 7. 断点与行动项（按依赖落地）

1. P0：先收敛 §9 的能力合同、准入身份、审批消费、幂等与状态投影，迁移仍独立派发的旧入口。
2. P1：再整合浏览器候选、模型容量、上下文、业务核验与观测；逐入口核对，不用公共入口的单测替代其他消费者。
3. P1/P2：各业务域和外部执行器按原领域身份接回执与反馈；沿现有销售订单、履约与交付回执补齐原承诺交期和客户确认。采购、发运、服务、财务的 WorkflowDefinition 与事件触发复用原权限、审批和执行链，观察、决策、执行、记录与学习均按 §6 核对原始场景；不新建订单权威源或在本文另定风险策略。合入顺序由原仓库流程决定，本表是技术依赖，不能代替排队批准。

## 8. 维护约定

- 业务域/状态机变更同步 §3–§6；组件归属或调用方迁移同步 §9，更新精确提交、替代路径、剩余边界和验收结果。
- 本文档为纯文档 SSOT，沿用 [SSOT_INDEX.md](../SSOT_INDEX.md) 的 `docs-ssot` 登记；未新增机器检查器，不虚构 enabled 领域。登记 lint 通过只证明文档一致，不证明业务通过。
- 来源、权限、事件、价格、发布配置仍在各原领域维护；这里只记录跨域关系，不复制其配置值。新增兼容入口须指向现有实现；退出旧路径须给出删除或纯转发证据。

## 9. 组件权威来源、迁移与验收

### 9.1 判定口径与共同边界

以下是 **14 项统一性核查范围，不是已证实的 14 套重复实现**。状态列保留 2026-11-21 指定基线的源码核查结论，不冒充当前集成提交的验收结果；集成候选契约见 §2.2–2.3，关闭证据按 §9.4 更新。“已定位”仅表示当时已读源码；“候选”指当时未合入的 PR；“待核验”表示证据不足，不等同于缺失。实现、分支回归、main 合入、同 SHA 发布和真实业务验收分别记录，不相互替代。

- 按职责确定决策拥有方。宿主沿用 AgentOrchestrator；MODstore、Para、Kellai 保留各自领域记录，通过适配器关联原请求/任务/回执，不强制跨进程共用一张表或直接调用宿主实例。
- 请求键、task、run、step/call、attempt、外部任务 ID、会话/轮次和 trace 分别表达不同身份。保留其映射及账号/租户/Mod/工作区范围；trace 仅作观测，不作为幂等键或任务主键。
- 风险源、完整 ToolSpec 合同、模型目录和权限过滤视图分层维护。审批依现有注册策略、硬边界、当前权限与原批准内容决定；不得用模型参数、远端 readOnlyHint 或新入口扩权，也不在纯文档中改写现有风险策略。
- 原子准入、执行队列租约和副作用账本分别解决创建、worker 归属和执行结果核对。未知写入保留原身份，先查询原回执；对端没有精确请求键查询且 task ID 丢失时保留人工核对，不换键、换 CLI、换通道或重放脚本。不承诺跨系统 exactly-once。
- `accepted`、HTTP 200、SSE EOF、审批通过、CLI 文字、页面变化和产物生成均不能单独宣告业务完成。公共分类、领域独立读回和 Business Harness 汇总分层复用；记忆引用证据与来源，不覆盖原事实。
- `FHD/mods/ → FHD/XCAGI/mods/` 和源 workflow → 根 `.github/workflows/` 已有生成关系，不计作独立实现。市场包目录、员工花名册、运行时工具目录与官网能力证据职责不同；统一关联，不合成一张万能目录。

### 9.2 组件清单与迁移责任

下表“收敛动作”是待落实和验证的要求；不因写入本文就变成已实现。链接指向基线已有文件，候选新增浏览器文件另用固定提交链接。

| 项 / 优先级 | 现有职责与源码依据 | 调用方及收敛动作 | 核查状态 / 候选 |
|---|---|---|---|
| U01 执行准入 / P0 | [unified_task](../../app/application/agent_orchestrator/unified_task.py)、[task_plan](../../app/application/agent_orchestrator/task_plan.py) 和 [Orchestrator](../../app/application/agent_orchestrator/orchestrator.py) 共用执行核心 | 聊天、任务 API、公共 tools/skills、管理端员工、Mod/SDK、移动 relay 共享稳定请求键和原子准入；旧入口只做鉴权/参数适配 | 已定位不同准入路径；[tools_execute](../../app/fastapi_routes/tools_execute.py) 未登记路径仍可转 archive；#3440/#3441 候选 |
| U02 状态与回执 / P0 | [AgentTask](../../app/application/agent_orchestrator/task_models.py) 是跨运行投影；[AgentRun/Step/Call](../../app/application/agent_orchestrator/run_models.py)、[任务队列](../../app/application/agent_orchestrator/task_execution_models.py)、员工账本各有事实粒度 | 按原 task/run/attempt 综合运行、队列控制和业务回执；迟到快照不覆盖新代次；不能只信聊天或只忽略队列故障 | 已定位分层；#3441/#3433 候选；等待态具体问题见 U14 |
| U03 权限与审批 / P0 | [AutonomyGuard](../../app/domain/autonomy/autonomy_guard.py)、[审批持久化](../../app/application/workflow/approval_persistence.py)、[执行 grant](../../app/application/agent_orchestrator/approval_grant.py) | 公共工具、员工子工具、排队/恢复绑定当前主体、范围、完整计划和工具合同；保留业务审批、运行 grant、当前权限检查各自职责 | [员工写审批](../../app/application/employee_runtime/write_approval.py) 已复用原策略，并非另一审批引擎；#3440/#3441 扩充绑定候选 |
| U04 能力定义与发现 / P0 | [风险表](../../config/risk_actions.registry.json) → [执行 registry](../../app/services/tools_execution/registry.py) 合并 MCP → [ToolSpec](../../app/application/agent_orchestrator/tool_spec.py) 组合 schema/合同；[注册能力](../../app/application/tools/registered_capabilities.py) 提供模型视图 | 小 C、Planner、MCP、REST 与员工按实际权限发现能力；[旧 workflow 目录](../../app/application/tools/workflow.py) 的别名/手工描述绑定规范动作，缺 handler 的 schema 不冒充可执行能力 | 主链派生已存在；动态扩展、完整输入输出合同及旧别名消费仍需对齐，#3440/#3443 候选 |
| U05 幂等与恢复 / P0 | [执行租约](../../app/application/agent_orchestrator/execution_lease.py)、[安全续接](../../app/application/agent_orchestrator/run_lifecycle.py)、[队列仓储](../../app/application/agent_orchestrator/task_execution_sql_repository.py) | 工具、远端派工、自维护和脚本入口共用原请求与结果语义；区分未派发、明确失败、未知副作用；metadata 不冒充分布式互斥 | 已有机制，跨消费者闭环待验；#3437/#3440/#3441 候选 |
| U06 浏览器与桌面 / P1 | main 已有 AIOPEN 持屏和 MCP 入口；[#3430 直接执行器](https://github.com/42433422/XCMAX/blob/8a165d72c5e8620e2243d28dbf9ceacfd6dd9563/FHD/app/desktop_automation/computer_browser.py) 与 [#3434 直接执行器](https://github.com/42433422/XCMAX/blob/a224a9a92ed970bd2cb8a42cca6399756a61d088/FHD/app/infrastructure/browser/runtime.py) 均管理 context/origin/locator/核验 | 直接 Playwright 候选需选定共同运行时/政策实现，并明确保留、适配或退休范围；OS 桌面、持屏页面、MCP 传输和 Agent 动态决策保留分层 | 两个直接候选已确认职责重叠，文件尚不在 main；#3439 的会话持有/决策循环不能当重复引擎删除 |
| U07 模型路由与容量 / P1 | [账号选路](../../app/application/market_llm/routing.py)、[容量目录](../../app/infrastructure/llm/model_context_windows.py) 与原 MODstore LiteLLM | 各操作按实际选中模型取容量；同次请求的预算和发送共用一次选路，文字不盖掉视觉；摘要使用独立输入/输出预算，不带 Planner 工具合同 | main 静态目录仍有折半/32K 上限；#3443 候选贯穿容量；路由预算一致性待验 |
| U08 对话与任务上下文 / P1 | [ContextWindowManager](../../app/application/agent_orchestrator/context_window_manager.py)、[workflow_session](../../app/application/ai_chat/workflow_session.py)、[会话仓储](../../app/application/task_conversation_store.py) | 历史/摘要只提供输入投影；已接受澄清、审批、任务代次和业务记忆保留原持久权威，恢复核对 revision 与范围 | 压缩组件已存在；#3433/#3443 职责交叉须同版本验收 |
| U09 结果核验与反馈 / P1 | [公共结果分类](../../app/domain/task_lifecycle/results.py) 已被 [员工 verifier](../../app/application/employee_runtime/result_verifier.py) 复用；[Business Harness](../../app/application/agent_orchestrator/business_harness.py) 汇总身份与业务证据 | 首次执行、超时、重启和账本回读消费一致分类；各业务验证器读取原对象，反馈记忆附证据，不能再建平行成功判定 | 已有共用核心；#3437/#3441/#3398 为消费者补齐候选 |
| U10 Trace、错误、耗时 / P1 | [HTTP Trace](../../app/middleware/neuro_http_trace.py)、[NeuroBus tracer](../../app/neuro_bus/tracer.py)、[模型遥测](../../app/infrastructure/llm/genai_telemetry.py) | HTTP/流/工具 attempt/模型/前端保留父子关联和各层 span，使用真实持续时间；观测故障不重发业务、不覆盖原错误 | 多 span 属正常分层；#3438 传播与终态计时候选 |
| U11 定时与自治调度 / P1 | [CI 调度规范](../../../docs/CI_SSOT.md)、[自治手册](../../../docs/autonomy.md)、[员工 scheduler](../../app/application/employee_runtime/scheduler.py) 及 MODstore 原调度 | 同一业务 job 明确唯一触发拥有方、稳定任务身份和恢复查询；多种调度器存在不等于重复触发，逐 job 核对 | #3396/#3398/#3437 候选；未完成全部 job 运行审计，不宣称已消除重复调度 |
| U12 客来来与数据接入 / P2 | [Kellai 绑定应用层](../../app/application/kellai_binding_app_service.py)、原客户草稿/跟进和 [ELT](../../app/application/elt/) | 宿主与 Kellai 关联原连接、授权和 request_id；配对不等于发送授权，accepted/送达/已读分别回执；ELT 保留源文件和预演确认 | #3435 及配套 Kellai #2 候选；不另造模型池或客户事实库，未据候选声明真实送达 |
| U13 市场资源目录 / P2 | [Mod 商店门面](../../app/application/mod_store_catalog_app.py)、[员工花名册](../../config/duty_roster.json) 和各原领域目录 | 模块/员工分类共用原包身份、授权、安装与完整分页；商品包、员工身份、工具动作和公开能力证据不互相替代 | #3415 为界面/目录消费候选；未证明需要合并底层存储 |
| U14 前端状态投影 / P1 | [planned_workflow_dispatch](../../app/application/ai_chat/planned_workflow_dispatch.py)、[agentRunExecution](../../frontend/src/utils/agentRunExecution.ts) 与各客户端读回 | 聊天、任务页、审批页、移动端以原运行/队列/回执投影，回调或流结束不独立完成任务 | main 静态发现等待态用 `setdefault`，不能覆盖已有 completed；#3446 修复叠在 #3441，本轮未执行该反例 |

### 9.3 开放候选身份与整合约束

2026-11-21 读取 API 元数据时，下列 PR 均 open、未合入。表中 head 是核查快照，不是“永远最新”或测试通过声明；候选变化须重读代码差异及该提交检查。正文中的旧 SHA、测试总数和 mergeable 标志不代替合入或发布证据。

| PR | 核查 head | 接入关系 |
|---|---|---|
| [#3440](https://github.com/42433422/XCMAX/pull/3440) | `8440f9a32ceb95e2d578d1fe80e66355986bf027` | 工具入口、授权范围与安全重试；与 #3441 共改员工/工具入口，须语义整合 |
| [#3441](https://github.com/42433422/XCMAX/pull/3441) | `910babadc74559628ae3713b11b686e2dcd50c6c` | 原子准入/状态候选；其 [§2.2](https://github.com/42433422/XCMAX/blob/910babadc74559628ae3713b11b686e2dcd50c6c/FHD/docs/architecture/PROCESS_FLOW_SSOT.md) 为实现来源，集成契约保留于本文 §2.2；章节合并不代表 publish_task_run 已在 main 或通过全部验收 |
| [#3446](https://github.com/42433422/XCMAX/pull/3446) | `8728855690accb824594f1d1671e6232817a40ff` | base 为 #3441 分支 `910babad…`，不能按独立 main 修复直接排合入 |
| [#3433](https://github.com/42433422/XCMAX/pull/3433) | `a28ed80eaa0d7bc1db97fcd1bb6d2aa190d129a9` | 上下文/澄清/恢复；metadata base SHA 为 `48f8f40d…`，需核对主线差异与 #3443 交叉修改 |
| [#3443](https://github.com/42433422/XCMAX/pull/3443) | `cfbbb44adb2bea1473e0afcef41b9335a8669127` | 真实模型容量、摘要和预算接入；保留完整工具合同及原业务记忆 |
| [#3430](https://github.com/42433422/XCMAX/pull/3430) | `8a165d72c5e8620e2243d28dbf9ceacfd6dd9563` | 桌面与直接浏览器；先处理 U06 重叠 |
| [#3434](https://github.com/42433422/XCMAX/pull/3434) | `a224a9a92ed970bd2cb8a42cca6399756a61d088` | AIOPEN 桥接与直接浏览器；与 #3430 统一站点/文件/结果政策 |
| [#3439](https://github.com/42433422/XCMAX/pull/3439) | `b959ae0ce377466bb31f86f13590b6f489f8352f` | MCP 持久会话与动态观察决策，接统一授权和原步骤身份 |
| [#3437](https://github.com/42433422/XCMAX/pull/3437) | `7989dfe541f4af0aee68247f196164032a87f119` | 原生回执、幂等及恢复消费者 |
| [#3438](https://github.com/42433422/XCMAX/pull/3438) | `d17e7e84274bb79c151316348e3e432d96c03151` | 跨层 Trace、错误与持续时间，不改变业务权威 |
| [#3435](https://github.com/42433422/XCMAX/pull/3435) | `de1e26d479223df7e140b5fbeca604b60e430c7d` | 宿主客来来；配套 [Kellai #2](https://github.com/42433422/kellai/pull/2) 还需核对 gitlink、scope 和真实回执 |
| [#3398](https://github.com/42433422/XCMAX/pull/3398) | `59034f0d4893000950bcda4a70fc2ed4e74cd8c6` | 企业自治、预算与业务反馈；原 MODstore 事务和资金责任不由宿主摘要替代 |
| [#3396](https://github.com/42433422/XCMAX/pull/3396) | `a0cf41c3f3d9007089d327fc86241938ce4eed72` | 调度治理来源；与 #3398 的包含关系须按提交祖先核对，不重复应用 |
| [#3415](https://github.com/42433422/XCMAX/pull/3415) | `ae2ddf0094ef326155b1ceaf5314252c9c5e8f47` | 市场模块/员工分类，复用原目录和安装链 |

本表不授权整批合入，不修改原主序列或架构评审。整合者逐项记录“保留 / 适配并指向替代提交 / 退休并证明旧调用方退出 / 仍未完成”。已有集成 PR（如 #3418）不因包含旧 head 自动涵盖本表的新 head；有文件重叠也不自动等于同责重复。

### 9.4 验收与关闭条件

每项关闭记录须包含 U 编号、被验提交、入口/场景、原 request/task/run/attempt 映射、独立业务回执、测试或 CI 链接和剩余边界。敏感账号、客户数据和正文使用权限受控证据；公开文档只放必要身份摘要。缺环境、skip、未运行不记通过；业务 unknown 不记业务完成，正确保留 unknown 并禁止重放的负向测试可通过对应保护合同验收。

| 验收组 | 必须证明的行为 | 可复用的现有测试入口（不是本轮通过记录） |
|---|---|---|
| 准入与调用方迁移 | 同范围同键并发一个赢家，同范围同键改内容拒绝；跨账号/租户/Mod 不得复用原任务或回执；事务失败不留半条 task/run；旧无键客户端明确能力边界；各入口独立验证 | [registered capabilities](../../tests/test_application/test_registered_capabilities.py)、#3441 新增准入回归 |
| 权限与审批 | 换主体/租户/Mod/员工权限/工作区/计划/工具合同拒绝旧批准；排队与恢复重新核对；批准仅续接原动作 | [approval persistence](../../tests/test_application/test_approval_persistence.py)、[employee write approval](../../tests/application/test_employee_runtime_write_approval.py) |
| 恢复与副作用 | 发送后丢回包、崩溃、租约过期、多设备部分成功只查原回执；未知不重放；对端无精确查询保持人工核对 | [tool idempotency](../../tests/test_application/test_tool_idempotency.py)、[native recovery](../../tests/test_application/test_native_task_recovery.py)、[task execution](../../tests/test_application/test_task_execution_repository.py) |
| 状态与投影 | waiting/unknown/paused 不被 success/EOF 覆盖；队列故障可见；迟到 worker/旧 run 不覆盖新代次；聊天/桌面/移动与原回执一致 | [task lifecycle](../../tests/test_domain/test_task_lifecycle_acceptance.py)、#3446 等待态反例 |
| 容量与上下文 | 原问候携完整工具目录按实际模型选路；预算/发送同一能力快照；工具调用/回执成组，已接受澄清保留；摘要失败不推进游标 | [context budget](../../tests/test_application/test_context_budget_regressions.py)、[clarification roundtrip](../../tests/test_application/test_planning_clarification_roundtrip.py) |
| 浏览器与外部适配 | 两个直接候选使用同一套 origin/locator/取消/截止时间/上传下载/核验合同；MCP 丢会话不伪造续接；Kellai/Para 分别核对授权和原请求回执 | #3430/#3434/#3439 的真实浏览器回归、#3435 跨仓回执；缺环境不记通过 |
| 核验、Trace 与记忆 | 公共分类与领域读回一致；ACK/文本不冒充成功；Trace 故障不重发；业务反馈引用原证据和时间，不覆盖事实 | [employee verifier](../../tests/application/test_employee_result_verifier.py)、§9.2 U09/U10 的消费者回归 |

完成文档登记后还须在同一集成提交验证上述合同，并沿原 CI/评审流程合入；发布与真实业务验收另记精确身份。仅更新本文件不会自动删除旧实现、接通入口或取得生产验收。
