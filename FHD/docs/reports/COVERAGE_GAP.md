# 覆盖率差距报告（全量口径 · 2026-06-14 基线）

> 由 `scripts/dev/coverage_ratchet.py` 配套生成；数据源为 `.venv` CI 等价依赖（不含 ml extra）实测。
> 唯一可复现 SSOT，禁止用富依赖环境数字（历史 58/60.63/66.33）对外混报。

## 基线总览

| 维度 | 后端（pytest，source=[app]+branch） | 前端（vitest，src/\*\*） |
|------|-----------------------------------|--------------------------|
| 行覆盖率 | **36.35%**（27,253 / 74,982） | **21.52%**（10,817 / 50,264） |
| 分支覆盖率 | **18.42%**（4,055 / 22,014） | **49.07%**（1,164 / 2,372） |
| 函数覆盖率 | coverage.py 不原生统计（前端经 v8 统计） | **26.08%**（495 / 1,898） |
| 语句数 | 74,982 | 50,264 |
| 被测文件 | 906（零覆盖 184） | 472（零覆盖 255） |
| 当前 floor | 行 35 / 分支 17 | lines20 / branches48 / functions25 / statements20 |
| 目标 | 行 ≥90 / 分支 ≥85 | lines ≥80 / branches ≥75 / functions ≥80 |
| 测试运行 | 1789 passed / 98 skipped / 0 failed / 110.86s | 209 passed / 4 skipped / 0 failed / ~16s |

> 注：开启 branch 后 coverage 的合并指标为 32.28%；本表行/分支分别由原始计数算出（铁律6）。

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
