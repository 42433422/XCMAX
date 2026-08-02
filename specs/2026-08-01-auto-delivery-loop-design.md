# 自动交付闭环设计(Auto-Delivery Loop)

> **状态**:设计稿 v3(修正前端入口 + 复用已有客服工单系统)
> **日期**:2026-08-01
> **适用范围**:`XCMAX/` 根仓,跨 FHD + MODstore + yuangon
> **依赖**:`specs/product-lines-3-plus-2.md`(产品线 3+2)
> **v1 修正**:v1 错把所有交付等同于"合 main → fhd-pack-release → 客户端整包更新"。v2 基于代码实证修正为 **6 条并行交付流水线**。
> **v3 修正**:v2 设计"新建 `customer_tickets.py` + `TicketFeedback.vue`"是重复造轮子。v3 基于代码实证修正为 **复用已有 3 个前端入口 + 已有 8 张客服工单表 + 已有编排层**,唯一新增是一个"工单 → 流水线"桥接层。**前端零改动**。

---

## 0. 一句话目标

**客户提工单 → daily-orchestrator 按 category 路由到 6 条交付流水线之一 → 56 个 AI 员工协作处理 → 客户端按模块机制收到交付 → 回执闭环**,全程零人工干预(异常才升级人工)。

---

## 1. 模块边界盘点(代码实证)

FHD 实际有 **8 个独立更新模块**,各自机制不同:

| # | 模块 | 路径 | 更新机制 | 客户端影响 | 实证 |
|---|------|------|---------|-----------|------|
| 1 | 服务器 API | `FHD/app/` + `XCAGI/` + `alembic/` | fhd-pack-release → push CVM(119.27.178.147)→ cron fhd-auto-update → fhd-apply-release | **无(对客户透明)** | `fhd-pack-release.sh` L125 |
| 2 | 服务器 admin-console | `FHD/admin-console/` → `templates/admin-vue-dist/` | 随 fhd-pack-release 一起打包(sha256 守护) | 无(管理端) | `fhd-pack-release.sh` L132 |
| 3 | 服务器 mods/ | `FHD/mods/` | 随 fhd-pack-release 一起打包 | 客户端 catalog API 拉新 mod | `fhd-pack-release.sh` L125 |
| 4 | 桌面壳 | `FHD/desktop/main.ts` + `updater.ts` | electron-builder → 推 update 站 `xiu-ci.com/releases/stable/enterprise/` → electron-updater 拉 `latest.yml` | **用户确认下载+重启** | `main.ts:269` + `updater.ts:265` |
| 5 | 桌面端后端 | `FHD/app/`(PyInstaller 内嵌到 `backend/_internal/`) | 随桌面壳整包更新 | 整包升级 | `main.ts:693` |
| 6 | 桌面端前端 | `FHD/frontend/` → `vue-dist`(PyInstaller 内嵌) | 随桌面壳整包更新(**无独立热更新**) | 整包升级 | `electron-builder.yml:21` |
| 7 | Entitlement | 服务器 → 企业端 | `/admin/market/users/{user_id}/entitlements/push` + `xcmax_sync_service` outbox 双向同步 | **客户端自动同步,无操作** | `xcmax_admin.py:1341` + `xcmax_sync_service.py:780` |
| 8 | AI 员工 / Mod catalog | `yuangon/` 56 员工 + `FHD/mods/` | 注册到 MODstore catalog → 推送 entitlement → 客户端拉 `/catalog` API | **catalog 出现新员工,一键启用** | `mod_store_routes.py:460` |

### 1.1 关键事实

1. **fhd-pack-release.sh 只更新 CVM 服务器**(`/opt/fhd-full`),**不更新客户桌面端**
2. **桌面端走 electron-updater 整包升级**,feed URL = `https://xiu-ci.com/releases/stable/enterprise/`
3. **vue-dist 被 PyInstaller 内嵌进桌面安装包**(`process.resourcesPath/backend/_internal/templates/vue-dist/index.html`),无独立热更新通道
4. **fhd-push-frontend-dist.sh 推的是服务器 admin-console 的 vue-dist**,不是桌面端的
5. **mods/entitlement 可以独立交付,不需要重装桌面端**:
   - 服务器 mods/ 更新 → 客户端通过 `/catalog` API 拉取
   - entitlement 推送 → outbox 同步到企业端

### 1.2 服务器端 update 站结构

```
/var/www/update/releases/
├── stable/
│   ├── server/          # 服务器 API 包(fhd-pack-release)
│   │   ├── fhd-manifest.json
│   │   └── fhd-full-<version>-<sha>.tar.gz
│   ├── enterprise/      # 企业桌面端安装包(electron-updater feed)
│   │   ├── latest.yml
│   │   ├── latest-mac.yml
│   │   └── XCAGI-Enterprise-Setup-*.exe / .dmg
│   ├── personal/        # 个人桌面端(冻结)
│   └── vue-dist/        # 服务器 admin-console 前端
└── staging/
    └── server/
```

### 1.3 已有前端入口盘点(代码实证,**不新建前端**)

FHD + MODstore 已有 **3 个完整前端入口 + 完整客服工单后端**:

#### 3 个前端入口(全部已实现)

| # | 入口 | 路径 | 当前能力 |
|---|------|------|---------|
| 1 | **MODstore 智能客服** | `MODstore_deploy/market/src/views/CustomerServiceView.vue` | 完整对话 + 工单列表 + 进度 timeline + "需要跟进时帮你建工单" + 图片上传 + 快捷提示 |
| 2 | **浮窗 AI 客服** | `MODstore_deploy/market/src/components/floating-agent/FloatingAgentRoot.vue` | 悬浮球 + 对话面板 + AgentEngine + Skills + Orchestrator + 权限弹窗 + 主动建议 + vibe-coding 改写进度遮罩 |
| 3 | **官网 AI 客服** | `成都修茈科技有限公司/corp-butler/corp-butler.js` + `marketing-site/templates/partials/corp-butler.njk` | 官网访客对话,挂载到 `#xc-corp-butler-root`,加载 corp-butler.js + css |

#### 制造员工入口(已实现,主动制造非反馈)

| 入口 | 路径 | 能力 |
|------|------|------|
| `ModAuthoringView.vue` → `ModAuthoringPage.vue` | `MODstore_deploy/market/src/features/mod-authoring/` | Wizard(分步)+ Expert(专家)双模式制造 Mod/员工 |
| `MyEmployeesView.vue` | `MODstore_deploy/market/src/views/` | 我的员工管理(查看/启用已分配员工) |
| `MakeFlowView.vue` | `MODstore_deploy/market/src/components/workbench/make/` | 工作台内制造流程 |
| `EmployeePanel.vue` | `MODstore_deploy/market/src/components/workbench/` | 员工面板 |

