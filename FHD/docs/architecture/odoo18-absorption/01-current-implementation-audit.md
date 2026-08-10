# ODOO-W0-02｜ERP 吸收可信度审计（Current Implementation Credibility Audit）

- **目标项目**：Odoo 18（吸收源）
- **本仓项目**：FHD
- **审计范围**：`FHD/` 下已提交的 Odoo 派生实现（销售/复式记账/报表/多地址/补货/Agent 注册表/澄清门控/对话路由）
- **审计方式**：只读代码走查 + 内存库/临时目录探针（不改产品测试、不改配置、不改包、不改 KB/JSON/lock、不写 git、不联网、不 rm、不用 uv）
- **审计日期**：2026-08-10
- **基于**：`XCAGI/kb/absorption/odoo18/absorption_tasks.json`（9 项待吸收能力清单）

> 本文件为本次任务唯一新增/改动路径。所有被引用路径在审计时均已核实存在。

---

## 0. 结论摘要（TL;DR）

> **最高诚实成熟度主张**：Odoo 吸收目前处于 **「模型层 + 注册表层可信、业务副作用层未接通」** 的骨架阶段。
> 9 项能力中 **2 项可信（多功能地址、Agent 注册表）、6 项部分（销售闭环、复式记账、报表、补货、澄清门控、对话路由）、1 项缺失（多单位换算）**。
> **销售→收款闭环、开票/收款记账、发货扣库存这三条 ERP 核心业务副作用全部未落地**——它们只以“状态字符串推进”存在，绿色单测无法证明其业务效果。

关键差异（一句话）：**结构（schema/模型/注册表）基本到位，行为（状态机严格性 + 库存、应收/收入、现金/应收记账副作用）大面积缺失。**
结构本身也仅是 **骨架/中低**：ERP 表无专属 Alembic 迁移、唯一约束为全局、DB 层允许不平衡的已过账（posted）记账凭证提交。

---

## 1. 当前测试基线（Current Test Baseline）

命令（在 `FHD/` 下，`.venv/bin/python` = Python 3.11.15）：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_sales_model.py \
  tests/test_services/test_accounting_model.py \
  tests/test_services/test_accounting_services.py \
  tests/test_services/test_erp_e2e_modules.py \
  tests/test_services/test_report_service.py \
  tests/test_application/test_customer_app_service.py \
  tests/test_application/test_workflow_clarification.py \
  tests/test_services/test_tools_workflow_registered.py
