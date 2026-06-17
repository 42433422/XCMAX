# 覆盖率差距报告（全量口径 · 2026-06-17 更新）

> 由 `scripts/dev/coverage_ratchet.py` 配套生成；数据源为 `.venv` CI 等价依赖（不含 ml extra）实测。
> 唯一可复现 SSOT：`metrics/coverage-dual-summary.json` + `metrics/coverage-history.jsonl`。
> 禁止用富依赖环境数字（历史 58/60.63/66.33/77.4%）或窄包 70% 对外混报。

## 当前快照（2026-06-17）

| 层级 | 后端行 | 后端分支 | 前端行 | 前端分支 | pytest | 状态 |
|------|-------:|---------:|-------:|---------:|--------|------|
| **HEAD**（`1569dfa4` · 06-14 bump） | **52.74%** | **37.17%** | **55.82%** | **62.80%** | 3,785 / 0 fail | 全绿 · 棘轮已 bump |
| **WIP**（工作区 · 06-17） | **74.56%** | **61.80%** | **74.15%** | **69.54%** | 12,675 / **196 fail + 7 err** | 未提交 · 不可对外宣称 |

**棘轮 floor**：后端行 **51%** / 分支 **36%**；前端 lines **54%** / branches **62%** / functions **50%**。

**距终态（按 WIP 计）**：后端行差 **~15pp**（目标 90%）；前端 lines 差 **~6pp**（目标 80%）。
**阻塞**：须先清零 196 个失败 + 7 个 error，再 `--bump`。

**WIP 红灯聚类**

| 模块 | 失败数（约） | 备注 |
|------|------------|------|
| `purchase_service` | ~7 | 源码改动未对齐测试 |
| `wechat_contact_cache_import` | ~5 | 同上 |
| `wechat_task_service` | ~2 | 同上 |
| `tools_workflow_registered` | ~2 | 同上 |
| `test_im_sync` / `test_im_v0` | 7 errors | SQLAlchemy 环境 |

## Phase 4 迭代（p4-ramp-r24 · 2026-06-14 · 最后全绿 bump）

| 维度 | 上回合 | 本回合实测 | Δ | floor |
|------|--------|-----------|----|-------|
| 后端行 | 51.52% | **51.68%**（38,780 / 75,042） | **+0.16pp** | 行 floor **51** |
| 后端分支 | 35.50% | **35.61%**（7,843 / 22,026） | **+0.11pp** | 分支 floor **35** |
| 前端行 | 53.81% | **53.92%** | **+0.11pp** | lines floor **53** |
| 前端分支 | 62.63% | **62.88%** | **+0.25pp** | branches floor **62** |
| 前端函数 | 49.89% | **50.10%** | **+0.21pp** | functions floor **50** |
| pytest | 3753 | **3785 passed** / 51 skipped / 0 failed | +32 | 全绿 |
| vitest | 1123 | **1143 passed** / 4 skipped / 0 failed | +20 | `test:coverage` 退出码 **0** |

**本回合新增**

| 栈 | 文件 | 主攻 |
|----|------|------|
| 后端 | `tests/test_coverage_ramp_phase4_p24_backend.py`（32 用例） | `init_db` 种子复制/Mod 专用库/模板表、`print_utils` 不可用路径、`mobile_api_extensions` sync/home/devices |
| 前端 | `coreWorkflowDispatcher.deep.test.ts`、`coreWorkflowTaskUi.deep.test.ts` | 工作流调度/任务圆点全分支 |
| 修复 | `erpDomainPaths.deep.test.ts` | 补 mock `clientModProvidesErpApi`（与 `protectedMods` 新 API 对齐） |

**距终态**：后端行仍差 **~38pp**（目标 90%）；前端 lines 差 **~26pp**（目标 80%）。下批 ROI：`ai_chat_app_service.process_chat` 深路径、`planner` ReAct mock 树、`coreWorkflowMonitor` 分支 sweep。

## Phase 4 迭代（p4-backend-ramp · 2026-06-14 · 持续攻坚后端）

> SSOT 口径：`coverage_ratchet.py read_backend`（行=covered_lines/num_statements，分支=covered_branches/num_branches）。

