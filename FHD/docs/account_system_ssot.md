# 产品端与账号体系：单一真相源 + 自动派生

> 本文档描述 XCMAX/FHD 的产品端矩阵、账号体系四个维度、行业/Persona 派生规则、各自的
> **真相源字段**、**运行时派生规则**、**字段写入权限**与**校验规则**。实现遵循「单一真相源（SSOT）+
> 自动派生」：每个维度只有一个持久化写入点，所有运行时身份/档位均由真相源派生，不再由前端登录入口决定。

## 零、产品端与分发矩阵

| 产品端 | 分发/入口 | 支持平台 | 允许账号 | 规则 |
|--------|-----------|----------|----------|------|
| 网站 | 官网 / AI 市场 / 软件下载页 | Web | personal / enterprise / admin | 唯一公开注册与购买入口；个人账号仅能在网站使用 |
| 桌面端软件 | 软件下载 / 企业交付包 | Windows / macOS | enterprise / admin | 必须绑定企业或管理员会话；不接受 personal 账号进入本地工作台 |
| 手机 App | 应用商店 / 企业分发 | Android / iOS / HarmonyOS | enterprise / admin | 作为企业移动工作台与消息/审批入口；账号能力跟随企业授权 |

产品端只决定可进入的运行环境，不决定账号身份。账号身份仍以 `User.tier` 与市场身份提升规则为准。

### 0.1 产品端能力边界

| 产品端 | personal | enterprise | admin |
|--------|----------|------------|-------|
| 官网/网站 | 注册、登录、购买 VIP/月计划、查看个人消费 | 企业注册、购买体验/永久账户、下载软件、管理授权 | 平台后台、市场运营、企业审核、软件下载发布 |
| 桌面端 Windows/macOS | 不允许进入 | 本地业务工作台、行业 Mod、文件/打印/本地数据能力 | 运维诊断、代管排障、企业配置审计 |
| 手机端 Android/iOS/HarmonyOS | 不允许进入 | 消息、审批、移动看板、扫码登录/绑定桌面端 | 移动运维告警、企业会话排障 |

约束：个人账号只服务网站个人消费场景；企业账号是业务系统主体；管理员账号是平台运营主体。桌面端和手机端只能接受企业或管理员会话，不能因为前端入口传了 `account_kind` 就放行 personal。

### 0.2 入口与下载分发

| 入口 | 主要用途 | 绑定规则 |
|------|----------|----------|
| 官网 | 对外介绍、需求问卷、开户注册、软件下载入口 | 表单预算只作为销售线索，不直接写 `User.account_tier` |
| AI 市场 | VIP/月计划、额度、企业身份/管理员身份来源 | 市场身份只能向上提升本地 `User.tier` |
| 软件下载页 | Windows/macOS/Android/iOS/HarmonyOS 安装包分发 | 下载可公开，首次使用必须登录并校验账号端权限 |
| 管理后台 | 企业审核、授权、RBAC、套餐/行业配置 | 仅 admin 或具备管理权限的企业角色可进入对应后台 |

## 一、四维真相源

| 维度 | 真相源字段 | 取值 | 写入点 | 派生消费点 |
|------|-----------|------|-------|-----------|
| 1 账号身份 | `User.tier` | personal / enterprise / admin | 注册（按 SKU）/ 管理端 / 登录时按市场身份提升 | `Session.account_kind`（登录派生） |
| 2 行业 | `User.industry_id` + `User.entitled_industries` | 通用/涂料/考勤/批发/电商/餐饮/物流/管理端 | 注册 / 管理端 | `request.state.industry_id` → Persona 身份 |
| 3 会员体系 | 修茈市场会员等级（外部，`user_plans`） | free/vip/vip_plus/svip/svip2..svip8 | 市场侧月计划购买 | `Session.market_membership_tier`（登录同步） |
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
| 1–5 万 | normal |
| 5–10 万 | pro |
| 10–50 万 | max |
| 50–100 万 | ultra |
| 空 / 暂未确定 / 未知 | normal（默认） |

> 旧值 `5 万以内` / `5–20 万` / `20–50 万` / `50 万以上` 作为兼容别名保留。匹配时对连字符（`–`/`-`/`—`）与空格做归一化。实现：[app/application/account_tier_derivation.py](../app/application/account_tier_derivation.py)。

### 2.2.1 企业购买形态

