# 覆盖率差距报告（全量口径 · 2026-06-14 基线）

> 由 `scripts/dev/coverage_ratchet.py` 配套生成；数据源为 `.venv` CI 等价依赖（不含 ml extra）实测。
> 唯一可复现 SSOT，禁止用富依赖环境数字（历史 58/60.63/66.33）对外混报。

## Phase 2 迭代（p2-frontend-ramp-r2 · 2026-06-14 · 本轮）


| 维度   | 本回合实测                         | 较 p2-frontend-ramp Δ | 备注                                               |
| ---- | ----------------------------- | -------------------- | ------------------------------------------------ |
| 前端行  | **40.35%**（20,768 / 51,472）   | **+5.05pp**          | 棘轮 bump 后 floor **40**                           |
| 前端分支 | **58.95%**（2,474 / 4,197）     | **+0.87pp**          | floor branches**58**                             |
| 前端函数 | **37.94%**（923 / 2,433）       | **+4.24pp**          | floor functions**37**                            |
| 前端语句 | **40.35%**                    | **+5.05pp**          | floor statements**40**                           |
| 新增用例 | 前端 **+132**（21 个新 `.test.ts`） | —                    | vitest **707 passed** / 4 skipped / **0 failed** |


**本回合新增测试文件（前端 21）**


| 区域             | 文件                                                                                                                                                                     |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `utils/`       | `memory-manager`、`pretext`、`excelImportPersistence`、`geometry-real`、`serviceWorker`、`tts.speak`、`workflowEmployeeOnboard`、`workspacePrefsApi`、`textParser.ext`         |
| `composables/` | `useChatOrchestration`、`useChatWorkflowPanel`、`useChatVoiceInput`、`usePerformanceMonitor`、`usePerformanceMonitor.frames`、`useChatPersistence.export`、`useShipmentTask` |
| `router/`      | `index.guards`                                                                                                                                                         |
| `components/`  | `TopAssistantFloat.deep`                                                                                                                                               |
| `views/`       | `hostBridgeViews.mount`、`hostBridgeViews.extra`、`ChatView.mount`                                                                                                       |


**附带修复（非测试）**：`ProductOnboardingView.vue` 非 TS script 中 `Set<string>()` 导致 vitest/babel 收集失败；改为 `new Set()` 恢复 `test:coverage` 全绿。

**距终态（lines≥80% / branches≥75% / functions≥80%）**：行 **−39.65pp**；分支 **−16.05pp**；函数 **−42.06pp**。**未达标**。

**停止条件**：会话 +132 用例（<250）；三轮行增量 +2.34 / +0.77 / +1.93pp；距 80% 差距过大，本轮硬停。

**测量命令**：

```bash
cd frontend && CI=true npm run test -- --run && CI=true npm run test:coverage -- --run
cd .. && .venv/bin/python scripts/dev/coverage_ratchet.py --bump --margin 0 --frontend-summary frontend/coverage/coverage-summary.json
```

## Phase 3 迭代（p3-backend-ramp · 2026-06-14 · 本轮）


| 维度     | 本回合实测                                       | 较 p2-backend-ramp Δ | 备注                                  |
| ------ | ------------------------------------------- | ------------------- | ----------------------------------- |
| 后端行    | **47.35%**（35,533 / 75,042）                 | **+1.52pp**         | 棘轮 floor 行 **47** / 分支 **29**       |
| 后端分支   | **29.89%**（6,583 / 22,026）                  | **+1.55pp**         |                                     |
| 新增用例   | 后端 **+84**（3 新文件 + industry 断言修复）           | —                   | 全 mock，无真实 PG/Redis                 |
| pytest | **3172 passed** / 51 skipped / **0 failed** | +84 vs 3088         | `XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1` |


**本回合新增测试文件（后端 3）**


| 区域                                                                  | 文件                                                      |
| ------------------------------------------------------------------- | ------------------------------------------------------- |
| workflow/planner + price_list + service_bridge + excel_extract      | `tests/test_coverage_ramp_phase3_p1_deep_backend.py`    |
| wechat_contact + purchase + xcagi_compat_product + tools_registered | `tests/test_coverage_ramp_phase3_p2_services_routes.py` |
| legacy_chat_adapter + planner fallback                              | `tests/test_coverage_ramp_phase3_p3_planner_legacy.py`  |