#### 已有客服工单后端(modstore_server,8 张表 + 编排层 + API)

| 组件 | 路径 | 能力 |
|------|------|------|
| `customer_service_api.py` | `MODstore_deploy/modstore_server/` | 7 个 API endpoint |
| `customer_service_orchestrator.py` | 同上 | 对话优先 / 意图识别 / 自动建单 / 决策 / 审计 |
| `customer_service_tools.py` | 同上 | audit / build_action / execute_action / execute_matching_integrations |
| `models_cs.py` | 同上 | **8 张表**(见下) |

**8 张客服工单表**:
- `customer_service_sessions`(会话:user_id / channel / status / intent / context_json)
- `customer_service_tickets`(工单:ticket_no / title / intent / subject_type / subject_id / status / priority / evidence_json / summary / decision_status / automation_level / assigned_admin_id)
- `customer_service_messages`(消息)
- `customer_service_standards`(服务标准)
- `customer_service_decisions`(决策)
- `customer_service_actions`(动作:idempotency_key 去重)
- `customer_service_integrations`(集成)
- `customer_service_audit_logs`(审计日志)

**已有 API 端点**:
- `POST /api/customer-service/chat`(对话,30s 超时)
- `GET /api/customer-service/sessions`(会话列表)
- `GET /api/customer-service/sessions/{id}`(会话详情)
- `GET /api/customer-service/tickets?status=`(工单列表)
- `GET /api/customer-service/tickets/{id}`(工单详情)
- `GET /api/customer-service/actions?ticket_id=`(动作列表)
- `GET /api/customer-service/standards`(服务标准)

**已有意图识别**(`customer_service_orchestrator.py`):
- 8 种 intent:`greeting` / `general` / `product_issue` / `refund` / `catalog_complaint` / `catalog_review` / `account_support` / `llm_extension`
- 3 种 issue_domain:`platform`(平台)/ `software`(软件)/ `custom`(客户定制)
- ESCALATE_RE 正则识别"转人工/提交工单/升级处理"等关键词
- 对话优先:寒暄/一般咨询只回复不建单;材料齐可自动受理或用户明确升级时才建单

#### v3 核心策略

1. **前端零改动**:3 个入口已完整,不新建任何前端组件
2. **后端零新建**:不新建 `customer_tickets.py`,扩展 `customer_service_orchestrator.py`
3. **唯一新增**:一个"工单 → 交付流水线"桥接层 `ticket_pipeline_bridge.py`
   - 在 `customer_service_orchestrator` 建单后调用
   - 根据 `intent` + `subject_type` + `issue_domain` 映射到 6 条流水线
   - 调用对应流水线的入口(ai-issue-implement / catalog-push / entitlement-push / xcmax-sync / direct-reply)

---

## 2. 6 条并行交付流水线

不同工单类别触发不同交付流水线,**不要硬塞进一条**:

| 工单 category | 影响模块 | 交付流水线 | 客户动作 | SLA(r1) |
|--------------|---------|-----------|---------|---------|
| `cat/bug-backend` | 服务器 API | 合 main → fhd-ci-cd.yml → fhd-pack-release → fhd-push-release → CVM cron auto-update | **无** | 24h |
| `cat/bug-admin` | admin-console | 随 fhd-pack-release(sha256 守护) | **无** | 24h |
| `cat/bug-desktop` | 桌面壳 main.ts | 合 main → release-desktop.yml → 推 update 站 enterprise/ → electron-updater feed | 用户下载+重启 | 72h |
| `cat/bug-frontend` | 桌面端 vue-dist | 随桌面壳整包(无热更新) | 用户下载+重启 | 72h |
| `cat/craft-employee` | 新增员工 | craft-workshop 造 → 注册 catalog → push entitlement → 客户端 `/catalog` 拉 | 一键启用 | 48h |
| `cat/craft-mod` | 新增 Mod | 同上 | 一键启用 | 48h |
| `cat/inquiry` | 无代码 | user-customer-service-officer 直接回复 | 无 | 4h |
| `cat/entitlement` | 授权变更 | `/admin/market/users/{user_id}/entitlements/push` → outbox sync | **无** | 1h |
| `cat/config` | 客户配置 | xcmax_sync_service push outbox(personnel/department/template 等) | 无 | 4h |

### 2.1 闭环数据流

```
[已有前端入口,零改动]
  MODstore 智能客服 │ 浮窗 AI 客服 │ 官网 corp-butler
  (CustomerServiceView) (FloatingAgentRoot) (corp-butler.js)
  └────────────────┴────────────────┘
                   ▼
  POST /api/customer-service/chat(已有 API,零改动)
  - customer_service_orchestrator 识别 intent + issue_domain
  - 寒暄/一般咨询只回复不建单
  - 材料齐或用户升级 → 建单到 customer_service_tickets 表
                   ▼
  ticket_pipeline_bridge.py(新,桥接层)
  - 根据 intent + issue_domain 映射到 6 条流水线
  - 写 action(dispatch_pipeline)
  - 调用对应 adapter
                   ▼ 按 intent + domain 路由
  ┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
  ▼              ▼              ▼              ▼              ▼              ▼
[流水线 1]    [流水线 2]    [流水线 3]    [流水线 4]    [流水线 5]    [流水线 6]
server-api    desktop-shell  catalog-push  entitlement   config-sync   direct-reply
                            (Phase 2)     -sync(Phase4)  (Phase 4)
server_api    desktop_shell catalog_push   entitlement    config_sync   direct_reply
_adapter      _adapter      _adapter       _sync_adapter  _adapter      _adapter
(Phase 1)     (Phase 3)     (Phase 2)                                   (Phase 1)
合 main →     合 main →     craft-         /admin/.../    xcmax_sync    user-
ai-issue-     release-      workshop       entitlements   _service      customer-
implement →   desktop.yml   造员工         /push →        push          service-
ai-review →  → update 站   → 注册 catalog  outbox sync    outbox        officer
合并 →        → electron-   → push         → 客户端       → 客户端       → 回复
fhd-pack →    updater feed  entitlement    自动同步       业务数据同步
push CVM →    ↓             ↓
cron auto-   [用户下载      [客户端
update       +重启]         catalog 出
             (72h SLA)     现新员工]
[客户下次                    ↓
 请求即是                  [一键启用]
 新版]                     (48h SLA)
(24h SLA)
                   ▼
  各 adapter 回写 customer_service_actions 表
  (action_type: pipeline_progress / pipeline_delivered / pipeline_failed)
                   ▼
  前端 CustomerServiceView.vue 的 loadTickets 自动拉取展示
  (已有逻辑,零改动)
                   ▼
                [客户在工单列表看到交付进度]
```