| 维度 | 会话起点 | 本回合实测 | Δ | floor |
|------|---------|-----------|----|-------|
| 后端行 | 47.35% | **49.46%**（37,115 / 75,042） | **+2.11pp** | 行 floor **48 → 49** |
| 后端分支 | 29.89% | **32.99%**（7,266 / 22,026） | **+3.10pp** | 分支 floor **31 → 32** |
| pytest | — | **3448 passed** / 51 skipped / 0 failed | — | 全绿 |

**本会话新增测试文件（rounds 6–10，全 mock/真实临时文件，无网络/PG/Redis）**

| 轮次 | 文件 | 主攻 |
|------|------|------|
| 6 | `tests/test_coverage_ramp_phase4_p6_backend.py` | `xcagi_compat_chat_helpers`（15.7%→，HTTP 异常映射/token 闸/excel 路径/超时 env/SSE/守卫流） |
| 7 | `tests/test_coverage_ramp_phase4_p7_backend.py` | `mod_manager` scan/load/install/import 深路径 + `planner._plan_with_llm`/critic mock |
| 8 | `tests/test_coverage_ramp_phase4_p8_backend.py` | `excel_template_analyzer`（**0%→90%**，真实 xlsx 跑 analyze 全管线） |
| 9 | `tests/test_coverage_ramp_phase4_p9_backend.py` | `template_export_utils`（**0%→**）+ `upload_helpers`（**0%→**） |
| 10 | `tests/test_coverage_ramp_phase4_p10_backend.py` | `traditional_mode_fs`（12%→，临时 ROOT_DIR 跑 list/read/write/move/copy/snapshot） |

**剩余最大单文件缺口（按未覆盖行）**

| 未覆盖 | 语句 | 覆盖% | 文件 |
|-------:|-----:|------:|------|
| 461 | 1414 | 62.2% | `app/application/ai_chat_app_service.py` |
| 372 | 844 | 52.8% | `app/infrastructure/mods/mod_manager.py` |
| 331 | 614 | 41.1% | `app/fastapi_routes/xcmax_admin.py` |
| 318 | 710 | 53.0% | `app/application/tools/workflow.py` |
| 318 | 667 | 47.1% | `app/fastapi_routes/market_account.py` |
| 313 | 430 | 24.7% | `app/services/deepseek_intent_service.py` |
| 297 | 782 | 61.3% | `app/application/workflow/planner.py` |
| 281 | 313 | 8.2% | `app/utils/print_utils.py`（Windows-only，本机不可测） |
| 271 | 425 | 33.1% | `app/services/xcmax_sync_service.py` |
| 268 | 383 | 27.2% | `app/application/aibiz_web_terminal_service.py` |
| 268 | 357 | 22.0% | `app/services/conversation/modstore_adapter.py` |

## Phase 2 迭代（p2-p1-biz · 2026-06-14）

| 维度 | 本回合实测 | 较基线 Δ |
|------|-----------|---------|
| 后端行 | **41.02%** | +2.0pp |
| 后端分支 | **23.32%** | +1.3pp |
| Phase 2 五域 | **35.26%** | +2.4pp（距 72% 仍有差距） |
| 前端行 | **26.90%** | +3.6pp |

新增 10 个测试文件（后端 102 + 前端 4 用例）；`ModStore`/`ProductsView`/`AIOpenPanel` 由 0% 升至 49–61%。

## Phase 3 迭代（p3-p2-fill · 2026-06-14）

| 维度 | 本回合实测 | 较基线 Δ | 备注 |
|------|-----------|---------|------|
| 后端行 | **41.01%**（30,743 / 75,036） | **+2.0pp** | `coverage_ratchet.py --check` 行 floor 通过 |
| 后端分支 | **23.29%**（5,132 / 22,026） | **+1.3pp** | 分支 floor 22 通过 |
| 前端行 | 基线 **23.28%** 仍有效 | — | 全量 `test:coverage` 因 6 个既有失败用例导致 v8 合并异常；排除后约 21.81%（不可作棘轮 bump） |
| 新增用例 | 后端 **+38** / 前端 **+28** | — | 全 mock，无真实 PG/Redis |