**各 Phase 距目标差距（后端行）**


| 里程碑        | 目标           | 当前              | 差距                      |
| ---------- | ------------ | --------------- | ----------------------- |
| Phase 2 五域 | 72%          | 47.35%          | **−24.65pp**            |
| Phase 3 冲刺 | 85%          | 47.35%          | **−37.65pp**            |
| 终态         | 90% / 85% 分支 | 47.35% / 29.89% | **−42.65pp / −55.11pp** |


**停止条件检查**：未达 90%/85% 分支；会话新增 84 用例（<400）；连续 1 轮行增量 <0.2pp（R3 +0.12pp），未达 6 轮耐心阈值。

**下一轮高 ROI**：`planner.py` ReAct 深路径、`ai_chat_app_service.py` stream、`market_account.py`、`tools_payload_legacy.py` 分支 sweep、`neuro_bus/domains` handler。

**测量命令**：

```bash
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ -q --cov=app --cov-branch --cov-report=json:coverage.json --cov-fail-under=0
.venv/bin/python scripts/dev/coverage_ratchet.py --check && .venv/bin/python scripts/dev/coverage_ratchet.py --bump --margin 0
```

## Phase 2 迭代（p2-backend-ramp · 2026-06-14 · 本轮）


| 维度     | 本回合实测                                       | 较上轮基线 Δ      | 备注                                  |
| ------ | ------------------------------------------- | ------------ | ----------------------------------- |
| 后端行    | **45.83%**（34,393 / 75,036）                 | **+0.93pp**  | 棘轮 floor 行 **45** / 分支 **28**       |
| 后端分支   | **28.34%**（6,242 / 22,026）                  | **+0.86pp**  |                                     |
| 新增用例   | 后端 **+105**（6 个新文件）                         | —            | 全 mock，无真实 PG/Redis                 |
| pytest | **3088 passed** / 51 skipped / **0 failed** | +105 vs 2983 | `XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1` |


**本回合新增测试文件（后端 6）**


| 区域                                                           | 文件                                                     |
| ------------------------------------------------------------ | ------------------------------------------------------ |
| conversation + kitten + persistence + rag/payment            | `tests/test_coverage_ramp_phase2_p2_backend.py`        |
| conversation context + chart_data + wechat + deepseek/rasa   | `tests/test_coverage_ramp_phase2_p2_ext_backend.py`    |
| price_list + llm + mods + neuro_bus events import            | `tests/test_coverage_ramp_phase2_p3_backend.py`        |
| workflow import + planner tools + ai_chat + semantic chunker | `tests/test_coverage_ramp_phase2_p3_ext_backend.py`    |
| extract_log + wechat_contact_store + contexts                | `tests/test_coverage_ramp_phase2_p4_routes_backend.py` |
| misc helpers + mods package + session_account_meta           | `tests/test_coverage_ramp_phase2_p5_misc_backend.py`   |


**各 Phase 距目标差距（后端行）**


| 里程碑        | 目标           | 当前              | 差距                      |
| ---------- | ------------ | --------------- | ----------------------- |
| Phase 2 五域 | 72%          | 45.83%          | **−26.17pp**            |
| Phase 3 冲刺 | 85%          | 45.83%          | **−39.17pp**            |
| 终态         | 90% / 85% 分支 | 45.83% / 28.34% | **−44.17pp / −56.66pp** |


**停止条件检查**：未达 90%/85% 分支；会话新增 105 用例（<300）；连续 3 轮行增量 <0.3pp（+0.14 / +0.02 / +0.06），未达 4 轮耐心阈值。

**下一轮高 ROI**：`ai_chat_app_service.py` 深路径、`planner.py`/`tools/workflow.py` 执行分支、`price_list_export.py` docx 填充、`fastapi_routes/domains` sweep、`neuro_bus/domains` handler。

**测量命令**：

```bash
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ -q --cov=app --cov-branch --cov-report=json:coverage.json --cov-fail-under=0
.venv/bin/python scripts/dev/coverage_ratchet.py --check && .venv/bin/python scripts/dev/coverage_ratchet.py --bump --margin 0
```

## Phase 2 迭代（p2-frontend-ramp · 2026-06-14 · 本轮）