### 2.2 设计原则

1. **6 条流水线并行**,工单 category 决定走哪条,不要统一流水线
2. **GitHub Issue 是工单内部表示**,不另开工单数据库
3. **客户身份 = entitlement_id**,不要求客户有 GitHub 账号
4. **tier 决定 SLA**,复用 r0/r1/r2/r3 风险分级
5. **优先走对客户透明的流水线**(bug-backend / entitlement / config),桌面壳升级作为最后手段
6. **回执双通道**:Issue 评论(内部)+ 桌面端通知 + 工单状态页(客户)
7. **失败兜底**:任何 AI 员工失败 → 3 次重试 → escalated → 人工

---

## 3. 数据模型(复用已有 customer_service_tickets)

### 3.1 已有字段复用

`customer_service_tickets` 表已有字段直接复用:

| 字段 | 用途 | v3 扩展 |
|------|------|---------|
| `ticket_no` | 工单号(自动生成) | 无需改 |
| `user_id` | 客户标识(FK to users) | 无需改 |
| `intent` | 意图(8 种) | 无需改 |
| `subject_type` | 业务对象类型 | 无需改 |
| `subject_id` | 业务对象 ID | 无需改 |
| `status` | 工单状态 | 扩展取值(见 §4.4) |
| `priority` | 优先级 | 无需改 |
| `evidence_json` | 证据 JSON | 扩展结构(见 §3.2) |
| `summary` | 摘要 | 无需改 |
| `decision_status` | 决策状态 | 扩展取值(`auto_dispatched` 等) |
| `automation_level` | 自动化级别 | `auto` = 自动路由到流水线 |
| `assigned_admin_id` | 指定管理员 | escalated 时填 |

### 3.2 evidence_json 结构扩展

```json
{
  "customer_tier": "r1",
  "entitlement_id": "ent_xxx",
  "source": "desktop",
  "pipeline": "server-api",
  "pipeline_dispatched_at": "2026-08-01T10:01:00+08:00",
  "sla_deadline": "2026-08-02T10:00:00+08:00",
  "target_module": "app/services/shipment/",
  "attachments": [
    {"name": "screenshot.png", "url": "https://modstore.../uploads/xxx.png"}
  ],
  "original_message": "后台导出 Excel 时 500 报错,日志显示 KeyError: 'shipment_id'",
  "capability_proposal_id": null,
  "corp_chat_session_id": 456
}
```

### 3.3 工单状态机(复用 status 字段)

```
open(orchestrator 建单)
  ↓ 桥接层接管
dispatching(路由到流水线中)
  ↓ adapter 开始执行
in_progress(流水线执行中)
  ↓ 处理完成(需 review 的流水线)
reviewing(ai-review 中)
  ↓ 审核通过
deploying(部署中)
  ↓ 交付完成
delivered(回执已推送)
  ↓ 客户确认或 7 天自动
closed
```

异常分支:
- 任何阶段失败 3 次 → `escalated`(`assigned_admin_id` 填人工)
- reviewing 不通过 → 退回 `in_progress`
- deploying 失败 → 自动回滚 → `escalated`

### 3.4 actions 表(复用已有,扩展 action_type)

`customer_service_actions` 表记录工单全生命周期动作:

| action_type | 触发者 | 说明 |
|------------|--------|------|
| `dispatch_pipeline` | 桥接层 | 分派到流水线 |
| `pipeline_progress` | adapter | 进度更新(如 fix_ready / reviewed / merged) |
| `pipeline_delivered` | adapter | 交付完成 |
| `pipeline_failed` | adapter | 流水线失败 |
| `pipeline_escalated` | 桥接层 | 升级人工 |

前端 `CustomerServiceView.vue` 的 `cs-ticket__body` 已能展示 actions timeline(通过 `api.customerServiceActions` 拉取),**零改动**。

---

## 4. API 设计(复用已有 customer-service API)

### 4.1 已有 API(零改动,直接复用)

| 端点 | 方法 | 用途 | 已有实现 |
|------|------|------|---------|
| `/api/customer-service/chat` | POST | 客户对话 / 意图识别 / 自动建单 | `customer_service_api.py` |
| `/api/customer-service/sessions` | GET | 会话列表 | 同上 |
| `/api/customer-service/sessions/{id}` | GET | 会话详情 | 同上 |
| `/api/customer-service/tickets?status=` | GET | 工单列表 | 同上 |
| `/api/customer-service/tickets/{id}` | GET | 工单详情(含 actions timeline) | 同上 |
| `/api/customer-service/actions?ticket_id=` | GET | 工单动作列表(进度 timeline) | 同上 |
| `/api/customer-service/standards` | GET | 服务标准 | 同上 |

**前端已对接**:`CustomerServiceView.vue` 的 `api.customerServiceChat` / `api.customerServiceTickets` / `api.customerServiceTicketDetail`。

### 4.2 新增内部 API(桥接层用,不暴露给前端)

```
POST /api/customer-service/internal/dispatch
# 桥接层调用,orchestrator 建单后自动触发
# 根据 intent + subject_type + issue_domain 映射到流水线

Body:
{
  "ticket_id": 123,
  "intent": "product_issue",
  "issue_domain": "platform",
  "subject_type": "shipment_export",
  "evidence_json": {...}
}

Response 200:
{
  "pipeline": "server-api",
  "dispatched": true,
  "adapter": "server_api_adapter",
  "estimated_sla_hours": 24
}
```

```
POST /api/customer-service/internal/pipeline-progress
# 流水线适配器回写进度

Body:
{
  "ticket_id": 123,
  "action_type": "pipeline_progress",  # 或 pipeline_delivered / pipeline_failed
  "actor": "ai-issue-implement",
  "event": "fix_ready",
  "note": "修复已提交,等待 review"
}
```

### 4.3 intent + domain → pipeline 映射表(桥接层核心逻辑)

| intent | issue_domain | → pipeline | → adapter | SLA(r1) |
|--------|-------------|-----------|-----------|---------|
| `product_issue` | `platform` | `server-api` | `server_api_adapter` | 24h |
| `product_issue` | `software` | `desktop-shell` | `desktop_shell_adapter` | 72h |
| `product_issue` | `custom` | `catalog-push` | `catalog_push_adapter` | 48h |
| `catalog_complaint` | `software` | `server-api` | `server_api_adapter` | 24h |
| `catalog_review` | - | `direct-reply` | `direct_reply_adapter` | 4h |
| `refund` | - | `entitlement-sync` | `entitlement_sync_adapter`(Phase 4) | 1h |
| `account_support` | - | `config-sync` | `config_sync_adapter`(Phase 4) | 4h |
| `llm_extension` | - | `catalog-push` | `catalog_push_adapter` | 48h |
| `general` / `greeting` | - | `direct-reply` | `direct_reply_adapter` | 4h |