```

| 测试文件 | 用例数 | 实测结果 |
|---|---|---|
| `tests/test_services/test_sales_model.py` | 8 | 8 passed |
| `tests/test_services/test_accounting_model.py` | 6 | 6 passed |
| `tests/test_services/test_accounting_services.py` | 8 | 8 passed |
| `tests/test_services/test_erp_e2e_modules.py` | 5 | 5 passed |
| `tests/test_services/test_report_service.py` | 35 | 35 passed |
| `tests/test_application/test_customer_app_service.py` | 39 | 39 passed |
| `tests/test_application/test_workflow_clarification.py` | 19 | 19 passed |
| `tests/test_services/test_tools_workflow_registered.py` | 96 | 96 passed |
| **合计** | **216** | **216 passed** |

> **直接相关缺口**：`tests/` 下 **不存在** `test_sales_app_service.py`（销售服务层闭环无任何测试）、**不存在** `test_replenishment_service.py`（补货服务无测试）、**不存在** `test_report_sales_order.py`（新 SalesOrder→报表无测试）。所谓“销售闭环”目前只有模型层 `tests/test_services/test_sales_model.py` 的 8 条状态字符串断言。

---

## 2. 9 项吸收任务映射与可信度分类

> 分类定义：**缺失**（无对应实现）｜**表面**（有字段/占位，无行为）｜**部分**（有机制，业务副作用/集成缺失）｜**可信**（机制+副作用+测试齐备）。

### od-absorb-01 销售到收款闭环（Sales-to-Payment）— **部分（骨架可信，业务副作用缺失）**

- 模型：`app/db/models/sales.py` `SalesOrder`(L20) / `SalesOrderItem`(L73)，状态常量 `SALES_ORDER_STATUS_FLOW`(L15)，`advance()`(L45-54)。
- 服务：`app/application/sales_app_service.py` `quote()`(L77) / `_advance()`(L148) / `deliver()`(L170) / `invoice()`(L173) / `payment()`(L176) / `cancel()`(L197)。
- 探针证据（内存库，patch `get_db`）：
  - **跳过转移未被禁止**：`quote→invoice` 直接成功（`invoice` 返回 success，状态变为 `invoiced`）。`advance()` 只校验“回退”，不校验“跳步”。
  - **发货无数量/库存副作用**：`deliver()` 后 `SalesOrderItem.delivered_quantity` 仍为 `0.0000`；`inventory_ledger` 无任何行。
  - **开票无应收账款/收入记账**：`invoice()` 后 `journal_entries` 中无 `reference_type='sale'` 行。
  - **收款无现金/应收账款记账**：`payment()` 后无 `reference_type='payment'` 行。
  - **收款未按“已开票”门控且可重复收款**：对处于 `quote` 的订单直接 `payment()` 成功；同一订单 `payment(100)` 两次，`paid_amount` 累计为 `200.0`（超收/重复收款无守卫）。
- 判定：**单一线性状态机**（quote→confirmed→delivered→invoiced→paid）的“字符串推进”存在且测试覆盖，但业务副作用（库存、记账、部分交付、收款分配）全部缺失 → **部分**。

### od-absorb-02 财务复式记账（Double-entry）— **部分（机制可信，业务事件未自动接入）**

- 模型：`app/db/models/accounting.py` `ChartOfAccount`(L17) / `JournalEntry`(L40，`reversed_of_id/reversed_at` L54-55) / `JournalEntryLine`(L90)，`is_balanced()`(L61)。
- 服务：`app/services/accounting_services.py` `create_journal_entry()`(L108，借贷平衡校验 L143-147) / `seed_default_chart_of_accounts()`(L229) / `journal_entry_reverse()`(L247) / `aging_report()`(L311)。
- 关联：`app/db/models/finance.py` `FinancialTransaction.journal_entry_id`(L27)。
- 探针/测试证据：手工构造“借应收/贷收入”“借库存/贷应付”平衡分录通过；`test_erp_e2e_modules.py` 链路 1 证明采购入库自动生成 `借1401/贷2201` 平衡分录（L105-158）；冲销/账龄测试通过。
- **缺口**：销售订单 `invoice()`/`payment()` **不会自动生成**任何记账凭证（探针证实）。复式记账目前只被“采购入库”与“手工 `journal_entry_create`”触发，**销售侧的收入/应收/现金记账链未接入**。
- **判定**：借贷平衡、科目表、冲销、账龄机制可信，但销售/收款不会自动生成凭证 → **部分**。

### od-absorb-03 报表中心工具化（Reporting as tools）— **部分（工具已注册，数据源未接 SalesOrder）**

- 注册：`config/risk_actions.registry.json` `reports`(L714-749)；路由 `app/services/tools_workflow_registered.py` `_registered_router_reports`(L586-619)。
- 服务：`app/services/report_service.py` `get_sales_report()`(L40-115)。
- **关键缺陷**：`get_sales_report()` 查询的是 **遗留 `ShipmentRecord`**（L48 `db.query(ShipmentRecord, ...)`），**不是新增的 `SalesOrder`**。即“销售报表”不读吸收后的销售单状态机，新销售数据对报表不可见。
- 判定：工具/路由/注册齐备，但销售报表数据源与 SalesOrder 脱节 → **部分**。

### od-absorb-04 多单位换算（UOM）— **缺失**

- `app/db/models/product.py` `Product.unit`(L25) 为单值字符串；`InventoryLedger.unit`(inventory.py L64) 亦为字符串。
- **全仓无 UOM 换算表/换算系数**；`normal_chat_dispatch.py` 无单位换算逻辑（仅“出 500 斤”类歧义无处理，见 od-absorb-08）。
- 判定：无任何换算实现 → **缺失**。

### od-absorb-05 客户多地址（发票/送货分离）— **可信**

- 模型：`app/db/models/crm.py` `CustomerAddress`(L15)，`ADDRESS_TYPES={invoice,delivery}`(L12)。
- 服务：`app/application/customer_app_service.py` `add_address()` / `get_addresses()`（经 `test_customer_app_service.py` 39 条 + `test_erp_e2e_modules.py` 链路 4 覆盖）。
- 判定：模型+服务+测试齐备 → **可信**。

### od-absorb-06 库存补货预警（Replenishment alert）— **部分**

- 服务：`app/services/replenishment_service.py` `suggest_replenishment()`(L19-71)，基于 `Material.min_stock/max_stock`（L32 过滤，L40-43 建议量）。
- 注册：`risk_actions.registry.json` `inventory.low_stock_alert`(L534) / `replenishment_suggest`(L540)；路由 `tools_workflow_registered.py` L452-465。
- **缺口**：补货建议作用域是独立的 `Material` 表，**未与 `InventoryLedger`/`Product` 的库存阈值打通**；`Product`/`InventoryLedger` 无 `min_stock/max_stock` 字段。低库存口径与“库存报表/看板”的 `InventoryLedger.available_quantity<=0`（report_service.py L301-306）不一致。
- 判定：对 Material 可用，但未集成到库存/产品阈值 → **部分**。

### od-absorb-07 Agent 工具注册表扩容（Registry expansion）— **可信（含边界）**

- 配置：`risk_actions.registry.json` `sales`(L646-713) / `reports`(L714-749) / `finance`(L750-820) / `inventory`(L534-561)，均带 `risk/idempotent/required_params/action_class`。
- 路由映射：`app/services/tools_workflow_registered.py` `_REGISTERED_WORKFLOW_ROUTERS`(L3094-3132) 含 `sales/reports/finance/mrp`。
- 参数校验：`app/services/tools_execution/registry.py` `REQUIRED_PARAMS_BY_TOOL_ACTION`(L55-121) 含 `sales/finance`。
- 测试：`test_tools_workflow_registered.py` `TestErpToolRegistry`(L601+) 覆盖 sales/reports/finance 的 risk/idempotent/required_params。
- 判定：销售/报表/财务/补货工具均已注册且标注齐全 → **可信**。边界：`init_db.py` `ensure_erp_bootstrap()`(L1281) 已建 ERP 表，但 `_WorkflowRouterMap._hidden_keys`(L3088) 隐藏 `employee/business_db`，销售链路仍需在真实 DB 接通。

### od-absorb-08 反问澄清业务化（ERP clarification gate）— **部分**

- 现状：`app/application/workflow/clarification_node.py` 处理参数缺失/同名歧义（`_action_required` L80-88、`needs_clarification` L135）。
- 测试：`test_workflow_clarification.py` 19 条通过。
- **缺口**：无 ERP 业务维度澄清——多单位（“出 500 斤”）、报表口径、冲销/盘点、批量范围均未识别（UOM 缺失也导致无法就单位反问）。
- 判定：通用澄清机制存在，ERP 业务澄清未实现 → **部分**。

### od-absorb-09 对话路由与响应接入（Chat slot routing）— **部分**

- 路由：`app/application/normal_chat_dispatch.py` `report_keywords`(L72-87) / `replenish_keywords`(L144-149) / `sales_keywords`(L195-208)，均有对应 intent 与 slots。
- 服务接线：`tools_workflow_registered.py` 已可执行 `sales/reports/finance` 动作。
- **缺口**：`sales_keywords` 含独立 `"销售"` 单字(L199)，易过度命中；路由命中→执行→结构化返回的端到端仅由注册表测试覆盖，无“关键词→真正执行销售动作”的集成测试。
- 判定：槽位路由已加，但执行链覆盖不足且关键词过宽 → **部分**。

---

## 3. 最高诚实成熟度主张

### 3.1 一句话主张

> **FHD 当前对 Odoo 18 的吸收 = “Schema/模型 + 工具注册表面 + 通用机制” 已落地（2/9 项可信），但 “ERP 业务副作用闭环”（发货扣库存、开票记应收/收入、收款记现金/应收、部分交付、严格正交状态、多单位换算）尚未接通。结构本身也仅是骨架（无专属 Alembic 迁移、全局唯一约束、DB 层不校验借贷平衡）。**

### 3.2 各层成熟度

| 层 | 成熟度 | 依据 |
|---|---|---|
| 数据模型层（schema） | **骨架 / 中低** | ERP 表 **无专属 Alembic 迁移**，仅 `ensure_erp_bootstrap`(`app/db/init_db.py` L1281) 用 `Base.metadata.create_all(tables=missing, checkfirst=True)` 建“缺失表”，**无法 ALTER 既有 schema**；唯一约束为**全局**（`sales_orders.order_no`、`journal_entries.entry_no`、`chart_of_accounts.code` 均 `unique=True`，非租户复合）；**DB 模型允许不平衡的已过账（posted）JournalEntry 提交**（`is_balanced()` 仅内存方法，无 `CheckConstraint`）。在专属迁移与约束通过前，schema 只能按骨架/中低计 |
| 工具注册层（Agent 发现） | **高** | sales/reports/finance/replenishment 均注册 + risk/idempotent/required_params 齐全 |
| 通用机制层（借贷平衡/冲销/账龄/澄清） | **中** | 机制实现 + 测试通过；**但审批门控是 fail-open 而非 fail-closed**（`ApprovalService.check_node_requires_approval` L50-62 捕获注册表查询异常后返回 `False`），且**无“销售信号→审批→确认前不写→后置条件”端到端测试** |
| 业务副作用层（库存/记账/销售报表） | **低** | 探针证实发货/开票/收款无任何库存/记账副作用；销售报表读遗留表 |

> 因此不要宣称“销售到收款闭环已实现”。**诚实表述是：销售状态机与记账机制“可用并可测”，但离真正的业务闭环还差库存、记账、报表三个副作用接线，且结构层需先补专属迁移与 DB 约束。**

---

## 4. 优先级缺陷（Prioritized Defects）

### P0（阻断“闭环”可信度）

| 编号 | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| **P0-1** | 状态机为单一线性且允许跳步、收款未门控 | `SALES_ORDER_STATUS_FLOW`(sales.py L15) 强制 `quote→confirmed→delivered→invoiced→paid` 单一线性；`advance()`(sales.py L45-54) 只禁回退不禁跳步；`payment()`(L176) 不校验状态 → 探针 `quote→invoice` 直接成功、`quote` 态可收款 | 违背 Odoo 正交维度：商业单状态、履行、开票、收款应各自独立推进；实际业务可能“先开票后发货” |
| **P0-2** | 发货无库存/数量副作用 | `deliver()`(L170) 仅 `_advance`；探针 `delivered_quantity=0`、无 inventory_ledger 行 | “发货”不真实扣减库存，也无部分交付/backorder/return 建模 |
| **P0-3** | 开票/收款不生成记账凭证 | `invoice()`(L173)/`payment()`(L176) 仅改状态与 `paid_amount`；探针无 `reference_type='sale'/'payment'` 凭证 | 财务闭环断链，销售不进入账本 |
| **P0-4** | 销售报表读遗留 `ShipmentRecord` 而非 `SalesOrder` | `report_service.get_sales_report`(L48) | 新销售数据报表不可见，闭环“报表可查”验收失效 |
| **P0-5** | ERP schema 无专属 Alembic 迁移 + 全局唯一约束 + DB 层不校验借贷平衡 | `alembic/versions/` 无 `sales_orders`/`journal_entries`/`chart_of_accounts` 建表迁移（仅 `ensure_erp_bootstrap` 幂等 `create_all`）；`order_no/entry_no/code` 为全局 `unique=True`；`JournalEntry.is_balanced()` 无 DB `CheckConstraint` | 无法对既有库改 schema、跨租户编号冲突、可提交不平衡的已过账凭证 |

### P1（正确性/健壮性/一致性）

| 编号 | 缺陷 | 证据 |
|---|---|---|
| **P1-1** | 收款可重复/超收，无分配与冲销 | `payment()`(L176) 无条件累加 `paid_amount`；探针重复 payment 至 200.0；无 receivable 分配（unpaid/partial/paid/refunded） |
| **P1-2** | 多单位换算整体缺失 | `Product.unit`(product.py L25) 单值；无换算表 |
| **P1-3** | ERP 业务澄清缺失 | `clarification_node.py` 无多单位/报表口径/冲销/批量维度 |
| **P1-4** | 唯一约束为全局而非租户级 | `order_no`(sales.py L25)/`entry_no`(accounting.py L45)/`code`(accounting.py L22) 均 `unique=True`；探针跨租户同 `order_no` 抛 `IntegrityError` |
| **P1-5** | 补货作用域限于 Material，未接 Product/InventoryLedger 阈值 | `replenishment_service.py` L28-33；`Product`/`InventoryLedger` 无 min/max |
| **P1-6** | 服务层错误处理粗糙 | `quote()` 用不存在 product 时抛原始 `IntegrityError`（FK），未返回 `{"success": False}`（原子性由 `get_db` 事务作用域保住，见 `session.py` L97-113） |
| **P1-7** | `SalesOrderItem.status` 流程定义但从未推进 | `SALES_ITEM_STATUS_FLOW`(sales.py L17) 无 `deliver/invoice` 调用推进 |
| **P1-8** | 审批门控 fail-open（非 fail-closed） | `approval_service.py` `check_node_requires_approval`(L39-62)：风险注册表查询被 `except Exception` 捕获后返回 `False`（L60-62）→ 注册表异常/缺失时默认放行，**不写即不安全的“失败即关闭”缺失**；`ApprovalGatedEngine` 存在但**无销售“信号→审批→确认前不写→后置条件”端到端测试** |

### 已核实为“健康”的项（勿误修）
- **跨租户隔离**：`app/db/tenant_filter.py` `install_tenant_filter()`(L53, L107) 全局注入 `with_loader_criteria`；探针确认租户 2 读不到租户 1 的订单。写入在 `before_flush`(L87-103) 自动打标/拒绝。（注意：隔离有效，但**唯一约束仍是全局的**，见 P1-4/P0-5。）
- **借贷平衡 & 冲销幂等（服务层）**：`create_journal_entry` 拒写不平衡凭证(L143-147)；`journal_entry_reverse` 拒绝重复冲销(L258-262)。（注意：这是**服务层校验**，DB 层无约束，见 P0-5。）
- **Decimal 完整性（探针）**：`0.1×3` 经 float 计算后 `Decimal(str(...))` 落库为 `Decimal('0.30')`，被 `Numeric(18,2)` 刻度规整，测试样例无精度残差。注意金额先在 float 域累加（`sales_app_service.py` L117/L137），大数多行累加存在精度风险，属低严重度观察项。
- **注意**：**“审批与写入解耦”不再列入“健康”**。`approval_gated_engine.py` + `HybridRiskGate` 的代码存在（`app/application/workflow/approval_gated_engine.py` L107/L171），但**从代码存在不能判定健康**：既缺“销售信号→审批→确认前零写入→后置条件”的端到端测试，`ApprovalService` 又对注册表查询异常 fail-open（P1-8）。**fail-closed 审批是一个 required 工作项（见 W1-08）。**

---

## 5. 假性完成屏障（Fake-Completion Shields）

读这些“全绿”测试时要清醒——它们证明的是机制存在，不是业务闭环：

1. **`test_sales_model.py` 只测模型层状态字符串**：断言 `advance()` 的 `status` 字段变化，**不测** deliver 扣库存、invoice 生成凭证、payment 记账。→ 绿 ≠ 闭环。它甚至把单一线性状态机当“正确顺序”固化下来。
2. **`test_accounting_model.py` 手工构造平衡分录**：测试里是自己拼的“借应收/贷收入”，**不测**销售订单 `invoice()/payment()` 是否自动生成该分录；**也不测**不平衡分录能否被 DB 拒绝（DB 无约束）。
3. **`test_tools_workflow_registered.py` 只验注册表（配置字符串）**：断言 `reg["sales"]["actions"]` 存在且 risk/idempotent 正确，**不执行**任何销售动作。
4. **`test_report_service.py` 测的是 `ShipmentRecord` 报表**，不是新 `SalesOrder` → 报表“可查”验收被旧表数据掩盖。
5. **无 `test_sales_app_service.py` / `test_replenishment_service.py`**：服务层行为（建单推进、补货建议）零直接测试。
6. **失败路径被吞**：`quote()` 对不存在产品抛原始 `IntegrityError`，任何“成功”断言都不会走到该分支，故“原子回滚”从未被显式断言。
7. **审批“全绿”是假象**：注册表/机制测试只证明 `approval_gated_engine.py` 存在，**未证明**“销售写入在审批前零持久化、确认后才落库”；`ApprovalService` 对注册表异常 fail-open（P1-8）未在任何测试中捕获。

---

## 6. ODOO-W1 十条工单（implementation-ready，正交冲突无关架构）

> 验收以**业务后置条件**为主（“系统状态+库存+账本+报表四者一致”），不以“代码存在”为准。每条含：依赖、独占写区（既有路径或 TO CREATE 路径）、后置条件、聚焦命令（fail-closed）、受保护文件。

### 正交维度模型（替代单一线性状态机）

不强制“先发货后开票”（真实业务可能先开票后发货），采用 Odoo 派生的正交维度（self-research）：

- **商业单状态（commercial order state）**：`draft / quote / sent / confirmed / cancel`——独立维度。
- **履行（fulfillment，派生口径）**：**仅由 `ordered / reserved / delivered / returned` 数量**与 **stock moves**（复用现有 `inventory_transactions` 表，不新建 move 表）计算得出，**不读取订单金额**；含 `partial / backorder / return`。
- **开票状态（invoice status）**：独立计算；含 `invoice` 与 `credit-note` 链接。
- **收款状态（payment state）**：在 **receivables（应收）** 上跟踪分配；`unpaid / partial / paid / refunded`。

W1-01 一次性写出该正交 schema（**全部 ORM 模型**）+ 唯一 Alembic 迁移；W1-02..08 各自拥有独占文件、并行实现；W1-09 为唯一外观/路由/配置组装写者；W1-10 为端到端契约与桌面验收。**W1-02..10 一律保护全部 ORM 模型、迁移与 schema 注册文件，永不编辑它们。**

### 依赖图

```text
W1-01（唯一 schema + 唯一 Alembic 迁移写者：全部 ORM 模型 + 专属迁移 + schema 迁移测试）
   │
   └─►（并行，独占文件所有权）
        ├─► W1-02 销售生命周期命令模块
        ├─► W1-03 履行/预留/backorder/return 模块
        ├─► W1-04 开票/贷项通知单 & 记账模块
        ├─► W1-05 收款分配/退款/冲销模块
        ├─► W1-06 UOM 与补货服务
        ├─► W1-07 报表读模型
        └─► W1-08 fail-closed 预览/审批/幂等/租户工具契约
   │
   └─► W1-09（唯一外观/路由/配置组装写者：SalesAppService + 工具路由 + 风险注册表 + 对话路由）
             └─► W1-10（端到端契约 + 桌面验收）