| 维度   | 本回合实测                                 | 较基线 Δ       | 备注                                                      |
| ---- | ------------------------------------- | ----------- | ------------------------------------------------------- |
| 前端行  | **35.30%**（18,122 / 51,335）           | **+5.15pp** | 棘轮 bump 后 floor **35**                                  |
| 前端分支 | **58.08%**（2,436 / 4,194）             | **+0.67pp** | floor branches**58**                                    |
| 前端函数 | **33.70%**（820 / 2,433）               | **+2.34pp** | floor functions**33**                                   |
| 前端语句 | **35.30%**                            | **+5.15pp** | floor statements**35**                                  |
| 新增用例 | 前端 **+153**（42 个新 `.test.ts` + 3 处扩写） | —           | 全 mock；vitest **575 passed** / 4 skipped / **0 failed** |


**本回合新增测试文件（前端 42）**


| 区域             | 文件                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `utils/`       | `wechatIntent`、`wechatShipmentDetect`、`modPrimaryWorkflow`、`xcagiModPick`、`productUnitsList`、`workflowEmployeeDisplayName`、`plannerToolsPaths`、`plannerChatPaths`、`lanPagePaths`、`officeEmployeePagePaths`、`chatExportTemplatesRegistry`、`commandBuffer`、`tts`、`butlerTaskBus`、`postLoginReveal`、`sidebarTheme`、`shipmentMgmtPostPrint`、`authSessionCache`、`multimodalAttachments`、`modLoadingStatus`、`workflowEmployeeRegistry`、`dataSourceIcons`、`clientDebugLog`、`desktopShell`、`modRoutesSharedFetch`、`refreshTenantScopedClientStores` |
| `domain/`      | `yuangonDutyRoster`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `fhd/`         | `dbTokenHeaders`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `composables/` | `useImSounds`、`useDigitalRain`、`useAnimations`、`useModBootstrap`                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `api/`         | `modStore`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `stores/`      | `modStore`、`tutorial`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `router/`      | `registerModRoutes`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `workflow/`    | `coreWorkflowPrefs`、`coreWorkflowTaskUi`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `components/`  | `TopAssistantFloat`、`kitten/KittenAnalyzerView`、`template/LabelVisualEditor`                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `views/`       | `DiscoverView`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |


**附带修复（非测试）**：`workflowAiEmployees.ts` 缺失 `enableEmployees` 函数头导致 vitest 收集失败；`ModStore.test.ts` 文案/mock 对齐当前 UI。

**距 Phase 目标（lines≥80% / branches≥75%）**：行仍差 **44.70pp**；分支差 **16.92pp**。下一轮高 ROI：`useChatOrchestration`、`useChatWorkflowPanel`、`TopAssistantFloat` 深路径、`tts.ts` speak 分支、`router/index` 守卫。

**测量命令**：

```bash
cd frontend && CI=true npm run test -- --run && CI=true npm run test:coverage -- --run
cd .. && .venv/bin/python scripts/dev/coverage_ratchet.py --bump --margin 0 --frontend-summary frontend/coverage/coverage-summary.json
```

## Phase 1 迭代（p1-p0-core · 2026-06-14 续）


| 维度     | 本回合实测                                       | 较 p56 基线 Δ        | 备注                                  |
| ------ | ------------------------------------------- | ----------------- | ----------------------------------- |
| 后端行    | **44.90%**（33,690 / 75,036）                 | **+3.15pp**       | 棘轮 bump 后 floor **44**；未达 55%       |
| 后端分支   | **27.48%**（6,052 / 22,026）                  | **+3.64pp**       | 棘轮 bump 后 floor **27**              |
| 前端行    | **30.15%**                                  | +1.8pp（vitest 全绿） | floor lines**30**                   |
| 新增用例   | 后端 **+345**（8 个新文件 + 既有 p2 文件）              | —                 | 全 mock，无真实 PG/Redis                 |
| pytest | **2983 passed** / 51 skipped / **0 failed** | +345              | `XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1` |
| vitest | **422 passed** / 4 skipped / **0 failed**   | —                 | stores/api/composables 沿用既有覆盖       |


**本回合新增测试文件（p1-p0-core 续 · 后端 8）**