### 4.4 工单状态扩展(复用已有 status 字段)

已有 `customer_service_tickets.status` 字段,扩展取值:

| status | 含义 | 触发 |
|--------|------|------|
| `open` | 已建单,待分派 | orchestrator 建单 |
| `dispatching` | 桥接层路由中 | 桥接层接管 |
| `in_progress` | 流水线执行中 | adapter 开始执行 |
| `reviewing` | ai-review 中 | server-api / desktop-shell 适配器 |
| `deploying` | 部署中 | fhd-pack-release / release-desktop.yml |
| `delivered` | 已交付 | adapter 监听完成 |
| `escalated` | 升级人工 | 失败 3 次 |
| `closed` | 已关闭 | 客户确认或 7 天自动 |

### 4.5 actions 表扩展(复用已有 action_type)

已有 `customer_service_actions` 表,扩展 action_type 取值:

| action_type | 含义 |
|------------|------|
| `dispatch_pipeline` | 桥接层分派到流水线 |
| `pipeline_progress` | 流水线进度更新 |
| `pipeline_delivered` | 流水线交付完成 |
| `pipeline_failed` | 流水线失败 |
| `pipeline_escalated` | 升级人工 |

前端 `CustomerServiceView.vue` 的 `loadTickets` + `cs-ticket__body` 已能展示 actions timeline,**零改动**。

---

## 5. 6 条交付流水线详解

### 5.1 流水线 1:server-api(服务器 API 更新)

**触发**:`cat/bug-backend` / `cat/bug-admin`

**执行步骤**:
```
1. fhd-core-maintainer 接管 → 调用 ai-issue-implement.py(memory 已实证)
2. ai-issue-implement 写代码 → ai-review.py 审 → github-pr-gatekeeper 合并到 main
3. main 合并触发 fhd-ci-cd.yml
4. fhd-ci-cd 通过 → fhd-pack-release.sh 打包(含 app/ + XCAGI/ + mods/ + admin-vue-dist)
5. fhd-push-release.sh 推 CVM(119.27.178.147)
6. CVM cron fhd-auto-update.sh(每 5 分钟)→ fhd-apply-release.sh
7. 健康检查通过 → delivery-receipt-officer 推回执
```

**回滚**:`fhd-apply-release.sh` 失败自动从 `/opt/fhd-full-backups/` 回滚(memory 已有机制)

**客户感知**:无,下次请求即是新版

**关键复用**:
- `ai_issue_implement.py` / `ai_review.py` / `ai_self_heal.py`(`FHD/scripts/ci/`)
- `fhd-pack-release.sh` / `fhd-push-release.sh` / `fhd-auto-update.sh` / `fhd-apply-release.sh`(`FHD/scripts/deploy/`)
- `fhd-ci-cd.yml` / `fhd-release-orchestrator.yml`

### 5.2 流水线 2:desktop-shell(桌面壳升级)

**触发**:`cat/bug-desktop` / `cat/bug-frontend`

**执行步骤**:
```
1. fhd-core-maintainer 接管 → 修 desktop/main.ts 或 frontend/src/
2. ai-review 审 → 合并到 main
3. main 合并触发 release-desktop.yml
4. electron-builder 打包(Windows .exe + macOS .dmg)
5. 上传 update 站 /var/www/update/releases/stable/enterprise/
6. 更新 latest.yml / latest-mac.yml
7. 客户端 electron-updater 拉 latest.yml → 发现新版 → 通知客户
8. 客户确认下载 → quitAndInstall(false, true)
9. 重启后 triggerRollbackSafe 验证启动稳定性(memory 已有机制)
10. delivery-receipt-officer 推回执
```

**回滚**:`runBackendMigrationWithRollback` + `triggerRollbackSafe`(main.ts:877/888)+ electron-updater Ed25519 签名 + 自动回滚观察期

**客户感知**:需要下载+重启,SLA 长

**关键复用**:
- `release-desktop.yml` / `release-desktop-mac-ota.yml` / `fix-mac-update-feed.yml`
- `updater.ts`(electron-updater 集成)
- `SKU_UPDATE_URL`(main.ts:267)

### 5.3 流水线 3:catalog-push(造员工 / 造 Mod)

**触发**:`cat/craft-employee` / `cat/craft-mod`

**执行步骤**:
```
1. craft-workshop 全流程(memory 已有 12 员工):
   employee-planner → artifact-generator → code-validator → sandbox-tester
   → quality-validator → pack-registrar
2. employee-pack-quality-interviewer + employee-interview-assistant 质检
3. pack-registrar 注册到 MODstore catalog(/catalog API)
4. /admin/market/users/{user_id}/mods POST 分配到客户
5. /admin/market/users/{user_id}/entitlements/push 推送 entitlement
6. 客户端 xcmax_sync_service outbox 同步 → catalog 出现新员工
7. 客户桌面端"我的员工"页面 → 一键启用
8. delivery-receipt-officer 推回执
```

**回滚**:从客户 entitlement 移除该员工即可

**客户感知**:catalog 出现新员工,一键启用

**关键复用**:
- craft-workshop 12 员工(`yuangon/craft-workshop/`)
- `employee-pack-curator` / `employee-pack-quality-interviewer` / `employee-interview-assistant`
- `/catalog` API(`mod_store_routes.py:460`)
- `/admin/market/users/{user_id}/mods` + `/entitlements/push`(`xcmax_admin.py:1098/1103/1341`)
- `xcmax_sync_service.py` outbox 同步

### 5.4 流水线 4:entitlement-sync(授权变更)

**触发**:`cat/entitlement`

**执行步骤**:
```
1. user-customer-service-officer 或 enterprise-adoption-officer 处理
2. /admin/market/users/{user_id}/entitlements/push 调用
3. xcmax_sync_service record_change(account_entitlements, ...)
4. push_outbox 推送到企业端
5. 企业端 apply_inbox → entitlement 更新
6. delivery-receipt-officer 推回执
```

**客户感知**:无,自动同步

**关键复用**:
- `xcmax_sync_service.py:780`(`_apply_account_entitlements`)
- `/admin/market/users/{user_id}/entitlements/push`
- `/sync/entitlements/current`

