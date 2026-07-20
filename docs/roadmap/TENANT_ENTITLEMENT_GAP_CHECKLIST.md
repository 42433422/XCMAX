# 租户权益策略缺口清单（Tenant Entitlement Policy Gap Checklist）

> **用途**：T-E02 交付物，对照 `docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md` L209 「下一步补租户权益策略」与 MODstore_deploy 代码现状，列出未完成权益策略条目与文件锚点。
> **生成时间**：2026-07-20
> **对照路径**：`成都修茈科技有限公司/MODstore_deploy/modstore_server/`

## 评分对齐

| 评分维度 | 当前状态 | 目标态 |
|---------|---------|--------|
| S3 客户价值付费 | 已有 `payment.paid` 事件 + `Entitlement/UserPlan/Quota` 表，但权益判定全部按 `user_id` 单维度 | S3：至少 1 条租户级权益策略 + 「客户不感知 AI/人」黑盒验收 |
| S4 多租户隔离 | 无 `Tenant` 实体表，无 Row-Level Security | S4：租户级成本上限 + 配额上限 + 审计日志 |

## 现状摘要（按文件锚点）

| 模块 | 文件 | 当前实现 |
|------|------|---------|
| 履约策略 | `modstore_server/payment_fulfilment.py` | 三种策略 `Item/Plan/Wallet`，全部按 `user_id` 写入，无租户上下文 |
| 权益写入 | `modstore_server/eventing/subscribers.py::_on_payment_paid_entitlement` | 订阅 `payment.paid`，仅依赖 `out_trade_no/user_id` |
| 企业 Mod 白名单 | `modstore_server/enterprise_entitlements.py` | 静态白名单 `ENTERPRISE_ASSIGNABLE_MODS`（4 项），无租户隔离 |
| 账单表 | `modstore_server/db/billing.py` | `Entitlement/UserPlan/Quota/Invoice` 均按 `user_id` 维度，无 `tenant_id` 列 |
| 钱包/交易 | `modstore_server/db/identity.py` | `Wallet/Transaction` 仅 `user_id` FK |
| 用户 Mod 关联 | `modstore_server/db/catalog.py::UserMod` | 仅 `user_id/mod_id`，无租户级隔离 |

## 缺口清单（按优先级）

### G1 · 无 `TenantEntitlementPolicy` 抽象层（P0）

- **现状**：权益判定逻辑散落在 `payment_fulfilment.py`（直接写入）+ `enterprise_entitlements.py`（静态白名单），无统一策略接口。
- **影响**：
  - 无法在请求路由层提前拦截越权访问（如普通用户访问企业 Mod）。
  - 无法对新增权益类型（按租户、按订阅档位、按地区）扩展。
- **文件锚点**：
  - 缺失：`modstore_server/tenant_entitlement/policy.py`（ABC + 具体策略）
  - 缺失：`modstore_server/tenant_entitlement/__init__.py`（导出）
- **目标态**：S3 — 提供 `TenantEntitlementPolicy` ABC + `check(tenant_id, action, resource) -> Decision`。
- **T-E03 落点**：在本清单标识后，立即实现 G1+G3 合并的 `TenantModAccessPolicy`。

### G2 · 无 `Tenant` 实体表（P0）

- **现状**：`db/identity.py::User` 只有 `is_enterprise` 布尔字段，无独立 Tenant 实体。
- **影响**：
  - 无法表达「一个企业多个员工共享一份权益」的语义。
  - 无法做租户级成本/配额聚合。
- **文件锚点**：
  - 缺失：`db/identity.py::Tenant` 表（id, name, owner_user_id, plan_tier, created_at）
  - 缺失：`db/identity.py::User.tenant_id` FK 列
- **目标态**：S4 — 引入 Tenant 实体 + Alembic 迁移 + 数据回填脚本。
- **MVP 决策**：T-E03 阶段采用「软租户」退化，`tenant_id` 临时等于 `user_id`，避免大迁移。后续 S4 再做真实 Tenant 表。

### G3 · 无租户级 Mod 访问策略（P0）

- **现状**：`UserMod` 表只记录「某用户安装了某 Mod」，不区分租户边界。任何登录用户理论上都能 `GET /api/mods/{mod_id}` 拉取任意 Mod。
- **影响**：
  - 企业 Mod（如 `attendance-industry`、`coating-industry`）可能被未授权个人账号访问。
  - 无法做「企业版 Mod 仅企业租户可见」的市场过滤。
