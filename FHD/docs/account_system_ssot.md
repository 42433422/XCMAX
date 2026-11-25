# 产品端与账号体系：单一真相源 + 自动派生

> 本文档描述 XCMAX/FHD 的产品端矩阵、账号体系四个维度、行业/Persona 派生规则、各自的
> **真相源字段**、**运行时派生规则**、**字段写入权限**与**校验规则**。实现遵循「单一真相源（SSOT）+
> 自动派生」：每个维度只有一个持久化写入点，所有运行时身份/档位均由真相源派生，不再由前端登录入口决定。
>
> **定价 SSOT（运行时）**：本文 §2.2.1（企业宿主）与 §2.4（市场会员）为**商业化定价**的文档 SSOT；
> 机器配置分别为 [`config/saas_plans.json`](../config/saas_plans.json) 与 MODstore
> [`init_default_plan_templates`](../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/db_base.py)。
> 销售/法务以以上定价源为准；退役历史文档的恢复入口见 [`ARCHIVE_POINTER.md`](../../ARCHIVE_POINTER.md)。

## 零、产品端与分发矩阵

本节矩阵的 `personal` 指尚未开通客户端方案的网站身份。已开通个人免费方案的账号复用现有宿主会话，但受独立的免费档能力上限约束，见 §0.3；不能从兼容身份或租户绑定推定拥有企业业务权限。

| 产品端 | 分发/入口 | 支持平台 | 允许账号 | 规则 |
|--------|-----------|----------|----------|------|
| 网站 | 官网 / AI 市场 / 软件下载页 | Web | personal / enterprise / admin | 市场提供统一注册和方案选择；**管理端（`/admin`）仅网页** |
| 桌面端软件 | 软件下载 / 企业交付包 | Windows / macOS | **仅 enterprise** | 必须绑定企业会话；**禁止** personal / **禁止管理员登录与本地 `/admin` 运维台**；管理员请走网页管理端 |

| 手机 App | 应用商店 / 企业分发 | **Flutter**（`mobile-flutter-poc`，覆盖 Android/iOS） | enterprise / admin | 企业移动工作台；账号能力跟随企业授权；**完整管理后台仍以网页为准** |

产品端只决定可进入的运行环境，不决定账号身份。账号身份仍以 `User.tier` 与市场身份提升规则为准。

### 0.1 产品端能力边界

| 产品端 | personal | enterprise | admin |
|--------|----------|------------|-------|
| 官网/网站 | 注册、登录、购买 VIP/月计划、查看个人消费 | 企业注册、购买体验/永久账户、下载软件、管理授权 | **唯一**平台后台入口（独立运维台 `/admin` / admin-console） |
| 桌面端 Windows/macOS | 不允许进入 | 本地业务工作台、行业 Mod、文件/打印/本地数据能力 | **不允许进入**（登录拒绝；不挂载本地 `/admin`；壳内无「管理员登录」入口） |
| 手机端（Flutter） | 不允许 personal | 消息、审批、移动看板、扫码绑定桌面端 | 移动运维告警、会话排障（完整管理台仍走网页） |

约束：个人账号只服务网站个人消费场景；企业账号是业务系统主体；管理员账号是平台运营主体，**仅网页管理端可登录**。桌面端只接受企业会话；不能因为前端入口传了 `account_kind=admin` 或 User.tier=admin 就放行桌面壳。  
桌面端若仍出现 ADMIN 运维对话 / 可进 `/admin`，视为 **SSOT 违规**（实现缺陷），须拒登并引导使用网页版管理端。

### 0.2 入口与下载分发

| 入口 | 主要用途 | 绑定规则 |
|------|----------|----------|
| 官网 | 对外介绍、需求问卷、开户注册、软件下载入口 | 表单预算只作为销售线索，不直接写 `User.account_tier` |
| AI 市场 | VIP/月计划、额度、企业身份/管理员身份来源 | 市场身份只能向上提升本地 `User.tier` |
| 软件下载页 | Windows/macOS/Android/iOS/HarmonyOS 安装包分发 | 下载可公开，首次使用必须登录并校验账号端权限 |
| 管理后台 | 企业审核、授权、RBAC、套餐/行业配置 | 仅 admin 或具备管理权限的企业角色可进入对应后台 |

### 0.3 注册入口契约

