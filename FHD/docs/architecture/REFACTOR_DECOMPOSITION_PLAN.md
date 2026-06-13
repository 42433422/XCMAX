# 大类拆分 / 架构降债方案（REFACTOR DECOMPOSITION PLAN）

> 版本锁：**v10 全产品线锁**。本文仅为**拆分方案**，所有后续改动一律记为「v10 线内迭代」，
> 不 bump 任何锚点。落地前每一步都「先验证、后扩面、最小 diff」。
>
> 适用范围：后端 `services/`↔`application/` 双层、Android God ViewModel/Repository、
> 前端路由守卫、前端 mods store。
>
> 本文是对既有 DDD 文档的**更新与落地补充**（既有文档写于「33 个 services」时期，现已 106 个，
> 严重滞后）：
> - `FHD/docs/architecture/ddd-refactoring-plan.md`（陈旧，仅供目标架构参考）
> - `FHD/docs/architecture/target-structure.md`（依赖方向铁律，仍有效）
> - `FHD/app/application/README.md`（应用层规范，仍有效）

最后更新：2026-06-13 · 维护：XCAGI 工程团队

---

## 0. 原则与统一护栏

1. **绞杀者模式（Strangler）**：不大爆炸重写。新接缝处先「抽取 + 委托（delegation shim）」，
   旧入口保持可用，再逐个迁移调用方，最后删空壳。
2. **每步独立可编译可发版**：任一步骤合并后，后端 `pytest` 不回归、前端 `vue-tsc`+`vitest` 绿、
   Android `assembleDebug` 通过。
3. **行为零变化优先**：先做「等价重构」（移动/抽取/改依赖方向），**不**在同一步混入逻辑修改。
4. **棘轮护栏（ratchet）**：对每类债设「只减不增」CI 校验，防止边修边长。
5. **覆盖率不退**：后端 gate 现 ~60.63%（`FHD/metrics/coverage-dual-summary.json`），
   拆分时**同步补特征测试**，新抽出的纯函数/UseCase 必须带测试。

---

## 1. 后端 `services/` ↔ `application/` 双层降债

### 1.1 现状证据（实测 2026-06-13）

| 指标 | 实测 | 证据 |
|---|---|---|
| `app/services/**/*.py` | **106** | `glob` |
| `app/application/**/*.py` | **131**（含 `ports/`、`facades/`、`workflow/` 子树） | `glob` |
| `_app_service*.py`（应用服务） | 56 | 既往核实 |
| **`_v2` 与同名非 v2 并存** | **17 对** | 见下表 |
| **路由直依赖 `app.services`（违规）** | **14 个路由文件** | `grep "from app.services" fastapi_routes/` |
| 路由依赖 `app.application`（合规） | ~50 文件 | `grep` |
| `application/` 反向依赖 `app.services` | ~67 处 | 过渡包装，预期内 |

**核心问题**（与既有文档诊断一致，但规模翻 3 倍）：
- **路由绕过应用层**：14 个 `fastapi_routes/*` 仍直接 `from app.services import ...`，违反
  `target-structure.md` 的 `routes → application → domain` 铁律。
  代表：`contract_lifecycle_api.py`(16)、`finance_invoices_api.py`(8)、`domains/wechat/routes.py`(7)、
  `user_cs_wechat_passive_compat.py`(6)、`operations_line_api.py`(5)。
- **`_v2` 双版本并存**：17 个领域同时存在 `xxx_app_service.py` 与 `xxx_app_service_v2.py`：
  `auth / user / customer / product / material / ocr / print / purchase / inventory / template /
  conversation / file_analysis / shipment / extract_log / wechat_contact / user_preference /
  user_memory_vector`。这是 `MIGRATION_v2_DROP_PLAN.md` 受控债，但「并存」本身是读者认知负担。
- **`services/` 职责混杂**：106 个文件里混着领域逻辑、基础设施、AI 引擎、工具。

### 1.2 `services/` 实际分类（决定各自去向）