| 购买形态 | 价格/额度 | 到期规则 | 账号等级 |
|----------|-----------|----------|----------|
| 体验账户 | 99 元购买，含 100 元额度 | 30 天到期后冻结 | normal |
| 永久账户 · normal | 1–5 万 | 永久 | normal |
| 永久账户 · pro | 5–10 万 | 永久 | pro |
| 永久账户 · max | 10–50 万 | 永久 | max |
| 永久账户 · ultra | 50–100 万 | 永久 | ultra |

企业 SaaS 定价的机器配置为 [config/saas_plans.json](../config/saas_plans.json)。`account_tier` 只表达企业授权档位，不根据 AI 额度消耗动态升降。

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
- VIP 是月计划权益层（vip / vip_plus / svip / svip2..svip8），与企业永久授权档位并列存在；AI 额度消耗不反向决定 VIP 或 `account_tier`。
- 实现：[app/fastapi_routes/market_account.py](../app/fastapi_routes/market_account.py) `fetch_market_membership_tier` / `market_membership_plans`。

### 2.5 行业 → Persona
`request.state.industry_id ← User.industry_id`（admin → 管理端，兜底 通用），再派生 Persona 身份。
- 实现：[app/middleware/industry_context.py](../app/middleware/industry_context.py)、[app/application/planner_compat_service.py](../app/application/planner_compat_service.py)。

行业体系的当前可注册范围为 7 选 1：通用、涂料、考勤、批发、电商、餐饮、物流；管理端为 admin 专用行业，不出现在企业注册选择中。后续新增行业只能先进入 [config/industry_presets.json](../config/industry_presets.json)，再绑定对应 Mod、字段词表、导航标签、示例数据与权限策略。

Persona 不作为用户可随意填写的字段持久化，统一运行时派生：

| 输入 | 派生内容 | 用途 |
|------|----------|------|
| `account_kind` | personal / enterprise / admin 工作身份 | 决定入口、权限边界、默认工具集 |
| `industry_id` | 行业助手人格 | 决定术语、快捷指令、菜单标签、业务对象称呼 |
| `account_tier` | normal / pro / max / ultra 能力档位 | 决定企业能力包、并发/自动化/高级工具上限 |
| 产品端 | web / desktop / mobile 交互人格 | 决定界面密度、离线/本地能力、移动审批与消息能力 |

换句话说：行业是“业务语境”，Persona 是“在某个端、某个账号、某个行业里说话和做事的执行角色”。新增 Persona 时必须能被上述四个输入稳定派生，禁止单独开一套手工选择的人格系统。

### 2.6 账号类型总表

| 账号类型 | 真相源 | 购买/开通 | 可用端 | 数据归属 | 说明 |
|----------|--------|-----------|--------|----------|------|
| 个人账号 | `User.tier=personal` | 网站注册 / VIP 月计划 | 网站 | 个人消费与个人资料 | 只能使用网站能力；不能进入桌面端、手机端企业工作台 |
| 企业账号 | `User.tier=enterprise` | 体验账户或永久账户 | 网站 + 桌面端 + 手机端 | 企业租户 `tenant_id` | 业务系统主体；行业、授权、Mod、人员、审批、数据都挂在企业租户下 |
| 平台管理员账号 | `User.tier=admin` | 平台创建/市场管理员身份提升 | 网站后台 + 桌面/手机运维入口 | 平台运维数据 | 用于运营、审核、排障、代管；不是客户企业的数据所有者 |

企业内部的“管理员”不是 `User.tier=admin`。企业管理员应通过 RBAC 角色表达，仍然属于 `User.tier=enterprise`；平台管理员才是 `User.tier=admin`。

### 2.7 管理账号体系

| 层级 | 推荐角色 | 权限边界 | 禁止事项 |
|------|----------|----------|----------|
| 平台超级管理员 | `platform_owner` | 全局配置、管理员账号、套餐、发布、应急开关 | 禁止作为日常业务用户写入企业业务数据 |
| 平台运营管理员 | `platform_ops` | 企业审核、订单/授权核查、软件下载发布、公告 | 禁止修改底层安全策略和密钥 |
| 平台客服/实施 | `platform_support` | 查看企业状态、发起代管、处理工单 | 禁止无审批直接改企业数据 |
| 企业所有者 | `enterprise_owner` | 企业资料、套餐、行业、成员、账单、RBAC | 禁止越租户访问其他企业 |
| 企业管理员 | `enterprise_admin` | 成员、业务配置、审批流程、行业 Mod | 禁止改套餐和企业所有权 |
| 企业操作员 | `enterprise_operator` | 日常业务录入、审批、执行自动化 | 禁止改权限、账单、行业授权 |
| 企业只读/审计 | `enterprise_viewer` | 看板、报表、审计记录 | 禁止写业务数据 |