- 网页、桌面和手机共用市场 `/market/register`，填用户名和密码。邮箱选填，填写时需要验证码。
- 注册后继续原来选择的方案；未选择时进入同一购买页。来源 `xcagi-desktop` 或 `xcagi-mobile` 仅用于页面交接，授权由服务端校验，回跳只允许站内路径。
- XCAGI 统一分发。个人使用版是同一客户端的免费档，无 Mod 权限。免费档开通不要求领取赠额；验证当前账号的邮箱且活动预算可用时，可领取 5 元 AI 额度，钱包确认入账后才显示领取成功。旧个人 SKU 和本地账户继续兼容既有安装。
- 免费档在宿主中持久化 `User.account_tier=personal`。这不是企业预算等级，而是基础聊天、本人私人记忆的能力上限；即使兼容路径保留企业身份或租户绑定，也不能取得行业 Mod、ERP、财务或 ELT 写入权限。既有业务 API、Agent 工具和持久任务执行均须复核该上限。

### 0.4 MODstore PAT 能力边界

- PAT 是带 scope 的机器凭证，不是登录 JWT，不能转成无范围的 User 权限；有效 PAT 访问未声明能力契约的通用入口返回 403，无效、过期、吊销或用户删除返回 401。
- 当前明确支持 `/v1/mod-sync/*` 的 `mod:sync`，同时检查资源归属；模型网关的 `llm:use` 仅在专用计费服务明确配置并启用后可用。管理员 PAT 也不能越过其他入口的 scope 边界。空 scope 不表示全部权限，存储允许的其他 scope 名称不表示对应接口已迁移。
- 开发者凭证管理与 browser handoff 只接受相应用户登录凭证，不允许 PAT 自我扩权或换成 JWT。历史已派生的 JWT 不会因本次代码修复自动撤销，需独立处置。
- `cst_ro_` 工单读取身份独立，仍执行公司、路径、方法、到期、撤销与脱敏检查；不得并入通用 PAT。
- 未迁移 SDK/员工/工作流的 PAT 调用将被拒绝；恢复支持须逐路由声明 scope、所有权及正反测试，不按 HTTP GET 推定只读。开发者 README/01/02/05/08 页面及文档/Token 面板是本节派生消费页，登记在 `config/ssot.yaml`。这描述代码契约，不代表部署或客户验收完成。

## 一、四维真相源

| 维度 | 真相源字段 | 取值 | 写入点 | 派生消费点 |
|------|-----------|------|-------|-----------|
| 1 账号身份 | `User.tier` | personal / enterprise / admin | 注册（按 SKU）/ 管理端 / 登录时按市场身份提升 | `Session.account_kind`（登录派生） |
| 2 行业 | `User.industry_id` + `User.entitled_industries` | 通用/饰品包装/涂料/考勤/批发/电商/餐饮/物流/管理端 | 注册 / 管理端 | `request.state.industry_id` → Persona 身份 |
| 3 会员体系 | 修茈市场会员等级（外部，`user_plans`） | free/vip/vip_plus/svip/svip2..svip8 | 市场侧月计划购买 | `Session.market_membership_tier`（登录同步） |
| 4 账号等级 | `User.account_tier`（已确认的软件授权） | personal / normal / 历史 pro / max / ultra | 付款履约 / 管理端；免费档受 §0.3 上限约束 | `/api/auth/me` 返回；预算不授予权限 |

## 二、派生规则（运行时计算）

### 2.1 账号身份 → 会话档位
`Session.account_kind ← derive_account_kind_from_user(User.tier, market_is_admin, market_is_enterprise)`
- 以 `User.tier` 为主真相源；修茈市场身份只能**向上提升**（admin > enterprise > personal），不能下调。
- **前端登录入口不再决定档位**（旧 `account_kind` 参数仅作 hint）。
- 登录时若市场身份高于本地 `tier` 且本地为空/personal，则回写 `User.tier` 使本地真相源收敛。
- 例外：impersonation（管理员代管）会话仍由 `/admin/impersonate` 显式设置。
- 实现：[app/application/session_account_meta.py](../app/application/session_account_meta.py) `derive_account_kind_from_user`；
  [app/application/enterprise_login_flow.py](../app/application/enterprise_login_flow.py) `_derive_and_heal_account_kind` / `finalize_enterprise_login`。