| 类别 | 代表文件 | 目标层 |
|---|---|---|
| 领域逻辑（无状态业务规则） | `rule_engine.py`、`ai_product_parser.py`、`product_import_service.py`、`intent_service.py`、`hybrid_intent_service.py` | `app/domain/services/` |
| 基础设施 / 适配器 | `database_service.py`、`session_service.py`、`ocr_service.py`、`tts_service.py`、`printer_service.py`、`paddle_ocr_runner.py`、`mobile_push.py`、`catalog_client.py` | `app/infrastructure/` |
| AI 引擎（模型相关） | `bert_intent_service.py`、`deepseek_intent_service.py`、`rasa_nlu_service.py`、`distilled_intent_service.py`、`distillation_trainer.py` | `app/infrastructure/ai_engines/`（或独立模块） |
| 用例编排（应被应用层吸收） | `auth_service.py`、`user_service.py`、`materials_service.py`、`purchase_service.py`、`report_service.py`、`inventory_service.py` | 合并入对应 `application/xxx_app_service.py` |
| 子领域包（结构尚可，保留再规整） | `conversation/`、`tools_execution/`、`document_templates/`、`kitten_report/`、`skills/`、`user_cs_*` | 原地保留，后续按需归位 |

### 1.3 增量迁移策略（先挑 3 个最低风险样板）

**目标：先消灭"路由绕过应用层"，再消灭"_v2 并存"，最后下沉 services 分类。**

#### 阶段 A：路由收口（最高收益、最低风险，先做）
把 14 个违规路由逐个改为只依赖 `application/`。挑 3 个样板首发：

1. **`operations_line_api.py`（5 处 import）**
   - 现：`from app.services.operations_line_bridge import ...`
   - 后：新增/复用 `application/operations_line_app_service.py` 作为编排门面，路由只调它；
     `operations_line_bridge` 降级为被 application 调用的实现。
2. **`im_routes.py`（services 2 / application 1，已半迁移）**
   - 把剩余 2 处 services 调用并入 `im_app_service.py`，路由 0 处直连 services。
3. **`print_routes.py`（services 1 / application 3）**
   - 已基本走 `print_app_service`，把最后 1 处 `printer_service` 直连改为经应用层（应用层内部再调
     `infrastructure/printing`）。

每个样板的步骤（可独立提交）：
```
1) application/ 内新增/补全门面方法（委托现有 services 实现，行为等价）
2) 路由改 import + 调用点（仅此处 diff）
3) 跑该域路由的集成测试 + grep 确认该文件 0 处 from app.services
4) 提交：refactor(layer): <域> 路由收口至 application（v10 线内迭代）
```

#### 阶段 B：`_v2` 收敛（与 `MIGRATION_v2_DROP_PLAN.md` 联动）
对 17 对中**已无调用方引用旧版**者，按 drop plan 的 allowlist 流程删旧版、去 `_v2` 后缀；
仍有引用的，先把调用方切到 v2，再进 drop allowlist。**不在本文私自删除**，遵循既有 CI guard。

#### 阶段 C：`services/` 分类下沉
按 1.2 表逐文件 `git mv` + 留 import shim（旧路径 `from app.services.x import *` 重导出新位置），
一个文件一提交，shim 保留到调用方全部迁移后由阶段 D 统一清。

### 1.4 护栏（CI 棘轮）
- 新增 `scripts/dev/check_layer_ratchet.py`：
  - 统计 `fastapi_routes/` 中 `from app.services` 出现的**文件数**，写入基线（当前 14），
    PR 若 **> 基线** 则 fail（只减不增）。
  - 统计 `app/services/**/*.py` 文件数基线（当前 106），新增即 fail（强制新代码进 domain/infra）。
- 纳入 `verify_version_anchors.py` 同级的 dev 校验流程。

### 1.5 风险与验证
| 风险 | 缓解 |
|---|---|
| 循环依赖（application↔services 互引） | 先抽 `ports/` 接口，application 依赖接口、infra 实现 |
| 本地测试不可复现（321 failed，环境耦合） | 迁移前先修「测试可复现性」（见 §6），否则无法判断回归 |
| 改 import 漏改运行时动态导入 | `grep` 动态 `importlib`/字符串路径；按域整体迁移而非散点 |

### 1.6 工作量
阶段 A：3 样板 ~1 天，全部 14 路由 ~3-4 天；阶段 B 跟随 drop plan；阶段 C ~5-8 天（机械但量大）。

---

## 2. Android God ViewModel：`AppViewModel.kt`（955 行）

