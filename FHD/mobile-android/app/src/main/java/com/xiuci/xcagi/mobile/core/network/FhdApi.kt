package com.xiuci.xcagi.mobile.core.network

import com.google.gson.JsonObject
import com.xiuci.xcagi.mobile.core.model.AccessRequestPayload
import com.xiuci.xcagi.mobile.core.model.AdminMobileHomeData
import com.xiuci.xcagi.mobile.core.model.DeviceRegisterBody
import com.xiuci.xcagi.mobile.core.model.ChatRequest
import com.xiuci.xcagi.mobile.core.model.DiscoverHintData
import com.xiuci.xcagi.mobile.core.model.CodexSuperEmployeeMobileMessageBody
import com.xiuci.xcagi.mobile.core.model.MobileEnvelope
import com.xiuci.xcagi.mobile.core.model.MobileLoginData
import com.xiuci.xcagi.mobile.core.model.MeData
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.model.CsMessageResponseDto
import com.xiuci.xcagi.mobile.model.CsMessagesListDto
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming

data class MobileLoginRequest(
    val username: String,
    val password: String,
    val account_kind: String,
)

data class MobilePhoneLoginRequest(
    val phone: String,
    val code: String,
    val account_kind: String = "enterprise",
)

data class AuthQrConfirmBody(
    val qr_id: String,
    val username: String = "",
    val password: String = "",
    val account_kind: String = "",
)

data class OidcExchangeBody(
    val code: String,
    val state: String,
)

data class MobileRefreshRequest(val refresh_token: String)

data class RegisterRequest(
    val username: String,
    val password: String,
    val email: String? = null,
    val verification_code: String? = null,
)

data class ApproveBody(val approver_id: Int, val opinion: String = "")
data class RejectBody(val approver_id: Int, val reason: String = "")
data class BridgeRespondBody(val response: String, val responded_by: String? = null, val status: String = "resolved")
data class PairingExchangeBody(val nonce: String = "", val code: String = "")
data class RelayConfirmBody(val relay_id: String, val code: String)
data class RelayConfirmCodeBody(val code: String)
data class RelayTaskCreateBody(
    val relay_id: String,
    val kind: String = "codex.invoke",
    val payload: Map<String, Any?> = emptyMap(),
)

data class SyncPullBody(val since_cursor: Int = 0)

data class SyncPushItem(
    val entity_type: String,
    val entity_id: String,
    val operation: String = "update",
    val payload: Map<String, Any?> = emptyMap(),
)

data class SyncPushBody(val items: List<SyncPushItem> = emptyList())

data class ImDirectBody(val peer_user_id: Int)

data class ImSendBody(val body: String)

/**
 * 钱包余额信息（移动端"我"页面展示）。
 */
data class WalletBalanceDto(
    val balance: Double? = null,
    val currency: String = "CNY",
    val membership_level: String? = null,
    val experience: Long? = null,
    val byok_configured: Boolean = false,
    val byok_count: Int = 0,
    val synced: Boolean = false,
    val message: String? = null,
)

/**
 * 侧栏菜单项（与桌面端侧栏对齐）。
 */
data class NavMenuItem(
    val key: String = "",
    val name: String = "",
    val icon: String = "",
    val path: String = "",
    val source: String = "core",
    val mod_id: String? = null,
)

/**
 * 侧栏菜单响应（探索 Tab 配对后动态渲染工具列表）。
 */
data class NavMenuData(
    val items: List<NavMenuItem> = emptyList(),
    val account_kind: String = "enterprise",
)

interface FhdApi {
    @GET("api/health")
    suspend fun health(): Map<String, Any?>

    @GET(ApiEndpoints.HEALTH)
    suspend fun mobileHealth(): MobileEnvelope<Map<String, String>>

    @POST(ApiEndpoints.AUTH_LOGIN)
    suspend fun mobileLogin(@Body body: MobileLoginRequest): MobileEnvelope<MobileLoginData>

    @POST(ApiEndpoints.AUTH_LOGIN_WITH_PHONE_CODE)
    suspend fun mobileLoginWithPhone(@Body body: MobilePhoneLoginRequest): MobileEnvelope<MobileLoginData>