**本回合新增测试文件**

| 区域 | 文件 |
|------|------|
| `desktop_runtime/` | `tests/test_desktop_runtime_phase3.py`（cache / queue / logging） |
| `neuro_bus/` | `test_lifeline.py`、`test_neuro_trace_config.py`、`test_route_event_publisher.py`、`test_event_publisher_mixin.py` |
| `mod_sdk/` | `test_audit.py`、`test_decoupling_progress.py` |
| `contexts/`、`di/` | 沿用既有 `test_manifest_and_flags.py`、`test_registry_and_deps.py`（未重复新建） |
| `frontend/src/utils` | `typeGuards`、`resolveApiError`、`chatTaskLabels`、`textParser`、`csrfCookie`、`sidebarActiveKey`、`lightMarkdown` |
| `frontend/src/router` | `adminHostRoutes.stub.test.ts` |

**仍待 Phase 3/4 的大块（未覆盖语句/行仍高）**

- 后端：`app/neuro_bus/events`（~696）、`app/neuro_bus/domains`（~421）、`mod_sdk` 各 compat 门面、`desktop_runtime/support_bundle` / `migrate`
- 前端：`src/utils/tts.ts`（~396）、`registerModRoutes.ts`（需 mock Vite glob）、`src/router/index.ts` 守卫逻辑
- 全绿阻塞：已消除（`test_routing_policy` torch stub 冲突已修）；可继续 `coverage_ratchet.py --bump`

## Phase 2 迭代（p2-frontend-ramp-r4 · 2026-06-14 · 修分支门禁回归）

上一轮（r3）因分母增大令前端分支 pct 跌破 floor 59，`test:coverage` 退出码 1。本轮补**分支密集型纯逻辑测试**把分支拉回，门禁恢复绿色（退出码 0），随后棘轮只升不降地把分支 floor 提到 60。

| 维度 | 本回合实测 | 较 r3 Δ | 备注 |
|------|-----------|---------|------|
| 前端行 | **48.85%**（25,247 / 51,683） | +0.51pp | floor lines **48** |
| 前端分支 | **60.42%**（3,617 / 5,986） | **+2.31pp** | floor branches **59 → 60**；**回归已修复** |
| 前端函数 | **40.98%**（1,136 / 2,772） | +0.38pp | floor functions **40** |
| 前端语句 | **48.85%** | +0.51pp | floor statements **48** |
| 测试运行 | **931 passed** / 4 skipped / **0 failed** | 前端 +84 | `test:coverage` 退出码 **0**（门禁绿） |

**本回合新增测试文件（6 个 `.deep`/`.validation`，全部纯逻辑、确定性、无意义断言为零）**

| 区域 | 文件 | 主攻分支 |
|------|------|---------|
| `utils/` | `commandBuffer.deep.test.ts` | contains/token 相似命中、stale 过期、损坏 JSON、命中计数自增 |
| `utils/` | `lightMarkdown.deep.test.ts` | 标题/列表/引用/表格对齐/围栏/mermaid/公式/图片/自动链接/强调 |
| `utils/` | `erpDomainPaths.deep.test.ts` | 门面开关、客户 Mod 优先级、wechat 兼容、host-only 直通 |
| `utils/` | `textParser.deep.test.ts` | 中文数字十位、p00/p00b/p00c/p00d/p3/p4 解析路径、增删改命令 |
| `constants/` | `genericModPack.deep.test.ts` | bridge/workflow/员工包判定、`catalogStoreCollection` 全分支 |
| `domain/` | `employeeConfigV2.validation.test.ts` | tone/provider/temperature/top_p/max_tokens/access_level/ASR/知识库校验 |

> 终态目标仍为 lines ≥80 / branches ≥75 / functions ≥80；分支已越过中段（60%），行/函数为后续主攻方向（views/components mount+交互、`useChat*` 深路径、零覆盖大文件）。

## Phase 2 迭代（p2-frontend-ramp-r5 · 2026-06-14 · 攻零覆盖 store/composable/api）

