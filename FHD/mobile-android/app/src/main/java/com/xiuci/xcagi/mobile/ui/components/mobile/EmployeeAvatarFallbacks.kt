package com.xiuci.xcagi.mobile.ui.components.mobile

private val employeeAvatarFallbacks: Map<String, AppAvatarFallback> =
    mapOf(
        "site-content-editor" to AppAvatarFallback.EMP_SITE_CONTENT_EDITOR,
        "seo-sitemap-curator" to AppAvatarFallback.EMP_SEO_SITEMAP_CURATOR,
        "flask-entry-keeper" to AppAvatarFallback.EMP_FLASK_ENTRY_KEEPER,
        "marketing-site-builder" to AppAvatarFallback.EMP_MARKETING_SITE_BUILDER,
        "nginx-config-engineer" to AppAvatarFallback.EMP_NGINX_CONFIG_ENGINEER,
        "push-update-context-officer" to AppAvatarFallback.EMP_PUSH_UPDATE_CONTEXT_OFFICER,
        "deploy-release-officer" to AppAvatarFallback.EMP_DEPLOY_RELEASE_OFFICER,
        "security-secrets-guard" to AppAvatarFallback.EMP_SECURITY_SECRETS_GUARD,
        "log-monitor-incident" to AppAvatarFallback.EMP_LOG_MONITOR_INCIDENT,
        "retention-officer" to AppAvatarFallback.EMP_RETENTION_OFFICER,
        "dbops-engineer" to AppAvatarFallback.EMP_DBOPS_ENGINEER,
        "llm-ops-engineer" to AppAvatarFallback.EMP_LLM_OPS_ENGINEER,
        "legacy-archive-curator" to AppAvatarFallback.EMP_LEGACY_ARCHIVE_CURATOR,
        "modstore-backend-api" to AppAvatarFallback.EMP_MODSTORE_BACKEND_API,
        "employee-pack-curator" to AppAvatarFallback.EMP_EMPLOYEE_PACK_CURATOR,
        "payment-billing-reconciler" to AppAvatarFallback.EMP_PAYMENT_BILLING_RECONCILER,
        "java-payment-bridge-officer" to AppAvatarFallback.EMP_JAVA_PAYMENT_BRIDGE_OFFICER,
        "market-frontend-dev" to AppAvatarFallback.EMP_MARKET_FRONTEND_DEV,
        "workbench-ux-stylist" to AppAvatarFallback.EMP_WORKBENCH_UX_STYLIST,
        "fhd-core-maintainer" to AppAvatarFallback.EMP_FHD_CORE_MAINTAINER,
        "vibe-coding-maintainer" to AppAvatarFallback.EMP_VIBE_CODING_MAINTAINER,
        "mods-and-eskill-curator" to AppAvatarFallback.EMP_MODS_AND_ESKILL_CURATOR,
        "change-request-auditor" to AppAvatarFallback.EMP_CHANGE_REQUEST_AUDITOR,
        "daily-orchestrator" to AppAvatarFallback.EMP_DAILY_ORCHESTRATOR,
        "intake-dispatcher" to AppAvatarFallback.EMP_INTAKE_DISPATCHER,
        "task-router-officer" to AppAvatarFallback.EMP_TASK_ROUTER_OFFICER,
        "github-pr-gatekeeper" to AppAvatarFallback.EMP_GITHUB_PR_GATEKEEPER,
        "user-customer-service-officer" to AppAvatarFallback.EMP_USER_CUSTOMER_SERVICE_OFFICER,
        "enterprise-adoption-officer" to AppAvatarFallback.EMP_ENTERPRISE_ADOPTION_OFFICER,
        "delivery-receipt-officer" to AppAvatarFallback.EMP_DELIVERY_RECEIPT_OFFICER,
        "mobile-android-release-officer" to AppAvatarFallback.EMP_MOBILE_ANDROID_RELEASE_OFFICER,
        "mobile-ios-release-officer" to AppAvatarFallback.EMP_MOBILE_IOS_RELEASE_OFFICER,
        "test-qa-runner" to AppAvatarFallback.EMP_TEST_QA_RUNNER,
        "doc-knowledge-curator" to AppAvatarFallback.EMP_DOC_KNOWLEDGE_CURATOR,
        "employee-interview-assistant" to AppAvatarFallback.EMP_EMPLOYEE_INTERVIEW_ASSISTANT,
        "employee-pack-quality-interviewer" to AppAvatarFallback.EMP_EMPLOYEE_PACK_QUALITY_INTERVIEWER,
        "intent-analyst" to AppAvatarFallback.EMP_INTENT_ANALYST,
        "employee-planner" to AppAvatarFallback.EMP_EMPLOYEE_PLANNER,
        "artifact-generator" to AppAvatarFallback.EMP_ARTIFACT_GENERATOR,
        "quality-validator" to AppAvatarFallback.EMP_QUALITY_VALIDATOR,
        "miniapp-builder" to AppAvatarFallback.EMP_MINIAPP_BUILDER,
        "script-binder" to AppAvatarFallback.EMP_SCRIPT_BINDER,
        "workflow-automator" to AppAvatarFallback.EMP_WORKFLOW_AUTOMATOR,
        "pack-registrar" to AppAvatarFallback.EMP_PACK_REGISTRAR,
        "sandbox-tester" to AppAvatarFallback.EMP_SANDBOX_TESTER,
        "code-validator" to AppAvatarFallback.EMP_CODE_VALIDATOR,
        "self-checker" to AppAvatarFallback.EMP_SELF_CHECKER,
        "host-checker" to AppAvatarFallback.EMP_HOST_CHECKER,
        "hex-quality-assessor" to AppAvatarFallback.EMP_HEX_QUALITY_ASSESSOR,
        "ecosystem-partner-onboard-officer" to AppAvatarFallback.EMP_ECOSYSTEM_PARTNER_ONBOARD_OFFICER,
        "ecosystem-joint-catalog-officer" to AppAvatarFallback.EMP_ECOSYSTEM_JOINT_CATALOG_OFFICER,
        "ecosystem-delivery-reporter" to AppAvatarFallback.EMP_ECOSYSTEM_DELIVERY_REPORTER,
        "ecosystem-investor-portal-officer" to AppAvatarFallback.EMP_ECOSYSTEM_INVESTOR_PORTAL_OFFICER,
        "ecosystem-revenue-share-reconciler" to AppAvatarFallback.EMP_ECOSYSTEM_REVENUE_SHARE_RECONCILER,
        "avatar-generation-employee" to AppAvatarFallback.EMP_AVATAR_GENERATION_EMPLOYEE,
    )