- **文件锚点**：
  - 缺失：`tenant_entitlement/policy.py::TenantModAccessPolicy`（具体策略）
  - 缺失：在 `modstore_server/api/catalog.py` / `modstore_server/catalog_api.py` 调用策略守卫
- **目标态**：S3 — `TenantModAccessPolicy.check(tenant_id, "access_mod", mod_id) -> Decision`，查 `UserMod` 表判定。
- **T-E03 落点**：实现本策略 + 单元测试覆盖 allow/deny/边界。

### G4 · 无租户级成本上限（P1）

- **现状**：`Wallet.balance` 只看用户级，无租户级月度成本上限；员工执行（`employee_execution_metrics` 表）成本归集到用户而非租户。
- **影响**：
  - 企业账号下 5 个员工各跑 LLM 调用，可能击穿企业月度预算而无告警。
- **文件锚点**：
  - 缺失：`tenant_entitlement/policy.py::TenantCostCeilingPolicy`
  - 缺失：在 `modstore_server/llm_billing.py`（成本归集处）插入策略守卫
- **目标态**：S4 — 租户级月度成本上限 + 超限告警 + 自动熔断。

### G5 · 无租户级配额上限（P1）

- **现状**：`Quota` 表按 `user_id` 维度，无 `tenant_id`；员工数、API 调用次数、存储空间等配额无法在租户维度聚合。
- **影响**：
  - 个人 VIP 套餐 `employee_count=3`，但企业租户应允许 `employee_count=50`，目前无机制表达。
- **文件锚点**：
  - 缺失：`tenant_entitlement/policy.py::TenantQuotaCeilingPolicy`
  - 缺失：`db/billing.py::Quota.tenant_id` 列（待 G2 完成后）
- **目标态**：S4 — 租户级配额上限 + 共享配额池（多用户共享一份配额）。

### G6 · 无租户级审计日志（P2）

- **现状**：`audit_logger.py` 按用户维度记录，无 `tenant_id` 字段；事件溯源只有 `event_outbox.jsonl` 全局流。
- **影响**：
  - 企业合规审计（SOC2/ISO27001）无法按租户导出独立审计报告。
- **文件锚点**：
  - 现有：`modstore_server/audit_logger.py`
  - 缺失：在 audit log 中加 `tenant_id` 列 + 按 `tenant_id` 过滤查询 API
- **目标态**：S5 — 租户级审计日志导出 + 合规报告自动生成。

### G7 · 无 Row-Level Security（P2）

- **现状**：SQLite 无 RLS；PostgreSQL 模式下也未配置 RLS 策略。所有 SQL 查询都按 `user_id` WHERE 过滤，依赖应用层正确性。
- **影响**：
  - 任何 SQL 注入或 ORM 误用都可能跨租户泄露数据。
  - 无法满足金融/医疗行业客户的「物理隔离」要求。
- **文件锚点**：
  - 缺失：PostgreSQL RLS 策略（`CREATE POLICY tenant_isolation ON ... USING (tenant_id = current_setting('app.tenant_id')::int)`）
  - 缺失：连接池设置 `SET app.tenant_id = ?` 的中间件
- **目标态**：S6 — PostgreSQL 模式下启用 RLS + 应用层 fallback 校验。

## T-E03 落点决策

**实现**：G1（抽象层）+ G3（具体策略）合并实现。

**理由**：
- G1 提供 ABC，G3 是第一个具体实现，两者天然耦合。
- G2（Tenant 实体表）需要 Alembic 迁移 + 数据回填，单次任务过大，留到 S4。
- G4-G7 都是 S4+ 才能落地的策略，依赖 G2 完成。

**交付物**：
- `modstore_server/tenant_entitlement/__init__.py` — 包导出
- `modstore_server/tenant_entitlement/policy.py` — `Decision` / `TenantEntitlementPolicy` ABC / `TenantModAccessPolicy` 具体策略
- `tests/test_tenant_entitlement_policy.py` — 单元测试覆盖 allow/deny/边界

**MVP 退化**：`tenant_id` 在 S3 阶段等于 `user_id`（软租户），策略实现不破坏现有 API，只新增判定层。

## 引用

- `docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md` L209：「下一步补租户权益策略」
- `modstore_server/enterprise_entitlements.py::ENTERPRISE_ASSIGNABLE_MODS` — 现有企业 Mod 白名单（4 项），T-E03 不破坏此 API
- `FHD/app/enterprise/mod_entitlements.py` — FHD 桌面端读取 `UserMod` 表的入口，T-E03 与其保持数据源一致
