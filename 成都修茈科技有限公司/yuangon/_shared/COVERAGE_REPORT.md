# Yuangon 覆盖率审计报告（Phase 1）

> 生成时间（UTC）：`2026-05-08T14:26:37.102357+00:00`  
> 仓库根：`E:\成都修茈科技有限公司`  
> 员工数量（employee.yaml）：**26**  

> **说明**：扫描会跳过 `.git`、`node_modules`、`.venv`、`dist` 等与 OWNERSHIP §五 / 运维约定一致的目录；这些路径下的文件不计入「扫描文件数」，也不参与盲区计算。

## 总览统计

| 指标 | 值 |
|------|-----|
| 扫描文件数 | 2467 |
| 显式忽略（OWNERSHIP §五）文件数 | 123 |
| 非忽略文件中「无人可写」数量 | 0 |
| 非忽略文件总数 | 2344 |
| 覆盖率（非忽略） | **100.0%** |
| 多员工同时可写（潜在冲突） | 1218 |
| 配置自相矛盾（同员工 scope∩forbidden）采样数 | 751 |
| scope×forbidden 交叉（跨员工）采样行数 | 2009 |

## §1 盲区清单（无人可写，且非显式忽略）

*未发现盲区。*

## §2 权限冲突清单（≥2 名员工同时可写）

> 共 **1218** 条；以下为前 500 条。