实现原则：账号身份用 `User.tier`，细粒度管理能力用 `Role` / `Permission`。不要新增 `admin_type`、`enterprise_role` 之类平行字段，除非先证明 RBAC 无法表达。

### 2.8 行业体系

行业不是前端标签，也不是单个 Mod。行业是“业务语境 + 授权范围 + 行业包 + Persona 输入”的组合。

| 层 | 真相源/配置 | 作用 | 禁止事项 |
|----|-------------|------|----------|
| 行业 ID | `User.industry_id` | 当前默认行业，进入请求上下文 | 禁止前端临时覆盖未授权行业 |
| 授权行业 | `User.entitled_industries` | 租户可切换/可安装的行业集合 | 禁止 `industry_id` 不在授权集合内 |
| 行业 UI 词表 | [config/industry_presets.json](../config/industry_presets.json) | 欢迎语、快捷按钮、菜单名、业务对象称呼 | 禁止只改页面文案不改 SSOT |
| 行业能力包 | [config/industry_baseline.json](../config/industry_baseline.json) | 核心 Mod、可选 Mod、行业包绑定、开放状态 | 禁止无 Mod/服务支撑就标成正式行业 |
| 行业别名 | [config/industry_mod_aliases.json](../config/industry_mod_aliases.json) | 行业与 Mod/市场别名兼容 | 禁止把别名当成新行业 |

当前行业分层：

| 类型 | 行业 | 状态 | 说明 |
|------|------|------|------|
| 基础行业 | 通用 | ga | 所有账号兜底行业；不绑定专属行业包 |
| 首批行业包 | 涂料、考勤 | pilot/ga 优先 | 已在 `industry_baseline.json` 明确 `industry_packages`，可作为首批真实交付行业 |
| 预置方向 | 批发、电商、餐饮、物流 | draft/pilot | 已有 UI 词表与基础 Mod 组合，正式开放前必须补行业包、测试数据和闭环验证 |
| 平台行业 | 管理端 | admin-only | 平台运维专用，不进入企业注册 7 选 1 |

企业注册当前展示 7 选 1：通用、涂料、考勤、批发、电商、餐饮、物流。开放策略不能只看展示列表，还要看 `industry_baseline.json.onboarding_open_industry_ids`：只有进入该列表的行业才允许作为首批自助开通行业；其余行业可以保留为销售/实施选择，但不能声称已完整交付。

行业包必须包含：

| 模块 | 必填内容 | 验收口径 |
|------|----------|----------|
| 词表 | 业务对象、字段别名、菜单标签、快捷按钮、提示语 | `industry_presets.json` 有完整条目 |
| 数据模型 | 核心实体、导入字段、列表/详情、查询条件 | 至少有一个真实读写闭环 |
| 流程 | 查询、录入、审批、导入导出、打印中的至少一条主流程 | API/前端/测试账号可跑通 |
| Mod 绑定 | host Mod、optional Mod、行业专属 Mod | `industry_baseline.json` 可追溯 |
| 权限 | owner/admin/operator/viewer 对行业对象的读写边界 | RBAC 权限可表达 |
| 样例 | 种子数据、演示账号、演示任务 | 新租户可一键体验 |
| 测试 | 配置校验、路由/API、核心流程 smoke | CI 或本地测试可验证 |

行业授权规则：

| 账号 | 初始化授权 | 可变更方式 | 运行时规则 |
|------|------------|------------|------------|
| personal | `["通用"]` | 不开放 | 固定通用，不进入行业工作台 |
| enterprise | `["通用", industry_id]` | 企业管理员申请，平台/企业 owner 审批 | active industry 必须属于 `entitled_industries` |
| admin | `["管理端"]` | 平台超级管理员 | 默认管理端；代管企业时只继承被代管企业授权，不写回自身 |

行业生命周期：

| 阶段 | 状态 | 进入条件 | 对用户可见性 | 退出条件 |
|------|------|----------|--------------|----------|
| 草稿 | draft | 只有概念、词表或页面样稿 | 不出现在注册选择 | 补齐词表和主流程进入 pilot |
| 试点 | pilot | 有一个可跑闭环、行业包草版、测试账号 | 仅管理员、销售实施或灰度企业可见 | 补齐权限/数据/测试进入 ga |
| 正式 | ga | 行业包、样例数据、权限、文档、测试均完成 | 可进入自助注册/开通列表 | 发现重大缺口降级为 pilot |
| 退役 | retired | 被新行业替代或无人维护 | 不允许新开通，存量只读或迁移 | 完成迁移后移除入口 |