```

依赖图：`W1-01 → 并行 W1-02..08 → W1-09 → W1-10`。**`config/risk_actions.registry.json` 仅由 W1-09 写入**；W1-08 不得触碰它（或其他路由/配置外观）。

### 独占所有权矩阵（Exclusive Ownership Matrix）

> **独占写区** = 该工单**唯一**可写入的路径。**自动化复核规则**：任一路径不得出现在多于一个工单的**独占写区**中；仅出现在“受保护文件”中的路径（只读边界，不授予写入权）不参与该去重判定。提交前须校验本文件不含『履行被锁定』与『降级不损失数据』之承诺，并人工核对矩阵中每个独占写区全局唯一。

| 工单 | 独占写区（唯一写入权） |
|---|---|
| W1-01 | `app/db/models/sales.py`、`app/db/models/accounting.py`、`app/db/models/inventory.py`、`app/db/models/product.py`、`app/db/models/__init__.py`（schema 注册）、`app/db/init_db.py`（fresh create 兜底）、TO CREATE `app/db/models/receivable_allocation.py`、唯一 `alembic/versions/YYYY_MM_DD_erp_absorb_orthogonal.py`、TO CREATE `tests/test_services/test_erp_schema_migration.py` |
| W1-02 | TO CREATE `app/application/sales_lifecycle_service.py` + `tests/test_services/test_sales_lifecycle_service.py` |
| W1-03 | `app/services/inventory_service.py`、TO CREATE `app/services/fulfillment_service.py` + `tests/test_services/test_fulfillment_service.py` |
| W1-04 | TO CREATE `app/application/invoicing_service.py` + `tests/test_services/test_invoicing_service.py`、`app/services/accounting_services.py` |
| W1-05 | TO CREATE `app/application/payment_service.py` + `tests/test_services/test_payment_service.py` |
| W1-06 | TO CREATE `app/services/uom_service.py` + `tests/test_services/test_uom_service.py`、`app/services/replenishment_service.py` |
| W1-07 | `app/services/report_service.py`、TO CREATE `tests/test_services/test_report_sales_order.py` |
| W1-08 | `app/application/workflow/approval_service.py`、`app/application/workflow/approval_gated_engine.py`、TO CREATE `tests/test_services/test_sales_approval_failclosed.py` |
| W1-09 | `app/application/sales_app_service.py`、`app/services/tools_workflow_registered.py`、`app/application/normal_chat_dispatch.py`、`config/risk_actions.registry.json`、既有 `tests/test_services/test_tools_workflow_registered.py`、TO CREATE `tests/test_services/test_sales_facade_integration.py` |
| W1-10 | TO CREATE `tests/test_services/test_erp_absorb_e2e.py`、TO CREATE 目录 `docs/evidence/e2e/odoo18-w1-desktop-acceptance/` |

---

### W1-01｜唯一 schema + 唯一 Alembic 迁移写者（全部 ORM 模型 / 分配 / 租户复合唯一 / DB 会计约束 / UOM / 补货规则 / schema 迁移测试）
- **依赖**：无（根）。
- **独占写区（唯一写入权）**：
  - `app/db/models/sales.py`（改造为**正交**：`state`=draft/quote/sent/confirmed/cancel；`fulfillment` 由 ordered/reserved/delivered/returned 数量派生；`invoice_status` 独立；`payment_state` 独立；新增 `backorder/return` 关联）
  - `app/db/models/accounting.py`（新增 `CheckConstraint` 强制 posted 分录借贷平衡；`credit-note` 关联字段）
  - `app/db/models/inventory.py`（**stock moves 复用现有 `inventory_transactions` 表**，不新建 move 表：在其上加 `ordered_quantity`/`delivered_quantity` 与 `sales_order_id`/`sales_order_item_id` 引用，即可作为履行 move 载体）
  - `app/db/models/product.py`（UOM category/factor；`min_stock/max_stock` 补货规则）
  - `app/db/models/__init__.py`（**schema 注册**：import 并 export 新增的 receivable allocation 模型，使它们进入 `Base.metadata`，`Base.metadata.create_all` 才能建出对应新表）
  - `app/db/init_db.py`（`ensure_erp_bootstrap` 的 **fresh create 兜底**：仅当缺表时用 `Base.metadata.create_all(tables=missing, checkfirst=True)` 建新表，**只服务于全新空库/一次性临时库**；不复制任何 ALTER/backfill 逻辑，也绝不替代 Alembic 对既有库的升级）
  - TO CREATE：`app/db/models/receivable_allocation.py`（receivables 分配：unpaid/partial/paid/refunded）
  - TO CREATE：`alembic/versions/YYYY_MM_DD_erp_absorb_orthogonal.py`（**唯一**专属迁移；含 `upgrade`/`downgrade`/`backfill`；SQLite 改动用 `op.batch_alter_table(recreate="auto")`）
  - TO CREATE：`tests/test_services/test_erp_schema_migration.py`（schema 迁移测试）
- **schema 注册说明**：新建的 receivable allocation ORM 模型必须在 `app/db/models/__init__.py` 中 import 并写入 `__all__`，否则 `Base.metadata` 不会登记其 `__table__`，`Base.metadata.create_all` 也无法建出该表。`ensure_erp_bootstrap`（`app/db/init_db.py` L1281）仅作 fresh create 兜底：对**全新**库以幂等 `create_all(tables=missing, checkfirst=True)` 补齐缺失新表；它**不写任何 ALTER/backfill**、**不替代 Alembic**。既有桌面库与既有数据库的升级**一律走** W1-01 的唯一 Alembic 迁移 `alembic upgrade head`，bootstrap 不得对其做任何 schema 变更。
- **后置条件（业务）**：`alembic upgrade head`（**forward upgrade**）在 **SQLite 与 PostgreSQL** 均成功（建表 + 改既有表 + 存量 **backfill**），**forward upgrade 与 backfill 保留全部既有数据**；`order_no/entry_no/code` 变更为 `UniqueConstraint(tenant_id, xxx)`（跨租户允许重复）；posted JournalEntry 借贷必平衡（DB 级约束）；UOM 换算与补货规则字段就位。**`downgrade` 仅在一次性（disposable）临时 DB 上验证**：恢复旧 schema 且可再次 `upgrade head`（幂等一致），并**显式文档化：新维度数据（正交状态/分配/租户复合唯一/DB 约束/UOM/补货字段）在 downgrade 后可能被丢弃**；**不承诺 downgrade 后数据完整保留**。
- **验收**：`Base.metadata` 含全部新增表（含 receivable allocation）；fresh bootstrap 在全新/一次性临时库上建出这些表；而**既有 schema 的升级测试仍运行 Alembic**（`alembic upgrade head`），证明 bootstrap 只是 fresh create 兜底、不接管既有库升级。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_erp_schema_migration.py && (一次性临时 DB) alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
- **受保护文件**：`sales_app_service.py`、`accounting_services.py`、`report_service.py`、`inventory_service.py`、`approval_service.py`、`tools_workflow_registered.py`、`normal_chat_dispatch.py`。

### W1-02｜销售生命周期命令模块（commercial order state）
- **依赖**：W1-01（schema 稳定）。
- **独占写区**：TO CREATE `app/application/sales_lifecycle_service.py`（命令模块：quote/sent/confirm/cancel，只改 `state` 维度）+ TO CREATE `tests/test_services/test_sales_lifecycle_service.py`。
- **后置条件（业务）**：`state` 在 `draft/quote/sent/confirmed/cancel` 间按规则推进；**不**再驱动履行/开票/收款（各维度独立）；`cancel` 仅对未履行/未开票单允许；`quote→sent→confirmed` 合法，`confirmed→sent` 回退被拒。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_sales_lifecycle_service.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`sales_app_service.py`、`accounting_services.py`、`report_service.py`、`inventory_service.py`、`uom_service.py`、`approval_service.py`、`tools_workflow_registered.py`、`normal_chat_dispatch.py`。

### W1-03｜履行/预留/backorder/return 模块
- **依赖**：W1-01。
- **独占写区**：`app/services/inventory_service.py`（新增按单预留/扣减/回补入口）；TO CREATE `app/services/fulfillment_service.py` + `tests/test_services/test_fulfillment_service.py`。
- **后置条件（业务）**：履行维度**仅由 ordered / reserved / delivered / returned 四类数量派生，全部落于 `inventory_transactions`（stock moves，不新建 move 表）+ `inventory_ledger.reserved_quantity`；不使用订单金额**；`deliver(qty<order_qty)` 记为 **partial** 交付并触发 **backorder**；`deliver(qty>order_qty)` 超量被拒；**return** 生成反向 move 并回补库存。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_fulfillment_service.py tests/test_services/test_erp_e2e_modules.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`sales_app_service.py`、`accounting_services.py`、`report_service.py`、`uom_service.py`、`approval_service.py`。

### W1-04｜开票/贷项通知单 & 记账模块
- **依赖**：W1-01。
- **独占写区**：TO CREATE `app/application/invoicing_service.py` + `tests/test_services/test_invoicing_service.py`；`app/services/accounting_services.py`（暴露**可复用的平衡记账 API**：`create_sale_invoice_entry`/`create_credit_note_entry`）。
- **后置条件（业务）**：`invoice()` 自动生成平衡凭证 `借应收账款(1122, partner)/贷主营业务收入(6001)`，`reference_type='sale'`、`reference_id=order_id`；**invoice status 独立计算**（可先开票后发货）；`credit-note` 生成反向凭证并经 `reversed_of_id` 关联；重复 `invoice()` 不重复生成。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_invoicing_service.py tests/test_services/test_accounting_services.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`sales_app_service.py`、`inventory_service.py`、`report_service.py`、`fulfillment_service.py`。

### W1-05｜收款分配/退款/冲销模块
- **依赖**：W1-01（receivable 模型）。
- **独占写区**：TO CREATE `app/application/payment_service.py` + `tests/test_services/test_payment_service.py`。
- **后置条件（业务）**：`payment()` 调用已存在 `app/services/accounting_services.py` 的 `create_journal_entry` 通用平衡记账 API 生成凭证 `借库存现金(1001)/贷应收账款(1122)`（W1-05 不编辑 `accounting_services.py`，仅消费其已有通用平衡记账 API）；写入由 W1-01 `receivable_allocation.py` 模型承接的 **receivables 分配**（unpaid/partial/paid/refunded）；累计收款不超应收（超收被拒）；同单同金额重复收款幂等；全额 → paid；**refund/reversal** 生成反向凭证并更新分配。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_payment_service.py tests/test_services/test_accounting_services.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件（含 `receivable_allocation.py`）、`app/services/accounting_services.py`、`sales_app_service.py`、`inventory_service.py`、`report_service.py`、`invoicing_service.py`。

### W1-06｜UOM 与补货服务
- **依赖**：W1-01（product UOM/reorder schema 就位）。
- **独占写区**：TO CREATE `app/services/uom_service.py` + `tests/test_services/test_uom_service.py`；`app/services/replenishment_service.py`（改接 `InventoryLedger`/`Product` 阈值）。
- **后置条件（业务）**：同一产品多单位 + 换算率；`“出 500 斤”` 歧义时反问确认单位而非按默认单位执行；换算后数量/金额一致（如 10 箱×20斤/箱=200斤）；`replenishment_suggest` 基于 `available_quantity` 与 `min_stock/max_stock`，低库存口径与库存报表一致。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_uom_service.py tests/test_services/test_replenishment_service.py tests/test_application/test_workflow_clarification.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件（含 `product.py`）、`sales_app_service.py`、`accounting_services.py`、`inventory_service.py`、`fulfillment_service.py`。

### W1-07｜报表读模型
- **依赖**：W1-01。
- **独占写区**：`app/services/report_service.py`（`get_sales_report()` 改接 SalesOrder 正交读模型）；TO CREATE `tests/test_services/test_report_sales_order.py`。
- **后置条件（业务）**：`reports.sales_summary` 按 `SalesOrderItem` 聚合（产品/客户/日期），`summary.total_amount` 与 `SalesOrder.total_amount` 一致；`dashboard.monthly_sales` 读 SalesOrder；旧 `ShipmentRecord` 路径保留但不再作为销售主源。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_report_sales_order.py tests/test_services/test_report_service.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`sales_app_service.py`、`accounting_services.py`、`inventory_service.py`。

### W1-08｜fail-closed 预览/审批/幂等/租户工具契约
- **依赖**：W1-01。
- **独占写区**：`app/application/workflow/approval_service.py`（改为 fail-closed：注册表查询异常/缺失时**默认要求审批**而非放行）；`app/application/workflow/approval_gated_engine.py`（审批前零写入契约）；TO CREATE `tests/test_services/test_sales_approval_failclosed.py`。
- **后置条件（业务）**：对**写动作**存在“**销售信号 → 载荷预览 → 审批 pending → 确认前零持久化 → 确认后租户作用域落库 → 后置条件校验**”的端到端契约测试；注册表异常时**拒绝执行（fail-closed）**而非放行；写动作幂等（同载荷重试不重复记账/扣库存）；跨租户隔离在审批落库后仍成立。**不触碰 `config/risk_actions.registry.json` 或任何路由/配置外观**（其写入权归 W1-09）。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_sales_approval_failclosed.py tests/test_application/test_workflow_clarification.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`sales_app_service.py`、`accounting_services.py`、`report_service.py`、`inventory_service.py`、`tools_workflow_registered.py`、`config/risk_actions.registry.json`。

### W1-09｜唯一外观/路由/配置组装（facade/router/config composition）
- **依赖**：W1-02、W1-03、W1-04、W1-05、W1-06、W1-07、W1-08（全部就绪后）。
- **独占写区**：`app/application/sales_app_service.py`（仅做组合/外观，**不复制领域逻辑**）、`app/services/tools_workflow_registered.py`、`app/application/normal_chat_dispatch.py`、`config/risk_actions.registry.json`（**风险注册表唯一写者**）、既有 `tests/test_services/test_tools_workflow_registered.py`、TO CREATE `tests/test_services/test_sales_facade_integration.py`。
- **后置条件（业务）**：`SalesAppService` 组合并**消费 W1-02 生命周期、W1-03 履行、W1-04 开票、W1-05 收款等（不复制/不重复领域逻辑，仅编排）**；工具路由/风险注册表/对话路由（chat slots）全部接线；`sales_keywords` 收窄 `"销售"` 单字过度命中（L199）；“关键词→执行→结构化返回”端到端有集成测试。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_tools_workflow_registered.py tests/test_services/test_sales_app_service.py tests/test_services/test_erp_e2e_modules.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、`accounting_services.py`、`inventory_service.py`、`report_service.py`、`uom_service.py`、`approval_service.py`、`fulfillment_service.py`、领域命令模块（W1-02..05 独占文件）。

### W1-10｜端到端契约 + 桌面验收
- **依赖**：W1-09。
- **独占写区**：TO CREATE `tests/test_services/test_erp_absorb_e2e.py`（自然语言写意图 → 预览 → 审批 → 零持久化 → 确认 → 一致性）+ TO CREATE 目录 `docs/evidence/e2e/odoo18-w1-desktop-acceptance/`（桌面验收产物）。
- **后置条件（业务，逐条证明）**：
  1. **自然语言写意图**：`“把 A 产品卖给客户B，10 个，单价 100，开票收款”` 解析为明确写载荷。
  2. **载荷预览**：执行前向用户展示待写载荷（订单/履行/凭证/分配）。
  3. **审批 pending**：写动作进入 pending，未确认不执行。
  4. **确认前零持久化**：审批 pending 期间 DB 无任何订单/库存/凭证/分配行。
  5. **确认后租户作用域持久化**：审批通过后落库，且仅落在当前租户作用域内。
  6. **库存/记账/报表一致性**：确认后 inventory_ledger、journal_entries、report read model 三者一致。
  7. **幂等重试**：同载荷重复提交不重复记账/扣库存。
  8. **回滚清理**：任一步失败则整链回滚，无半成品残留。
  9. **可见桌面验收**：在桌面端可见审批工作台与结果，验收在桌面运行展示。
  10. **无生产/发布主张**：本验收**不做生产或发布宣称**，仅证明契约与一致性。
- **聚焦命令（fail-closed）**：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_services/test_erp_absorb_e2e.py`
- **受保护文件**：全部 ORM 模型、迁移与 schema 注册文件、所有领域模块与外观层（本工单只读既有实现，仅新增 e2e 测试与验收脚本）。