### 2.2 购买记录 → 账号等级

新购软件只有 `normal` 一个标准档；免费个人档仍遵守 §0.3。预算只保存为需求线索，不能获得或升级软件权限。兼容函数 `derive_account_tier` 对任何预算返回 `normal`，既有 `pro` / `max` / `ultra` 按已购记录保留，不用预算重新计算或降级。

历史预算选项和别名继续可读，用于管理旧线索；新的永久软件推荐统一返回 `saas-permanent-standard`。用户不能通过填写预算、购买 AI 额度或选择前端页面改变授权。

### 2.2.1 企业购买形态

| 收费项目 | 价格（CNY） | 购买与交付 |
|----------|-------------|------------|
| XCAGI 软件买断 | **6,800，一次付款** | `saas-permanent-standard`；标准软件永久使用，`normal`，无需软件续租 |
| 定制 | **2,980 起** | 先确认需求、交付清单、验收标准和最终报价，再走既有定制订单；起价不是可直接购买的通用定制 SKU |
| AI 调用 | **按实际用量** | 复用钱包、模型价格与用量账单；独立计费，不改变软件授权期限 |

机器真相源为 [config/saas_plans.json](../config/saas_plans.json)：`plans` 只列新售项目，`commercial_terms` 提供定制起价和 AI 说明，`legacy_plans` 仅供历史履约。官网由生成脚本派生价格，独立支付服务的条款镜像受 account-system 漂移检查约束。

次级入口保留 `saas-personal-free`（基础聊天与本人记忆，无 Mod；赠额规则见 §0.3）和 `saas-trial-30`（**99 元 / 30 天，含 100 元模型额度**）。试用到期取服务端原始授权时间，重复登录不能重新获得 30 天；已有永久授权不被试用覆盖。

历史 `saas-permanent-starter` / `growth` / `max` / `ultra` 停止新购，但保留原订单金额、授权档位与履约查找。支付回调核验原订单及金额，重复回调不得重复开通或充值；不能用新售价重算旧账。已有永久软件的账号不能再次购买同一永久软件或试用。

技术测试价只在既有测试开关开启时可创建新订单，默认不出现在正式购买列表；已生成测试订单仍按原记录核对。测试支付或本地测试通过不代表真实支付渠道、生产部署和客户交付已验收。

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
- VIP 是可选的月计划权益层（vip / vip_plus / svip / svip2..svip8），与软件永久授权独立；软件买断不要求订阅 AI 会员，余额耗尽不取消软件授权，AI 额度消耗不反向决定 VIP 或 `account_tier`。
- 会员套餐机器配置：MODstore `PlanTemplate`（种子 [`init_default_plan_templates`](../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/db_base.py)）；当前档：**VIP ¥9.9** → **SVIP8 ¥4,999**。
- 实现：[app/fastapi_routes/market_account.py](../app/fastapi_routes/market_account.py) `fetch_market_membership_tier` / `market_membership_plans`。

### 2.4.1 L1–L6 AI 智能服务订阅（2026-11-25 产品设计候选；尚未生效）

新售 VIP / SVIP 目标名称为 **XCAGI L1–L6 AI 智能服务订阅**。产品定义以[产品宪章](../../specs/product-lines-3-plus-2.md) P011–P015、P026–P027、P072–P080、P087、I025–I027 为准（#3661，已确认目标、尚未生产生效）。个人免费主账号默认 L1，会员解锁相应 L2–L6 调用权；有效企业软件授权及企业体验均可选择 L1–L6，不受会员等级限制，会员仅增加资源权益。认证、RBAC、预算和审批仍独立限制实际执行。个人会员不取得企业业务或 Mod 权益。企业新售永久授权目标 ¥3,000、定制目标 ¥999 起、体验 ¥99/30 天含 ¥100 AI 额度；现行收费及历史合同继续由既有订单和运行时目录履约，候选价格不得直接生效。

| 订阅计划 | 月费（CNY，候选） | 月度 AI 赠额（CNY，候选） | 个人版最高可申请调用等级 | 并发任务上限（候选） | 调度优先级（候选） |
|---|---:|---:|---|---:|---|
| L1 | 0 | 0 | L1 | 1 | 普通 |
| L2 | 19 | 38 | L2 | 1 | 普通 |
| L3 | 49 | 98 | L3 | 2 | 优先 |
| L4 | 99 | 198 | L4 | 3 | 高 |
| L5 | 299 | 598 | L5 | 5 | 很高 |
| L6 | 699 | 1398 | L6 | 8 | 最高 |