门禁修复后继续冲终态：本轮主攻 0% 的 store / composable / api 大文件，行/函数/分支同步上行，门禁保持绿色。

| 维度 | 本回合实测 | 较 r4 Δ | floor（bump 后） |
|------|-----------|---------|------------------|
| 前端行 | **49.87%**（≈25,800 / 51,7xx） | **+1.02pp** | **48 → 49** |
| 前端分支 | **61.36%**（3,817 / 6,220） | **+0.94pp** | **60 → 61** |
| 前端函数 | **42.62%**（≈1,182 / 2,7xx） | **+1.64pp** | **40 → 42** |
| 前端语句 | **49.87%** | **+1.02pp** | **48 → 49** |
| 测试运行 | 全绿 / 0 failed | 前端 +53 | `test:coverage` 退出码 **0** |

**本回合新增测试文件（5 个，零覆盖大文件转中高覆盖）**

| 区域 | 文件 | 0%→ |
|------|------|-----|
| `stores/` | `productQuery.test.ts` | `productQuery.ts`（公司/产品查询、过滤、CRUD、导出、reset） |
| `stores/` | `tutorial.test.ts` | `tutorial.ts`（教程流程：start/next/prev/click/exit/finish、pro 回退、测试统计） |
| `composables/` | `useServiceBridge.test.ts` | `useServiceBridge.ts`（请求/统计/实例加载、outbox 回退、标签/时间格式化） |
| `composables/` | `useAnimations.test.ts` | `useAnimations.ts`（rAF 驱动动画、CSS 动画、过渡、全 easing 分支） |
| `api/` | `xcmaxMarketProxy.test.ts` | `xcmaxMarketProxy.ts`（GET/POST/PUT 分发、本地探针缓存、404 回退） |

## Phase 2 迭代（p2-frontend-ramp-r6 · 2026-06-14 · 续攻零覆盖 + 修门禁 flake）

继续攻零覆盖大文件；同时定位并根治一个**潜伏的门禁 flake**：`vitest.setup.ts` 用 `vi.fn()` 注册 `window.matchMedia`，而 15 个用例文件会调 `vi.restoreAllMocks()/resetAllMocks()` 将其实现清空（返回 `undefined`）；跨文件 fork 复用时，`MainLayout` 等组件异步 `onMounted` 里 `window.matchMedia(...).matches` 抛**未捕获异常**，使 `test:coverage` 退出码 1（与覆盖率阈值无关）。改为「普通函数 stub + 每用例前重建」后根治，全套 0 unhandled error。

| 维度 | 本回合实测 | 较 r5 Δ | floor（bump 后） |
|------|-----------|---------|------------------|
| 前端行 | **50.92%** | **+1.05pp** | **49 → 50** |
| 前端分支 | **61.61%** | +0.25pp | **61** |
| 前端函数 | **43.74%** | **+1.12pp** | **42 → 43** |
| 前端语句 | **50.92%** | **+1.05pp** | **49 → 50** |
| 测试运行 | **1015 passed** / 4 skipped / **0 failed** / **0 error** | 前端 +37 | `test:coverage` 退出码 **0**（门禁真绿） |

**本回合新增测试文件（3 个）**：`stores/materials.test.ts`、`stores/workflowEmployeeSpace.test.ts`、`api/modStore.full.test.ts`（覆盖 23 个市场 API 函数的成功/失败/非 JSON 分支）。
**门禁修复**：`frontend/vitest.setup.ts` matchMedia stub 改普通函数 + `beforeEach` 重建。

## Phase 2 迭代（p2-frontend-ramp-r7 · 2026-06-14 · 续攻零覆盖 composable/工具/教程）

门禁保持真绿（退出码 0、0 unhandled error）。本轮主攻 0% 的 composable / 懒加载注册 / 教程步骤工厂等纯逻辑大文件，行/函数同步上行。

