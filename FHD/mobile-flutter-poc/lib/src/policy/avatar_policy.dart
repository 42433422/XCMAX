import '../models/conversation.dart';
import 'pinned_ids.dart';

enum AppAvatarFallback {
  user,
  assistant,
  customerService,
  aiEmployee,
  empSiteContentEditor,
  empSeoSitemapCurator,
  empFlaskEntryKeeper,
  empMarketingSiteBuilder,
  empNginxConfigEngineer,
  empPushUpdateContextOfficer,
  empDeployReleaseOfficer,
  empSecuritySecretsGuard,
  empLogMonitorIncident,
  empRetentionOfficer,
  empDbopsEngineer,
  empLlmOpsEngineer,
  empLegacyArchiveCurator,
  empModstoreBackendApi,
  empEmployeePackCurator,
  empPaymentBillingReconciler,
  empJavaPaymentBridgeOfficer,
  empMarketFrontendDev,
  empWorkbenchUxStylist,
  empFhdCoreMaintainer,
  empVibeCodingMaintainer,
  empModsAndEskillCurator,
  empChangeRequestAuditor,
  empDailyOrchestrator,
  empIntakeDispatcher,
  empTaskRouterOfficer,
  empGithubPrGatekeeper,
  empUserCustomerServiceOfficer,
  empEnterpriseAdoptionOfficer,
  empDeliveryReceiptOfficer,
  empMobileAndroidReleaseOfficer,
  empMobileIosReleaseOfficer,
  empTestQaRunner,
  empDocKnowledgeCurator,
  empEmployeeInterviewAssistant,
  empEmployeePackQualityInterviewer,
  empIntentAnalyst,
  empEmployeePlanner,
  empArtifactGenerator,
  empQualityValidator,
  empMiniappBuilder,
  empScriptBinder,
  empWorkflowAutomator,
  empPackRegistrar,
  empSandboxTester,
  empCodeValidator,
  empSelfChecker,
  empHostChecker,
  empHexQualityAssessor,
  empEcosystemPartnerOnboardOfficer,
  empEcosystemJointCatalogOfficer,
  empEcosystemDeliveryReporter,
  empEcosystemInvestorPortalOfficer,
  empEcosystemRevenueShareReconciler,
  empAvatarGenerationEmployee,
  codex,
  claude,
  cursor,
  trae,
}