| 区域                                                 | 文件                                                       |
| -------------------------------------------------- | -------------------------------------------------------- |
| `domains/auth`                                     | `tests/test_coverage_ramp_phase1_p1_auth_routes.py`      |
| `domains` 路由 sweep                                 | `tests/test_coverage_ramp_phase1_p1_domains_routes.py`   |
| `template` + `wechat` + `customer`                 | `tests/test_coverage_ramp_phase1_p1_template_wechat.py`  |
| `conversation/helpers` + `compat_db` + app_service | `tests/test_coverage_ramp_phase1_p1_helpers_services.py` |
| `tools/workflow` + `planner`                       | `tests/test_coverage_ramp_phase1_p1_workflow_tools.py`   |
| `ai_chat` + `system` + `auth` 扩展                   | `tests/test_coverage_ramp_phase1_p1_ai_chat_system.py`   |
| `system` performance + `approval_workspace`        | `tests/test_coverage_ramp_phase1_p1_system_approval.py`  |
| `xcagi_compat_chat_helpers`                        | `tests/test_coverage_ramp_phase1_p1_chat_helpers.py`     |


**距 Phase 1 里程碑（55% 行）**：仍差 **10.10pp**（约 **7,579** 语句未覆盖）。连续 3 轮 <0.3pp 未触发（本轮 +0.44pp vs 上轮 p1-round2）；下一轮高 ROI：`planner.py`（~~599）、`tools/workflow.py`（~~519）、`ai_chat_app_service.py` 深路径、`infrastructure/persistence/compat_db`。

**测量命令**：

```bash
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -q --cov=app --cov-branch --cov-report=json:coverage.json --cov-fail-under=0
python scripts/dev/coverage_ratchet.py --check && python scripts/dev/coverage_ratchet.py --bump --margin 0
cd frontend && npm run test -- --run
```

## Phase 1 迭代（p1-round2 · 2026-06-14）


| 维度     | 本回合实测                                       | 较第一轮 Δ           | 备注                              |
| ------ | ------------------------------------------- | ---------------- | ------------------------------- |
| 后端行    | **44.68%**（33,523 / 75,036）                 | **+0.67pp**      | 未达 55% 中期目标；棘轮 floor **43** 仍有效 |
| 后端分支   | **27.16%**（5,983 / 22,026）                  | **+3.1pp**       | 分支 floor **24** 仍有效             |
| 新增用例   | 后端 **+79**（3 个新文件）                          | —                | 全 mock，无真实 PG/Redis             |
| pytest | **2953 passed** / 51 skipped / **0 failed** | +229 vs 第一轮 2724 | 全绿；排除 `phase2_p1_biz`（torch 依赖） |


**本回合新增测试文件（Phase 1 第二轮）**


| 区域                                          | 文件                                                                                                                |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `ai_chat_app_service`                       | `tests/test_coverage_ramp_phase1_p2_ai_chat.py`（Excel 导入捷径 / process_chat 异常 / 工具分支）                              |
| `fastapi_routes/domains`                    | `tests/test_coverage_ramp_phase1_p2_routes_ext.py`（conversation compat / auth / misc / product compat / customer） |
| `workflow/planner` + `conversation/helpers` | `tests/test_coverage_ramp_phase1_p2_planner_helpers.py`（execute_tool / fallback_plan / SSE / db-read-token）       |


**关键文件覆盖率（本轮后）**


| 文件                                                   | 行%        | 较第一轮          |
| ---------------------------------------------------- | --------- | ------------- |
| `app/application/ai_chat_app_service.py`             | **60.3%** | +45pp（原 ~15%） |
| `app/fastapi_routes/domains/`**                      | **50.1%** | +24pp         |
| `app/application/workflow/planner.py`                | **23.4%** | +13pp         |
| `app/fastapi_routes/domains/conversation/helpers.py` | **57.4%** | +31pp         |


**距 55% 里程碑（后端行）**：仍差 **10.32pp**（约 **7,746** 行）。下一轮高 ROI 块：`planner.py`（~~599 行未覆盖）、`tools/workflow.py`（~~519）、`infrastructure/persistence`（compat_db writes）、`services/conversation`。

**测量命令**（与 CI 等价）：

```bash
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 pytest tests/ --ignore=tests/test_coverage_ramp_phase2_p1_biz_backend.py \
  --cov=app --cov-branch --cov-fail-under=0 --cov-report=json:coverage.json -q
```

## Phase 4 迭代（p56-backend · 2026-06-14）


