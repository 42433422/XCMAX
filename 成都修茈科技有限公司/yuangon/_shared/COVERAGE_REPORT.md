# Yuangon 覆盖率与编制契约审计报告

> 生成时间（UTC）：`2026-06-19T17:07:41.178168+00:00`  
> 仓库根：`/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司`  
> 员工数量：**52**

## 总览

| 指标 | 值 |
|---|---:|
| 扫描文件数 | 3035 |
| 忽略构建/缓存文件数 | 35829 |
| 有写入责任人 | 3035 |
| 无写入责任人 | 0 |
| 覆盖率 | 100.00% |
| 多员工可写 | 1445 |
| 同员工 scope/forbidden 冲突 | 47 |
| 编制契约错误 | 0 |
| 依赖循环节点 | 0 |

## 编制契约错误

- 无

## 无写入责任人（前 200 项）

- 无

## 多员工可写（前 200 项）

- `.github/workflows/README.md`：doc-knowledge-curator, push-update-context-officer
- `.github/workflows/ci-backend-python.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-market.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-marketing-site.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-payment-java.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-root-frontend.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-runtime-artifacts-guard.yml`：test-qa-runner, push-update-context-officer
- `.github/workflows/ci-vibe-coding.yml`：test-qa-runner, push-update-context-officer
- `ESkill.md`：mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-label-print/README.md`：mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-real-phone/README.md`：mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/README.md`：delivery-receipt-officer, mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/backend/__init__.py`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/backend/blueprints.py`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/backend/employees/__init__.py`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/backend/employees/receipt_confirm.py`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/frontend/routes.js`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-receipt-confirm/manifest.json`：delivery-receipt-officer, mods-and-eskill-curator
- `FHD/mods/xcagi-workflow-employee-shipment-mgmt/README.md`：mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-wechat-msg/README.md`：mods-and-eskill-curator, doc-knowledge-curator
- `FHD/mods/xcagi-workflow-employee-wechat-phone/README.md`：mods-and-eskill-curator, doc-knowledge-curator
- `MODstore_deploy/.github/workflows/README.md`：doc-knowledge-curator, push-update-context-officer
- `MODstore_deploy/.github/workflows/ci-backend-python.yml`：test-qa-runner, push-update-context-officer
- `MODstore_deploy/chaos/README.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/desktop-shell/README.md`：doc-knowledge-curator, deploy-release-officer
- `MODstore_deploy/docs/OPS_MONITORING.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/PAYMENT_CONTRACT.md`：java-payment-bridge-officer, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/README.md`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/catalog.item_published.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/catalog.package_published.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/employee.execution_completed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/employee.pack_registered.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/invoice.created.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/llm.quota_consumed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/payment.paid.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/refund.approved.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/refund.failed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/refund.rejected.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/subscription.renewal_failed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/subscription.renewed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/wallet.balance_changed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/workflow.event_trigger.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/workflow.execution_completed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/workflow.execution_failed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/events/workflow.sandbox_completed.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/openapi/modstore-server.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/orchestration/README.md`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/orchestration/ci_pipeline.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/contracts/orchestration/deploy_topology.schema.json`：modstore-backend-api, doc-knowledge-curator
- `MODstore_deploy/docs/nginx-https-example.conf`：doc-knowledge-curator, nginx-config-engineer
- `MODstore_deploy/docs/observability.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/routing-table.md`：task-router-officer, doc-knowledge-curator
- `MODstore_deploy/docs/runbooks/chaos-game-day.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/disaster-recovery.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/2026-05-04/EXERCISE.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-api-restart-dryrun.log`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-payment-restart-dryrun.log`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/2026-05-04/chaos-redis-stop-dryrun.log`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/2026-05-04/dr-restore-postgres-dryrun.log`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/exercises/README.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/runbooks/file-retention.md`：doc-knowledge-curator, retention-officer
- `MODstore_deploy/docs/runbooks/incident-response.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/sre-operating-model.md`：doc-knowledge-curator, log-monitor-incident
- `MODstore_deploy/docs/yuangon-process-loop.md`：intake-dispatcher, doc-knowledge-curator
- `MODstore_deploy/java_payment_service/DATABASE_MIGRATION.md`：payment-billing-reconciler, doc-knowledge-curator
- `MODstore_deploy/java_payment_service/DESIGN_DOC.md`：payment-billing-reconciler, doc-knowledge-curator
- `MODstore_deploy/java_payment_service/PERFORMANCE_TEST.md`：payment-billing-reconciler, doc-knowledge-curator
- `MODstore_deploy/java_payment_service/README.md`：payment-billing-reconciler, doc-knowledge-curator
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/model/Order.java`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/repository/OrderRepository.java`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/src/main/java/com/modstore/service/OrderService.java`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/src/test/java/com/modstore/service/OrderServiceTest.java`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/target/classes/com/modstore/model/Order.class`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/target/classes/com/modstore/repository/OrderRepository.class`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/target/classes/com/modstore/service/OrderService.class`：payment-billing-reconciler, ecosystem-revenue-share-reconciler
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/AlipayConfig.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/AlipayConfig.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/OpenApiConfig.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/OpenApiConfig.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/SecurityConfig.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/SecurityConfig.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.config/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AlipayController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AlipayController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AuthController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/AuthController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController$1.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/PaymentController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/RefundController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/RefundController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WalletController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WalletController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController$ReplayWebhookRequest.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookAdminController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WebhookController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WechatPayController.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/WechatPayController.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.controller/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/EventContracts.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/EventContracts.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.event/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/PendingOrderCleanupScheduler.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/PendingOrderCleanupScheduler.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.job/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/AccountExperienceLedger.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/AccountExperienceLedger.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/CatalogItem.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/CatalogItem.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Entitlement.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Entitlement.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Order.html`：payment-billing-reconciler, ecosystem-revenue-share-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Order.java.html`：payment-billing-reconciler, ecosystem-revenue-share-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/PlanTemplate.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/PlanTemplate.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Purchase.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Purchase.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Quota.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Quota.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Refund.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Refund.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Transaction.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Transaction.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/User.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/User.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/UserPlan.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/UserPlan.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Wallet.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/Wallet.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/WalletHold.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/WalletHold.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.model/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/AuthenticatedUser.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/AuthenticatedUser.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/JwtAuthenticationFilter.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/JwtAuthenticationFilter.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.security/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AccountLevelService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AccountLevelService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AlipayService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/AlipayService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/CurrentUserService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/CurrentUserService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService$1.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/EntitlementService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/OrderService.html`：payment-billing-reconciler, ecosystem-revenue-share-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/OrderService.java.html`：payment-billing-reconciler, ecosystem-revenue-share-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/RefundService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/RefundService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/SecurityService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/SecurityService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WalletService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WalletService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WebhookDispatcher.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WebhookDispatcher.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService$1.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService$2.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/WechatPayService.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.service/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder$Threshold.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/LevelProfileBuilder.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/MoneyUtils.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/MoneyUtils.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore.util/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/Application.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/Application.java.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/com.modstore/index.source.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/index.html`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchfc.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchnc.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/branchpc.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/bundle.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/class.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/down.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/greenbar.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/group.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/method.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/package.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/prettify.css`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/prettify.js`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/redbar.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/report.css`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/report.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/session.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/sort.gif`：payment-billing-reconciler, retention-officer
- `MODstore_deploy/java_payment_service/target/site/jacoco/jacoco-resources/sort.js`：payment-billing-reconciler, retention-officer

## 同员工 scope/forbidden 冲突（前 200 项）

- `MODstore_deploy/docs/adr/0003-artifacts-bundles-employee-packs.md`：doc-knowledge-curator
- `MODstore_deploy/docs/employee_publish_wizard.md`：doc-knowledge-curator
- `MODstore_deploy/docs/fhd-employee-composition.md`：doc-knowledge-curator
- `MODstore_deploy/market/src/components/admin/AdminDigestUnlockModal.vue`：market-frontend-dev
- `MODstore_deploy/market/src/components/admin/AdminDutyEmployeeGraph.vue`：market-frontend-dev
- `MODstore_deploy/market/src/components/catalog/CatalogCreatorProfile.vue`：pack-registrar
- `MODstore_deploy/market/src/domain/catalog/types.ts`：pack-registrar
- `MODstore_deploy/market/src/views/AdminAiAccountsView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminCustomerServiceView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminDatabaseView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminDutyEmployeesView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminEmployeeAutonomyView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminEmployeeChangeRequestsView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminOpsAuditView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminOpsTerminalView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminOrchestrateJobsView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/AdminYuangonOnboardView.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/workbench/WorkbenchShell.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/workbench/nodes/EmployeeModuleNode.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/workbench/panels/CanvasStage.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/workbench/panels/LeftRail.vue`：market-frontend-dev
- `MODstore_deploy/market/src/views/workbench/panels/RightRail.vue`：market-frontend-dev
- `MODstore_deploy/modstore_server/domain/catalog/__init__.py`：pack-registrar
- `MODstore_deploy/modstore_server/domain/catalog/invariants.py`：pack-registrar
- `MODstore_deploy/modstore_server/domain/catalog/ports.py`：pack-registrar
- `MODstore_deploy/modstore_server/domain/catalog/types.py`：pack-registrar
- `MODstore_deploy/modstore_server/models.py`：daily-orchestrator
- `MODstore_deploy/modstore_server/scripts/audit_public_employee_packs.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/migrate_sqlite_to_pg.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/migrate_workflows_to_script.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/onboard_yuangon_employees.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/promote_catalog_enterprise.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/register_doc_sync_eskill.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/seed_csv_employees.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/seed_excel_employees.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/seed_host_foundation_employee.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/seed_word_employees.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/scripts/seed_workflow_employee_mods.py`：deploy-release-officer
- `MODstore_deploy/modstore_server/workbench_script_runs/smoke-deepseek-1778044568_iter0_ov9dlpjr/modstore_runtime/__init__.py`：retention-officer
- `MODstore_deploy/modstore_server/workbench_script_runs/smoke-deepseek-1778044568_iter0_ov9dlpjr/script.py`：retention-officer
- `MODstore_deploy/scripts/audit_yuangon_roster.py`：deploy-release-officer
- `MODstore_deploy/scripts/build_routing_table.py`：deploy-release-officer
- `MODstore_deploy/scripts/coverage_audit.py`：deploy-release-officer
- `MODstore_deploy/scripts/intake_watcher.py`：deploy-release-officer
- `MODstore_deploy/scripts/yuangon_resync.py`：deploy-release-officer
- `docs/adr/0003-artifacts-bundles-employee-packs.md`：doc-knowledge-curator
- `docs/modstore/员工制作增强设计方案.md`：doc-knowledge-curator