    @POST(ApiEndpoints.AUTH_QR_CONFIRM)
    suspend fun authQrConfirm(@Body body: AuthQrConfirmBody): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.AUTH_OIDC_EXCHANGE)
    suspend fun oidcExchange(@Body body: OidcExchangeBody): MobileEnvelope<MobileLoginData>

    @POST(ApiEndpoints.AUTH_REFRESH)
    suspend fun mobileRefresh(@Body body: MobileRefreshRequest): MobileEnvelope<MobileLoginData>

    @GET(ApiEndpoints.HOST_DISCOVER_HINT)
    suspend fun discoverHint(): MobileEnvelope<DiscoverHintData>

    @GET(ApiEndpoints.ME)
    suspend fun me(): MobileEnvelope<MeData>

    @POST("api/auth/register")
    suspend fun register(@Body body: RegisterRequest): Map<String, Any?>

    @POST("api/lan/access-requests")
    suspend fun lanAccessRequest(@Body body: AccessRequestPayload): Map<String, Any?>

    @GET("api/lan/status")
    suspend fun lanStatus(): Map<String, Any?>

    @POST("api/ai/chat")
    suspend fun chat(@Body body: ChatRequest): Map<String, Any?>

    @Streaming
    @POST("api/ai/chat/stream")
    suspend fun chatStream(@Body body: Map<String, String>): ResponseBody

    @GET(ApiEndpoints.APPROVAL_REQUESTS)
    suspend fun mobileApprovals(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
    ): MobileEnvelope<Map<String, Any?>>

    @GET("api/approval/requests/{id}")
    suspend fun approvalDetail(@Path("id") id: Int): Map<String, Any?>

    @POST("api/approval/requests/{id}/approve")
    suspend fun approvalApprove(@Path("id") id: Int, @Body body: ApproveBody): Map<String, Any?>

    @POST("api/approval/requests/{id}/reject")
    suspend fun approvalReject(@Path("id") id: Int, @Body body: RejectBody): Map<String, Any?>

    @GET(ApiEndpoints.CUSTOMERS)
    suspend fun mobileCustomers(
        @Query("page") page: Int = 1,
        @Query("per_page") perPage: Int = 20,
    ): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.SHIPMENTS)
    suspend fun mobileShipments(
        @Query("page") page: Int = 1,
        @Query("per_page") perPage: Int = 20,
    ): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.SERVICE_BRIDGE_REQUESTS)
    suspend fun mobileBridgeRequests(
        @Query("page") page: Int = 1,
        @Query("per_page") perPage: Int = 20,
    ): MobileEnvelope<Map<String, Any?>>

    @PUT(ApiEndpoints.SERVICE_BRIDGE_REQUESTS_RESPOND)
    suspend fun mobileBridgeRespond(
        @Path("id") id: Int,
        @Body body: BridgeRespondBody,
    ): MobileEnvelope<Map<String, Any?>>

    @GET("api/service-bridge/requests")
    suspend fun bridgeRequests(
        @Query("page") page: Int = 1,
        @Query("per_page") perPage: Int = 20,
    ): Map<String, Any?>

    @PUT("api/service-bridge/requests/{id}/respond")
    suspend fun bridgeRespond(
        @Path("id") id: Int,
        @Body body: BridgeRespondBody,
    ): Map<String, Any?>

    @GET(ApiEndpoints.MODS)
    suspend fun mobileMods(): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.PLATFORM_SHELL)
    suspend fun mobilePlatformShell(): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.HOME)
    suspend fun mobileHome(): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.NAV_MENU)
    suspend fun mobileNavMenu(): MobileEnvelope<NavMenuData>

    @GET(ApiEndpoints.ADMIN_HOME)
    suspend fun mobileAdminHome(): MobileEnvelope<AdminMobileHomeData>

    @GET(ApiEndpoints.SYNC_STATUS)
    suspend fun mobileSyncStatus(): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.SYNC_PULL)
    suspend fun mobileSyncPull(@Body body: SyncPullBody): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.SYNC_PUSH)
    suspend fun mobileSyncPush(@Body body: SyncPushBody): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.SYNC_CONFLICTS)
    suspend fun mobileSyncConflicts(): MobileEnvelope<Map<String, Any?>>

    @GET("api/inventory/items")
    suspend fun inventoryItems(): Map<String, Any?>

    @GET("api/mods/")
    suspend fun modsList(): Map<String, Any?>

    @POST(ApiEndpoints.DEVICES_REGISTER)
    suspend fun registerDevice(@Body body: DeviceRegisterBody): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.PAIRING_EXCHANGE)
    suspend fun pairingExchange(@Body body: PairingExchangeBody): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.RELAY_MOBILE_CONFIRM)
    suspend fun relayConfirm(@Body body: RelayConfirmBody): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.RELAY_MOBILE_CONFIRM_CODE)
    suspend fun relayConfirmCode(@Body body: RelayConfirmCodeBody): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.RELAY_MOBILE_DESKTOPS)
    suspend fun relayDesktops(): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.RELAY_TASKS)
    suspend fun relayCreateTask(@Body body: RelayTaskCreateBody): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.RELAY_TASKS_DETAIL)
    suspend fun relayTaskStatus(@Path("taskId") taskId: String): MobileEnvelope<Map<String, Any?>>

    @POST("api/market/account-sync")
    suspend fun marketAccountSync(@Body body: Map<String, String>): Map<String, Any?>

    @GET("api/market/session-handoff")
    suspend fun marketSessionHandoff(): Map<String, Any?>

    @GET("api/finance/summary")
    suspend fun financeSummary(): Map<String, Any?>

    @POST("api/im/conversations/direct")
    suspend fun imCreateDirect(@Body body: ImDirectBody): Map<String, Any?>

    @GET("api/im/conversations/{id}/messages")
    suspend fun imListMessages(
        @Path("id") conversationId: Int,
        @Query("limit") limit: Int = 50,
    ): Map<String, Any?>

    @POST("api/im/conversations/{id}/messages")
    suspend fun imSendMessage(
        @Path("id") conversationId: Int,
        @Body body: ImSendBody,
    ): Map<String, Any?>

    // ── 专属客服接口 ──
    @GET(ApiEndpoints.CS_INFO)
    suspend fun getCsInfo(): MobileEnvelope<CsInfoDto>

    @POST(ApiEndpoints.CS_MESSAGES)
    suspend fun sendCsMessage(@Body body: Map<String, String>): MobileEnvelope<CsMessageResponseDto>

    @GET(ApiEndpoints.CS_MESSAGES)
    suspend fun getCsMessages(@Query("since") since: String? = null): MobileEnvelope<CsMessagesListDto>

    @GET(ApiEndpoints.ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES)
    suspend fun getCodexSuperEmployeeMessages(
        @Query("limit") limit: Int = 80,
    ): MobileEnvelope<Map<String, Any?>>

    @POST(ApiEndpoints.ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES)
    suspend fun postCodexSuperEmployeeMessage(
        @Body body: CodexSuperEmployeeMobileMessageBody,
    ): MobileEnvelope<Map<String, Any?>>

    @GET(ApiEndpoints.WALLET_BALANCE)
    suspend fun mobileWalletBalance(): MobileEnvelope<WalletBalanceDto>
}