### 5.5 流水线 5:config-sync(配置同步)

**触发**:`cat/config`

**执行步骤**:
```
1. user-customer-service-officer 处理
2. xcmax_sync_service record_change(personnel/department/template/workflow_employee/...)
3. push_outbox → 企业端 apply_inbox
4. delivery-receipt-officer 推回执
```

**客户感知**:无,自动同步

**关键复用**:
- `xcmax_sync_service.py` 支持的 11 种实体类型(personnel/department/attendance/approval/print_job/template/model_config/ecosystem/workflow_employee/account_entitlements/im_message)

### 5.6 流水线 6:direct-reply(直接回复)

**触发**:`cat/inquiry`

**执行步骤**:
```
1. user-customer-service-officer 接管
2. 基于知识库 + Persy 记忆(Phase 4)生成回复
3. 在 Issue 评论 + 推送到桌面端通知 + 工单状态页
4. 工单 closed
```

**客户感知**:收到回复

**关键复用**:
- `user-customer-service-officer`(`yuangon/platform-core/`)
- `corp_chat_to_proposal.py`(若来自客服对话)

---

## 6. 前端入口复用策略(零改动)

### 6.1 三个已有入口的分工

| 入口 | 主要场景 | 工单触发方式 | 现状 |
|------|---------|------------|------|
| **MODstore 智能客服** (`CustomerServiceView.vue`) | 登录客户的工作台内反馈 | 对话 + "提交工单"按钮 + 自动受理 | 已完整对接 `/api/customer-service/*` |
| **浮窗 AI 客服** (`FloatingAgentRoot.vue`) | 任意页面浮窗对话 | 悬浮球 + 对话 + Skills 触发 | 已完整,含 AgentEngine + Orchestrator |
| **官网 AI 客服** (`corp-butler.js`) | 官网访客(未登录)咨询 | 官网浮窗对话 | 已完整,挂载到 `#xc-corp-butler-root` |

### 6.2 制造员工入口的反馈能力(已实现)

`ModAuthoringPage.vue` 的 Wizard/Expert 模式是**主动制造**入口,不是反馈入口。但制造过程中产生的"需要新员工/新 Mod"需求,可以通过 `craft-workshop` 员工直接对接到流水线 3(catalog-push),不需要走客服工单。

**两种路径并存**:
- **主动制造**:客户在 ModAuthoringPage 直接造 → craft-workshop 全流程 → 注册 catalog(不走工单)
- **反馈式造员工**:客户在客服对话说"我想要 XX 员工" → 客服识别 intent=`llm_extension` 或 `product_issue`+domain=`custom` → 建单 → 桥接层路由到流水线 3

### 6.3 客户身份(已有,无需新建)

- **登录客户**:MODstore 用户系统(User 表),`customer_service_sessions.user_id` FK
- **官网访客**:corp-butler 独立会话,可选后续引导注册
- **tier 来源**:EntitlementService(已有),工单创建时由 orchestrator 查询并写入 `evidence_json`

### 6.4 工单状态查看(已有,无需新建)

`CustomerServiceView.vue` 已有:
- "我的工单"侧边栏(tickets 列表)
- 工单展开进度(`cs-ticket__body`)
- 工单生命周期标签(`ticketLifecycleLabel` / `ticketLifecycleHint`)
- 工单域标签(`issueDomainLabel`)
- 工单刷新按钮

**唯一增强点**(后端,非前端):桥接层把流水线执行进度回写到 `customer_service_actions` 表,前端 `loadTickets` 自动拉取展示。前端代码零改动。

### 6.5 桌面端(Electron)的反馈入口

桌面端内嵌 Vue SPA,**复用 MODstore market 的 CustomerServiceView**(通过路由)。桌面端用户点击"客服"菜单 → 加载 CustomerServiceView → 对话/提工单。无需新建桌面端专属反馈组件。

浮窗 AI 客服(`FloatingAgentRoot.vue`)也可在桌面端任意页面显示,作为轻量反馈入口。

---

## 7. 编排层扩展

### 7.1 customer_service_orchestrator.py 扩展(已有文件,~10 行改动)

在现有建单逻辑后加一行调用桥接层:

```python
# customer_service_orchestrator.py 现有建单逻辑后
ticket = create_ticket_from_session(session, intent, domain, ...)
# v3 新增:建单后自动分派到流水线
from modstore_server.ticket_pipeline_bridge import dispatch
dispatch(ticket.id, intent=ticket.intent, issue_domain=ticket.issue_domain, ...)
```

同时扩展 intent 识别规则:
- `product_issue` + `platform` → 标记 `automation_level=auto`(可自动受理)
- `product_issue` + `software` → 标记 `automation_level=auto`(SLA 72h)
- `product_issue` + `custom` → 标记 `automation_level=auto`
- `llm_extension` → 标记 `automation_level=auto`
- `catalog_review` / `general` / `greeting` → 标记 `automation_level=auto`(direct-reply)
- `refund` / `account_support` → Phase 4 才标 `auto`,Phase 1 先 `manual`

### 7.2 ticket_pipeline_bridge.py(新,~250 行)

桥接层核心,负责工单 → 流水线路由:

```python
# ticket_pipeline_bridge.py 核心逻辑
PIPELINE_MAP = {
    ("product_issue", "platform"): ("server-api", "server_api_adapter", 24),
    ("product_issue", "software"): ("desktop-shell", "desktop_shell_adapter", 72),
    ("product_issue", "custom"): ("catalog-push", "catalog_push_adapter", 48),
    ("catalog_complaint", "software"): ("server-api", "server_api_adapter", 24),
    ("catalog_review", None): ("direct-reply", "direct_reply_adapter", 4),
    ("refund", None): ("entitlement-sync", "entitlement_sync_adapter", 1),  # Phase 4
    ("account_support", None): ("config-sync", "config_sync_adapter", 4),   # Phase 4
    ("llm_extension", None): ("catalog-push", "catalog_push_adapter", 48),
    ("general", None): ("direct-reply", "direct_reply_adapter", 4),
    ("greeting", None): ("direct-reply", "direct_reply_adapter", 4),
}

def dispatch(ticket_id, intent, issue_domain, **kwargs):
    pipeline, adapter_name, sla_hours = PIPELINE_MAP.get(
        (intent, issue_domain),
        ("direct-reply", "direct_reply_adapter", 4)  # 默认直接回复
    )
    # 1. 更新工单 status=dispatching + evidence_json
    # 2. 写 action(dispatch_pipeline)
    # 3. 调用对应 adapter
    # 4. adapter 执行结果回写 actions 表
```

