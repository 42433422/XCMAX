# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 与任何业务文档冲突时，以本文件为准。
> 最后更新：2026-11-10 · 登记：`docs/SSOT_INDEX.md`（领域 `process-flow`）

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