新增行业必须先补配置和验收资产，再开放入口。新增顺序为：`industry_presets.json` → `industry_baseline.json` → 行业 Mod/服务 → 种子数据/测试账号 → 注册/管理端入口。

### 2.9 人格体系

人格不是用户手动选择的“角色皮肤”。人格是运行时由账号、行业、档位、端、任务共同合成的执行身份，用于决定语气、工具、权限和默认工作方式。

Persona 由六层合成，后层只能收窄或特化，不能突破前层权限：

| 层 | 输入 | 例子 | 决定内容 |
|----|------|------|----------|
| 产品层 | 产品线 | XCMAX/FHD 企业助手 | 总体语气、安全边界、默认协作方式 |
| 账号层 | `account_kind` + RBAC | personal、enterprise_owner、enterprise_operator、admin | 可见数据、可执行动作、是否能管理他人 |
| 行业层 | `industry_id` | 涂料、考勤、物流、管理端 | 术语、菜单、业务对象、快捷问题 |
| 档位层 | `account_tier` + VIP | normal/pro/max/ultra、vip/svip | 模型/工具上限、自动化深度、并发与额度策略 |
| 端层 | surface | web、desktop、mobile | 交互密度、本地文件/打印、移动审批、扫码绑定 |
| 任务层 | 当前任务上下文 | 查价、开单、审批、导入 Excel、打印标签 | 临时工具选择、输出格式、确认策略 |

人格类型：

| 类型 | 触发来源 | 用户可见名称 | 典型行为 |
|------|----------|--------------|----------|
| 个人网站助手 | personal + web | 个人 AI 助手 | 解释产品、管理个人消费/VIP、不能进入企业数据 |
| 企业行业助手 | enterprise + 行业 + web/desktop/mobile | 涂料企业助手、考勤移动助手 | 围绕行业对象执行查询、开单、审批、导入导出 |
| 企业管理助手 | enterprise_owner/admin + web/desktop | 企业管理助手 | 管成员、RBAC、行业授权、账单、配置 |
| 企业操作助手 | enterprise_operator + 行业 | 业务操作助手 | 做日常业务，不改权限和套餐 |
| 平台运维助手 | admin + 管理端 | 平台运维助手 | 管平台、审核企业、发布软件、排障和代管 |
| 代管助手 | admin impersonation + enterprise tenant | 代管排障助手 | 临时进入企业上下文，所有动作必须审计 |

内部 Persona key 使用稳定拼接，不单独持久化：

```text
{account_kind}:{rbac_role}:{industry_id}:{account_tier}:{membership_tier}:{surface}
```

示例：

| 场景 | Persona key | 用户可见名称 |
|------|-------------|--------------|
| 涂料企业老板在桌面端 | `enterprise:enterprise_owner:涂料:pro:vip:desktop` | 涂料企业管理助手 |
| 考勤操作员在手机端 | `enterprise:enterprise_operator:考勤:normal:none:mobile` | 考勤移动助手 |
| 平台管理员在官网后台 | `admin:platform_ops:管理端:none:none:web` | 平台运维助手 |

人格合成伪规则：

```text
base = product persona
base = apply_account_policy(base, account_kind, rbac_role)
base = apply_industry_language(base, industry_id)
base = apply_plan_limits(base, account_tier, membership_tier)
base = apply_surface_capabilities(base, surface)
persona = apply_task_context(base, current_task)
```

权限优先级：RBAC/租户隔离 > 账号类型 > 行业授权 > 档位/VIP > 端能力 > 任务偏好。任何人格文案、快捷按钮或工具推荐都不能绕过这个优先级。

人格落地到界面和模型时遵循：
- UI 名称来自行业与端，例如 `涂料助手`、`考勤移动助手`、`平台运维助手`。
- System prompt 只引用派生后的 Persona，不允许用户输入覆盖 `account_kind`、`industry_id`、`tenant_id`。
- 工具列表按 Persona 过滤；不可用工具不展示、不注入、不接受后端调用。
- 任务完成后的审计记录必须写入真实账号、租户、行业和端，而不是只写 Persona 名称。

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