| 维度 | 本回合实测 | 较 r6 Δ | floor（bump 后） |
|------|-----------|---------|------------------|
| 前端行 | **52.16%** | **+1.24pp** | **50 → 52** |
| 前端分支 | **61.38%** | -0.23pp（分母增大；仍 > floor 61） | **61** |
| 前端函数 | **44.09%** | **+0.35pp** | **43 → 44** |
| 前端语句 | **52.16%** | **+1.24pp** | **50 → 52** |
| 测试运行 | **1034 passed** / 4 skipped / **0 failed** / **0 error** | 前端 +19（净增文件用例 25） | `test:coverage` 退出码 **0**（门禁真绿） |

**本回合新增测试文件（4 个）**

| 区域 | 文件 | 0%→ |
|------|------|-----|
| `composables/` | `useShipmentTask.test.ts` | `useShipmentTask.ts`（增删改命令、产品元数据探针、订单号水合、预览富化、表格列/行/单号解析） |
| `components/` | `lazy-load.test.ts` | `lazy-load.ts`（Pro 组件注册/获取/预加载/关联预加载映射） |
| `tutorial/` | `stepFactory.test.ts` | `stepFactory.ts`（createStep/侧栏导航/页面特性/高亮映射/兜底概览全工厂） |
| `tutorial/tracks/` | `basic.test.ts` | `tracks/basic.ts`（`buildBasicSteps` 全步骤构建、id 唯一性、标签兜底） |

## Phase 2 迭代（p2-frontend-ramp-r8 · 2026-06-14 · 批量补零覆盖 API 模块，主拉函数覆盖）

函数覆盖是当前最大缺口（44%↔目标 80%）。本轮专攻 0% 的 API 模块（每个导出函数=一个薄封装），一次性把 81 个函数从未覆盖转覆盖，函数率单轮 +2pp。门禁保持真绿。

| 维度 | 本回合实测 | 较 r7 Δ | floor（bump 后） |
|------|-----------|---------|------------------|
| 前端行 | **52.64%** | +0.48pp | **52** |
| 前端分支 | **61.89%** | +0.51pp | **61** |
| 前端函数 | **46.17%** | **+2.08pp** | **44 → 46** |
| 前端语句 | **52.64%** | +0.48pp | **52** |
| 测试运行 | **1059 passed** / 4 skipped / **0 failed** / **0 error** | 前端 +25 | `test:coverage` 退出码 **0** |

**本回合新增测试文件（4 个 API 模块，0%→ 高覆盖，覆盖成功/失败/回退分支）**

| 文件 | 0%→ | 函数数 |
|------|-----|-------|
| `api/wechat.test.ts` | `wechat.ts`（任务/联系人 CRUD + `ensureContactCache` 404/405/no-source 回退链） | 24 |
| `api/lanGate.test.ts` | `lanGate.ts`（局域网授权 host/status/keys/sessions/allowlist + `updateSettings` 405→PUT 回退） | 21 |
| `api/auth.test.ts` | `auth.ts`（登录/注册/二维码/会话/找回密码 + `uploadAvatar` FormData + `logout` 清缓存） | 18 |
| `api/chat.test.ts` | `chat.ts`（13 个会话封装 + `parseChatStreamErrorResponse` + `sendChatStream`/`consumeChatStream` SSE） | 18 |

## Phase 2 迭代（p2-frontend-ramp-r9 · 2026-06-14 · 续批补 0% API 模块）

延续 r8 的「函数优先」策略，再补 8 个 0% API 模块。函数率单轮再 +3pp，逼近 50%。门禁真绿。

| 维度 | 本回合实测 | 较 r8 Δ | floor（bump 后） |
|------|-----------|---------|------------------|
| 前端行 | **53.37%** | +0.73pp | **52 → 53** |
| 前端分支 | **62.32%** | +0.43pp | **61 → 62** |
| 前端函数 | **49.21%** | **+3.04pp** | **46 → 49** |
| 前端语句 | **53.37%** | +0.73pp | **52 → 53** |
| 测试运行 | **1101 passed** / 4 skipped / **0 failed** / **0 error** | 前端 +42 | `test:coverage` 退出码 **0** |