| 相对路径 | 可写员工 |
|----------|----------|
| `.cursor_admin_token.txt` | `retention-officer`, `security-secrets-guard` |
| `.cursor_case1_log.txt` | `log-monitor-incident`, `retention-officer` |
| `.cursor_case2_log.txt` | `log-monitor-incident`, `retention-officer` |
| `.cursor_case3_log.txt` | `log-monitor-incident`, `retention-officer` |
| `.cursor_smoke_log.txt` | `log-monitor-incident`, `retention-officer` |
| `.cursor_stage_a_log.txt` | `log-monitor-incident`, `retention-officer` |
| `ESkill.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `excel-to-ai.html` | `flask-entry-keeper`, `site-content-editor` |
| `requirements.txt` | `security-secrets-guard`, `flask-entry-keeper` |
| `setup-alipay.sh` | `payment-billing-reconciler`, `deploy-release-officer` |
| `xiu-ci.com_nginx.zip` | `nginx-config-engineer`, `retention-officer` |
| `成都修茈科技有限公司.code-workspace` | `doc-knowledge-curator`, `push-update-context-officer` |
| `腾讯云Pages部署指南.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `.cursor/contracts/error-code-map.yaml` | `doc-knowledge-curator`, `test-qa-runner`, `log-monitor-incident` |
| `.github/workflows/ci-auto-merge.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-backend-python.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-doc-health.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-market.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-marketing-site.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-payment-java.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-runtime-artifacts-guard.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/ci-vibe-coding.yml` | `test-qa-runner`, `push-update-context-officer` |
| `.github/workflows/README.md` | `doc-knowledge-curator`, `push-update-context-officer` |
| `alipay_package/model_payment_alipay.py` | `payment-billing-reconciler`, `retention-officer`, `security-secrets-guard` |
| `alipay_package/model_payment_compat.py` | `payment-billing-reconciler`, `retention-officer`, `security-secrets-guard` |
| `alipay_package/model_payment_order_store.py` | `payment-billing-reconciler`, `retention-officer`, `security-secrets-guard` |
| `assets/intro-video.mp4` | `retention-officer`, `site-content-editor` |
| `assets/test_image.jpg` | `retention-officer`, `site-content-editor` |
| `coverage/base.css` | `log-monitor-incident`, `retention-officer` |
| `coverage/block-navigation.js` | `log-monitor-incident`, `retention-officer` |
| `coverage/coverage-summary.json` | `log-monitor-incident`, `retention-officer` |
| `coverage/favicon.png` | `log-monitor-incident`, `retention-officer` |
| `coverage/index.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/prettify.css` | `log-monitor-incident`, `retention-officer` |
| `coverage/prettify.js` | `log-monitor-incident`, `retention-officer` |
| `coverage/sort-arrow-sprite.png` | `log-monitor-incident`, `retention-officer` |
| `coverage/sorter.js` | `log-monitor-incident`, `retention-officer` |
| `coverage/src/api.ts.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/App.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/index.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/router/index.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/router/index.ts.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/stores/auth.ts.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/stores/index.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/stores/wallet.ts.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/AdminDatabaseView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/AdminView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/AiStoreView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/CatalogDetailView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/DbViewerView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/HomeView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/index.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/LoginByEmailView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/LoginView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/ModAuthoringView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/MyStoreView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/OrderDetailView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/PaymentCheckoutView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/PaymentPlansView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/RegisterView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/RepositoryView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/WalletView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `coverage/src/views/WorkbenchView.vue.html` | `log-monitor-incident`, `retention-officer`, `site-content-editor` |
| `deploy/nginx/SECURITY-AUDIT-HANDOFF.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `docker/mod-sandbox/README.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `docs/deploy/nginx-paths.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `docs/deploy/nginx-snippets-index.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `docs/migration/new-repo-templates/modstore-backend/.github/workflows/ci.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/modstore-backend/.github/workflows/deploy.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/modstore-frontend/.github/workflows/ci.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/modstore-frontend/.github/workflows/deploy.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/modstore-payment-java/.github/workflows/ci.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/modstore-payment-java/.github/workflows/deploy.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/vibe-coding/.github/workflows/ci.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/migration/new-repo-templates/xiuci-marketing-site/.github/workflows/ci.yml` | `doc-knowledge-curator`, `push-update-context-officer` |
| `docs/modstore/ddd.md` | `employee-pack-curator`, `doc-knowledge-curator` |
| `docs/planning/腾讯云Pages部署指南.md` | `doc-knowledge-curator`, `deploy-release-officer` |
| `eskill-prototype/.gitignore` | `mods-and-eskill-curator`, `push-update-context-officer` |
| `eskill-prototype/CHANGELOG.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/PLUGIN_GUIDE.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/README.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/.github/workflows/ci.yml` | `mods-and-eskill-curator`, `push-update-context-officer` |
| `eskill-prototype/collaborative-mod-review/README.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/docs/CODE_LAYER_SELF_HEALING.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/docs/DUAL_LAYER_ARCHITECTURE.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/docs/MODSTORE_ESKILL_UPGRADE.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/docs/VIBE_CODING.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `eskill-prototype/src/eskill/adapter.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/analysis.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/architecture.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/async_runtime.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/audit.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/config.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/crystal.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/demo.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/diagnostics.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/discovery.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/dual_layer_bridge.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/employee_layer.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/errors.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/ESKILL_INSTRUCTION.md` | `mods-and-eskill-curator`, `doc-knowledge-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/health.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/llm_adapter.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/llm_skill_author.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/logging.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/market.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/memory.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/metrics.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/models.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/patch_planner.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/pipeline.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/policy.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/resilience.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/rollout.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/runtime.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/sandbox.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/skill_creator.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/skill_node_layer.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/sqlite_store.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/static_executor.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/store.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/strategy.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/testing.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/wrapper.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/__init__.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/diagnostics.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/hybrid.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/models.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/patch_generator.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/runtime.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/sandbox.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/store.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/validator.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/code/__init__.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/audit.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/cli.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/code_factory.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/config_factory.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/facade.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/workflow_engine.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/workflow_factory.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/workflow_models.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/__init__.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/__main__.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/nl/llm.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/nl/prompts.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `eskill-prototype/src/eskill/vibe_coding/nl/__init__.py` | `mods-and-eskill-curator`, `site-content-editor` |
| `marketing-site/package-lock.json` | `marketing-site-builder`, `site-content-editor` |
| `marketing-site/package.json` | `marketing-site-builder`, `site-content-editor` |
| `marketing-site/README.md` | `doc-knowledge-curator`, `marketing-site-builder` |
| `marketing-site/data/news.json` | `marketing-site-builder`, `site-content-editor` |
| `marketing-site/scripts/build.mjs` | `deploy-release-officer`, `marketing-site-builder` |
| `mianshi/README.md` | `intake-dispatcher`, `doc-knowledge-curator` |
| `mods/industry-solutions/README.md` | `mods-and-eskill-curator`, `doc-knowledge-curator` |
| `MODstore_deploy/pyproject.toml` | `daily-orchestrator`, `doc-knowledge-curator` |
| `MODstore_deploy/chaos/README.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/observability.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/OPS_MONITORING.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/routing-table.md` | `task-router-officer`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/sre-operating-model.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/yuangon-process-loop.md` | `intake-dispatcher`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/catalog.item_published.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/catalog.package_published.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/employee.execution_completed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/employee.pack_registered.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/invoice.created.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/llm.quota_consumed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/payment.paid.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/README.md` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/refund.approved.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/refund.failed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/refund.rejected.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/subscription.renewal_failed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/subscription.renewed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/wallet.balance_changed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/workflow.event_trigger.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/workflow.execution_completed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/workflow.execution_failed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/events/workflow.sandbox_completed.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/openapi/modstore-server.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/orchestration/ci_pipeline.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/orchestration/deploy_topology.schema.json` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/contracts/orchestration/README.md` | `modstore-backend-api`, `doc-knowledge-curator` |
| `MODstore_deploy/docs/runbooks/chaos-game-day.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/disaster-recovery.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/file-retention.md` | `doc-knowledge-curator`, `retention-officer` |
| `MODstore_deploy/docs/runbooks/incident-response.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/README.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-api-restart-dryrun.log` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-payment-restart-dryrun.log` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-redis-stop-dryrun.log` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/2026-05-04/dr-restore-postgres-dryrun.log` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/docs/runbooks/exercises/2026-05-04/EXERCISE.md` | `doc-knowledge-curator`, `log-monitor-incident` |
| `MODstore_deploy/java_payment_service/DATABASE_MIGRATION.md` | `payment-billing-reconciler`, `doc-knowledge-curator` |
| `MODstore_deploy/java_payment_service/DESIGN_DOC.md` | `payment-billing-reconciler`, `doc-knowledge-curator` |
| `MODstore_deploy/java_payment_service/PERFORMANCE_TEST.md` | `payment-billing-reconciler`, `doc-knowledge-curator` |
| `MODstore_deploy/java_payment_service/README.md` | `payment-billing-reconciler`, `doc-knowledge-curator` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-sessions.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco.csv` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco.xml` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/Application.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/Application.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/AlipayConfig.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/AlipayConfig.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/OpenApiConfig.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/OpenApiConfig.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/SecurityConfig.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/SecurityConfig.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AlipayController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AlipayController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AuthController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AuthController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController$1.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/RefundController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/RefundController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WalletController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WalletController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController$ReplayWebhookRequest.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WechatPayController.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WechatPayController.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/EventContracts.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/EventContracts.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/PendingOrderCleanupScheduler.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/PendingOrderCleanupScheduler.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/AccountExperienceLedger.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/AccountExperienceLedger.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/CatalogItem.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/CatalogItem.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Entitlement.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Entitlement.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Order.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Order.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/PlanTemplate.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/PlanTemplate.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Purchase.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Purchase.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Quota.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Quota.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Refund.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Refund.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Transaction.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Transaction.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/User.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/User.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/UserPlan.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/UserPlan.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Wallet.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Wallet.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/WalletHold.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/WalletHold.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/AuthenticatedUser.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/AuthenticatedUser.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/JwtAuthenticationFilter.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/JwtAuthenticationFilter.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AccountLevelService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AccountLevelService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AlipayService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AlipayService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/CurrentUserService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/CurrentUserService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService$1.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/OrderService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/OrderService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/RefundService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/RefundService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/SecurityService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/SecurityService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WalletService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WalletService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WebhookDispatcher.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WebhookDispatcher.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService$1.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService$2.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/index.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/index.source.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder$Threshold.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/MoneyUtils.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/MoneyUtils.java.html` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchfc.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchnc.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchpc.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/bundle.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/class.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/down.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/greenbar.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/group.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/method.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/package.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/prettify.css` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/prettify.js` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/redbar.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/report.css` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/report.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/session.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/sort.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/sort.js` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/source.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/up.gif` | `payment-billing-reconciler`, `retention-officer` |
| `MODstore_deploy/market/vite.config.ts` | `market-frontend-dev`, `test-qa-runner` |
| `MODstore_deploy/market/coverage/base.css` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/block-navigation.js` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/coverage-summary.json` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/favicon.png` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/prettify.css` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/prettify.js` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/sort-arrow-sprite.png` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/sorter.js` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/api.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/App.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/authPaths.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/byokEnvImport.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/employeeConfigV2.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/employeePackClientExport.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/i18n.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/llmIconUrls.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/llmModels.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/llmProviderHealth.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/realtimeClient.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/refundStatus.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/workflowMermaid.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/workflowSandboxPresets.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/analyticsApi.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/authApi.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/catalogApi.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/index.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/openApiConnectorsApi.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/application/paymentApi.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/customer-service/CustomerServiceActionCard.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/customer-service/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/AgentMarket.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/BalanceBadge.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/ChatSidebar.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/ConsumptionTierControl.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/EmployeePanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/MediaGenPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/MessageActions.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/MessageBody.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/OpenApiConnectorsPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/PersonalSettings.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/RepositoryPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/SkillToolbar.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/VoicePhoneModal.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/components/workbench/WorkflowPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/composables/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/composables/useEmployeePublishFlow.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/composables/useEmployeeWorkbenchState.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/accountLevel.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/analytics/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/analytics/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/auth/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/auth/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/catalog/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/catalog/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/employee/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/employee/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/llm/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/llm/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/payment/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/payment/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/wallet/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/wallet/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/workflow/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/domain/workflow/types.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/infrastructure/http/client.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/infrastructure/http/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/infrastructure/storage/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/infrastructure/storage/tokenStore.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/locales/en-US.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/locales/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/locales/zh-CN.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/router/guards.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/router/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/router/index.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/stores/auth.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/stores/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/stores/notifications.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/stores/wallet.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/agentBots.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/chatSkills.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/conversationStore.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/directAttachments.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/lightMarkdown.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/llmBillingRefresh.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/llmStream.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/notifyParentModsDeployed.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/utils/personalSettings.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AccountSettingsView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AdminCustomerServiceView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AdminDatabaseView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AdminView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AiStoreView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/AnalyticsView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/CatalogDetailView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/CustomerServiceView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/DbViewerView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/EmployeeAuthoringView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/ForgotPasswordView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/HomeView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/KnowledgeManagerView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/LoginByEmailView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/LoginView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/ModAuthoringView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/MyEmployeesChatView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/MyStoreView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/NotFoundView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/NotificationCenter.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/OrderDetailView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/OrderListView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/PaymentCheckoutView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/PaymentPlansView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/RefundApplyView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/RegisterView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/RepositoryView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/ScriptWorkflowComposerView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/ScriptWorkflowDetailView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/ScriptWorkflowListView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/UnifiedWorkbenchView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WalletLayoutView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WalletRechargeView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WalletView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WorkbenchHomeView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WorkbenchView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/WorkflowView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/developer/DeveloperDocsPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/developer/DeveloperPortalView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/developer/DeveloperTokensPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/developer/DeveloperWebhooksPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/developer/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/EmployeeBlockBuilder.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/SkillSelector.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step0TemplateSelect.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step1Identity.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step2Perception.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step3Memory.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step4Cognition.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step5Actions.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step6Collaboration.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step7Management.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step8Testing.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/Step9Listing.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/employee-steps/StepNavigation.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/templates/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/templates/TemplateDetailView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/templates/TemplatesView.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/WorkflowFlowEditor.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/WorkflowFlowEditorPage.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/composables/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/composables/useAutoLayout.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/composables/useNodeRegistry.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/composables/useWorkflowGraph.ts.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/nodes/GenericNode.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/nodes/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/panels/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/panels/NodeLibraryPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/panels/PropertiesPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/panels/ToolbarPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/coverage/src/views/workflow/v2/panels/VersionsPanel.vue.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/playwright-report/index.html` | `log-monitor-incident`, `retention-officer` |
| `MODstore_deploy/market/src/api.ts` | `market-frontend-dev`, `daily-orchestrator` |
| `MODstore_deploy/market/src/App.vue` | `market-frontend-dev`, `daily-orchestrator` |
| `MODstore_deploy/market/src/application/paymentApi.test.ts` | `daily-orchestrator`, `test-qa-runner` |

## §3 OWNERSHIP.md 一致性检查（轻量）

本节**不**解析 Markdown 表格单元格；仅做两类信号：(1) 根目录名称是否作为子串出现在 [yuangon/_shared/OWNERSHIP.md](OWNERSHIP.md) 正文中；(2) 各根级分区下文件覆盖计数。

### 根级名称未在 OWNERSHIP.md 正文中出现（可能文档未登记）

- `.cursor_case1_log.txt`
- `.cursor_case2_log.txt`
- `.cursor_case3_log.txt`
- `.cursor_paths_check.txt`
- `.cursor_paths_check2.txt`
- `.cursor_smoke_log.txt`
- `.cursor_stage_a_log.txt`
- `3月31日 (5)(1).mp4`
- `3月31日 (5)(2).mp4`
- `AI智能体建设需求报告.docx`
- `LLM调用制作Mod员工工作流全流程-修复方案.md`
- `LLM调用制作Mod员工工作流全流程.md`
- `OPC_填写指南.md`
- `__tmp_emp_brief.json`
- `__tmp_emp_exec.json`
- `baidu_verify_codeva-hVYlSoeYiP.html`
- `case-edu.html`
- `case-manufacture.html`
- `case-park.html`
- `nginx-default.conf`
- `nginx-xiu-ci-root.conf`
- `nginx-xiu-ci.conf`
- `playwright.global-setup.ts`
- `tsconfig.json`
- `tsconfig.node.json`
- `tsconfig.strict-baseline.json`
- `tsconfig.strict.json`
- `修复方案-评审报告.md`
- `腾讯云Pages部署指南.md`
- `风格`

### 根级分区文件统计

| 根级 | 文件数 | 已覆盖 | 显式忽略 | 盲区 |
|------|--------|--------|----------|------|
| `.cursor` | 4 | 4 | 0 | 0 |
| `.cursor_admin_token.txt` | 1 | 1 | 0 | 0 |
| `.cursor_case1_log.txt` | 1 | 1 | 0 | 0 |
| `.cursor_case2_log.txt` | 1 | 1 | 0 | 0 |
| `.cursor_case3_log.txt` | 1 | 1 | 0 | 0 |
| `.cursor_inspect_purge.py` | 1 | 0 | 1 | 0 |
| `.cursor_paths_check.txt` | 1 | 1 | 0 | 0 |
| `.cursor_paths_check2.txt` | 1 | 1 | 0 | 0 |
| `.cursor_smoke_log.txt` | 1 | 1 | 0 | 0 |
| `.cursor_stage_a_log.txt` | 1 | 1 | 0 | 0 |
| `.github` | 17 | 17 | 0 | 0 |
| `.gitignore` | 1 | 1 | 0 | 0 |
| `.gitleaks.toml` | 1 | 1 | 0 | 0 |
| `.pre-commit-config.yaml` | 1 | 1 | 0 | 0 |
| `.prettierignore` | 1 | 1 | 0 | 0 |
| `.prettierrc` | 1 | 1 | 0 | 0 |
| `.trae` | 9 | 9 | 0 | 0 |
| `3月31日 (5)(1).mp4` | 1 | 1 | 0 | 0 |
| `3月31日 (5)(2).mp4` | 1 | 1 | 0 | 0 |
| `AI智能体建设需求报告.docx` | 1 | 1 | 0 | 0 |
| `BingSiteAuth.xml` | 1 | 1 | 0 | 0 |
| `ESkill.md` | 1 | 1 | 0 | 0 |
| `LLM调用制作Mod员工工作流全流程-修复方案.md` | 1 | 1 | 0 | 0 |
| `LLM调用制作Mod员工工作流全流程.md` | 1 | 1 | 0 | 0 |
| `MODstore_deploy` | 1632 | 1512 | 120 | 0 |
| `MODstore_deploy.zip` | 1 | 1 | 0 | 0 |
| `OPC_填写指南.md` | 1 | 1 | 0 | 0 |
| `README.md` | 1 | 1 | 0 | 0 |
| `__tmp_emp_brief.json` | 1 | 1 | 0 | 0 |
| `__tmp_emp_exec.json` | 1 | 1 | 0 | 0 |
| `_local_secrets` | 6 | 6 | 0 | 0 |
| `_nginx_extract` | 4 | 4 | 0 | 0 |
| `about.html` | 1 | 1 | 0 | 0 |
| `activities.json` | 1 | 1 | 0 | 0 |
| `alipay_package` | 3 | 3 | 0 | 0 |
| `app.py` | 1 | 1 | 0 | 0 |
| `assets` | 6 | 6 | 0 | 0 |
| `baidu_urls.txt` | 1 | 1 | 0 | 0 |
| `baidu_verify_codeva-hVYlSoeYiP.html` | 1 | 1 | 0 | 0 |
| `case-edu.html` | 1 | 1 | 0 | 0 |
| `case-manufacture.html` | 1 | 1 | 0 | 0 |
| `case-park.html` | 1 | 1 | 0 | 0 |
| `cases.html` | 1 | 1 | 0 | 0 |
| `contact.html` | 1 | 1 | 0 | 0 |
| `coverage` | 35 | 35 | 0 | 0 |
| `deploy` | 12 | 12 | 0 | 0 |
| `docker` | 5 | 5 | 0 | 0 |
| `docs` | 41 | 41 | 0 | 0 |
| `env.d.ts` | 1 | 1 | 0 | 0 |
| `eskill-prototype` | 110 | 110 | 0 | 0 |
| `eslint.config.js` | 1 | 1 | 0 | 0 |
| `excel-to-ai.html` | 1 | 1 | 0 | 0 |
| `honors.html` | 1 | 1 | 0 | 0 |
| `index.html` | 1 | 1 | 0 | 0 |
| `main.js` | 1 | 1 | 0 | 0 |
| `marketing-site` | 8 | 8 | 0 | 0 |
| `mianshi` | 4 | 4 | 0 | 0 |
| `mods` | 7 | 7 | 0 | 0 |
| `new` | 29 | 29 | 0 | 0 |
| `news.html` | 1 | 1 | 0 | 0 |
| `news.json` | 1 | 1 | 0 | 0 |
| `nginx-default.conf` | 1 | 1 | 0 | 0 |
| `nginx-xiu-ci-root.conf` | 1 | 1 | 0 | 0 |
| `nginx-xiu-ci.conf` | 1 | 1 | 0 | 0 |
| `package-lock.json` | 1 | 1 | 0 | 0 |
| `package.json` | 1 | 1 | 0 | 0 |
| `playwright-report` | 1 | 1 | 0 | 0 |
| `playwright.config.ts` | 1 | 1 | 0 | 0 |
| `playwright.global-setup.ts` | 1 | 1 | 0 | 0 |
| `project-doc-generator.xcemp` | 1 | 1 | 0 | 0 |
| `public` | 1 | 1 | 0 | 0 |
| `py-doc-generator.xcemp` | 1 | 1 | 0 | 0 |
| `requirements.txt` | 1 | 1 | 0 | 0 |
| `robots.txt` | 1 | 1 | 0 | 0 |
| `scripts` | 15 | 15 | 0 | 0 |
| `services.html` | 1 | 1 | 0 | 0 |
| `setup-alipay.sh` | 1 | 1 | 0 | 0 |
| `site` | 11 | 11 | 0 | 0 |
| `sitemap.xml` | 1 | 1 | 0 | 0 |
| `solutions.html` | 1 | 1 | 0 | 0 |
| `src` | 29 | 29 | 0 | 0 |
| `stop_ports.py` | 1 | 1 | 0 | 0 |
| `styles.css` | 1 | 1 | 0 | 0 |
| `taiyangniao-pro` | 15 | 15 | 0 | 0 |
| `test-results` | 1 | 1 | 0 | 0 |
| `test_image.jpg` | 1 | 1 | 0 | 0 |
| `tsconfig.json` | 1 | 1 | 0 | 0 |
| `tsconfig.node.json` | 1 | 1 | 0 | 0 |
| `tsconfig.strict-baseline.json` | 1 | 1 | 0 | 0 |
| `tsconfig.strict.json` | 1 | 1 | 0 | 0 |
| `uploads` | 3 | 3 | 0 | 0 |
| `var` | 2 | 0 | 2 | 0 |
| `vibe-coding` | 207 | 207 | 0 | 0 |
| `vite.config.ts` | 1 | 1 | 0 | 0 |
| `xiu-ci.com_nginx.zip` | 1 | 1 | 0 | 0 |
| `yuangon` | 178 | 178 | 0 | 0 |
| `修复方案-评审报告.md` | 1 | 1 | 0 | 0 |
| `成都修茈科技有限公司.code-workspace` | 1 | 1 | 0 | 0 |
| `腾讯云Pages部署指南.md` | 1 | 1 | 0 | 0 |
| `风格` | 1 | 1 | 0 | 0 |

## §4 待决议项（与需求文档 / 现状张力）

- **`site/**`**：`retention-officer` 将整树纳入清理范围；`site-content-editor` 职责集中在根级营销页。 若 `site/*.html` 为活跃站点，需调整 scope 或设专职维护员。
- **`marketing-site/**`**：需求文档标记为盲区；请以本报告 §1 实测为准。
- **多写者**：§2 中路径需核对业务是否接受协作；若否，请收紧某一方的 `scope_globs` 并补充 `forbidden_globs`。

## 附录 A：scope ∩ forbidden（同员工）采样

- `docs/adr/0003-artifacts-bundles-employee-packs.md` → doc-knowledge-curator
- `docs/modstore/员工制作增强设计方案.md` → doc-knowledge-curator
- `MODstore_deploy/docs/employee_publish_wizard.md` → doc-knowledge-curator
- `MODstore_deploy/docs/fhd-employee-composition.md` → doc-knowledge-curator
- `MODstore_deploy/docs/nginx-https-example.conf` → nginx-config-engineer
- `MODstore_deploy/docs/adr/0003-artifacts-bundles-employee-packs.md` → doc-knowledge-curator
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/Application.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/config/AlipayConfig.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/config/OpenApiConfig.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/config/ProductionSecretsValidator.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/config/SecurityConfig.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/AlipayController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/AuthController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/PaymentController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/RefundController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/WalletController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/WebhookAdminController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/WebhookController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/controller/WechatPayController.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/event/EventContracts.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/job/PendingOrderCleanupScheduler.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/AccountExperienceLedger.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/CatalogItem.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Entitlement.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Order.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/PlanTemplate.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Purchase.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Quota.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Refund.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Transaction.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/User.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/UserPlan.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Wallet.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/WalletHold.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/AccountExperienceLedgerRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/CatalogItemRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/EntitlementRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/OrderRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/PlanTemplateRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/PurchaseRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/QuotaRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/RefundRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/TransactionRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/UserPlanRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/UserRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/WalletHoldRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/WalletRepository.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/security/AuthenticatedUser.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/security/JwtAuthenticationFilter.java` → site-content-editor
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/security/JwtRoleAuthorities.java` → site-content-editor

## 附录 B：显式忽略 glob 列表（来自 OWNERSHIP §五）

- `**/__pycache__/**`
- `**/.pytest_cache/**`
- `**/.mypy_cache/**`
- `**/.ruff_cache/**`
- `**/node_modules/**`
- `**/.venv/**`
- `**/.git/**`
- `**/dist/**`
- `**/modstore.egg-info/**`
- `**/*.pyc`
- `**/*.pyo`
- `.coverage`
- `MODstore_deploy/library/**`
- `MODstore_deploy/modstore_server/catalog_data/**`
- `MODstore_deploy/modstore_server/*.db`
- `MODstore_deploy/var/**`
- `var/**`
- `MODstore_deploy/market/market-dist-upload.tgz`
- `MODstore_deploy/market/tmp_tsc.log`
- `.cursor_inspect_purge.py`