### 2.1 现状证据
单个 `@HiltViewModel` 注入 `repo: XcagiRepository` 等，混入 **15+ 特性域**的 StateFlow 与动作
（行号据 `grep`）：

| 特性域 | 代表成员（行） |
|---|---|
| 启动/导航 | `navReady`(127)、`startRoute`(130)、`refreshStartRoute`(281)、`handleDeepLink`(944) |
| 认证/登录 | `tryAutoLogin`(301)、`loginFhd`(566)、`register`(597)、`loginPhone`(618)、`exchangeQr`(635)、`confirmAuthQr`(680) |
| 站点/引导设置 | `setHost`(541)、`setMode`(551)、`probeHealth`(557)、`completeSetup`(515)、`skipToCloud`(521)、`scanSubnet`(560) |
| 同步 | `runSyncNow`(451)、`setAutoSync`(470)、`updateSyncWork`(476) |
| 聊天/AI | `chatMessages`(136)、`streaming`(154)、`sendChat`(718)、`stopChat`(793)、`inferChatAction`(773)、`chatSuggestions`(191) |
| 审批 | `approvalDetail`(148)、`loadApprovals`(813)、`approve`(830)、`reject`(840)、`refreshApprovalCount`(709) |
| 企业列表 | `loadCustomers`(850)、`loadShipments`(852)、`loadInventory`(882)、`loadFinance`(892)、`loadMarket`(880) |
| Mods | `modInfos`(224)、`dynamicMenuItems`(226)、`loadMods`(861)、`requestModOpen`(903)、`modUrl`(899) |
| IM | `connectImWebSocket`(921)、`observeImMessages`(928)、`imSendMessage`(933)、`imOpenDirect`(925) |
| 首页 Hub | `homeHub`(185)、`loadHomeHub`(401) |
| 应用配置/更新 | `appConfig`(216)、`checkForUpdate`(329)、`updatePrompt`(221) |
| 设置/账号 | `setThemeMode`(370)、`setBiometricEnabled`(367)、`submitFeedback`(372)、`deleteAccount`(382)、`exportAccount`(394) |
| 消息提示 | `message`(133)、`snack`(534)、`clearSnack`(537) |

### 2.2 目标分解（按特性域拆 ViewModel + UiState；保持 Compose `collectAsState` 习惯）
包 `com.xiuci.xcagi.mobile.ui.feature.*`，每个特性一个 `@HiltViewModel`，并把零散 StateFlow 收进
`data class XxxUiState`：

| 新类（建议） | 职责 | 从 AppViewModel 迁出的成员 |
|---|---|---|
| `feature/auth/AuthViewModel` + `AuthUiState` | 登录/注册/自动登录/扫码 | 认证域全部 |
| `feature/setup/SetupViewModel` | 站点探测/引导/局域网扫描 | 设置/引导域 |
| `feature/chat/ChatViewModel` + `ChatUiState` | 聊天流、建议、动作 | 聊天/AI 域 |
| `feature/approval/ApprovalViewModel` | 审批列表/详情/审批动作 | 审批域 |
| `feature/enterprise/EnterpriseListViewModel` | 客户/发货/库存/财务/市场列表 | 企业列表域（共用 `loadEnterpriseList`(798) 抽成 UseCase） |
| `feature/mods/ModsViewModel` | Mod 列表/菜单/打开 | Mods 域 |
| `feature/im/ImViewModel` | IM 连接/消息流/收发 | IM 域 |
| `feature/home/HomeViewModel` | 首页 Hub、更新提示、app 配置 | Hub/更新/配置域 |
| `feature/settings/SettingsViewModel` | 主题/生物识别/反馈/账号删除导出 | 设置/账号域 |
| `ui/common/SnackController` | 全局消息提示（注入复用） | message/snack |

`AppViewModel` 收敛为**仅** App 级编排：`navReady`/`startRoute`/`handleDeepLink` + 持有
`SnackController`。

