# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 与任何业务文档冲突时，以本文件为准。
> 最后更新：2026-11-22（本次核对统一能力、执行入口与回执，§2.2–§2.3；其他业务域矩阵未重新验收） · 登记：`docs/SSOT_INDEX.md`（领域 `process-flow`）

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
- 管理端员工执行必须提供稳定请求键；缺键拒绝为未开始，不再直接调用员工运行器。注册能力及管理端同步路径的原子准入不冒充后台 SQL 队列租约；`_execute_with_durable_lease` 的 metadata 也不是分布式锁。
- Web 管理端不再自动切换到缺少原键回读契约的 market 或旧 Mod HTTP 执行口；新本机入口不可用时明确阻断。已有员工执行器和 Mod 组件仍由新本机入口调用，部署须保持前后端同版。
- 通用 unknown 状态仍需要原工具/执行端的确定回执或人工核对。没有业务供应方的幂等接口和读回凭证，LangGraph 检查点、数据库事务及客户端去重不能证明外部副作用恰好一次。
- Codex 的 thread/turn/item 协议是本次状态对照来源；本仓既有超级员工与中继适配不因此自动获得完整 app-server 协议、所有模型能力或生产成熟度。
- 本地 SQLite/内存并发和 Web 定向测试属于代码、自动测试证据。真实 PostgreSQL、多进程长时间故障演练、项目固定 Flutter 工具链、真实模型/设备及部署同版验收须分别取得证据；未执行项不能记作通过。合入、部署和运行身份以 PR/CI/发布回执为准。

### 2.3 能力契约与调用方迁移（T03–T12）

本节记录集成候选的代码边界；不把分支回归视为主干、发布或真实业务联调通过。

唯一权威能力是 `ToolActionSpecV2`。内置动作只在现有 `risk_actions.registry.json` 定义，外部 MCP 只经现有注册器装载；身份重复即拒绝，供应方移除的动作不保留旧授权。Workflow、模型工具、AIOPEN 与小 C 都从 `capability_catalog.py` 投影这份契约。OpenAPI 的 HTTP 路径只作非执行资源说明，不能成为第二套能力或任意 URL 执行通道。

| 项目 | 集成实现 | 重点回归 |
|---|---|---|
| T03 权威目录 | 删除重复参数表与商品能力注册；保留原 MCP 动作名、完整 schema 与版本 | `test_tool_spec_v2.py`、`test_capability_catalog.py`、MCP 注册回归 |
| T04 小 C 真实发现 | 重新核对有效账号、租户、Mod、员工工具授权、API Key scope 和实际员工包；管理端复用现有可信上下文桥接 | `test_capability_catalog.py`、`test_xiaoc_admin_context.py`，MODstore butler/context 回归 |
| T05 统一执行 | 小 C、REST、MCP、Planner 和员工调用进入注册能力及现有 AgentTask/AgentRun 执行链 | `test_unified_tool_entry.py`、`test_tools_execute_agent_route.py`、`test_aiopen_operation_call.py` |
| T06 权限、审批与幂等 | 真实会话密封绑定；同一契约权限、原任务键与审批摘要；审批后重查凭据、连接与 schema；不接受模型自报身份/批准 | `test_approval_scope_binding.py`、`test_tool_receipt_permissions.py`、AIOPEN 真实会话回归 |
| T07 稳定状态与回执 | 原 task/run/step/approval/request 标识贯穿执行与核验；不同等待原因保留；未知结果禁止自动重放 | §2.2 回归及 `test_verification_recovery.py` |
| T08 现有企业状态 | `business_db.read`、`tasks.query` 与实际员工目录读取现有仓储；按权限裁剪实体；不另建企业状态表 | `test_task_query_capability.py`、真实 SQLite 归属与撤权回归 |
| T09 外部适配 | MCP/Para 沿用共享契约；客来来绑定当前用户/租户/授权范围，固定本机传输，原 run/step 派生供应方请求 ID；OpenClaw 使用受审批能力 | `test_kellai_tools.py`、`test_kellai_binding.py`、共享执行与 OpenClaw 回归 |
| T10 核验与反馈 | 分派前冻结契约；保存不可变回执摘要；独立业务读回；只有已持久化且同源的核验结果可回写原会话记忆 | `test_result_verification_engine.py`、`test_verification_integrity.py`、`test_verified_result_feedback.py` |
| T11 旧调用迁移 | 桌面公共请求层、手机既有 turn、管理端 SSE/员工请求、Planner Mod、业务 REST 和外部 SDK 使用稳定原请求；业务路由只做格式与可信上下文适配 | 桌面请求层、手机回执、MODstore 前端和业务路由真实会话回归 |
| T12 删除重复实现 | 删除旧 tools executor/context、tools_payload 执行族、员工重复目录、任意 HTTP gateway、AIOPEN 独立审批、Qclaw/OpenClaw 直达执行、旧 skills/Workflow 业务别名、随包 Mod 私有处理器及前端令牌解锁重发与任意 URL 执行回退；旧导入实现退役，使用现有 ELT 契约 | 活跃调用扫描、已迁移入口回归、preflight 与 CI |

