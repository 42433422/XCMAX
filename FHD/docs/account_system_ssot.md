# 账号体系：单一真相源 + 自动派生

> 本文档描述 XCMAX/FHD 账号体系的四个维度、各自的**真相源字段**、**运行时派生规则**、
> **字段写入权限**与**校验规则**。实现遵循「单一真相源（SSOT）+ 自动派生」：每个维度只有一个
> 持久化写入点，所有运行时身份/档位均由真相源派生，不再由前端登录入口决定。

## 一、四维真相源

| 维度 | 真相源字段 | 取值 | 写入点 | 派生消费点 |
|------|-----------|------|-------|-----------|
| 1 账号身份 | `User.tier` | personal / enterprise / admin | 注册（按 SKU）/ 管理端 / 登录时按市场身份提升 | `Session.account_kind`（登录派生） |
| 2 行业 | `User.industry_id` + `User.entitled_industries` | 通用/涂料/考勤/批发/电商/餐饮/物流/管理端 | 注册 / 管理端 | `request.state.industry_id` → Persona 身份 |
| 3 会员体系 | 修茈市场会员等级（外部，`user_plans`） | free/vip/vip_plus/svip1..svip8 | 市场侧购买 | `Session.market_membership_tier`（登录同步） |
| 4 账号等级 | `User.account_tier`（派生来源 `User.budget_range`） | normal / pro / max / ultra | 注册时按预算派生 / 管理端 | `/api/auth/me` 返回；仅 enterprise 有意义 |

## 二、派生规则（运行时计算）

### 2.1 账号身份 → 会话档位
`Session.account_kind ← derive_account_kind_from_user(User.tier, market_is_admin, market_is_enterprise)`
- 以 `User.tier` 为主真相源；修茈市场身份只能**向上提升**（admin > enterprise > personal），不能下调。
- **前端登录入口不再决定档位**（旧 `account_kind` 参数仅作 hint）。
- 登录时若市场身份高于本地 `tier` 且本地为空/personal，则回写 `User.tier` 使本地真相源收敛。
- 例外：impersonation（管理员代管）会话仍由 `/admin/impersonate` 显式设置。
- 实现：[app/application/session_account_meta.py](../app/application/session_account_meta.py) `derive_account_kind_from_user`；
  [app/application/enterprise_login_flow.py](../app/application/enterprise_login_flow.py) `_derive_and_heal_account_kind` / `finalize_enterprise_login`。

### 2.2 预算 → 账号等级
`User.account_tier ← derive_account_tier(User.budget_range)`（注册时派生；仅 enterprise 有意义）

| budget_range | account_tier |
|--------------|--------------|
| 5 万以内 | normal |
| 5–20 万 | pro |
| 20–50 万 | max |
| 50 万以上 | ultra |
| 空 / 暂未确定 / 未知 | normal（默认） |

> 匹配时对连字符（`–`/`-`/`—`）与空格做归一化。实现：[app/application/account_tier_derivation.py](../app/application/account_tier_derivation.py)。

### 2.3 行业授权初始化
`User.entitled_industries ← init_entitled_industries_for_user(tier, industry_id)`
- personal → `["通用"]`
- enterprise → `["通用", industry_id]`（去重保序）
- admin → `["管理端"]`

> 实现：[app/application/entitled_industries_init.py](../app/application/entitled_industries_init.py)。

### 2.4 会员等级同步
`Session.market_membership_tier ← 修茈市场 GET /api/payment/my-plan 的 membership.tier`
- 登录响应不含会员等级，登录 finalize 时用市场 token 单独拉取。
- 套餐列表由后端 `GET /api/market/membership-plans` 代理市场 `GET /api/payment/plans`，前端 `ModelPaymentView` 读取（失败回退本地 FALLBACK）。
- 实现：[app/fastapi_routes/market_account.py](../app/fastapi_routes/market_account.py) `fetch_market_membership_tier` / `market_membership_plans`。

### 2.5 行业 → Persona
`request.state.industry_id ← User.industry_id`（admin → 管理端，兜底 通用），再派生 Persona 身份。
- 实现：[app/middleware/industry_context.py](../app/middleware/industry_context.py)、[app/application/planner_compat_service.py](../app/application/planner_compat_service.py)。

## 三、字段写入权限矩阵

| 字段 | 用户自写 | 管理端写 | 系统派生 |
|------|---------|---------|---------|
| `User.tier` | 注册时按 SKU | ✅ | 登录时按市场身份向上提升 |
| `User.industry_id` | ✅（注册） | ✅ | — |
| `User.entitled_industries` | 注册时初始化 | ✅ | 注册时按 tier 初始化 |
| `User.account_tier` | — | ✅（仅 enterprise） | ✅（注册时从 budget 派生） |
| `User.budget_range` | ✅（注册） | ✅ | — |
| `Session.account_kind` | ❌ | ❌（除 impersonation） | ✅（登录时从 `User.tier`） |
| `Session.market_membership_tier` | ❌ | ❌ | ✅（登录时从市场） |

## 四、校验规则

- `industry_id` 必须 ∈ `entitled_industries`（管理端显式提供 entitled 时强校验，否则自动并入）→ 否则 422。
- `account_tier` 仅 `tier=enterprise` 时可设；非企业设置 → 422；非法值（非 normal/pro/max/ultra）→ 422。
- `tier` 必须 ∈ {personal, enterprise, admin} → 否则 422。
- 实现：[app/fastapi_routes/xcmax_admin.py](../app/fastapi_routes/xcmax_admin.py) `admin_set_user_profile`。

## 五、对前端的暴露