### 7.3 daily-orchestrator(已有,不改)

AI 员工编排器(`yuangon/platform-core/daily-orchestrator/`)保持不变,由 adapter 按需调用:
- `server_api_adapter` → 调 `ai_issue_implement.py`(已有)
- `catalog_push_adapter` → 调 craft-workshop 员工(已有)
- `direct_reply_adapter` → 调 `user-customer-service-officer`(已有)

**不再需要**:
- `customer-tickets-dispatch.yml`(v2 设计,已废弃,因为不通过 GitHub Issue 触发)
- `dispatch_customer_ticket.py`(v2 设计,已废弃)
- daily-orchestrator 的 customer 标签识别(v2 设计,已废弃)

---

## 8. 分阶段实施

### Phase 1:对客户透明的两条流水线(1 周)

**目标**:客户在已有客服入口(CustomerServiceView / FloatingAgent / corp-butler)对话,orchestrator 识别 `product_issue`+`platform` 或 `general`/`greeting` 意图后建单,桥接层自动路由到 `server-api` 或 `direct-reply` 流水线,全程零人工。

**为什么选这两条**:
- `server-api`(对应 intent=`product_issue`+domain=`platform`):复用 memory 2026-07-21 已通的"写→审→合→部署"链路,改动最小
- `direct-reply`(对应 intent=`general`/`greeting`/`catalog_review`):无代码,直接回复,最简单
- 都不需要桌面端配合,客户感知最弱,验证闭环最快
- **前端零改动**,只扩展后端 orchestrator + 加桥接层

**新代码**(3 个文件,~430 行):
| 文件 | 内容 | 行数估 |
|------|------|--------|
| `MODstore_deploy/modstore_server/ticket_pipeline_bridge.py` | 工单 → 流水线桥接层:建单后调用,根据 intent+domain 映射到流水线,回写 actions 表 | ~250 |
| `MODstore_deploy/modstore_server/pipeline_adapters/server_api_adapter.py` | 流水线 1 适配器:调 ai-issue-implement.py + 监听 PR 合并 + 回写进度 | ~100 |
| `MODstore_deploy/modstore_server/pipeline_adapters/direct_reply_adapter.py` | 流水线 6 适配器:调 user-customer-service-officer 生成回复 + 写回 messages | ~80 |

**改动**(3 处,~30 行):
- `customer_service_orchestrator.py`:建单后调用 `ticket_pipeline_bridge.dispatch(ticket)`
- `customer_service_orchestrator.py`:扩展 intent 识别,把 `product_issue`+`platform` 标记为可自动受理
- `customer_service_tools.py`:`execute_action` 支持新的 action_type(`dispatch_pipeline` / `pipeline_progress` / `pipeline_delivered`)

**验收标准**:
- [ ] 客户在 CustomerServiceView 对话说"后台导出 Excel 500 报错"
- [ ] orchestrator 识别 intent=`product_issue`+domain=`platform` → 建单(ticket_no 自动生成)
- [ ] 桥接层调用 server_api_adapter → 触发 ai-issue-implement.py
- [ ] ai-issue-implement 修复 → ai-review 通过 → 合并到 main
- [ ] fhd-ci-cd.yml 通过 → fhd-pack-release → push CVM → cron auto-update
- [ ] server_api_adapter 监听 PR 合并 + CVM 健康检查 → 回写 `customer_service_actions`(action_type=`pipeline_delivered`)
- [ ] 客户在 CustomerServiceView 工单列表看到"已交付"状态,**全程无操作**
- [ ] 客户说"你好" → orchestrator 识别 intent=`greeting` → 不建单,直接回复
- [ ] 客户说"商品审核流程是什么" → intent=`catalog_review` → 建单 → direct_reply_adapter 回复 → closed

**Phase 1 不做**:其他 4 条流水线 / 制造员工路径 / 桌面壳升级 / 官网 corp-butler 对接(只支持登录客户)/ SLA 报表

### Phase 2:catalog-push 流水线(2 周)

**目标**:客户在客服对话说"我想要 XX 员工",orchestrator 识别 intent=`llm_extension` 或 `product_issue`+domain=`custom` → 建单 → 桥接层路由到 catalog-push 流水线 → craft-workshop 造员工 → 注册 catalog → 推送 entitlement → 客户在 MyEmployeesView 一键启用。

**新代码**(2 个文件,~300 行):
| 文件 | 内容 | 行数估 |
|------|------|--------|
| `MODstore_deploy/modstore_server/pipeline_adapters/catalog_push_adapter.py` | 流水线 3 适配器:调 craft-workshop + 注册 catalog + push entitlement + 回写进度 | ~200 |
| `MODstore_deploy/modstore_server/services/employee_delivery.py` | 推送员工到客户 entitlement(调 `/admin/market/users/{id}/mods` + `/entitlements/push`) | ~100 |

**改动**(2 处,~20 行):
- `ticket_pipeline_bridge.py`:加 intent=`llm_extension` / `product_issue`+domain=`custom` → `pipeline/catalog-push` 映射
- `customer_service_orchestrator.py`:扩展 intent 识别,`llm_extension` 标记为可自动受理

**验收标准**:
- [ ] 客户在 CustomerServiceView 对话说"我想要一个售后申诉处理员工"
- [ ] orchestrator 识别 intent=`llm_extension` → 建单
- [ ] 桥接层调用 catalog_push_adapter → 触发 craft-workshop 全流程
- [ ] 造好的员工注册到 catalog + 推送到客户 entitlement
- [ ] 客户在 MyEmployeesView 看到新员工 → 一键启用 → 正常工作
- [ ] 工单状态自动更新为"已交付"
- [ ] 客户在 CustomerServiceView 工单列表看到进度 timeline(前端零改动,后端回写 actions 表)

### Phase 3:desktop-shell 流水线(2 周)

**目标**:客户反馈桌面端 bug,orchestrator 识别 intent=`product_issue`+domain=`software` → 建单 → 桥接层路由到 desktop-shell 流水线 → 修复 → release-desktop.yml 构建 → 推 update 站 → 客户端 electron-updater 自动检测通知。

**新代码**(2 个文件,~250 行):
| 文件 | 内容 | 行数估 |
|------|------|--------|
| `MODstore_deploy/modstore_server/pipeline_adapters/desktop_shell_adapter.py` | 流水线 2 适配器:调 ai-issue-implement(改 desktop/ 或 frontend/)+ 触发 release-desktop.yml + 监听构建完成 + 回写进度 | ~150 |
| `FHD/scripts/dev/desktop_release_orchestrator.py` | release-desktop.yml 编排入口(打包 + 推 update 站 enterprise/) | ~100 |