### 2.3 增量步骤（每步独立可编译，先抽叶子域）
```
Step 1  抽 SnackController（最叶子、零业务）→ AppViewModel 委托它 → 编译/跑
Step 2  抽 ImViewModel（边界最干净：IM 成员只被 IM 屏幕用）→ 改 IM 屏幕注入新 VM
Step 3  抽 SettingsViewModel → 改设置屏幕
Step 4  抽 ApprovalViewModel / EnterpriseListViewModel（共享 loadEnterpriseList → UseCase）
Step 5  抽 ChatViewModel、ModsViewModel、AuthViewModel、SetupViewModel、HomeViewModel
Step 6  AppViewModel 仅剩导航编排；删除已迁空成员
```
每步：先新 VM 委托 repo 旧方法（行为等价）→ 改对应 Compose 屏幕 `hiltViewModel()` 注入 →
`./gradlew :app:assembleDebug` → 提交。

### 2.4 测试（当前仅 2 个路由常量测试）
- 抽出的纯逻辑 `inferChatAction`(773)、`rebuildChatSuggestions`(438) → 提为 `ChatActionMapper` /
  `ChatSuggestionBuilder` 纯函数，加 JUnit 单测（无需 Android runtime）。
- 各 ViewModel 用 `kotlinx-coroutines-test`（已在 deps）+ fake repository 写状态流转测试。
- 收益：拆分后每个 VM 可独立 mock `XcagiRepository`（见 §3 拆分后更细）。

### 2.5 工作量：~5-8 天（10 个屏幕的注入点需逐个改），低-中风险（等价委托）。

---

## 3. Android God Repository：`XcagiRepository.kt`（1018 行）

### 3.1 现状证据
单个 `@Inject` 仓库（class@58），混 **9 个域**（行号据 `grep`）：

| 域 | 代表方法（行） |
|---|---|
| 基础设施/装配 | `fhd()`(156)、`modstore()`(171)、`authHeader`(101)、`syncRouterFromStore`(75)、`fhdApiForBase`(444) |
| 认证/登录（最大，~400 行） | `loginFhd`(195)、`register*`(259/265/279)、`loginMarketPhone`(548)、`loginMarketPassword`(583)、`loginUnified`(596)、`pairingExchange`(370)、`confirmAuthQr`(454)、`applyMarketAuth`(514) |
| 账号 | `refreshMe`(301)、`fetchAppConfig`(309)、`deleteAccount`(317)、`exportAccountData`(326)、`submitFeedback`(333) |
| 健康/LAN | `checkHealth`(183)、`scanLan`(193)、`requestLanAccess`(475) |
| 聊天 | `streamChat`(606)、`streamChatCloud`(638)、`loadCachedChat`(670) |
| 审批 | `approvals`(673)、`approvalDetail`(692)、`approve`(700)、`reject`(709) |
| 企业数据 | `customers`(718)、`shipments`(723)、`bridgeRequests`(741)、`inventory`(888)、`financeSummary`(899) |
| Mods | `mods`(769)、`loadModInfos`(772)、`parseModInfo`(803)、`marketCatalog`(860)、`modWebUrl`(907) |
| IM | `connectImWebSocket`(933)、`observeImMessages`(942)、`imSendMessage`(977) 等 |

### 3.2 目标分解（按域拆 Repository，共享一个装配核）
包 `com.xiuci.xcagi.mobile.core.repository.*`：

| 新类 | 职责 |
|---|---|
| `ApiProvider`（或 `RepositoryCore`） | `fhd()`/`modstore()`/`authHeader`/`fhdApiForBase`/`bearer` 等装配与鉴权头，供各域注入 |
| `AuthRepository` | 全部登录/注册/扫码/market 鉴权（最大块，单独受益最多） |
| `AccountRepository` | refreshMe / appConfig / 删除导出 / 反馈 / 设备 token |
| `ChatRepository` | streamChat / streamChatCloud / 缓存 |
| `ApprovalRepository` | approvals / detail / approve / reject |
| `EnterpriseDataRepository` | customers / shipments / bridge / inventory / finance |
| `ModsRepository` | mods / loadModInfos / parseModInfo / market catalog / modWebUrl |
| `ImRepository` | IM 连接/消息流/收发（已有 `ImMessageCache` Room 依赖，边界清晰，先抽） |
| `ConnectivityRepository` | checkHealth / scanLan / requestLanAccess |

`parseMobileList`(990)、`parseModInfo`(803) 等解析器 → `core/repository/parse/` 纯函数，带单测。