extension AppAvatarFallbackX on AppAvatarFallback {
  String get assetPath {
    switch (this) {
      case AppAvatarFallback.user:
        return 'assets/avatars/avatar_default_user.png';
      case AppAvatarFallback.assistant:
        return 'assets/avatars/avatar_assistant.png';
      case AppAvatarFallback.customerService:
      case AppAvatarFallback.aiEmployee:
        return 'assets/avatars/avatar_default_ai_employee.png';
      case AppAvatarFallback.empSiteContentEditor:
        return 'assets/avatars/avatar_emp_site_content_editor.png';
      case AppAvatarFallback.empSeoSitemapCurator:
        return 'assets/avatars/avatar_emp_seo_sitemap_curator.png';
      case AppAvatarFallback.empFlaskEntryKeeper:
        return 'assets/avatars/avatar_emp_flask_entry_keeper.png';
      case AppAvatarFallback.empMarketingSiteBuilder:
        return 'assets/avatars/avatar_emp_marketing_site_builder.png';
      case AppAvatarFallback.empNginxConfigEngineer:
        return 'assets/avatars/avatar_emp_nginx_config_engineer.png';
      case AppAvatarFallback.empPushUpdateContextOfficer:
        return 'assets/avatars/avatar_emp_push_update_context_officer.png';
      case AppAvatarFallback.empDeployReleaseOfficer:
        return 'assets/avatars/avatar_emp_deploy_release_officer.png';
      case AppAvatarFallback.empSecuritySecretsGuard:
        return 'assets/avatars/avatar_emp_security_secrets_guard.png';
      case AppAvatarFallback.empLogMonitorIncident:
        return 'assets/avatars/avatar_emp_log_monitor_incident.png';
      case AppAvatarFallback.empRetentionOfficer:
        return 'assets/avatars/avatar_emp_retention_officer.png';
      case AppAvatarFallback.empDbopsEngineer:
        return 'assets/avatars/avatar_emp_dbops_engineer.png';
      case AppAvatarFallback.empLlmOpsEngineer:
        return 'assets/avatars/avatar_emp_llm_ops_engineer.png';
      case AppAvatarFallback.empLegacyArchiveCurator:
        return 'assets/avatars/avatar_emp_legacy_archive_curator.png';
      case AppAvatarFallback.empModstoreBackendApi:
        return 'assets/avatars/avatar_emp_modstore_backend_api.png';
      case AppAvatarFallback.empEmployeePackCurator:
        return 'assets/avatars/avatar_emp_employee_pack_curator.png';
      case AppAvatarFallback.empPaymentBillingReconciler:
        return 'assets/avatars/avatar_emp_payment_billing_reconciler.png';
      case AppAvatarFallback.empJavaPaymentBridgeOfficer:
        return 'assets/avatars/avatar_emp_java_payment_bridge_officer.png';
      case AppAvatarFallback.empMarketFrontendDev:
        return 'assets/avatars/avatar_emp_market_frontend_dev.png';
      case AppAvatarFallback.empWorkbenchUxStylist:
        return 'assets/avatars/avatar_emp_workbench_ux_stylist.png';
      case AppAvatarFallback.empFhdCoreMaintainer:
        return 'assets/avatars/avatar_emp_fhd_core_maintainer.png';
      case AppAvatarFallback.empVibeCodingMaintainer:
        return 'assets/avatars/avatar_emp_vibe_coding_maintainer.png';
      case AppAvatarFallback.empModsAndEskillCurator:
        return 'assets/avatars/avatar_emp_mods_and_eskill_curator.png';
      case AppAvatarFallback.empChangeRequestAuditor:
        return 'assets/avatars/avatar_emp_change_request_auditor.png';
      case AppAvatarFallback.empDailyOrchestrator:
        return 'assets/avatars/avatar_emp_daily_orchestrator.png';
      case AppAvatarFallback.empIntakeDispatcher:
        return 'assets/avatars/avatar_emp_intake_dispatcher.png';
      case AppAvatarFallback.empTaskRouterOfficer:
        return 'assets/avatars/avatar_emp_task_router_officer.png';
      case AppAvatarFallback.empGithubPrGatekeeper:
        return 'assets/avatars/avatar_emp_github_pr_gatekeeper.png';
      case AppAvatarFallback.empUserCustomerServiceOfficer:
        return 'assets/avatars/avatar_emp_user_customer_service_officer.png';
      case AppAvatarFallback.empEnterpriseAdoptionOfficer:
        return 'assets/avatars/avatar_emp_enterprise_adoption_officer.png';
      case AppAvatarFallback.empDeliveryReceiptOfficer:
        return 'assets/avatars/avatar_emp_delivery_receipt_officer.png';
      case AppAvatarFallback.empMobileAndroidReleaseOfficer:
        return 'assets/avatars/avatar_emp_mobile_android_release_officer.png';
      case AppAvatarFallback.empMobileIosReleaseOfficer:
        return 'assets/avatars/avatar_emp_mobile_ios_release_officer.png';
      case AppAvatarFallback.empTestQaRunner:
        return 'assets/avatars/avatar_emp_test_qa_runner.png';
      case AppAvatarFallback.empDocKnowledgeCurator:
        return 'assets/avatars/avatar_emp_doc_knowledge_curator.png';
      case AppAvatarFallback.empEmployeeInterviewAssistant:
        return 'assets/avatars/avatar_emp_employee_interview_assistant.png';
      case AppAvatarFallback.empEmployeePackQualityInterviewer:
        return 'assets/avatars/avatar_emp_employee_pack_quality_interviewer.png';
      case AppAvatarFallback.empIntentAnalyst:
        return 'assets/avatars/avatar_emp_intent_analyst.png';
      case AppAvatarFallback.empEmployeePlanner:
        return 'assets/avatars/avatar_emp_employee_planner.png';
      case AppAvatarFallback.empArtifactGenerator:
        return 'assets/avatars/avatar_emp_artifact_generator.png';
      case AppAvatarFallback.empQualityValidator:
        return 'assets/avatars/avatar_emp_quality_validator.png';
      case AppAvatarFallback.empMiniappBuilder:
        return 'assets/avatars/avatar_emp_miniapp_builder.png';
      case AppAvatarFallback.empScriptBinder:
        return 'assets/avatars/avatar_emp_script_binder.png';
      case AppAvatarFallback.empWorkflowAutomator:
        return 'assets/avatars/avatar_emp_workflow_automator.png';
      case AppAvatarFallback.empPackRegistrar:
        return 'assets/avatars/avatar_emp_pack_registrar.png';
      case AppAvatarFallback.empSandboxTester:
        return 'assets/avatars/avatar_emp_sandbox_tester.png';
      case AppAvatarFallback.empCodeValidator:
        return 'assets/avatars/avatar_emp_code_validator.png';
      case AppAvatarFallback.empSelfChecker:
        return 'assets/avatars/avatar_emp_self_checker.png';
      case AppAvatarFallback.empHostChecker:
        return 'assets/avatars/avatar_emp_host_checker.png';
      case AppAvatarFallback.empHexQualityAssessor:
        return 'assets/avatars/avatar_emp_hex_quality_assessor.png';
      case AppAvatarFallback.empEcosystemPartnerOnboardOfficer:
        return 'assets/avatars/avatar_emp_ecosystem_partner_onboard_officer.png';
      case AppAvatarFallback.empEcosystemJointCatalogOfficer:
        return 'assets/avatars/avatar_emp_ecosystem_joint_catalog_officer.png';
      case AppAvatarFallback.empEcosystemDeliveryReporter:
        return 'assets/avatars/avatar_emp_ecosystem_delivery_reporter.png';
      case AppAvatarFallback.empEcosystemInvestorPortalOfficer:
        return 'assets/avatars/avatar_emp_ecosystem_investor_portal_officer.png';
      case AppAvatarFallback.empEcosystemRevenueShareReconciler:
        return 'assets/avatars/avatar_emp_ecosystem_revenue_share_reconciler.png';
      case AppAvatarFallback.empAvatarGenerationEmployee:
        return 'assets/avatars/avatar_emp_avatar_generation_employee.png';
      case AppAvatarFallback.codex:
        return 'assets/avatars/codex_app_icon.png';
      case AppAvatarFallback.claude:
        return 'assets/avatars/claude_app_icon.png';
      case AppAvatarFallback.cursor:
        return 'assets/avatars/cursor_app_icon.png';
      case AppAvatarFallback.trae:
        return 'assets/avatars/trae_app_icon.png';
    }
  }
}