**改动**(2 处,~15 行):
- `ticket_pipeline_bridge.py`:加 intent=`product_issue`+domain=`software` → `pipeline/desktop-shell` 映射
- `customer_service_orchestrator.py`:扩展 intent 识别,`product_issue`+domain=`software` 标记为可自动受理(SLA 72h)

**验收标准**:
- [ ] 客户在 CustomerServiceView 对话说"桌面端导出 Excel 闪退"
- [ ] orchestrator 识别 intent=`product_issue`+domain=`software` → 建单
- [ ] 桥接层调用 desktop_shell_adapter → 触发 ai-issue-implement(改 desktop/ 或 frontend/)
- [ ] 修复 → ai-review 通过 → 合并到 main
- [ ] release-desktop.yml 自动构建(Windows .exe + macOS .dmg)
- [ ] 推送到 update 站 enterprise/ + 更新 latest.yml
- [ ] 客户端 electron-updater 自动检测到新版 → 通知客户(复用已有 updater.ts,前端零改动)
- [ ] 客户下载+重启 → triggerRollbackSafe 验证启动稳定性
- [ ] 失败自动回滚
- [ ] desktop_shell_adapter 监听构建完成 → 回写 actions 表 → 工单状态"已交付"

### Phase 4:entitlement-sync + config-sync + Persy(持续)

**目标**:intent=`refund` 和 intent=`account_support` 跑通 + Persy 记忆驱动 + SLA 报表。

**新代码**(3 个文件,~350 行):
| 文件 | 内容 | 行数估 |
|------|------|--------|
| `MODstore_deploy/modstore_server/pipeline_adapters/entitlement_sync_adapter.py` | 流水线 4 适配器:调 `/admin/market/users/{id}/entitlements/push` + xcmax_sync_service outbox | ~150 |
| `MODstore_deploy/modstore_server/pipeline_adapters/config_sync_adapter.py` | 流水线 5 适配器:调 xcmax_sync_service push outbox(personnel/department/template 等) | ~100 |
| `MODstore_deploy/modstore_server/services/sla_report.py` | SLA 报表 API(基于 customer_service_tickets + actions 表聚合) | ~100 |

**改动**:
- `ticket_pipeline_bridge.py`:激活 `refund` / `account_support` → `auto` 映射
- `customer_service_orchestrator.py`:把 `refund` / `account_support` 标记为 `automation_level=auto`
- `MODstore_deploy/market/src/views/AdminCustomerServiceView.vue`:已有 admin 视图,展示 SLA 报表(前端零改动,后端加 API)

**验收标准**:
- [ ] 客户说"我要退款" → intent=`refund` → 建单 → entitlement_sync_adapter 推送 entitlement 变更 → 1h 内客户端同步
- [ ] 客户说"修改账号配置" → intent=`account_support` → 建单 → config_sync_adapter 推送配置 → 4h 内客户端同步
- [ ] 同一客户多次提工单,系统记住历史上下文(Persy 记忆)
- [ ] SLA 报表:按 tier / intent / 客户 统计交付时长(后端 API,前端复用 AdminCustomerServiceView)

---

## 9. 复用资产清单(零改动)

### 9.1 写审合部署链路(memory 2026-07-21 实证已通)

| 资产 | 路径 | 用途 |
|------|------|------|
| ai_self_heal.py | `FHD/scripts/ci/` | 自动修复 bug |
| ai_review.py | `FHD/scripts/ci/` | PR 审查 |
| ai_issue_implement.py | `FHD/scripts/ci/` | Issue → 代码实现 |
| github-pr-gatekeeper | `yuangon/platform-core/` | PR 合并守门 |
| fhd-ci-cd.yml | `.github/workflows/` | 全量 CI/CD |
| fhd-release-orchestrator.yml | 同上 | 发布编排 |

### 9.2 服务器 API 交付(流水线 1)

| 资产 | 路径 | 用途 |
|------|------|------|
| fhd-pack-release.sh | `FHD/scripts/deploy/` | 打包 API + admin + mods |
| fhd-push-release.sh | 同上 | 推 CVM |
| fhd-auto-update.sh | CVM 端 | cron 拉取应用 |
| fhd-apply-release.sh | CVM 端 | 应用 + 失败回滚 |
| autonomy_guard | `FHD/app/domain/autonomy/` | 生产发布授权 |

### 9.3 桌面壳交付(流水线 2)

| 资产 | 路径 | 用途 |
|------|------|------|
| release-desktop.yml | `.github/workflows/` | Windows + macOS 构建 |
| release-desktop-mac-ota.yml | 同上 | macOS OTA |
| fix-mac-update-feed.yml | 同上 | Mac feed 修复 |
| updater.ts | `FHD/desktop/` | electron-updater 集成 |
| SKU_UPDATE_URL | `FHD/desktop/main.ts:267` | feed URL |
| triggerRollbackSafe | `FHD/desktop/main.ts:888` | 启动失败回滚 |

### 9.4 catalog-push 交付(流水线 3)

| 资产 | 路径 | 用途 |
|------|------|------|
| craft-workshop 12 员工 | `yuangon/craft-workshop/` | 造员工全流程 |
| employee-pack-curator | `yuangon/modstore-backend/` | 员工包策展 |
| employee-pack-quality-interviewer | `yuangon/quality-and-docs/` | 员工包质检 |
| /catalog API | `mod_store_routes.py:460` | catalog 查询 |
| /admin/market/users/{id}/mods | `xcmax_admin.py:1098/1103` | 分配 mod |
| /admin/market/users/{id}/entitlements/push | `xcmax_admin.py:1341` | 推送授权 |
| /sync-modstore-library | `mod_store_routes.py:972` | 同步库 |

### 9.5 entitlement + config 同步(流水线 4/5)

| 资产 | 路径 | 用途 |
|------|------|------|
| xcmax_sync_service.py | `FHD/app/services/` | 双向同步(outbox/inbox) |
| _apply_account_entitlements | 同上:780 | entitlement 应用器 |
| /sync/push /sync/pull /sync/receive | `xcmax_admin.py:2457/2519/2487` | 同步端点 |
| /sync/entitlements/current | `xcmax_admin.py:2533` | 当前权益 |
| /sync/status /sync/stream | `xcmax_admin.py:2432/2696` | 同步状态/流 |

### 9.6 编排与回执