### 3.3 增量步骤
```
Step 0  抽 ApiProvider（装配核），XcagiRepository 注入它、内部调用不变 → 编译
Step 1  抽 ImRepository（最干净）→ ViewModel/调用方改注入 → 编译
Step 2  抽 ChatRepository、ApprovalRepository、EnterpriseDataRepository、ModsRepository
Step 3  抽 AuthRepository（最大，最后做，单独 PR 充分测试）
Step 4  XcagiRepository 删空或降为 facade（若仍有聚合调用方，保留薄门面委托）
```
配合 §2：ViewModel 拆分后各自只注入所需 Repository（依赖收窄）。

### 3.4 测试
- 解析器纯函数（`parseModInfo`/`parseMobileList`）→ JUnit 单测，喂样例 JSON map。
- 各 Repository 用 MockWebServer / fake `FhdApi` 写 happy-path + 错误路径测试。

### 3.5 工作量：~4-6 天，中风险（`AuthRepository` 涉及 market/PC 双链路，需重点测）。

> §2/§3 联动：建议先做 §3 的 `ApiProvider` + 叶子 Repository，再做 §2 的 ViewModel 拆分，
> 这样新 ViewModel 直接注入细粒度 Repository，避免二次改注入。

---

## 4. 前端路由守卫：`router/index.ts` `beforeEach`（~290 行 / 16 关注点）

### 4.1 现状证据（行号据全文读取，确认 16 个独立分支）
1. admin-console planner-bridge 路径改写（427-434）
2. admin operator 受限路由拦截（436-443）
3. workflow-visualization 菜单权限门（445-474）
4. admin 冷启动重定向运维总览（476-494）
5. 未匹配 `/mod/` → 客服宿主/planner-bridge/首页（496-511）
6. planner-bridge 受保护 mod 重定向（513-519）
7. 局域网授权门（host-admin 路由）（521-537）
8. `clientModsUiOff` mod 页重定向（539-547）
9. chat 首页 / planner 页重定向（549-560）
10. 平台壳模式重定向（562-575）
11. （已注释：erp-domain / core-workflow mod 重定向 577-602）
12. 客服侧别（enterprise/admin）门（604-624）
13. `requiresAdminAccount` 门（626-641）
14. 企业版会话校验 + admin 重定向（643-682）
15. product onboarding（684-692）
16. host-pack onboarding（694-714）

确认 editions：`minimal` / `enterprise` / `generic`（`isEnterpriseEdition(sku)`、`VITE_XCAGI_EDITION`）。

### 4.2 目标分解（有序 guard 管线，行为逐字等价）
新建 `frontend/src/router/guards/`，每个守卫签名统一：
```ts
// 返回 RouteLocationRaw=重定向 / false=中断 / true|void=放行下一个
type GuardResult = RouteLocationRaw | false | true | void;
type Guard = (to, from) => GuardResult | Promise<GuardResult>;
```
按当前**执行顺序**抽（顺序必须保持，因存在短路 return）：

| 守卫文件 | 覆盖原分支 |
|---|---|
| `guards/adminConsole.ts` | 1,2,4 |
| `guards/modBridge.ts` | 5,6,8 |
| `guards/workflowMenu.ts` | 3 |
| `guards/lanGate.ts` | 7 |
| `guards/chatHome.ts` | 9 |
| `guards/platformShell.ts` | 10 |
| `guards/customerService.ts` | 12 |
| `guards/adminAccount.ts` | 13 |
| `guards/enterpriseSession.ts` | 14 |
| `guards/onboarding.ts` | 15,16 |

新 `beforeEach` 仅做编排：
```ts
const pipeline: Guard[] = [
  adminConsoleGuard, modBridgeGuard, workflowMenuGuard, lanGateGuard,
  chatHomeGuard, platformShellGuard, customerServiceGuard,
  adminAccountGuard, enterpriseSessionGuard, onboardingGuard,
];
router.beforeEach(async (to, from, next) => {
  for (const g of pipeline) {
    const r = await g(to, from);
    if (r === false) return next(false);
    if (r && r !== true) return next(r as RouteLocationRaw);
  }
  next();
});
```

### 4.3 增量步骤
```
Step 1  原样抽第 1 个守卫为函数（逻辑剪切粘贴，0 改动）→ 在 beforeEach 顶部调用 → vitest+手测
Step 2..N  逐个抽，保持顺序；每抽一个跑一次全套路由测试
Step last  beforeEach 收敛为 pipeline 循环
```
**关键：一次只搬一个分支，diff 必须是"剪切=粘贴"**，禁止顺手改条件。

