# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 本文件约束跨组件职责与迁移验收；账号授权、事件、版本和发布仍分别服从已登记领域的规范。实现现状以指定提交的源码与实际回执为证，文档不能覆盖运行事实。
> 最后更新：2026-11-21 · 登记：[SSOT_INDEX.md](../SSOT_INDEX.md)（领域 `process-flow`）。本轮核查基线：[main@171418352d24667a7123b6556c55bad445ef3440](https://github.com/42433422/XCMAX/commit/171418352d24667a7123b6556c55bad445ef3440)；开放候选见 §9.3。

---

## 1. 目的与范围

本文档定义 XCMAX（FHD 企业桌面 ERP + AI 员工平台）的**业务工作流程**与**对外交付流程**，作为 AGI 主导编排时的流程基线。目标是让每一段业务链路上升为可触发的 `WorkflowDefinition`，并使 AGI 能回答三个问题：

1. **观察**：某张单据/某个业务对象当前处于哪个环节？
2. **决策**：下一步有哪些合法动作、各自风险等级、是否需要人签核？
3. **执行**：动作由谁触发（LLM 编排 / 事件驱动 / 人工），落库何张单据？

范围：**业务域状态、跨域编排、组件权威归属及迁移验收**。CI/CD 与合入顺序见 [CI_SSOT.md](../../../docs/CI_SSOT.md)，自治运营见 [autonomy.md](../../../docs/autonomy.md)。本轮为源码核对与规范修订，未执行真实业务或重跑候选 PR 的测试。

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

以下为宿主聊天主链规范；公共工具、员工、移动端与外部执行器的迁移范围和剩余边界见 §9，不能据此宣称全部入口已统一。

在线聊天流式、非流式及语音命令入口共用 `AIChatApplicationService`；compat 端点只做鉴权、格式适配和调用该主服务。每条消息都交给账户配置的平台模型，由模型选择生成普通回复或完整业务计划；不再用本地对话分类分流，也不保留独立直回复路径。两种输出都进入同一个 `LangGraph StateGraph`：普通回复作为内部无副作用节点运行，业务计划则在图执行前经独立于模型的确定性审核，核对图结构、工具动作、参数引用、服务端风险/幂等属性、当前权限和计划节点绑定。模型输出缺失、无效或被拒绝时明确失败，不回退到规则计划或未核验的业务回答。会话历史、跨会话个人记忆及本轮授权知识随请求提供；个人记忆按当前用户、租户和 Mod 授权独立注入，不依赖企业知识库权限。审批快照绑定完整计划和当前工具契约摘要；恢复时复核请求归属、租户、参数、整张计划、步骤清单及当前工具契约。代码在副作用后读取工具回执及业务状态；模型回复和运行状态不能代替业务核验。语音命令不再本地分类后直接调用工具。旧 workflow engine、旧普通聊天意图执行器和 shadow/canary 执行分支已退役。

LangGraph 处理 AND 依赖、条件分支、未选分支、澄清/审批暂停、失败终止与死端。工具错误、超时、权限拒绝、限流和熔断保留结构化结果及恢复提示；安全的短暂故障可自动重试，配额/并发拒绝标为未执行并等待后续重试，副作用结果未知则转人工核对，禁止自动重放。审批驳回会取消挂起计划。只有工具自带明确补偿契约的动作才可回滚，系统不猜测通用回滚。

模型入口按认证账户限 60 次/分钟、租户限 600 次/分钟（可用 `XCAGI_MODEL_CALLS_PER_MINUTE` 与 `XCAGI_TENANT_MODEL_CALLS_PER_MINUTE` 覆盖），进程并发上限默认 32，单账户/供应商连续 5 次瞬时失败后熔断 30 秒；工具入口按租户/动作限 120 次/分钟，单进程并发上限 32、单租户上限 16、单租户动作上限 8，连续 5 次瞬时故障后按租户动作熔断 30 秒。生产/预发布要求 Redis 分布式速率限流；Redis 不可用时限流门禁 fail-closed；并发闸门和熔断在每个应用进程内生效。平台余额与套餐仍由模型平台核算。

短期会话历史按用户、租户、Mod 与会话隔离；可召回个人记忆跨会话共享，但仍按用户、租户和 Mod 隔离。向量记忆最多保留 90 天/400 个片段，并在写入或召回时物理清理过期/超额片段，单次模型上下文最多 120 条、48,000 字符。凭据在记忆存储与模型上下文中脱敏；附件记忆只保留名称、类型和大小。线上业务查询不再由旧 slot 路由或直达处理器短路，模型没有生成有效计划时不执行。离线模式只开放原有受限本地业务处理，不提供普通离线大模型问答。代码、模型回复或 checkpoint 状态都不是业务成功证据；验收须以原始场景核对业务读回。

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

后续补齐的是原订单、批准计划、实际履约和客户确认之间的可追溯关联；应先核对现有领域服务，不能再新建一套订单域或依据字段存在宣称交付完成。

## 5. 统一单据生命周期规范（AGI 编排契约）

统一跨域读取与结果解释，保留领域状态的含义。销售订单已有商业 `state`、`invoice_status`、`payment_state` 和按明细数量派生的履约维度；旧线性 `status` 是兼容读取，不能覆盖这些正交维度。
跨域投影应携带原对象 ID、所属账号/租户、来源、版本/观测时间和核验状态；过期或来源不可读时回查原系统并保留未知。任务控制态、审批决定和业务完成态分别读取，不把所有业务表迁成同一套 `pending/completed` 枚举。

## 6. 流程自动化与 AGI 编排就绪度矩阵

| 范围 | 本轮已核对 | 后续验收证据 |
|---|---|---|
| 采购、发运、服务、财务 | §3 的模型/处理器/调度源码可定位 | 同账号原始输入、批准、业务写入与独立读回；本轮未执行 |
| 销售与客户交付 | §4 的订单模型和事务执行入口可定位 | 原计划确认后不中途换计划；履约/会计/导出/客户确认逐项回读；本轮未执行 |
| 跨入口统一 | §9 的来源关系与具体静态缺口 | 同一集成提交的原子准入、恢复、权限、核验及各客户端回归；开放 PR 不计为 main 已完成 |

## 7. 断点与行动项（按依赖落地）

1. P0：先收敛 §9 的能力合同、准入身份、审批消费、幂等与状态投影，迁移仍独立派发的旧入口。
2. P1：再整合浏览器候选、模型容量、上下文、业务核验与观测；逐入口核对，不用公共入口的单测替代其他消费者。
3. P1/P2：各业务域和外部执行器按原领域身份接回执与反馈；按 §6 完成原始业务场景。合入顺序由原仓库流程决定，本表是技术依赖，不能代替排队批准。

## 8. 维护约定

- 业务域/状态机变更同步 §3–§6；组件归属或调用方迁移同步 §9，更新精确提交、替代路径、剩余边界和验收结果。
- 本文档为纯文档 SSOT，沿用 [SSOT_INDEX.md](../SSOT_INDEX.md) 的 `docs-ssot` 登记；未新增机器检查器，不虚构 enabled 领域。登记 lint 通过只证明文档一致，不证明业务通过。
- 来源、权限、事件、价格、发布配置仍在各原领域维护；这里只记录跨域关系，不复制其配置值。新增兼容入口须指向现有实现；退出旧路径须给出删除或纯转发证据。

## 9. 组件权威来源、迁移与验收

### 9.1 判定口径与共同边界

以下是 **14 项统一性核查范围，不是已证实的 14 套重复实现**。“已定位”仅表示本轮已读源码；“候选”指未合入的 PR；“待核验”表示证据不足，不等同于缺失。实现、分支回归、main 合入、同 SHA 发布和真实业务验收分别记录，不相互替代。

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
| [#3441](https://github.com/42433422/XCMAX/pull/3441) | `910babadc74559628ae3713b11b686e2dcd50c6c` | 原子准入/状态候选；其 [§2.2](https://github.com/42433422/XCMAX/blob/910babadc74559628ae3713b11b686e2dcd50c6c/FHD/docs/architecture/PROCESS_FLOW_SSOT.md) 为实现证据，本文不占用该章节或提前宣称 publish_task_run 已在 main |
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
