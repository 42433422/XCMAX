package com.xiuci.xcagi.mobile.core.model

data class AppConfigResponse(
    val ok: Boolean = false,
    val privacy_url: String = "",
    val terms_url: String = "",
    val legal_version: String = "1",
    val sku: String = "",
    val icp_number: String = "",
    val app_filing_approved: Boolean = false,
    val app_filing_beian_url: String = "https://beian.miit.gov.cn/",
    val app_filing_number: String = "",
    val min_android_version: Int = 0,
    val latest_android_version: Int = 0,
    val latest_android_version_name: String = "",
    val force_update: Boolean = false,
    val apk_download_url: String = "",
    val apk_delta: ApkDeltaConfig = ApkDeltaConfig(),
    val feedback_email: String = "",
    val profile_page: ProfilePageConfig = ProfilePageConfig(),
)

data class ApkDeltaConfig(
    val available: Boolean = false,
    val format: String = "",
    val patch_url: String = "",
    val base_version_code: Int = 0,
    val base_version_name: String = "",
    val target_version_code: Int = 0,
    val target_version_name: String = "",
    val patch_sha256: String = "",
    val base_apk_sha256: String = "",
    val target_apk_sha256: String = "",
    val patch_size: Long = 0,
    val apk_size: Long = 0,
)

data class ProfilePageConfig(
    val enabled: Boolean = false,
    val revision: String = "",
    val hero_variant: String = "glass",
    val headline: String = "",
    val subtitle: String = "",
    val status_ready: String = "",
    val status_syncing: String = "",
    val primary_chip: String = "",
    val secondary_chip: String = "",
    val accent: String = "indigo",
)

data class AccountDeleteBody(val password: String)

data class AppFeedbackBody(
    val message: String,
    val contact: String = "",
    val app_version: String = "",
    val sku: String = "",
    val platform: String = "android",
)

data class DeviceRegisterBody(
    val fcm_token: String,
    val push_provider: String = "fcm",
    val push_token: String = "",
    val product_sku: String = "personal",
    val device_label: String = "",
    val platform: String = "android",
)