### 4.4 测试
- 现状：路由测试仅 Android 有 2 个常量测试；前端守卫**无**专测。
- 每个 guard 是纯/弱副作用函数，可对 `(to, from)` + mock pinia store 单测断言返回值。
- 先给「企业版会话校验」「onboarding」「客服侧别」三条高风险守卫补测，再动刀。

### 4.5 工作量：~2-3 天，**中风险**（守卫顺序与短路语义极敏感，错一处即登录/重定向回归）。

---

## 5. 前端 mods store：`stores/mods.ts`（1085 行 / 7 职责）

### 5.1 现状证据（行号据 `grep`）
| 职责块 | 行范围 | 代表 |
|---|---|---|
| 模块级探针缓存 + facade 开关副作用 | 100-300 | `readModProbeCache`、`setPlannerModFacadeEnabled` 等一串 `setXxxModFacadeEnabled` |
| 行业候选/权益解析（纯函数） | 230-300 | 行业匹配、`entitled_mod_ids` 解析 |
| state | 301-312 | `mods`、`modRoutes`、`activeModId`、`clientModsUiOff`、`isLoaded`、`loadError` |
| 账号上下文 + active mod 选择 | 314-450 | `resolveModsAccountContext`、`ensureActiveModSelection`、`setActiveModId` |
| 行业/权益同步 | 450-616 | `syncIndustryForActiveMod`、`applyEntitledActiveMod`、`syncActiveModWithServerIndustry` |
| 拉取/重试/加载态 | 616-797 | `fetchModsOnce`、`fetchModsWithRetry`、`fetchModRoutes`、loading hint |
| 侧栏菜单构建 | 824-957 | `getModMenu`、`modsContributingSidebarMenu`、`validateModMenuPaths` |
| 生命周期 | 957-1064 | `initialize`、`refresh` |

> 注：`facade 开关`是对**模块级单例**的副作用（非 store state），与 store 强耦合是债点之一。

### 5.2 目标分解
| 新单元 | 类型 | 职责 |
|---|---|---|
| `utils/modEntitlement.ts` | 纯函数模块 | 权益/行业候选解析（230-300 抽出，易测） |
| `utils/modMenu.ts` | 纯函数模块 | 菜单构建/去重/路径校验（824-957，输入 mods→输出菜单） |
| `composables/useModFacadeFlags.ts` | composable | 集中 `setXxxModFacadeEnabled` 副作用，与 store 解耦 |
| `stores/modsCatalog.ts` | Pinia store | state + 拉取/重试/加载态（616-797） |
| `stores/modsActiveSelection.ts` | Pinia store | active mod 选择 + 行业/权益同步（314-616） |
| `stores/mods.ts`（保留） | Pinia store（瘦身） | 组合上述、对外保持 `useModsStore()` 现有 API |

**关键约束**：`useModsStore()` 对外 API **保持不变**（门面重导出），避免改动所有消费方。

### 5.3 消费方（需评估改动面）
先 `grep useModsStore` 全量列出消费组件/视图（如 `router/index.ts`、各 `views/*`、侧栏组件），
拆分时**只在 store 内部重组**，对外 getter/action 签名不变 → 消费方零改动。

### 5.4 增量步骤
```
Step 1  抽纯函数 utils/modEntitlement.ts + utils/modMenu.ts（store 内改为调用）→ 补单测 → vitest
Step 2  抽 useModFacadeFlags composable
Step 3  抽 modsCatalog store（拉取/加载态），mods.ts 内部委托
Step 4  抽 modsActiveSelection store
Step 5  mods.ts 收敛为门面（return 维持原 API）
```

### 5.5 测试与覆盖率门
- 现状：`vitest.config.js` **显式排除** modStore 文件出主覆盖率 gate（核实属实）。
- 拆分时为新 `utils/mod*.ts` 纯函数补测，并**逐步把抽出的纯模块移出排除名单**，让覆盖率真实回升。

### 5.6 工作量：~3-4 天，低-中风险（纯函数先行降风险；门面保签名是关键安全垫）。

---