| 维度     | 本回合实测                                       | 较上回合 Δ      | 备注                           |
| ------ | ------------------------------------------- | ----------- | ---------------------------- |
| 后端行    | **41.75%**（31,327 / 75,036）                 | **+0.74pp** | `fail_under` floor **41** 保持 |
| 后端分支   | **23.84%**（5,251 / 22,026）                  | **+0.55pp** | 分支 floor **23** 保持           |
| 新增用例   | 后端 **+83**                                  | —           | 全 mock，无真实 PG/Redis          |
| pytest | **2638 passed** / 51 skipped / **0 failed** | +83         | 全绿                           |


**本回合新增测试文件（后端 4）**


| 区域                                     | 文件                                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------------------ |
| `neuro_bus/events`                     | `tests/test_neuro_bus/test_events_phase4.py`（基类 / DomainEvent / IntentEvent / 注册表）   |
| `mod_sdk` compat                       | `tests/test_mod_sdk/test_compat_facades.py`（neuro_bus / approval / lan / planner 门面） |
| `persistence` + `ai_chat` + `workflow` | `tests/test_coverage_ramp_phase56_backend.py`（compat_db / extract_log / helpers）     |
| `fastapi_routes/domains`               | `tests/test_coverage_ramp_phase56_routes.py`（static / misc helpers）                  |


**距里程碑差距（后端行）**


| 里程碑        | 目标           | 当前              | 差距                      |
| ---------- | ------------ | --------------- | ----------------------- |
| Phase 1 中期 | 55%          | 41.75%          | **−13.25pp**            |
| Phase 2 五域 | 72%          | ~35%（待复测）       | **~−37pp**              |
| Phase 3 冲刺 | 85%          | 41.75%          | **−43.25pp**            |
| 终态         | 90% / 85% 分支 | 41.75% / 23.84% | **−48.25pp / −61.16pp** |


## Phase 2 迭代（p2-p1-biz · 2026-06-14 · 本轮）


| 维度     | 本回合实测                                       | 较基线 Δ       | 备注                                 |
| ------ | ------------------------------------------- | ----------- | ---------------------------------- |
| 后端行    | **43.13%**（32,361 / 75,036）                 | **+1.38pp** | 棘轮 floor 行 **43** / 分支 **25**      |
| 后端分支   | **25.23%**（5,558 / 22,026）                  | **+1.39pp** |                                    |
| 前端行    | **30.15%**                                  | **+1.8pp**  | floor lines**30** / branches**57** |
| 新增用例   | 后端 **+78** / 前端 **+3**                      | —           | 全 mock                             |
| pytest | **2833 passed** / 51 skipped / **0 failed** | +109        | 全绿                                 |
| vitest | **421 passed**（含本轮 3）                       | +3          | 全绿                                 |


**本回合新增测试文件（11）**


| 区域                                              | 文件                                                                                                               |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `application` + `infrastructure` + `ai_engines` | `tests/test_coverage_ramp_phase2_p1_biz_backend.py`（price_list / aibiz / rag / rbac / sqlite_vector / compat_db） |
| `domain/services`                               | `test_chinese_number.py`、`test_shipment_rules_engine.py`、`test_product_import_validator.py`                      |
| `services/conversation` + `kitten_report`       | `test_modstore_adapter_helpers.py`、`test_conversation_api_helpers.py`、`test_kitten_report_plugins.py`            |
| `infrastructure/documents`                      | `test_price_list_export_helpers.py`                                                                              |
| `frontend/views`                                | `ProductOnboardingView.test.ts`、`ImMessengerView.test.ts`                                                        |
| `frontend/components/workflow`                  | `StitchStage.test.ts`                                                                                            |


**距里程碑差距（后端行）**


| 里程碑        | 目标  | 当前     | 差距           |
| ---------- | --- | ------ | ------------ |
| Phase 2 五域 | 72% | 43.13% | **−28.87pp** |


**Phase 2 剩余大块（优先下一批）**

- `app/infrastructure/persistence`（compat_db/writes、product_repository_impl、wechat_contact_store）
- `app/services/conversation`（manager / handlers / modstore_adapter 主体）
- `app/application/ai_chat_app_service.py`、`workflow/planner.py`
- `app/infrastructure/documents`（price_list_export 主体 docx 填充）
- `app/services/kitten_report`（service / docx_export）
- 前端：`src/components`（TopAssistantFloat、LabelVisualEditor、KittenAnalyzerView）、`src/views`（SettingsView 深化）

## Phase 2 迭代（p2-p1-biz · 2026-06-14）