**本回合新增测试文件（8 个 API 模块）**：`orders`（404→purchase_units 回退）、`print`、`products`（units 多形态/搜索条件分支）、`materials`、`excel`（DTO 归一推断 label/excel）、`templatePreview`（404/405/501 服务未开放包装）、`im`（apiFetch + readJson 非 JSON/未登录分支）、`privateDbAssistant`（Mod 路由可用性缓存 + 不可用回退）。

## 基线总览

| 维度 | 后端（pytest，source=[app]+branch） | 前端（vitest，src/\*\*） |
|------|-----------------------------------|--------------------------|
| 行覆盖率 | **41.02%**（Phase 2 合并） | **26.90%**（Phase 2） |
| 分支覆盖率 | **23.32%** | **55.14%** |
| 函数覆盖率 | coverage.py 不原生统计（前端经 v8 统计） | **29.09%** |
| 语句数 | ~75,032 | 50,264 |
| 被测文件 | 906+ | 472 |
| 当前 floor | 行 **41** / 分支 **23** | lines**26** / branches**55** / functions**29** / statements**26** |
| 目标 | 行 ≥90 / 分支 ≥85（Phase 3 冲刺 ~85% 线内） | lines ≥80 / branches ≥75 / functions ≥80 |
| 测试运行 | **2555 passed** / 51 skipped / **0 failed** | **353 passed** / 4 skipped / **0 failed** |

> 注：2026-06-14 Phase 1 迭代；开启 branch 后 coverage 合并指标与行/分支分列见棘轮脚本。

## 后端缺口分区（按未覆盖语句降序）

| 未覆盖 | 语句 | 覆盖% | 区域 | Phase |
|-------:|-----:|------:|------|-------|
| 2,721 | 3,678 | 26.0% | `app/fastapi_routes/domains` | 1 |
| 2,058 | 2,436 | 15.5% | `app/infrastructure/persistence` | 2 |
| 1,815 | 2,060 | 11.9% | `app/application/workflow` | 1/2 |
| 1,279 | 2,232 | 42.7% | `app/infrastructure/mods` | 2 |
| 1,202 | 1,414 | 15.0% | `app/application/ai_chat_app_service.py` | 1 |
| 1,106 | 1,404 | 20.4% | `app/services/conversation` | 2 |
| 922 | 1,159 | 20.4% | `app/infrastructure/documents` | 2 |
| 891 | 1,553 | 42.6% | `app/application/employee_runtime` | 1/2 |
| 783 | 800 | 2.1% | `app/infrastructure/skills` | 2 |
| 737 | 877 | 16.0% | `app/services/kitten_report` | 2 |
| 710 | 798 | 11.0% | `app/application/tools` | 1/2 |
| 696 | 946 | 26.4% | `app/neuro_bus/events` | 3 |
| 612 | 1,106 | 44.7% | `app/domain/services` | 2 |
| 421 | 1,018 | 58.6% | `app/neuro_bus/domains` | 3 |

## 后端 Top-20 单文件（按未覆盖行）

| 未覆盖 | 语句 | 覆盖% | 文件 | Phase |
|-------:|-----:|------:|------|-------|
| 1,202 | 1,414 | 15.0% | `app/application/ai_chat_app_service.py` | 1 |
| 740 | 782 | 5.4% | `app/application/workflow/planner.py` | 1/2 |
| 639 | 710 | 10.0% | `app/application/tools/workflow.py` | 1/2 |
| 467 | 667 | 30.0% | `app/fastapi_routes/market_account.py` | 1 |
| 432 | 438 | 1.4% | `app/services/tools_payload_legacy.py` | 2 |
| 407 | 842 | 51.7% | `app/infrastructure/mods/mod_manager.py` | 2 |
| 387 | 387 | 0.0% | `app/infrastructure/documents/price_list_export.py` | 2 |
| 377 | 398 | 5.3% | `app/services/tools_workflow_registered.py` | 2 |
| 374 | 430 | 13.0% | `app/services/deepseek_intent_service.py` | 2 |
| 367 | 387 | 5.2% | `app/domain/context/session_context.py` | 2 |
| 361 | 389 | 7.2% | `app/infrastructure/persistence/compat_db/writes.py` | 2 |
| 350 | 418 | 16.3% | `app/fastapi_routes/domains/conversation/helpers.py` | 1 |
| 350 | 418 | 16.3% | `app/fastapi_routes/xcagi_compat_chat_helpers.py` | 1 |
| 348 | 383 | 9.1% | `app/application/aibiz_web_terminal_service.py` | 1 |
| 339 | 339 | 0.0% | `app/application/excel_template_http_app_service.py` | 1 |
| 337 | 337 | 0.0% | `app/services/wechat_contact_service.py` | 2 |
| 331 | 614 | 46.1% | `app/fastapi_routes/xcmax_admin.py` | 1 |
| 327 | 442 | 26.0% | `app/fastapi_routes/mobile_api_extensions.py` | 1 |
| 317 | 317 | 0.0% | `app/fastapi_routes/domains/static/routes.py` | 1 |
| 312 | 355 | 12.1% | `app/infrastructure/persistence/product_repository_impl.py` | 2 |