新售计划每个完整付费月度周期的 AI 赠额统一为该计划订单锁定月费 × 2（以人民币分为整数计算，L1 为 0）；此为不可提现、不可转让的 AI 使用额度，不是现金返还或实际充值，不改变历史订单权益。升级、同级续费及到期语义按 P074–P078；具体补差及退款计算、折扣、成本和非完整周期边界须独立核验，禁止重复发放；上线前须核算满额消耗情形下的真实模型成本和贡献毛利，不满足成本门禁不开放收费。个人版高档向下兼容低档调用权；企业版六级选择权不依赖订阅。会员可增加并发、调度优先级与高级模型权益，具体配额仍待确认。L1 免费不等于模型无限免费；已有邮箱验证及活动预算下的一次性 5 元赠额按 §0.3 保留，不计作每月赠额。取消新计划的云存储扩容权益，不据此删除用户文件、取消基础存储安全限制或收回历史已购存储权益。上述价格、额度、并发及服务承诺为产品候选，尚未核算单位成本或通过支付、技术与交付验收；**本节不是新售价格运行时 SSOT，不得据此直接创建收费订单**。获准上线时迁移现有 PlanTemplate 唯一权威源、同步原派生页面，不另建会员、价格或钱包系统。

### 2.4.2 AI 能力说明书

AI 等级定义以产品宪章 P014、P042、§2 为唯一规范；下表是面向订阅评审的非独立权威说明。每级继承较低等级已验收能力；业务能力仍受产品授权、工具权限、预算及审批限制。

| 等级 | 定义 / 角色 | 能力范围 | 人类责任与边界 |
|---|---|---|---|
| L1 辅助智能 / Assisted Intelligence | AI 助手，提供辅助结果 | 对话问答、联网搜索、文档及多模态理解、私人记忆、内容创作、数据分析、工作建议 | 人类提出问题、决定和执行；不独立承担业务任务 |
| L2 执行智能 / Execution Intelligence | AI 执行员，完成明确任务 | 意图识别、工具选择、文件创建编辑、Excel 处理、代码编写执行、自定义技能、授权软件操作、任务结果核验 | 人类下达有限目标；不得自行扩大工具或数据权限 |
| L3 工作智能 / Workflow Intelligence | AI 员工，完成工作闭环 | 任务分解与规划、多步骤工作流、跨工具及系统协作、依赖管理、过程记录、重试恢复、审批交接、独立成果验证与交付；深度研究、定时任务、BYOK 按可用性开放 | 人类设定目标和验收标准；不自主改变经营目标 |
| L4 自治智能 / Autonomous Intelligence | 自治 AI 员工，持续承担职责 | 持续状态与恢复、业务感知、异常与待办发现、候选任务生成、事件驱动、后台长任务、多模型协作、多任务与员工协调、异常诊断、主动汇报及人工交接 | 人类设定职责、规则、期限、预算和授权；禁止越权和未知副作用重派 |
| L5 进化智能 / Evolutionary Intelligence | 进化型 AI 数字生命体，基于证据改善能力 | 自我能力认知、历史表现、反思、经验学习、策略与工作流改进、客户反馈、独立留出集实验、效果评估、退化识别、审批推广与回滚 | 人类确定进化规则；没有独立改善证据不升级，禁止无审批修改或推广 |
| L6 经营智能 / Strategic Intelligence | 经营型 AI 数字生命体，组织工作与评估经营结果 | 企业状态感知与世界模型、机会及问题发现、目标分解、方案比较（含不行动）、预测冻结及结果核验、员工管理、跨部门协作、资源与预算分配、成本收入效益分析、战略复盘及调整 | 人类设定经营使命与授权、资源及风险红线；重大经营决策审批不可绕过，AI 不具有独立法人身份，企业所有者承担最终责任 |

以上为能力定义和验收目标，不是当前已上线能力证明。新功能及实验能力须单独标明预览状态与风险，不得以 L4/L5/L6 订阅冒充已验收自治能力。

### 2.4.3 调用权、结算和存量迁移

