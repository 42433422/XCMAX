package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.annotation.DrawableRes
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.xiuci.xcagi.mobile.R

/**
 * 固定的图片头像兜底。禁止用姓名首字母或随机颜色生成头像，确保所有页面身份一致。
 */
enum class AppAvatarFallback(@DrawableRes val drawableRes: Int) {
    USER(R.drawable.avatar_default_user),
    ASSISTANT(R.drawable.avatar_assistant),
    CUSTOMER_SERVICE(R.drawable.avatar_default_ai_employee),
    AI_EMPLOYEE(R.drawable.avatar_default_ai_employee),
    EMP_SITE_CONTENT_EDITOR(R.drawable.avatar_emp_site_content_editor),
    EMP_SEO_SITEMAP_CURATOR(R.drawable.avatar_emp_seo_sitemap_curator),
    EMP_FLASK_ENTRY_KEEPER(R.drawable.avatar_emp_flask_entry_keeper),
    EMP_MARKETING_SITE_BUILDER(R.drawable.avatar_emp_marketing_site_builder),
    EMP_NGINX_CONFIG_ENGINEER(R.drawable.avatar_emp_nginx_config_engineer),
    EMP_PUSH_UPDATE_CONTEXT_OFFICER(R.drawable.avatar_emp_push_update_context_officer),
    EMP_DEPLOY_RELEASE_OFFICER(R.drawable.avatar_emp_deploy_release_officer),
    EMP_SECURITY_SECRETS_GUARD(R.drawable.avatar_emp_security_secrets_guard),
    EMP_LOG_MONITOR_INCIDENT(R.drawable.avatar_emp_log_monitor_incident),
    EMP_RETENTION_OFFICER(R.drawable.avatar_emp_retention_officer),
    EMP_DBOPS_ENGINEER(R.drawable.avatar_emp_dbops_engineer),
    EMP_LLM_OPS_ENGINEER(R.drawable.avatar_emp_llm_ops_engineer),
    EMP_LEGACY_ARCHIVE_CURATOR(R.drawable.avatar_emp_legacy_archive_curator),
    EMP_MODSTORE_BACKEND_API(R.drawable.avatar_emp_modstore_backend_api),
    EMP_EMPLOYEE_PACK_CURATOR(R.drawable.avatar_emp_employee_pack_curator),
    EMP_PAYMENT_BILLING_RECONCILER(R.drawable.avatar_emp_payment_billing_reconciler),
    EMP_JAVA_PAYMENT_BRIDGE_OFFICER(R.drawable.avatar_emp_java_payment_bridge_officer),
    EMP_MARKET_FRONTEND_DEV(R.drawable.avatar_emp_market_frontend_dev),
    EMP_WORKBENCH_UX_STYLIST(R.drawable.avatar_emp_workbench_ux_stylist),
    EMP_FHD_CORE_MAINTAINER(R.drawable.avatar_emp_fhd_core_maintainer),
    EMP_VIBE_CODING_MAINTAINER(R.drawable.avatar_emp_vibe_coding_maintainer),
    EMP_MODS_AND_ESKILL_CURATOR(R.drawable.avatar_emp_mods_and_eskill_curator),
    EMP_CHANGE_REQUEST_AUDITOR(R.drawable.avatar_emp_change_request_auditor),
    EMP_DAILY_ORCHESTRATOR(R.drawable.avatar_emp_daily_orchestrator),
    EMP_INTAKE_DISPATCHER(R.drawable.avatar_emp_intake_dispatcher),
    EMP_TASK_ROUTER_OFFICER(R.drawable.avatar_emp_task_router_officer),
    EMP_GITHUB_PR_GATEKEEPER(R.drawable.avatar_emp_github_pr_gatekeeper),
    EMP_USER_CUSTOMER_SERVICE_OFFICER(R.drawable.avatar_emp_user_customer_service_officer),
    EMP_ENTERPRISE_ADOPTION_OFFICER(R.drawable.avatar_emp_enterprise_adoption_officer),
    EMP_DELIVERY_RECEIPT_OFFICER(R.drawable.avatar_emp_delivery_receipt_officer),
    EMP_MOBILE_ANDROID_RELEASE_OFFICER(R.drawable.avatar_emp_mobile_android_release_officer),
    EMP_MOBILE_IOS_RELEASE_OFFICER(R.drawable.avatar_emp_mobile_ios_release_officer),
    EMP_TEST_QA_RUNNER(R.drawable.avatar_emp_test_qa_runner),
    EMP_DOC_KNOWLEDGE_CURATOR(R.drawable.avatar_emp_doc_knowledge_curator),
    EMP_EMPLOYEE_INTERVIEW_ASSISTANT(R.drawable.avatar_emp_employee_interview_assistant),
    EMP_EMPLOYEE_PACK_QUALITY_INTERVIEWER(R.drawable.avatar_emp_employee_pack_quality_interviewer),
    EMP_INTENT_ANALYST(R.drawable.avatar_emp_intent_analyst),
    EMP_EMPLOYEE_PLANNER(R.drawable.avatar_emp_employee_planner),
    EMP_ARTIFACT_GENERATOR(R.drawable.avatar_emp_artifact_generator),
    EMP_QUALITY_VALIDATOR(R.drawable.avatar_emp_quality_validator),
    EMP_MINIAPP_BUILDER(R.drawable.avatar_emp_miniapp_builder),
    EMP_SCRIPT_BINDER(R.drawable.avatar_emp_script_binder),
    EMP_WORKFLOW_AUTOMATOR(R.drawable.avatar_emp_workflow_automator),
    EMP_PACK_REGISTRAR(R.drawable.avatar_emp_pack_registrar),
    EMP_SANDBOX_TESTER(R.drawable.avatar_emp_sandbox_tester),
    EMP_CODE_VALIDATOR(R.drawable.avatar_emp_code_validator),
    EMP_SELF_CHECKER(R.drawable.avatar_emp_self_checker),
    EMP_HOST_CHECKER(R.drawable.avatar_emp_host_checker),
    EMP_HEX_QUALITY_ASSESSOR(R.drawable.avatar_emp_hex_quality_assessor),
    EMP_ECOSYSTEM_PARTNER_ONBOARD_OFFICER(R.drawable.avatar_emp_ecosystem_partner_onboard_officer),
    EMP_ECOSYSTEM_JOINT_CATALOG_OFFICER(R.drawable.avatar_emp_ecosystem_joint_catalog_officer),
    EMP_ECOSYSTEM_DELIVERY_REPORTER(R.drawable.avatar_emp_ecosystem_delivery_reporter),
    EMP_ECOSYSTEM_INVESTOR_PORTAL_OFFICER(R.drawable.avatar_emp_ecosystem_investor_portal_officer),
    EMP_ECOSYSTEM_REVENUE_SHARE_RECONCILER(R.drawable.avatar_emp_ecosystem_revenue_share_reconciler),
    EMP_AVATAR_GENERATION_EMPLOYEE(R.drawable.avatar_emp_avatar_generation_employee),
    CODEX(R.drawable.codex_app_icon),
    CLAUDE(R.drawable.claude_app_icon),
    CURSOR(R.drawable.cursor_app_icon),
    TRAE(R.drawable.trae_app_icon),
}

@Composable
fun AppAvatar(
    imageSource: Any? = null,
    fallback: AppAvatarFallback,
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    shape: Shape,
    contentDescription: String? = null,
) {
    val source = imageSource?.takeUnless { it is String && it.isBlank() }
    val fallbackPainter = painterResource(fallback.drawableRes)
    val imageModifier = modifier.size(size).clip(shape)

    if (source == null) {
        Image(
            painter = fallbackPainter,
            contentDescription = contentDescription,
            modifier = imageModifier,
            contentScale = ContentScale.Crop,
        )
    } else {
        AsyncImage(
            model = source,
            contentDescription = contentDescription,
            modifier = imageModifier,
            placeholder = fallbackPainter,
            error = fallbackPainter,
            fallback = fallbackPainter,
            contentScale = ContentScale.Crop,
        )
    }
}