const _employeeAvatarFallbacks = <String, AppAvatarFallback>{
  'site-content-editor': AppAvatarFallback.empSiteContentEditor,
  'seo-sitemap-curator': AppAvatarFallback.empSeoSitemapCurator,
  'flask-entry-keeper': AppAvatarFallback.empFlaskEntryKeeper,
  'marketing-site-builder': AppAvatarFallback.empMarketingSiteBuilder,
  'nginx-config-engineer': AppAvatarFallback.empNginxConfigEngineer,
  'push-update-context-officer': AppAvatarFallback.empPushUpdateContextOfficer,
  'deploy-release-officer': AppAvatarFallback.empDeployReleaseOfficer,
  'security-secrets-guard': AppAvatarFallback.empSecuritySecretsGuard,
  'log-monitor-incident': AppAvatarFallback.empLogMonitorIncident,
  'retention-officer': AppAvatarFallback.empRetentionOfficer,
  'dbops-engineer': AppAvatarFallback.empDbopsEngineer,
  'llm-ops-engineer': AppAvatarFallback.empLlmOpsEngineer,
  'legacy-archive-curator': AppAvatarFallback.empLegacyArchiveCurator,
  'modstore-backend-api': AppAvatarFallback.empModstoreBackendApi,
  'employee-pack-curator': AppAvatarFallback.empEmployeePackCurator,
  'payment-billing-reconciler': AppAvatarFallback.empPaymentBillingReconciler,
  'java-payment-bridge-officer': AppAvatarFallback.empJavaPaymentBridgeOfficer,
  'market-frontend-dev': AppAvatarFallback.empMarketFrontendDev,
  'workbench-ux-stylist': AppAvatarFallback.empWorkbenchUxStylist,
  'fhd-core-maintainer': AppAvatarFallback.empFhdCoreMaintainer,
  'vibe-coding-maintainer': AppAvatarFallback.empVibeCodingMaintainer,
  'mods-and-eskill-curator': AppAvatarFallback.empModsAndEskillCurator,
  'change-request-auditor': AppAvatarFallback.empChangeRequestAuditor,
  'daily-orchestrator': AppAvatarFallback.empDailyOrchestrator,
  'intake-dispatcher': AppAvatarFallback.empIntakeDispatcher,
  'task-router-officer': AppAvatarFallback.empTaskRouterOfficer,
  'github-pr-gatekeeper': AppAvatarFallback.empGithubPrGatekeeper,
  'user-customer-service-officer':
      AppAvatarFallback.empUserCustomerServiceOfficer,
  'enterprise-adoption-officer': AppAvatarFallback.empEnterpriseAdoptionOfficer,
  'delivery-receipt-officer': AppAvatarFallback.empDeliveryReceiptOfficer,
  'mobile-android-release-officer':
      AppAvatarFallback.empMobileAndroidReleaseOfficer,
  'mobile-ios-release-officer': AppAvatarFallback.empMobileIosReleaseOfficer,
  'test-qa-runner': AppAvatarFallback.empTestQaRunner,
  'doc-knowledge-curator': AppAvatarFallback.empDocKnowledgeCurator,
  'employee-interview-assistant':
      AppAvatarFallback.empEmployeeInterviewAssistant,
  'employee-pack-quality-interviewer':
      AppAvatarFallback.empEmployeePackQualityInterviewer,
  'intent-analyst': AppAvatarFallback.empIntentAnalyst,
  'employee-planner': AppAvatarFallback.empEmployeePlanner,
  'artifact-generator': AppAvatarFallback.empArtifactGenerator,
  'quality-validator': AppAvatarFallback.empQualityValidator,
  'miniapp-builder': AppAvatarFallback.empMiniappBuilder,
  'script-binder': AppAvatarFallback.empScriptBinder,
  'workflow-automator': AppAvatarFallback.empWorkflowAutomator,
  'pack-registrar': AppAvatarFallback.empPackRegistrar,
  'sandbox-tester': AppAvatarFallback.empSandboxTester,
  'code-validator': AppAvatarFallback.empCodeValidator,
  'self-checker': AppAvatarFallback.empSelfChecker,
  'host-checker': AppAvatarFallback.empHostChecker,
  'hex-quality-assessor': AppAvatarFallback.empHexQualityAssessor,
  'ecosystem-partner-onboard-officer':
      AppAvatarFallback.empEcosystemPartnerOnboardOfficer,
  'ecosystem-joint-catalog-officer':
      AppAvatarFallback.empEcosystemJointCatalogOfficer,
  'ecosystem-delivery-reporter': AppAvatarFallback.empEcosystemDeliveryReporter,
  'ecosystem-investor-portal-officer':
      AppAvatarFallback.empEcosystemInvestorPortalOfficer,
  'ecosystem-revenue-share-reconciler':
      AppAvatarFallback.empEcosystemRevenueShareReconciler,
  'avatar-generation-employee': AppAvatarFallback.empAvatarGenerationEmployee,
};