审批前不能执行业务写入。旧全局业务表的限制直接进入契约 `data_scope=legacy_global` 和共用权限门禁，管理员身份也不能让企业租户越界；已实现严格归属的客户删除、发货记录等沿用其现有租户仓储。工具目录不公开账号不可执行的旧全局能力，产品发现与执行共用套餐及权限检查。SQL 工具按当前可信租户进入严格归属范围；旧数据迁移开关不能使无租户行可读、可改或可删。模板上传与自动保存先按真实身份暂存内容及摘要，经同一上传能力审批后读取绑定字节；文件改变不能复用原批准。

桌面任务卡缺少有效能力契约时明确未开始，不向任意 URL 发起执行；已有原 run 的历史卡仍可只读核对原回执。旧 `requires_token` 保留为等待授权，解锁事件不能重发任务或充当审批。Excel 的读取、结构、查询和统计明确只读；查询必须提供有界 `query_expression` 并使用现有安全筛选器，结构直接读取真实表格，已移除失效的自然语言转任意 Pandas 代码执行链。

核验读取原始调用与当前真实业务对象，`success=true`、模型文本、HTTP 200 和供应方已受理都不能单独证明写入完成。凭据/连接变化、证据不匹配、丢失回执、尚有未核对副作用或其他 worker 持有租约时不能推进原任务。历史写入缺少核验契约时保留原回执及未知状态，后续安全读取成功也不能使整体任务完成。已回答的澄清步骤须有同一 run 的宿主回答事件才能认作控制转换；单独的答案字段不能绕过核验。回写小 C 的记忆必须绑定已持久化终态、原会话、原回执摘要及核验报告，重复核验不重复写入。

尚未取得的证据与能力边界：

- 当前源码没有找到可复用的真实企业地图数据源；系统能力地图不作为企业数据地图交付。
- 员工自建工具的生命周期表仅有定义、版本与参数校验，没有执行实现绑定；管理定义仍可查询并明确 `executable=false`，不会添加进模型可执行目录或把校验记录标为执行中。
- 太阳鸟 Mod 的客户、产品旧 SQLite 写入没有现成的统一归属契约；未经授权的独立写入入口停止提供执行能力，保留其原数据，不能静默改写为宿主的另一套业务库。
- 无租户的平台账号不能借用其他企业的审批存储。现有审批表与快照要求真实租户，缺少该范围的业务写入明确拒绝为未开始；不会创建假租户、绕开隔离或另建审批引擎。
- 客来来配套 [供应方 PR #2](https://github.com/42433422/kellai/pull/2) 已合入供应方主干，本集成将 gitlink 固定到该 PR 的 `8cf46e8313e658767098f4c810f4498c3fe6b6a0`。本地供应方部署及真实渠道发送/送达尚未验收；历史无账号绑定须重新配对，默认范围仍只读。
- 通用 MCP 适配不等于所有浏览器或 Para 特性已验收。只有已安装、已授权且有实际实现的动作可发现；没有独立核验器的写入不会因执行器自报成功而完成。
- 本地自动回归不能代替同提交 CI、受保护主干审查、正式部署和真实账号/设备/供应方联调。T12 的交付关闭仍须这些回执，不能仅凭删除清单宣布完成。

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
| 销售订单 Order / Sale | — | ❌ **无模块** |
| 发货单 | `shipment.py` | ✅ 有 + 打印 |
| 交付回执 / 客户签收 | — | ❌ **无** |

**断点结论**：系统能「采购 → 入库 → 发货」，但缺「销售订单 → 交付回执」对外的闭环。AGI 无法感知"客户要什么"，只能管"库存补什么"——这是 AGI 主导的最大障碍。

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
| 交付线 | ❌ 无订单 | ❌ | ❌ | ❌ | 🔴 |

图例：🟢 可自主闭环 · 🟡 半自动（需人签核）· 🟠 未编排 · 🔴 域缺失

## 7. 断点与行动项（AGI 主导落地序）

P0（域补齐，先做）：
1. 补齐**销售订单 → 交付回执**域，打通"客户需求 → 采购 → 发货 → 交付"全链。
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