`/api/auth/me` 与 `/api/auth/session/validate` 返回（只读展示）：
`tier`、`account_tier`（派生有效值，非企业为 null）、`budget_range`、`entitled_industries`、`market_membership_tier`、`account_kind`。
前端 store：[frontend/src/stores/accountProfile.ts](../frontend/src/stores/accountProfile.ts)。

## 六、注意事项

- 会员体系（维度 3，VIP/SVIP，AI 调用额度）与账号等级（维度 4，普通/Pro/Max/Ultra，SaaS 平台套餐）**两套并存**，互不派生。
- `contact.html` 的预算下拉仅作销售线索（提交进 message 文本发往市场），**不**作为 FHD `account_tier` 的派生来源；account_tier 仅在 `RegisterView` 注册时由 budget 派生。
- DB 列由 [app/db/init_db.py](../app/db/init_db.py) 的 `ensure_user_profile_columns` / `ensure_sessions_account_meta_columns` 在启动时幂等补齐；alembic 迁移 `2026_06_22_add_account_tier_to_users.py` 为对照。

## 七、多租户数据隔离

> 真相源 `User.tenant_id` → 派生 `request.state.tenant_id`（中间件注入）→ 业务数据查询自动按租户过滤。

### 机制（全局 ORM 事件）
- 业务模型继承 `TenantScopedMixin`（[app/db/mixins.py](../app/db/mixins.py)）获得 `tenant_id` 列；
  `User` / `Session` / `Permission` / `Role` **不**继承，故登录、会话校验、权限永不被租户过滤。
- 全局事件 [app/db/tenant_filter.py](../app/db/tenant_filter.py)（注册在 SQLAlchemy `Session` 基类）：
  - 读（`do_orm_execute` SELECT）：`with_loader_criteria(TenantScopedMixin, …)` 自动过滤主查询/JOIN/关系加载。
  - 写（`before_flush`）：新对象未显式设 `tenant_id` 时按当前租户自动打标。
- 当前租户读取 [app/infrastructure/tenant_scope.py](../app/infrastructure/tenant_scope.py) `current_tenant_id()`；
  后台任务用 `with tenant_scope(tid): …` 显式设定。

### 安全策略
- **NULL 容忍（默认）**：`tenant_id == 当前 OR IS NULL` —— 存量未打标数据不被隐藏。
- **严格模式**：`XCAGI_TENANT_STRICT=1` → `tenant_id == 当前`（数据回填后启用，硬隔离）。
- 当前租户为 None（管理员 / 未登录 / 后台无上下文）→ 不过滤，看全部。
- 逃生舱：`session.execute(stmt, execution_options={"skip_tenant_filter": True})`。
- 应急总开关：`XCAGI_DISABLE_TENANT_FILTER=1` 完全停用。

### 已纳入隔离的业务表（14）
products / purchase_units / materials / shipment_records / financial_transactions /
suppliers / purchase_orders / purchase_order_items / purchase_inbounds / purchase_inbound_items /
warehouses / storage_locations / inventory_ledger / inventory_transactions。

新增业务模型只需继承 `TenantScopedMixin` + 把表名加入 `ensure_business_tenant_id_columns` 与迁移 `2026_06_22_business_tenant_id.py` 即可自动隔离（无需改仓储）。

### 待办（硬隔离上线前）
- 存量 `tenant_id IS NULL` 数据回填到对应租户；之后开 `XCAGI_TENANT_STRICT=1`。
- 外围模型（ai / wechat / ai_circle / approval / miniprogram / service_request）如需隔离，按同一 mixin 模式纳入。

## 八、账户安全（登录加固）

### RBAC（已完整）
`Role` / `Permission` / `role_permissions` 模型 + 种子（[permission.py](../app/db/models/permission.py)）+ 全套 CRUD（`/api/rbac/*`：角色增删改查、权限定义增删、用户角色分配、seed）+ `require_permission` 守卫 + `get_user_permissions` 查库解析（[auth_app_service.py](../app/application/auth_app_service.py)）。无需新增。

### 账户锁定
- `User.failed_login_attempts` + `User.locked_until`；连续失败达阈值临时锁定，成功登录清零。
- 阈值：`XCAGI_MAX_LOGIN_ATTEMPTS`（默认 5）、`XCAGI_LOGIN_LOCKOUT_MINUTES`（默认 15）。
- 实现：[account_security.py](../app/application/account_security.py) + `AuthApplicationService.authenticate`。

### MFA（TOTP，无第三方依赖）
- `User.mfa_enabled` + `User.totp_secret`；RFC 6238 TOTP（HMAC-SHA1，标准认证器 App 兼容）。
- API：`POST /api/auth/mfa/setup`（生成密钥 + otpauth URI 供扫码）/ `mfa/enable`（校验后开启）/ `mfa/disable`。
- 登录强制：`authenticate(enforce_mfa=...)` —— 本地直登强制；市场优先流 `enforce_mfa=False`（修茈市场为认证权威）。opt-in（`mfa_enabled` 默认 False，不影响现有用户）。

### 邮箱验证
- `User.email_verified`（字段已加 + `/api/auth/me` 暴露）。
- 自助「发送验证邮件」流程需 SMTP 基建（当前仓库无邮件发送能力，延后）；企业注册的邮箱验证由修茈市场负责。

### 无状态 JWT（增量，默认关）
- [web_jwt.py](../app/security/web_jwt.py)：HS256 + iss/aud/exp，access(12h) / refresh(14d) 一次性轮转。
- 登录响应附带 `web_tokens`；`POST /api/auth/token/refresh` 轮转。
- `resolve_session_user` 仅在 `XCAGI_WEB_JWT_AUTH=1` 且 session 校验失败后，才用 web JWT 验签按 user_id 加载用户（默认关 → 有状态 session 行为零变化）。**开启该 flag + 前端改用 Bearer JWT 即为正式无状态化切换点。**