| 资产 | 路径 | 用途 |
|------|------|------|
| daily-orchestrator | `yuangon/platform-core/` | 编排(扩展) |
| intake-dispatcher | 同上 | 分流 |
| task-router-officer | 同上 | 路由 |
| delivery-receipt-officer | 同上 | 回执(扩展双通道) |
| user-customer-service-officer | 同上 | inquiry 处理 |
| fhd-core-maintainer | 同上 | bug 处理 |
| mods-and-eskill-curator | 同上 | mod 处理 |
| enterprise-adoption-officer | 同上 | entitlement 处理 |
| partner-ecosystem-onboard-officer | `yuangon/partner-ecosystem/` | 合作处理 |

### 9.7 客服与意图(v3 核心复用)

| 资产 | 路径 | 用途 |
|------|------|------|
| **customer_service_api.py** | `MODstore_deploy/modstore_server/` | **7 个 API endpoint(零改动)** |
| **customer_service_orchestrator.py** | 同上 | **意图识别 + 建单 + 决策(扩展 ~10 行)** |
| **customer_service_tools.py** | 同上 | **audit / action / integration(扩展 action_type)** |
| **models_cs.py** | 同上 | **8 张表(sessions/tickets/messages/standards/decisions/actions/integrations/audit_logs)** |
| **CustomerServiceView.vue** | `MODstore_deploy/market/src/views/` | **智能客服前端(对话+工单列表+进度,零改动)** |
| **FloatingAgentRoot.vue** | `MODstore_deploy/market/src/components/floating-agent/` | **浮窗 AI 客服(零改动)** |
| **corp-butler.js + corp-butler.njk** | `成都修茈科技有限公司/corp-butler/` + `marketing-site/templates/partials/` | **官网 AI 客服(零改动)** |
| **workbench.ts** | `MODstore_deploy/market/src/api/` | **API 封装(customerServiceChat 等,零改动)** |
| CorpChatSession + CorpChatMessage | `FHD/app/` | 对话留痕 |
| corp_chat_to_proposal.py | 同上 | 对话 → 提案 |
| cs_category_ssot.py | 同上 | 客服分类 |
| capability_proposal_recorder.py | `FHD/app/services/` | 能力提案记录 |
| strategic_planner.py | `FHD/app/domain/autonomy/` | 战略规划 |
| intent_confirmation_service.py | `FHD/app/` | 意图确认 |
| cvm_adapter.py | `FHD/scripts/autonomy/` | CVM 适配 |

### 9.8 基础设施

| 资产 | 路径 | 用途 |
|------|------|------|
| Neuro Bus | `FHD/XCAGI/` | 7 项可靠性机制 |
| Persy 记忆图谱 | `FHD/mcp_servers/persy_memory/` | Phase 4 用 |
| EntitlementService | `MODstore_deploy/java_payment_service/` | 客户授权 |
| WalletService / OrderService | 同上 | 钱包 / 订单 |
| 桌面端通知中心 | `FHD/frontend/src/components/` | 回执通道 |
| cvm-autonomy-watcher.yml | `.github/workflows/` | CVM 异常监控 |

---

## 10. 风险与边界

| 风险 | 缓解 |
|------|------|
| 客户数据进 GitHub Issue 隐私弱 | Phase 1 接受(私有仓 + label 隔离),Phase 5 后切内部 DB |
| 多客户并发编排冲突 | Neuro Bus 已有 DEDUP + CIRCUIT + RATE_LIMIT |
| AI 员工失败 | 3 次重试 → escalated → 人工 |
| 服务器 API 更新失败 | fhd-apply-release.sh 已有自动回滚 |
| 桌面壳升级失败 | electron-updater Ed25519 签名 + triggerRollbackSafe + 自动回滚观察期 |
| 造员工质量 | craft-workshop 含 quality-validator + sandbox-tester + employee-pack-quality-interviewer 三层校验 |
| 客户提交垃圾工单 | EntitlementService 校验 tier,免费 tier 限频 |
| GitHub API 限流 | 5000 req/h,前 100 客户足够;后续切内部任务队列 |
| 工单 body 含敏感信息 | 提交前自动扫描(security-secrets-guard) |
| 客户 tier 升级/降级 | EntitlementService 是 SSOT,工单实时读取 |
| bot token 泄漏 | 用 GitHub App 而非 PAT,最小权限 |
| 流水线交叉(category 误判) | daily-orchestrator 二次确认 + task-router-officer 校验 |
| 桌面壳升级客户不配合 | SLA 72h,过期 escalated 人工跟进 |

---

## 11. 不做(YAGNI)

- 不做客户自助注册(Phase 1 手动开通 entitlement)
- 不做工单 SLA 自动退款(Phase 4 之后)
- 不做多语言工单(Phase 1 中文)
- 不做邮件通道(Phase 4)
- 不做语音通道(不在路线图)
- 不做客户社区 / 论坛
- 不做工单优先级 AI 评估(先按 tier + 客户手选)
- 不做实时聊天(已有 corp_chat 够用)
- 不做客户 NPS 调研(Phase 4 后)
- 不做 mobile-flutter-poc 的工单入口(Phase 5 后)
- 不做 java_payment_service 自动退款联动(Phase 5 后)
- 不做 modstore_server 的工单入口(用 FHD 的就够了)

---

## 12. 成功指标

### Phase 1 验收(硬指标)

- [ ] 1 个客户提交 `cat/bug-backend` 工单,24h 内交付,零人工干预
- [ ] 1 个客户提交 `cat/inquiry` 工单,4h 内回复
- [ ] 失败自动回滚 + 升级人工

### 商业化指标(6 个月后)

- 客户工单平均交付时长 < 12h(对客户透明的流水线)
- 客户工单 7 天闭环率 > 80%
- AI 员工自动处理率 > 70%(剩余 30% 升级人工)
- 客户续费率 > 80%
- 单客户年均工单数 > 12

---

## 13. 后续演进

| 阶段 | 演进方向 |
|------|---------|
| Phase 5 | 工单系统从 GitHub Issue 切到内部 DB(隐私 + 多租户强化) |
| Phase 6 | 客户对话式工单(自然语言 → 工单,无需选类别) |
| Phase 7 | 造员工模板市场(客户互相交易定制员工) |
| Phase 8 | 多租户 Persy 记忆(每客户独立图谱,真正"会进化的 ERP") |
| Phase 9 | mobile-flutter-poc 工单入口 |
| Phase 10 | java_payment_service 自动退款联动 |

---

## 14. 下一步

1. 评审本文档(v2)
2. 调整方向(若有)
3. 进入 writing-plans,拆 Phase 1 为可执行任务清单
4. 按 Phase 1 验收标准实施

---

*最后更新:2026-08-01(v3:复用已有客服工单系统 + 前端零改动 + 桥接层设计)*
