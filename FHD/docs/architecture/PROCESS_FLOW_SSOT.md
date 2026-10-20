# 业务流程与交付流程 SSOT（AGI 编排的流程唯一真相源）

> **本文件为 XCMAX「工作流程 + 交付流程」的唯一真相源（SSOT）**，供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费。
> 与任何业务文档冲突时，以本文件为准。
> 最后更新：2026-08-05 · 登记：`docs/SSOT_INDEX.md`（领域 `process-flow`）

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

### 2.1 执行入口与状态归属（核心审计整改候选，2026-10-20）

以下是源码责任边界，不代表候选已合入、部署或通过真实业务验收。路径以仓库根为准；MODstore 前缀为 `成都修茈科技有限公司/MODstore_deploy/modstore_server/`。

| 入口 | 执行 owner / 事务台账 | 重试与结果合同 |
|---|---|---|
| FHD `agent_orchestrator/unified_task.py` | `task_background.py`；`run_sql_repository.py` 与 `task_execution_sql_repository.py`（均在 `FHD/app/application/agent_orchestrator/`） | Run/Step 与队列租约归属；unknown 不等于失败可重派；生产持久化初始化失败拒接 |
| FHD `app/di/registry.py` 的 workflow runtime | `app/application/workflow/runtime/`；checkpoint bridge | legacy 默认，其他模式显式配置；Workflow 与 AgentStep 入口共享条件/依赖规则，审批续跑保留分支决策；未选分支不执行 |
| FHD `xcmax_admin_part03_part01.py:local_employee_execute` | `employee_runtime/executor.py`；`run_ledger.py` 的租户日志（分别位于 routes 与 application） | 单次请求执行一次；工具授权在最终 dispatch；error/accepted/unknown 不得 verified；业务完成另需独立 readback |
| MODstore `customer_issue_intake.py` → `incident_bus.py` | outbox、唯一 incident 与 dispatch claim；`incident_team_dispatch.py` | 保留 event/task/attempt 身份；已受理或结果未知只核对原任务；新 fix 使旧 verify 失效 |
| MODstore `admin_duty_graph_api_part02.py` / `employee_orchestrator.py` | 持久 DutyRun/节点或动态图运行记录 | 下游仅接受成功依赖；失败、跳过、pending 分开；传统 workflow 必须到达 end 才能成功 |
| MODstore Para handler / 可选 Mac Control | 外部 API task ID / `mac_control_store.py` attempt | HTTP 200 不等于完成；子任务集合与原 ID 必须匹配；默认关闭的 Mac Control 不能替默认 Para 通道验收 |

跨入口回归以 `test_plan_graph_execution_contract.py`、`test_employee_run_tenant_isolation.py`、`test_tool_execution_deadline.py` 及 MODstore `test_workflow_terminal_contract.py` 为入口。稳定 facade 保留，新增合同应复用已有结果判定，避免反向动态 import 扩散。尚未提供真实进程隔离的同步工具在未开启严格 deadline 模式时仍可能挂起；该 F08 缺口及真实容量、连续 SLO、同发布 SHA 业务/恢复验收不得由本表替代。

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