extension ConversationAvatarPolicyX on ConversationType {
  AppAvatarFallback get avatarFallback {
    switch (this) {
      case ConversationType.pinnedCs:
        return AppAvatarFallback.customerService;
      case ConversationType.pinnedAssistant:
        return AppAvatarFallback.assistant;
      case ConversationType.pinnedCodex:
        return AppAvatarFallback.codex;
      case ConversationType.pinnedCursor:
        return AppAvatarFallback.cursor;
      case ConversationType.pinnedClaude:
        return AppAvatarFallback.claude;
      case ConversationType.pinnedTrae:
        return AppAvatarFallback.trae;
      case ConversationType.aiTask:
      case ConversationType.systemNotification:
        return AppAvatarFallback.aiEmployee;
    }
  }
}

bool isCodexConversation(String? conversationId) =>
    conversationId?.trim() == PinnedIds.codex;

bool isCursorConversation(String? conversationId) =>
    conversationId?.trim() == PinnedIds.cursor;

bool isClaudeConversation(String? conversationId) =>
    conversationId?.trim() == PinnedIds.claude;

bool isTraeConversation(String? conversationId) =>
    conversationId?.trim() == PinnedIds.trae;

AppAvatarFallback employeeAvatarFallback({
  required String? employeeId,
  String name = '',
  String avatarKey = '',
}) {
  final key = avatarKey.trim().toLowerCase();
  final id = _normalizedEmployeeId(employeeId);
  final label = name.trim().toLowerCase();
  final isXiaoc = id == 'xcagi-assistant' ||
      id == 'xiaoc-assistant' ||
      label.contains('小c');

  if (isXiaoc) return AppAvatarFallback.assistant;
  if (key == 'codex' || id.contains('codex') || label.contains('codex')) {
    return AppAvatarFallback.codex;
  }
  if (key == 'cursor' || id.contains('cursor') || label.contains('cursor')) {
    return AppAvatarFallback.cursor;
  }
  if (key == 'claude' || id.contains('claude') || label.contains('claude')) {
    return AppAvatarFallback.claude;
  }
  if (key == 'trae' || id.contains('trae') || label.contains('trae')) {
    return AppAvatarFallback.trae;
  }
  return _employeeAvatarFallbacks[id] ??
      _employeeAvatarFallbacks[id.replaceAll('_', '-')] ??
      _employeeAvatarFallbacks[key] ??
      _employeeAvatarFallbacks[key.replaceAll('_', '-')] ??
      AppAvatarFallback.aiEmployee;
}