## 6. 前置依赖：后端测试可复现性（阻塞 §1 验证）

### 6.1 实测结论（2026-06-13，已落地部分修复）

- 配置卫生：`pytest.ini` 仅声明 `release_gate`（已在 pyproject）却**完全覆盖** pyproject 的
  `[tool.pytest.ini_options]`（pytest 配置文件取第一命中者）。已**删除** `pytest.ini`，恢复
  pyproject 配置（`asyncio_mode=auto`、`--import-mode=importlib`、`testpaths`、marker、
  `filterwarnings`），marker 警告 16→1。
- 全量基线（删 ini 后，本地 + CI 环境变量）：**320 failed / 1509 passed / 51 skipped / 12 errors**，
  仅 ~24s（快速失败，**非网络超时**）。
- **CI 本分支同样全红**（`gh run list` 确认）—— 即此红是**既有状态**，不是重构引入。
- 失败根因分布（97 个失败文件）：
  - **幽灵/漂移**：测从未实现或已删改的 API。典型 `tests/test_utils/test_deployment_env_probe.py`
    （18）import 的 `app.utils.deployment` **整模块不存在**（仅 `is_desktop_mode` 散落在
    `app/desktop_runtime/paths.py`）。属 COVERAGE_RAMP 为凑覆盖率批量产出的死测试。
  - **环境耦合**：redis(`localhost:6379`)、postgres(`127.0.0.1:5432`)、`database is locked`、
    Mod 后端文件缺失 —— CI 有 redis 服务故通过，本地无。
  - **断言/其它**：行为漂移或测试陈旧。

### 6.2 已落地的可复现绿色信号（快车道）

- `tests/quarantine_known_red.txt`：97 个已知红文件的**显式燃尽清单**（非隐藏跳过；修一个删一行）。
- `scripts/dev/test_fast.py`：排除清单后运行，自动对齐 CI 环境变量。
  实测 **682 passed / 42 skipped / 0 failed（~14s）** —— 重构（如 §1 路由收口）可据此即时验证不引入新回归。
  ```bash
  python scripts/dev/test_fast.py            # 绿
  python scripts/dev/test_fast.py -k xxx     # 透传 pytest 参数
  ```

### 6.3 燃尽路线（后续）

1. **幽灵测试**：逐个判定「实现缺失模块」or「删除死测试」。`app.utils.deployment` 建议按
   `test_deployment_env_probe.py`（即其规格）实现一个薄环境探测工具模块，一次回收 18 项。
2. **环境耦合**：给 redis/postgres 类标 `@pytest.mark.integration`，并加 conftest「infra 不可达即 skip」；
   使 `-m "not integration"` 本地干净。
3. 每修复一类 → 从 `quarantine_known_red.txt` 删除对应行，快车道覆盖面自动扩大，直至清零。
4. 收尾后令 `test_fast.py` 等同全量，§1 后端重构即获完整安全网。

---

## 7. 推荐排期（建议顺序）

| 序 | 工作 | 风险 | 工作量 |
|---|---|---|---|
| 1 | §6 测试可复现性（解锁后端验证） | 中 | 2-3 天 |
| 2 | §1 阶段 A：3 路由样板收口 + CI 棘轮 | 低 | 2 天 |
| 3 | §5 阶段 1-2：mods 纯函数抽取 + 测试 | 低 | 2 天 |
| 4 | §3：Android `ApiProvider` + 叶子 Repository | 低-中 | 3 天 |
| 5 | §2：Android ViewModel 按域拆 | 中 | 5 天 |
| 6 | §4：路由守卫管线化（高敏感，单独 PR） | 中 | 3 天 |
| 7 | §1 阶段 B/C + §5 阶段 3-5（长尾） | 中 | 持续 |

> 每项落地都遵守 §0 护栏；任一项可独立启动、独立交付，不互相阻塞（除 §6→§1）。

---

## 8. 不在本方案范围（受控债 / 仓外 / 需单独决策）
- `_v2` 删除动作：遵循 `MIGRATION_v2_DROP_PLAN.md` 既有 allowlist + CI guard，不在此私改。
- 官网 HTTPS：服务器/证书侧，运维处置。
- `admin123` 默认凭据链、写路由认证：属安全策略变更，见安全审计结论，需产品决策后单独执行。