---

## 7. 审计自证（本文件为唯一改动 + 引用路径存在 + 无临时文件）

- 本次仅新建/修改：`docs/architecture/odoo18-absorption/01-current-implementation-audit.md`（本文件）。
- 未 stage / 未 commit。
- **唯一改动验证**：本任务仅编辑此一个文件，未产生临时文件、未触碰产品代码/配置/包/测试/锁文件/迁移，未做任何 git/网络/rm/uv 操作。此为 **required** 门禁。
- 被引用关键路径均已核实存在：
  - `app/db/models/{sales,accounting,crm,product,inventory,finance,shipment}.py`
  - `app/application/sales_app_service.py`、`app/application/normal_chat_dispatch.py`
  - `app/services/accounting_services.py`、`app/services/replenishment_service.py`、`app/services/tools_workflow_registered.py`、`app/services/report_service.py`、`app/services/tools_execution/registry.py`
  - `app/db/init_db.py`（`ensure_erp_bootstrap` L1281）、`app/db/tenant_filter.py`、`app/db/session.py`、`app/db/mixins.py`
  - `app/application/workflow/{approval_gated_engine,approval_service,clarification_node,engine}.py`
  - `alembic/`（`alembic/versions/` 现含 `2026_07_27_etl_folder_batches.py` 等迁移，**无 ERP 建表迁移**——证实 P0-5）
  - `config/risk_actions.registry.json`、`XCAGI/kb/absorption/odoo18/absorption_tasks.json`
  - `tests/test_services/{test_sales_model,test_accounting_model,test_accounting_services,test_erp_e2e_modules,test_report_service,test_tools_workflow_registered}.py`、`tests/test_application/{test_customer_app_service,test_workflow_clarification}.py`
- 审计命令为只读（无产品测试运行、无 `uv`、无 `rm`、无网络、无 git 写）。