## 前端缺口分区（按未覆盖行降序）

| 未覆盖 | 行 | 覆盖% | 区域 | Phase |
|-------:|----:|------:|------|-------|
| 11,084 | 13,281 | 16.5% | `src/components` | 2 |
| 9,739 | 11,076 | 12.1% | `src/composables` | 1 |
| 5,392 | 6,456 | 16.5% | `src/views` | 2 |
| 3,958 | 6,392 | 38.1% | `src/utils` | 3 |
| 2,885 | 3,977 | 27.5% | `src/stores` | 1 |
| 2,124 | 2,507 | 15.3% | `src/api` | 1 |
| 845 | 845 | 0.0% | `src/domain` | 2/3 |
| 726 | 1,392 | 47.8% | `src/tutorial` | 3 |
| 682 | 1,744 | 60.9% | `src/constants` | 3 |
| 429 | 820 | 47.7% | `src/router` | 3 |

## 前端 Top-15 单文件（按未覆盖行）

| 未覆盖 | 行 | 覆盖% | 文件 | Phase |
|-------:|----:|------:|------|-------|
| 1,007 | 1,341 | 24.9% | `src/composables/useChatOrchestration.ts` | 1 |
| 999 | 1,138 | 12.2% | `src/composables/useChatWorkflowPanel.ts` | 1 |
| 956 | 956 | 0.0% | `src/views/ModStore.vue` | 2 |
| 938 | 938 | 0.0% | `src/composables/useKittenAnalyzer.ts` | 1 |
| 768 | 1,263 | 39.2% | `src/components/TopAssistantFloat.vue` | 2 |
| 597 | 1,359 | 56.1% | `src/views/SettingsView.vue` | 2 |
| 578 | 578 | 0.0% | `src/components/aiopen/AIOpenPanel.vue` | 2 |
| 546 | 546 | 0.0% | `src/views/ProductOnboardingView.vue` | 2 |
| 514 | 514 | 0.0% | `src/components/workflow/StitchStage.vue` | 2 |
| 446 | 853 | 47.7% | `src/stores/mods.ts` | 1 |
| 440 | 440 | 0.0% | `src/views/ProductsView.vue` | 2 |
| 414 | 414 | 0.0% | `src/components/template/LabelVisualEditor.vue` | 2 |
| 397 | 397 | 0.0% | `src/components/kitten/KittenAnalyzerView.vue` | 2 |
| 396 | 445 | 11.0% | `src/utils/tts.ts` | 3 |
| 394 | 394 | 0.0% | `src/views/ImMessengerView.vue` | 2 |

## 推进策略

- 按 Phase 1→4 前后端并行（详见 `.cursor/plans/coverage-to-90`）。
- 每批闭环：写测试 → 全绿 → `coverage_ratchet.py --check` → `--bump` → commit。
- 优先攻零覆盖（后端 184 / 前端 255）与大文件，单位投入收益最高。
- 复测命令：
  - 后端：`XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 .venv/bin/python -m pytest tests/ --cov --cov-branch --cov-fail-under=0 --cov-report=json:coverage.json -q`
  - 前端：`cd frontend && CI=true npm run test:coverage`