- 复用现有市场会员订单和会话投影。分别表达产品自治选择范围、会员资源权益（个人另含等级调用权）、独立认证能力和任务请求等级；企业有效软件授权/体验的自治选择范围为 L1–L6，个人默认 L1 并按会员解锁。历史合同按原承诺履约。实际执行须同时满足产品授权、已认证部署能力、RBAC、任务授权、审批和预算；会员等级不得限制企业自治选择，也不得提升角色权限。缺失、过期、撤销或未知证据时拒绝不合规调用，不自动降级执行有副作用任务；客户端选项、模型提示、充值及 BYOK 均不能提权。
- 个人及企业身份与订阅独立；个人付费仍不可获得企业 ERP、行业 Mod、财务、企业员工管理等业务授权。买断客户未订阅、余额不足或订阅到期，不丧失已购软件的永久使用权。
- 新计划按原订单金额、SKU、版本、有效期、已授权范围履约；真实支付确认后幂等开通，重复回调不得重复赠额。赠额与实际充值分账，优先消耗将到期赠额，周期赠额到期不续存，实付余额不因会员变化被清零。按 P074–P078，高等级补差后立即升级，月度计划从升级日重计 30 天，清除旧会员未用赠额并重发新等级完整售价两倍赠额，充值余额保留；同级提前续费按购买时长延长，当前周期不重发赠额，下周期发放且旧赠额到期清零；有效期内不支持主动降级，到期重新选购，任务滑杆可随时调低。首次购买、续费、升级、到期及退款均须可审计回执；自动续费须明确授权。补差/退款具体计算、成本、套利、并发及履约须先确认并通过验证，未验证不得收费。
- 已售 VIP、VIP+、SVIP～SVIP8 保留原订单、金额、有效期、合同权益、历史账单和原 ID；不强制映射为 L 等级、不重算旧账或删除原记录。新售切换仅在全部迁移及真实结算门禁通过后进行；存量超额、无限量或驻场服务等承诺按原合同处理，不扩展至新售计划。
- 新计划不承诺无限 AI 调用、无限人工服务或尚未兑现的 SLA。服务优先级不得越过模型容量与安全隔离；高级模型、并发和服务优先级为待核算资源权益；技能、定时、BYOK、后台任务、多模型协作及学习经营能力按产品宪章、个人调用权或企业软件授权以及认证、权限、预算和审批治理，不以企业订阅等级锁定。其他服务承诺未确认、未验收，不售卖。

### 2.4.4 实施与正式发布门槛（全部待验收）

1. 复用现有 `PlanTemplate`、市场购买/钱包/支付履约及会话授权接口，迁移官网、市场、桌面、移动、管理端和失败回退目录；新计划与历史计划不得形成双权威。保留市场原身份、企业授权、RBAC、租户隔离和审批合同。
2. 正反控：免费账号独立订阅、不买断不获 ERP、有效企业买断或体验不订阅仍可选择 L1–L6，企业会员变更不改变自治选择范围；个人按会员解锁且向下兼容；伪造客户端等级、过期/撤销、未通过验收、跨租户、权限缓存和在途任务续跑必须被正确拒绝或受控交接。
3. 真实结算与独立账本：同一订单金额及版本、付款/退款/续期/到期、补差重置 30 天与新价两倍赠额、提前续费不提前发额、有效期内拒绝主动降级、重复或乱序回调、赠额优先消耗及实付余额保留、历史订单回读、失败回滚及账本对账。禁止以真实资金试错或未经授权发布。
4. 能力验收沿现有自治独立评估、运行账本和证据门禁执行；结合现有 WG12 独立自治验收与生产证据工单（#3523），绑定已合入 SHA、部署及独立真实回执。L4 的长期运行、L5 的真实留出集改善、L6 的长期真实经营效果不能由模拟或文档代替。
5. 定价前核算模型、并发、支付、赠额、服务与故障恢复成本，验证边际毛利；同一冻结 SHA 的 required CI、源治理/preflight、支付沙箱、正式渠道的受控验证、跨端权益和能力验收通过后才可逐级销售。未验证等级标记为研发中且不可收费，缺证据保持 BLOCKED；不直接更改生产数据库或生效价格。

### 2.5 行业 → Persona
`request.state.industry_id ← User.industry_id`（admin → 管理端，兜底 通用），再派生 Persona 身份。
- 实现：[app/middleware/industry_context.py](../app/middleware/industry_context.py)、[app/application/planner_compat_service.py](../app/application/planner_compat_service.py)。