fun employeeAvatarFallback(
    employeeId: String?,
    name: String = "",
    avatarKey: String = "",
): AppAvatarFallback {
    val key = avatarKey.trim().lowercase()
    val id = employeeId.normalizedEmployeeId()
    val label = name.trim().lowercase()
    val isXiaoc = id == "xcagi-assistant" || id == "xiaoc-assistant" || label.contains("小c")
    return when {
        isXiaoc -> AppAvatarFallback.ASSISTANT
        key == "codex" || id.contains("codex") || label.contains("codex") -> AppAvatarFallback.CODEX
        key == "cursor" || id.contains("cursor") || label.contains("cursor") -> AppAvatarFallback.CURSOR
        key == "claude" || id.contains("claude") || label.contains("claude") -> AppAvatarFallback.CLAUDE
        key == "trae" || id.contains("trae") || label.contains("trae") -> AppAvatarFallback.TRAE
        else -> employeeAvatarFallbacks[id]
            ?: employeeAvatarFallbacks[id.replace('_', '-')]
            ?: employeeAvatarFallbacks[key]
            ?: employeeAvatarFallbacks[key.replace('_', '-')]
            ?: AppAvatarFallback.AI_EMPLOYEE
    }
}

private fun String?.normalizedEmployeeId(): String {
    val value = this?.trim()?.lowercase().orEmpty()
    return if (value.startsWith("employee:")) value.substringAfterLast(":") else value
}