AppAvatarFallback chatAvatarFallback({
  required String? conversationId,
  required bool hasEmployeeProfile,
}) {
  if (isCodexConversation(conversationId)) return AppAvatarFallback.codex;
  if (isCursorConversation(conversationId)) return AppAvatarFallback.cursor;
  if (isClaudeConversation(conversationId)) return AppAvatarFallback.claude;
  if (isTraeConversation(conversationId)) return AppAvatarFallback.trae;
  if (hasEmployeeProfile) {
    return employeeAvatarFallback(employeeId: conversationId);
  }
  return AppAvatarFallback.assistant;
}

ConversationType conversationTypeForFixed({
  required String id,
  String kind = '',
  String title = '',
}) {
  final raw = id.trim();
  final key = kind.trim().toLowerCase();
  final label = title.trim().toLowerCase();

  if (raw == PinnedIds.cs || key == 'cs' || label.contains('客服')) {
    return ConversationType.pinnedCs;
  }
  if (raw == PinnedIds.assistant ||
      key == 'assistant' ||
      label.contains('小c')) {
    return ConversationType.pinnedAssistant;
  }
  if (raw == PinnedIds.codex || key == 'codex' || label.contains('codex')) {
    return ConversationType.pinnedCodex;
  }
  if (raw == PinnedIds.cursor || key == 'cursor' || label.contains('cursor')) {
    return ConversationType.pinnedCursor;
  }
  if (raw == PinnedIds.claude || key == 'claude' || label.contains('claude')) {
    return ConversationType.pinnedClaude;
  }
  if (raw == PinnedIds.trae || key == 'trae' || label.contains('trae')) {
    return ConversationType.pinnedTrae;
  }
  if (raw.startsWith('employee:')) return ConversationType.aiTask;
  return ConversationType.systemNotification;
}

AppAvatarFallback aiGroupMemberFallback(String employeeId) {
  switch (employeeId.trim()) {
    case AiGroupMemberIds.xiaocAssistant:
      return AppAvatarFallback.assistant;
    case AiGroupMemberIds.codexSuperEmployee:
      return AppAvatarFallback.codex;
    case AiGroupMemberIds.cursorSuperEmployee:
      return AppAvatarFallback.cursor;
    case AiGroupMemberIds.claudeSuperEmployee:
      return AppAvatarFallback.claude;
    case AiGroupMemberIds.traeSuperEmployee:
      return AppAvatarFallback.trae;
    default:
      return employeeAvatarFallback(employeeId: employeeId);
  }
}

AppAvatarFallback aiGroupAvatarFallback({
  required String employeeId,
  String name = '',
  String avatarKey = '',
}) {
  return employeeAvatarFallback(
    employeeId: employeeId,
    name: name,
    avatarKey: avatarKey,
  );
}

bool isRequiredAiGroupMember(String employeeId) =>
    employeeId.trim() == AiGroupMemberIds.xiaocAssistant;

String? relayKindForConversation(String? conversationId) {
  switch (conversationId?.trim()) {
    case PinnedIds.codex:
      return 'codex.invoke';
    case PinnedIds.cursor:
      return 'cursor.invoke';
    case PinnedIds.claude:
      return 'claude.invoke';
    case PinnedIds.trae:
      return 'trae.invoke';
    default:
      return null;
  }
}

String toolLabelForRelayKind(String kind) {
  if (kind.startsWith('claude')) return 'Claude';
  if (kind.startsWith('cursor')) return 'Cursor';
  if (kind.startsWith('trae')) return 'Trae';
  return 'Codex';
}

String? superEmployeeMessagesPath(String? conversationId) {
  switch (conversationId?.trim()) {
    case PinnedIds.codex:
      return 'api/mobile/v1/admin/codex-super-employee/messages';
    case PinnedIds.claude:
      return 'api/mobile/v1/admin/claude-super-employee/messages';
    case PinnedIds.cursor:
      return 'api/mobile/v1/admin/cursor-super-employee/messages';
    case PinnedIds.trae:
      return 'api/mobile/v1/admin/trae-super-employee/messages';
    default:
      return null;
  }
}

String _normalizedEmployeeId(String? value) {
  final id = value?.trim().toLowerCase() ?? '';
  return id.startsWith('employee:') ? id.split(':').last : id;
}