| 维度         | 本回合实测      | 较基线 Δ              |
| ---------- | ---------- | ------------------ |
| 后端行        | **41.02%** | +2.0pp             |
| 后端分支       | **23.32%** | +1.3pp             |
| Phase 2 五域 | **35.26%** | +2.4pp（距 72% 仍有差距） |
| 前端行        | **26.90%** | +3.6pp             |


新增 10 个测试文件（后端 102 + 前端 4 用例）；`ModStore`/`ProductsView`/`AIOpenPanel` 由 0% 升至 49–61%。

## Phase 3 迭代（p3-p3-frontend · 2026-06-14）


| 维度   | 本回合实测                        | 较 Phase 2 Δ | 备注                                                      |
| ---- | ---------------------------- | ----------- | ------------------------------------------------------- |
| 前端行  | **28.35%**（14,301 / 50,438）  | **+1.5pp**  | `coverage_ratchet.py --bump` 无新 floor（已 lines**28**）    |
| 前端分支 | **56.89%**（1,931 / 3,394）    | **+1.8pp**  | floor branches**56**                                    |
| 前端函数 | **31.16%**（667 / 2,140）      | **+2.1pp**  | floor functions**31**                                   |
| 前端语句 | **28.35%**                   | **+1.5pp**  | floor statements**28**                                  |
| 新增用例 | 前端 **+65**（21 个新 `.test.ts`） | —           | 全 mock；vitest **418 passed** / 4 skipped / **0 failed** |


**本回合新增测试文件**


| 区域               | 文件                                                                                                                                  |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `composables/`   | `useAppToast`、`useLanGate`、`useCoreNavLabel`、`useIndustryUiText`、`useWorkMode`、`useWorkflowPanoramaNavVisible`、`useChatDbTokenGate` |
| `stores/`        | `sidebarLayout`、`industry`                                                                                                          |
| `api/__tests__/` | `system`、`search`、`materials`                                                                                                       |
| `utils/`         | `shellMenuLabels`、`loginPreferences`、`safeJsonRequest`、`productSku`、`extractAccountMeta`、`appDialog`、`xcagiStorageKeys`             |
| `views/`         | `RegisterView`、`LanGateView`                                                                                                        |


## Phase 3 迭代（p3-p2-fill · 2026-06-14）


| 维度   | 本回合实测                       | 较基线 Δ      | 备注                                                               |
| ---- | --------------------------- | ---------- | ---------------------------------------------------------------- |
| 后端行  | **41.01%**（30,743 / 75,036） | **+2.0pp** | `coverage_ratchet.py --check` 行 floor 通过                         |
| 后端分支 | **23.29%**（5,132 / 22,026）  | **+1.3pp** | 分支 floor 22 通过                                                   |
| 前端行  | 基线 **23.28%** 仍有效           | —          | 全量 `test:coverage` 因 6 个既有失败用例导致 v8 合并异常；排除后约 21.81%（不可作棘轮 bump） |
| 新增用例 | 后端 **+38** / 前端 **+28**     | —          | 全 mock，无真实 PG/Redis                                              |


**本回合新增测试文件**


| 区域                    | 文件                                                                                                              |
| --------------------- | --------------------------------------------------------------------------------------------------------------- |
| `desktop_runtime/`    | `tests/test_desktop_runtime_phase3.py`（cache / queue / logging）                                                 |
| `neuro_bus/`          | `test_lifeline.py`、`test_neuro_trace_config.py`、`test_route_event_publisher.py`、`test_event_publisher_mixin.py` |
| `mod_sdk/`            | `test_audit.py`、`test_decoupling_progress.py`                                                                   |
| `contexts/`、`di/`     | 沿用既有 `test_manifest_and_flags.py`、`test_registry_and_deps.py`（未重复新建）                                            |
| `frontend/src/utils`  | `typeGuards`、`resolveApiError`、`chatTaskLabels`、`textParser`、`csrfCookie`、`sidebarActiveKey`、`lightMarkdown`    |
| `frontend/src/router` | `adminHostRoutes.stub.test.ts`                                                                                  |


**仍待 Phase 3/4 的大块（未覆盖语句/行仍高）**

