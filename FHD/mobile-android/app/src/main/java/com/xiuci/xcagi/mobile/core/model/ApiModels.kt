package com.xiuci.xcagi.mobile.core.model

import com.google.gson.JsonElement

data class MobileEnvelope<T>(
    val code: Int = 200,
    val message: String = "",
    val success: Boolean = true,
    val data: T? = null,
)

data class UserDto(
    val id: Int = 0,
    val username: String = "",
    val display_name: String = "",
    val email: String = "",
    val role: String = "",
    val is_active: Boolean = true,
    val avatar_url: String? = null,
)

data class MobileLoginData(
    val user: UserDto? = null,
    val session_id: String? = null,
    val access_token: String? = null,
    val refresh_token: String? = null,
    val account_kind: String? = null,
    val expires_in: Int? = null,
    val market_access_token: String? = null,
    val market_refresh_token: String? = null,
    val market_is_admin: Boolean = false,
    val market_is_enterprise: Boolean = false,
)

data class CodexSuperEmployeeMobileMessageBody(
    val body: String = "",
    val message: String = "",
    val context: Map<String, Any?> = mapOf("source" to "mobile", "client_surface" to "mobile"),
)

data class MeData(
    val user: UserDto? = null,
    val permissions: List<String>? = null,
    val account_kind: String? = null,
    val company_brand: String? = null,
    val mods: List<ModSummary>? = null,
)

data class ModSummary(val id: String = "")

data class DiscoverHintData(
    val lan: LanHostInfo? = null,
    val instance_name: String? = null,
    val api_port: Int? = null,
    val company: String? = null,
    val brand_url: String? = null,
)

data class LanHostInfo(
    val enabled: Boolean = false,
    val ip: String? = null,
    val is_admin_host: Boolean = false,
)

data class AccessRequestPayload(
    val device_label: String = "",
    val note: String = "",
)

data class ChatRequest(
    val message: String,
    val session_id: String? = null,
)

data class ChatResponse(
    val success: Boolean = false,
    val reply: String? = null,
    val message: String? = null,
    val data: JsonElement? = null,
)

data class ApprovalItem(
    val id: Int = 0,
    val title: String = "",
    val status: String = "",
    val requester: String = "",
    val created_at: String? = null,
)

data class ApprovalListResponse(
    val success: Boolean = false,
    val data: List<ApprovalItem>? = null,
    val items: List<ApprovalItem>? = null,
)

data class CustomerItem(
    val id: Int = 0,
    val name: String = "",
    val phone: String? = null,
)

data class ShipmentItem(
    val id: Int = 0,
    val order_number: String? = null,
    val status: String? = null,
)

data class MarketLoginBody(
    val phone: String,
    val code: String,
)

data class MarketPasswordLoginBody(
    val username: String,
    val password: String,
    val account_kind: String = "enterprise",
)

data class MarketSendCodeBody(val phone: String)

data class MarketRegisterBody(
    val username: String,
    val password: String,
    val email: String,
    val verification_code: String = "",
)

data class MarketUserInfo(
    val id: Int? = null,
    val username: String? = null,
    val is_enterprise: Boolean? = null,
)

data class MarketAuthResponse(
    val success: Boolean = false,
    val ok: Boolean = false,
    val account_kind: String? = null,
    val token: String? = null,
    val access_token: String? = null,
    val refresh_token: String? = null,
    val message: String? = null,
    val market_is_admin: Boolean = false,
    val is_enterprise: Boolean = false,
    val user: MarketUserInfo? = null,
) {
    fun isAuthenticated(): Boolean = success || ok

    fun accessToken(): String? =
        access_token?.trim()?.takeIf { it.isNotBlank() }
            ?: token?.trim()?.takeIf { it.isNotBlank() }

    fun userIsEnterprise(): Boolean? = user?.is_enterprise
}

data class MarketMeResponse(
    val id: Int? = null,
    val username: String? = null,
    val is_enterprise: Boolean = false,
)

data class MarketItem(
    val id: String = "",
    val name: String = "",
    val description: String? = null,
)

data class ModInfo(
    val id: String = "",
    val name: String = "",
    val version: String = "",
    val description: String = "",
    val author: String = "",
    val primary: Boolean = false,
    val industry: ModIndustry? = null,
    val avatar_url: String? = null,
    val frontend_menu: List<ModMenuItem> = emptyList(),
    val menu_overrides: List<ModMenuOverride> = emptyList(),
    val workflow_employees: List<WorkflowEmployeeInfo> = emptyList(),
)

data class WorkflowEmployeeInfo(
    val id: String = "",
    val label: String = "",
    val panel_title: String = "",
    val panel_summary: String = "",
    val api_base_path: String = "",
    val phone_channel: String = "",
    val workflow_placeholder: Boolean = false,
    val profile_source: String = "",
    val market_connected: Boolean = false,
    val market_pkg_id: String = "",
    val market_name: String = "",
    val market_description: String = "",
    val market_version: String = "",
    val market_author: String = "",
    val market_industry: String = "",
    val market_material_category: String = "",
    val market_license_scope: String = "",
    val market_security_level: String = "",
    val market_avatar: String? = null,
)

data class ModMenuItem(
    val id: String = "",
    val label: String = "",
    val icon: String = "",
    val path: String = "",
)

data class ModMenuOverride(
    val key: String = "",
    val label: String? = null,
    val icon: String? = null,
    val hidden: Boolean? = null,
)

data class ModIndustry(
    val id: String = "",
    val name: String = "",
)

data class AdminMobileEmployeeInfo(
    val id: String = "",
    val name: String = "",
    val label: String = "",
    val title: String = "",
    val description: String = "",
    val panel_summary: String = "",
    val version: String = "",
    val industry: String = "",
    val yuangon_area: String = "",
    val employee_scope: String = "",
    val employee_source: String = "",
    val is_duty_employee: Boolean = false,
    val is_store_employee: Boolean = false,
    val status: String = "",
    val api_base_path: String = "",
    val phone_channel: String = "",
    val profile_source: String = "",
    val market_connected: Boolean = false,
    val market_pkg_id: String = "",
    val market_name: String = "",
    val market_description: String = "",
    val market_version: String = "",
    val market_author: String = "",
    val market_industry: String = "",
    val market_material_category: String = "",
    val market_license_scope: String = "",
    val market_security_level: String = "",
    val market_avatar: String? = null,
)

data class AdminMobileFeature(
    val id: String = "",
    val title: String = "",
    val description: String = "",
    val category: String = "",
    val method: String = "GET",
    val api_path: String = "",
)

data class AdminMobileHomeData(
    val account_kind: String = "",
    val employees: List<AdminMobileEmployeeInfo> = emptyList(),
    val employee_count: Int = 0,
    val features: List<AdminMobileFeature> = emptyList(),
    val feature_count: Int = 0,
    val market_connected: Boolean = false,
    val market_profile_count: Int = 0,
    val market_error: String = "",
)
