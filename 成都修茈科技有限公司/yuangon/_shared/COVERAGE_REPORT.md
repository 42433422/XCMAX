# Yuangon 覆盖率与编制契约审计报告

> 生成时间（UTC）：`2026-06-28T12:16:06.313667+00:00`  
> 仓库根：`/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/成都修茈科技有限公司`  
> 员工数量：**55**

## 总览

| 指标 | 值 |
|---|---:|
| 扫描文件数 | 2703 |
| 忽略构建/缓存文件数 | 91 |
| 有写入责任人 | 2682 |
| 无写入责任人 | 21 |
| 覆盖率 | 99.22% |
| 多员工可写 | 1285 |
| scope 被 forbidden 收窄（forbidden 优先） | 47 |
| 编制契约错误 | 0 |
| 依赖循环节点 | 0 |

## 编制契约错误

- 无

## 无写入责任人（前 200 项）

- `marketing-assets/xc-brand-film/assets/logo-glow.png`
- `marketing-assets/xc-brand-film/assets/logo-source.png`
- `marketing-assets/xc-brand-film/assets/scene-02-workbench.png`
- `marketing-assets/xc-brand-film/assets/scene-03-document.png`
- `marketing-assets/xc-brand-film/assets/scene-03-report.png`
- `marketing-assets/xc-brand-film/assets/scene-03-support.png`
- `marketing-assets/xc-brand-film/assets/scene-04-founder-team.png`
- `marketing-assets/xc-brand-film/assets/website-qr.png`
- `marketing-assets/xc-brand-film/build.sh`
- `marketing-assets/xc-brand-film/output/render-brand-film`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-01.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-02.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-03a.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-03b.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-03c.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-04.png`
- `marketing-assets/xc-brand-film/output/verification-frames/scene-05.png`
- `marketing-assets/xc-brand-film/output/verify-film`
- `marketing-assets/xc-brand-film/output/xc-brand-film-poster.png`
- `marketing-assets/xc-brand-film/output/xc-brand-film-soundtrack.wav`
- `privacy.html`

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
- `MODstore_deploy/market/nginx.conf`：deploy-release-officer, nginx-config-engineer
- `MODstore_deploy/market/src/App.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/api.ts`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/api/admin.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/auth.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/catalog.test.ts`：ecosystem-joint-catalog-officer, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/catalog.ts`：ecosystem-joint-catalog-officer, daily-orchestrator
- `MODstore_deploy/market/src/api/developer.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/employees.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/llm.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/mods.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/shared.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/wallet.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/workbench-employee.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/workbench.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/api/workflow.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/analyticsApi.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/authApi.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/catalogApi.test.ts`：ecosystem-joint-catalog-officer, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/catalogApi.ts`：ecosystem-joint-catalog-officer, daily-orchestrator
- `MODstore_deploy/market/src/application/openApiConnectorsApi.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/paymentApi.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/application/sandboxApi.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/components/AppConfirmDialog.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/AppToastHost.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/admin/AdminDigestUnlockModal.vue`：workbench-ux-stylist, ecosystem-investor-portal-officer, daily-orchestrator
- `MODstore_deploy/market/src/components/admin/AdminDutyEmployeeGraph.vue`：workbench-ux-stylist, ecosystem-investor-portal-officer, daily-orchestrator
- `MODstore_deploy/market/src/components/catalog/CatalogCreatorProfile.vue`：market-frontend-dev, ecosystem-joint-catalog-officer, daily-orchestrator
- `MODstore_deploy/market/src/components/customer-service/CustomerServiceActionCard.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AdminAgentSkillMarket.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentActionPreview.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentChatHistory.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentMessageBubble.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentPermissionDialog.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentStatusBar.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentSuggestionToast.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/AgentVoiceInput.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/ButlerFilesDrawer.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/ButlerProgressOverlay.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/CorpContactIntakeModal.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/CorpWelcomeBoard.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/FloatingAgentBall.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/FloatingAgentPanel.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/floating-agent/FloatingAgentRoot.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/llm/LlmPricingAdminPanel.test.ts`：market-frontend-dev, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/components/llm/LlmPricingAdminPanel.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/store/EmployeePackTypeIcon.vue`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/AgentMarket.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/BalanceBadge.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/ChatSidebar.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/ConsumptionTierControl.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/EmployeeAiDraftReview.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/EmployeePanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/EmployeeSixDimModal.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/EmployeeSixDimPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/GlobalSidebar.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/JarvisCore.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/MediaGenPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/MessageActions.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/MessageBody.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/OpenApiConnectorsPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/OrbitRings.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/PersonalSettings.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/RepositoryPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/RightPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/SidebarUserMenu.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/SiriOrb.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/SkillToolbar.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/ThinkingRow.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/VibeCodeSkillPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/VoicePhoneModal.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/VoiceWorkPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/WorkbenchStarterProgress.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/WorkflowPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/direct/DirectChatView.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/direct/DirectFlowPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/direct/DirectGeneratedFileStack.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/direct/DirectMediaSettingsRail.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/make/MakeFlowView.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/sidebar/WorkbenchSidebar.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/voice/VoiceDock.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/voice/VoiceFlowPanel.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/voice/VoicePlanView.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/components/workbench/voice/VoiceTaskPanels.vue`：market-frontend-dev, workbench-ux-stylist, daily-orchestrator
- `MODstore_deploy/market/src/composables/agent/skills/corpIntakeSkill.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/skills/corpSiteSkill.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/useActionExecutor.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/useAgentEngine.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/useCorpAgentEngine.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/usePageAnalyzer.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/agent/usePrivacyManager.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/llmCatalogModelHelpers.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/mergeAsrLiveText.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/normalizeVoiceAsrText.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useAdminDigestUnlock.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useEmployeePublishFlow.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useEmployeeWorkbenchState.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useHostConnection.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useLlmPricingDisplay.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useManifestDiff.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useSpeechRecognition.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useStreamingTts.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/useVoiceContinuousChat.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/voiceEndpointLogic.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/voiceSessionAgent.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/voiceSpeculativeMatch.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/voiceUserTurnCoalesce.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/composables/voiceUtteranceRouter.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/constants/officeEmployeePack.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/content/siteKnowledge.corpWelcome.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/content/siteKnowledge.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/contracts/authSession.contract.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/contracts/catalogApi.contract.test.ts`：ecosystem-joint-catalog-officer, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/contracts/walletCheckout.contract.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/accountLevel.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/butlerEmployeeProfile.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/catalog/types.ts`：ecosystem-joint-catalog-officer, daily-orchestrator
- `MODstore_deploy/market/src/domain/clientWorkshops.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/employeeDraftPipeline.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/llm/defaultEmployeeLlm.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/domain/yuangonDutyRoster.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/e2e/app.spec.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/e2e/direct-composer-mobile.spec.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/features/mod-authoring/composables/useModAuthoringWizard.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/infrastructure/http/client.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/infrastructure/http/client.ts`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/infrastructure/storage/fhdMarketHandoff.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/infrastructure/storage/tokenStore.test.ts`：daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/router/aiTestRoutes.test.ts`：market-frontend-dev, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/router/guards.test.ts`：market-frontend-dev, daily-orchestrator, test-qa-runner
- `MODstore_deploy/market/src/router/guards.ts`：market-frontend-dev, daily-orchestrator
- `MODstore_deploy/market/src/router/index.test.ts`：market-frontend-dev, daily-orchestrator, test-qa-runner

## scope 被 forbidden 收窄（前 200 项）

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