- 后端：`app/neuro_bus/events`（~~696）、`app/neuro_bus/domains`（~~421）、`mod_sdk` 各 compat 门面、`desktop_runtime/support_bundle` / `migrate`
- 前端：`src/utils/tts.ts`（~396）、`registerModRoutes.ts`（需 mock Vite glob）、`src/router/index.ts` 守卫逻辑
- 全绿阻塞：已消除（`test_routing_policy` torch stub 冲突已修）；可继续 `coverage_ratchet.py --bump`

## 基线总览


| 维度       | 后端（pytest，source=[app]+branch）              | 前端（vitest，src/）                                                   |
| -------- | ------------------------------------------- | ----------------------------------------------------------------- |
| 行覆盖率     | **45.83%**（p2-backend-ramp）                 | **40.35%**（p2-frontend-ramp-r2）                                   |
| 分支覆盖率    | **28.34%**                                  | **58.95%**                                                        |
| 函数覆盖率    | coverage.py 不原生统计（前端经 v8 统计）                | **37.94%**                                                        |
| 语句数      | ~75,036                                     | 51,472                                                            |
| 被测文件     | 906+                                        | 472                                                               |
| 当前 floor | 行 **45** / 分支 **28**                        | lines**40** / branches**58** / functions**37** / statements**40** |
| 目标       | 行 ≥90 / 分支 ≥85（Phase 3 冲刺 ~85% 线内）          | lines ≥80 / branches ≥75 / functions ≥80                          |
| 测试运行     | **3088 passed** / 51 skipped / **0 failed** | **707 passed** / 4 skipped / **0 failed**                         |


> 注：2026-06-14 Phase 1 迭代；开启 branch 后 coverage 合并指标与行/分支分列见棘轮脚本。

## 后端缺口分区（按未覆盖语句降序）


| 未覆盖   | 语句    | 覆盖%   | 区域                                       | Phase |
| ----- | ----- | ----- | ---------------------------------------- | ----- |
| 2,721 | 3,678 | 26.0% | `app/fastapi_routes/domains`             | 1     |
| 2,058 | 2,436 | 15.5% | `app/infrastructure/persistence`         | 2     |
| 1,815 | 2,060 | 11.9% | `app/application/workflow`               | 1/2   |
| 1,279 | 2,232 | 42.7% | `app/infrastructure/mods`                | 2     |
| 1,202 | 1,414 | 15.0% | `app/application/ai_chat_app_service.py` | 1     |
| 1,106 | 1,404 | 20.4% | `app/services/conversation`              | 2     |
| 922   | 1,159 | 20.4% | `app/infrastructure/documents`           | 2     |
| 891   | 1,553 | 42.6% | `app/application/employee_runtime`       | 1/2   |
| 783   | 800   | 2.1%  | `app/infrastructure/skills`              | 2     |
| 737   | 877   | 16.0% | `app/services/kitten_report`             | 2     |
| 710   | 798   | 11.0% | `app/application/tools`                  | 1/2   |
| 696   | 946   | 26.4% | `app/neuro_bus/events`                   | 3     |
| 612   | 1,106 | 44.7% | `app/domain/services`                    | 2     |
| 421   | 1,018 | 58.6% | `app/neuro_bus/domains`                  | 3     |


## 后端 Top-20 单文件（按未覆盖行）


| 未覆盖   | 语句    | 覆盖%   | 文件                                                          | Phase |
| ----- | ----- | ----- | ----------------------------------------------------------- | ----- |
| 1,202 | 1,414 | 15.0% | `app/application/ai_chat_app_service.py`                    | 1     |
| 740   | 782   | 5.4%  | `app/application/workflow/planner.py`                       | 1/2   |
| 639   | 710   | 10.0% | `app/application/tools/workflow.py`                         | 1/2   |
| 467   | 667   | 30.0% | `app/fastapi_routes/market_account.py`                      | 1     |
| 432   | 438   | 1.4%  | `app/services/tools_payload_legacy.py`                      | 2     |
| 407   | 842   | 51.7% | `app/infrastructure/mods/mod_manager.py`                    | 2     |
| 387   | 387   | 0.0%  | `app/infrastructure/documents/price_list_export.py`         | 2     |
| 377   | 398   | 5.3%  | `app/services/tools_workflow_registered.py`                 | 2     |
| 374   | 430   | 13.0% | `app/services/deepseek_intent_service.py`                   | 2     |
| 367   | 387   | 5.2%  | `app/domain/context/session_context.py`                     | 2     |
| 361   | 389   | 7.2%  | `app/infrastructure/persistence/compat_db/writes.py`        | 2     |
| 350   | 418   | 16.3% | `app/fastapi_routes/domains/conversation/helpers.py`        | 1     |
| 350   | 418   | 16.3% | `app/fastapi_routes/xcagi_compat_chat_helpers.py`           | 1     |
| 348   | 383   | 9.1%  | `app/application/aibiz_web_terminal_service.py`             | 1     |
| 339   | 339   | 0.0%  | `app/application/excel_template_http_app_service.py`        | 1     |
| 337   | 337   | 0.0%  | `app/services/wechat_contact_service.py`                    | 2     |
| 331   | 614   | 46.1% | `app/fastapi_routes/xcmax_admin.py`                         | 1     |
| 327   | 442   | 26.0% | `app/fastapi_routes/mobile_api_extensions.py`               | 1     |
| 317   | 317   | 0.0%  | `app/fastapi_routes/domains/static/routes.py`               | 1     |
| 312   | 355   | 12.1% | `app/infrastructure/persistence/product_repository_impl.py` | 2     |