行业体系的当前可注册范围为 8 选 1：通用、饰品包装、涂料、考勤、批发、电商、餐饮、物流；管理端为 admin 专用行业，不出现在企业注册选择中。后续新增行业只能先进入 [config/industry_presets.json](../config/industry_presets.json)，再绑定对应 Mod、字段词表、导航标签、示例数据与权限策略。

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
| 客户私有交付 | [config/customer_delivery.json](../config/customer_delivery.json) | 客户品牌、`legacy_mod_id`（定制）与 `industry_mod_id`（通用行业包）映射；生产员工私有交付入口只暴露定制包；转返工开现有客服变更工单（`user_cs_change_request` · `bug_fix`）；**交付面 = 通用 Enterprise 包 + 私有交付进度** | 禁止把 `attendance-industry` 等通用行业包当作生产员工/私有交付项目；禁止另建返工工单系统；**禁止再发太阳鸟定制安装包（`太阳鸟-Setup`）作为正式交付** |

当前行业分层：

| 类型 | 行业 | 状态 | 说明 |
|------|------|------|------|
| 基础行业 | 通用 | ga | 所有账号兜底行业；不绑定专属行业包 |
| 首批行业包 | 饰品包装、涂料、考勤 | pilot/ga 优先 | 已在 `industry_baseline.json` 明确 `industry_packages`，可作为首批真实交付行业；考勤包保留历史行业选择兼容，新交付可作为跨行业通用模块组合使用 |
| 预置方向 | 批发、电商、餐饮、物流 | draft/pilot | 已有 UI 词表与基础 Mod 组合，正式开放前必须补行业包、测试数据和闭环验证 |
| 平台行业 | 管理端 | admin-only | 平台运维专用，不进入企业注册 8 选 1 |

企业注册当前展示 8 选 1：通用、饰品包装、涂料、考勤、批发、电商、餐饮、物流。开放策略不能只看展示列表，还要看 `industry_baseline.json.onboarding_open_industry_ids`：只有进入该列表的行业才允许作为首批自助开通行业；其余行业可以保留为销售/实施选择，但不能声称已完整交付。

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
| 行业层 | `industry_id` | 饰品包装、涂料、考勤、物流、管理端 | 术语、菜单、业务对象、快捷问题 |
| 档位层 | `account_tier` + VIP | normal/pro/max/ultra、vip/svip | 模型/工具上限、自动化深度、并发与额度策略 |
| 端层 | surface | web、desktop、mobile | 交互密度、本地文件/打印、移动审批、扫码绑定 |
| 任务层 | 当前任务上下文 | 查价、开单、审批、导入 Excel、打印标签 | 临时工具选择、输出格式、确认策略 |

人格类型：

| 类型 | 触发来源 | 用户可见名称 | 典型行为 |
|------|----------|--------------|----------|
| 个人网站助手 | personal + web | 个人 AI 助手 | 解释产品、管理个人消费/VIP、不能进入企业数据 |
| 企业行业助手 | enterprise + 行业 + web/desktop/mobile | 涂料企业助手、考勤移动助手 | 围绕行业对象执行查询、开单、审批、导入导出 |
| 企业管理助手 | enterprise_owner + web/desktop；admin 仅 web | 企业管理助手 | 管成员、RBAC、行业授权、账单、配置 |
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
| `User.account_tier` | — | ✅（仅 enterprise） | ✅（按已确认的软件授权；预算不授予权限） |
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

- 会员体系（维度 3，AI 调用额度）与软件授权（维度 4，标准软件及历史档位）独立，互不派生。
- `contact.html` 和注册信息中的预算都只作销售线索，不作为 `account_tier` 的派生来源，也不参与新软件报价。
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

### 已纳入隔离的业务表（15）
products / purchase_units / materials / shipment_records / financial_transactions /
suppliers / purchase_orders / purchase_order_items / purchase_inbounds / purchase_inbound_items /
warehouses / storage_locations / inventory_ledger / inventory_transactions / templates。

模板库额外约定：DB `templates.tenant_id` 读写过滤；文件系统发现仅扫内置目录 + `tenants/{tid}/templates`（不再扫共享 runtime，避免跨租户串文件）。

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
