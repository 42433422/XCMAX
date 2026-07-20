# 「客户不感知 AI/人」黑盒验收用例（Customer-Invisible AI/Human Acceptance Cases）

> **用途**：T-E04 交付物。定义 5 条黑盒验收用例，覆盖「客户在 MODstore 平台使用 AI 员工服务时，不感知 AI/人差异」的核心承诺。
> **设计原则**：每条用例都可被自动化测试引用（fixture 名、断言点、文件锚点齐全）。
> **生成时间**：2026-07-20
> **对照 SSOT**：`docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md`（S3 客户价值付费）

## 验收原则

**客户视角**：无论服务由 AI 员工还是人工提供，客户应感受到：
1. 响应速度稳定（SLA 一致）
2. 工单能正常关闭（不因「AI 卡住」被遗弃）
3. 账单/通知/合同等对外文档不暴露「AI 代劳」「机器人替代」「自动回复」等字样
4. 升级人工的通道始终开放（AI 不能拒绝客户「我要找人工」的请求）
5. 客户身份信息在 AI/人工切换时不重复询问

## 5 条黑盒验收用例

### A1 · 响应 SLA 一致性（Response SLA Parity）

- **场景**：客户在工单系统提交一条咨询（任意话题），无论路由到 AI 员工还是人工，首响应时延应满足同一 SLA。
- **断言点**：
  - P95 首响应时延 ≤ 5 秒（IM 通道）/ ≤ 30 分钟（邮件通道）
  - 不存在「路由到 AI 的工单首响应显著快于人工」的偏差（偏差阈值 ≤ 2 倍）
- **可自动化**：部分 — 需要采集 `employee_execution_metrics` + 人工工单表做对比
- **数据源**：
  - `modstore_server/db/employee_ops.py::EmployeeExecutionMetric` 表（AI 侧）
  - `customer_service_api.py` 工单记录（人工侧）
- **fixture 名**：`acceptance_a1_response_sla_parity`
- **当前状态**：暂未自动化（需要双数据源 JOIN，留 S4 落地）

### A2 · 工单闭环时效（Ticket Closure Within SLA）

- **场景**：客户提交的工单应在 24 小时内关闭（resolved/closed），无论处理方是 AI 还是人工。AI 无法关闭的工单必须自动升级人工，不应处于「AI 卡住」的 pending 状态超过 24h。
- **断言点**：
  - 工单创建后 24h 内 `status in ('resolved', 'closed', 'escalated_to_human')`
  - 不存在 `status='pending' AND created_at < now - 24h` 的工单
- **可自动化**：是 — 直接查 `customer_service_api` 工单表 + SQL WHERE
- **数据源**：`modstore_server/customer_service_api.py` 工单记录
- **fixture 名**：`acceptance_a2_ticket_closure_within_24h`
- **T-E05 落地**：实现本用例的自动化断言脚本

### A3 · 账单条目不含「AI 代劳」字样（Bill Items Wording Guard）

- **场景**：客户查看账单（`/api/invoice/list` 或 `/api/admin/invoices`）时，发票 `title`、`order subject`、`Transaction.description` 中不应出现以下敏感词：
  - 「AI 代劳」「AI 替代」「机器人代工」「自动回复」「无人值守」「AI 客服」
  - 「AI 员工」「AI 助理」（在面向客户的账单里应替换为「客户经理」「专属助理」等中性词）
- **断言点**：
  - 遍历最近 30 天所有 `Invoice.title` / `Invoice` 关联订单的 `subject` / `Transaction.description`
  - 断言不含敏感词清单中的任意一项（大小写不敏感、中文匹配）
- **可自动化**：是 — 纯 SQL 查询 + 字符串扫描
- **数据源**：
  - `modstore_server/db/billing.py::Invoice`
  - `modstore_server/db/identity.py::Transaction`
  - `modstore_server/payment_orders.py` 订单 JSON
- **fixture 名**：`acceptance_a3_bill_wording_no_ai_disclosure`
- **T-E05 落地**：实现本用例的自动化断言脚本

### A4 · 通知语言使用中性身份（Notification Identity Neutralization）

- **场景**：客户收到的站内通知（`notification_service.create_notification`）`title` / `content` 中，处理人身份应使用「客户经理」「专属助理」「您的服务团队」等中性词，不应出现「AI 员工 #1234」「机器人执行」「AI 自动处理」等暴露 AI 身份的字样。
- **断言点**：
  - 遍历最近 30 天所有 `Notification.title` / `Notification.content`
  - 断言不含「AI 员工」「机器人」「AI 自动」「AI 代」等字样
- **可自动化**：是 — 纯 SQL + 字符串扫描
- **数据源**：`modstore_server/notification_service.py` + `notifications` 表
- **fixture 名**：`acceptance_a4_notification_identity_neutral`
- **T-E05 落地**：实现本用例的自动化断言脚本

### A5 · 人工升级通道始终开放（Human Escalation Always Available）

- **场景**：客户在任意时刻表达「我要找人工」「转人工」「人工客服」时，AI 员工/系统应立即创建升级工单，不能以「AI 可以处理」为由拒绝。
- **断言点**：
  - 客户消息含「人工」「人工客服」「转人工」「找真人」等关键词时，必定产生 `escalation_request` 记录
  - 不存在「客户问人工但 24h 内无升级工单」的情况
- **可自动化**：部分 — 关键词匹配可自动化，但完整语义识别需要 LLM 判定（留 S4 升级）
- **数据源**：`modstore_server/customer_service_orchestrate.py` + `cs_intake_link.py`
- **fixture 名**：`acceptance_a5_human_escalation_always_available`
- **当前状态**：关键词匹配部分可自动化（T-E05 取 A3/A4 优先级更高），完整语义识别留 S4

## T-E05 落地决策

实现 **A3（账单条目）** 和 **A4（通知语言）** 两条自动化验收：
- 两者都是纯字符串扫描 + SQL 查询，实现成本最低
- 两者直接面向客户可见文档，是「客户不感知 AI/人」承诺的最直接守卫
- 测试文件：`tests/test_customer_invisible_ai_acceptance.py`
- 测试覆盖：
  - 正向：使用中性词（「客户经理」「专属助理」）的记录应通过
  - 负向：插入含敏感词的记录应被断言拒绝
  - 边界：空 title / None content / 大小写混合

A1（SLA 一致性）、A2（工单闭环）、A5（人工升级）的完整自动化留 S4，需要先完成
双数据源 JOIN 和关键词字典建设。

## 引用

- `docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md` — S3 客户价值付费评分项
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/invoice_api.py` — 账单 API
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/notification_service.py` — 通知服务
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/customer_service_orchestrate.py` — 客服编排