## 前端缺口分区（按未覆盖行降序）


| 未覆盖    | 行      | 覆盖%   | 区域                | Phase |
| ------ | ------ | ----- | ----------------- | ----- |
| 11,084 | 13,281 | 16.5% | `src/components`  | 2     |
| 9,739  | 11,076 | 12.1% | `src/composables` | 1     |
| 5,392  | 6,456  | 16.5% | `src/views`       | 2     |
| 3,958  | 6,392  | 38.1% | `src/utils`       | 3     |
| 2,885  | 3,977  | 27.5% | `src/stores`      | 1     |
| 2,124  | 2,507  | 15.3% | `src/api`         | 1     |
| 845    | 845    | 0.0%  | `src/domain`      | 2/3   |
| 726    | 1,392  | 47.8% | `src/tutorial`    | 3     |
| 682    | 1,744  | 60.9% | `src/constants`   | 3     |
| 429    | 820    | 47.7% | `src/router`      | 3     |


## 前端 Top-15 单文件（按未覆盖行）


| 未覆盖   | 行     | 覆盖%   | 文件                                              | Phase |
| ----- | ----- | ----- | ----------------------------------------------- | ----- |
| 1,007 | 1,341 | 24.9% | `src/composables/useChatOrchestration.ts`       | 1     |
| 999   | 1,138 | 12.2% | `src/composables/useChatWorkflowPanel.ts`       | 1     |
| 956   | 956   | 0.0%  | `src/views/ModStore.vue`                        | 2     |
| 938   | 938   | 0.0%  | `src/composables/useKittenAnalyzer.ts`          | 1     |
| 768   | 1,263 | 39.2% | `src/components/TopAssistantFloat.vue`          | 2     |
| 597   | 1,359 | 56.1% | `src/views/SettingsView.vue`                    | 2     |
| 578   | 578   | 0.0%  | `src/components/aiopen/AIOpenPanel.vue`         | 2     |
| 546   | 546   | 0.0%  | `src/views/ProductOnboardingView.vue`           | 2     |
| 514   | 514   | 0.0%  | `src/components/workflow/StitchStage.vue`       | 2     |
| 446   | 853   | 47.7% | `src/stores/mods.ts`                            | 1     |
| 440   | 440   | 0.0%  | `src/views/ProductsView.vue`                    | 2     |
| 414   | 414   | 0.0%  | `src/components/template/LabelVisualEditor.vue` | 2     |
| 397   | 397   | 0.0%  | `src/components/kitten/KittenAnalyzerView.vue`  | 2     |
| 396   | 445   | 11.0% | `src/utils/tts.ts`                              | 3     |
| 394   | 394   | 0.0%  | `src/views/ImMessengerView.vue`                 | 2     |


## 推进策略

- 按 Phase 1→4 前后端并行（详见 `.cursor/plans/coverage-to-90`）。
- 每批闭环：写测试 → 全绿 → `coverage_ratchet.py --check` → `--bump` → commit。
- 优先攻零覆盖（后端 184 / 前端 255）与大文件，单位投入收益最高。
- 复测命令：
  - 后端：`XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ --cov --cov-branch --cov-fail-under=0 --cov-report=json:coverage.json -q`
  - 前端：`cd frontend && CI=true npm run test:coverage`