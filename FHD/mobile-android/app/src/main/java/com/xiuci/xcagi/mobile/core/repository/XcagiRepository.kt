package com.xiuci.xcagi.mobile.core.repository

import android.os.Build
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.db.ApprovalCacheEntity
import com.xiuci.xcagi.mobile.core.db.ChatCacheEntity
import com.xiuci.xcagi.mobile.core.db.ConversationListStateEntity
import com.xiuci.xcagi.mobile.core.db.ShipmentCacheEntity
import com.xiuci.xcagi.mobile.core.db.XcagiDatabase
import com.xiuci.xcagi.mobile.core.db.ModInfoCacheEntity
import com.xiuci.xcagi.mobile.core.model.AccessRequestPayload
import com.xiuci.xcagi.mobile.core.model.AdminMobileHomeData
import com.xiuci.xcagi.mobile.core.model.AiGroupCreateBody
import com.xiuci.xcagi.mobile.core.model.AiGroupDto
import com.xiuci.xcagi.mobile.core.model.AiGroupMemberBody
import com.xiuci.xcagi.mobile.core.model.AiGroupMessageBody
import com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto
import com.xiuci.xcagi.mobile.core.model.AiGroupPostData
import com.xiuci.xcagi.mobile.core.model.ClaudeSuperEmployeeMobileMessageBody
import com.xiuci.xcagi.mobile.core.model.CodexSuperEmployeeMobileMessageBody
import com.xiuci.xcagi.mobile.core.model.CursorSuperEmployeeMobileMessageBody
import com.xiuci.xcagi.mobile.core.model.GitBranchDto
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.core.model.MarketAuthResponse
import com.xiuci.xcagi.mobile.core.model.MarketLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketPasswordLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketRegisterBody
import com.xiuci.xcagi.mobile.core.model.MarketSendCodeBody
import com.xiuci.xcagi.mobile.core.model.MobileLoginData
import com.xiuci.xcagi.mobile.core.model.ModIndustry
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.PendingNotification
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import com.xiuci.xcagi.mobile.core.model.ModMenuOverride
import com.xiuci.xcagi.mobile.core.model.TraeSuperEmployeeMobileMessageBody
import com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo
import com.xiuci.xcagi.mobile.core.network.ApproveBody
import com.xiuci.xcagi.mobile.core.network.AuthQrConfirmBody
import com.xiuci.xcagi.mobile.core.network.BridgeRespondBody
import com.xiuci.xcagi.mobile.core.model.AppConfigResponse
import com.xiuci.xcagi.mobile.core.model.AccountDeleteBody
import com.xiuci.xcagi.mobile.core.model.AppFeedbackBody
import com.xiuci.xcagi.mobile.core.model.DeviceRegisterBody
import com.xiuci.xcagi.mobile.core.network.FhdApi
import com.xiuci.xcagi.mobile.core.network.ImDirectBody
import com.xiuci.xcagi.mobile.core.network.ImSendBody
import com.xiuci.xcagi.mobile.core.db.ImMessageCacheEntity
import com.xiuci.xcagi.mobile.core.im.ImRepository
import com.xiuci.xcagi.mobile.core.im.ImWebSocketClient
import com.xiuci.xcagi.mobile.core.network.LanScanner
import com.xiuci.xcagi.mobile.core.network.ModstoreApi
import com.xiuci.xcagi.mobile.core.network.MobileLoginRequest
import com.xiuci.xcagi.mobile.core.network.MobilePhoneLoginRequest
import com.xiuci.xcagi.mobile.core.network.MobileRefreshRequest
import com.xiuci.xcagi.mobile.core.network.PairingExchangeBody
import com.xiuci.xcagi.mobile.core.network.RelayBindAccountBody
import com.xiuci.xcagi.mobile.core.network.RelayConfirmBody
import com.xiuci.xcagi.mobile.core.network.RelayConfirmCodeBody
import com.xiuci.xcagi.mobile.core.network.RelayTaskCreateBody
import com.xiuci.xcagi.mobile.core.network.RegisterRequest
import com.xiuci.xcagi.mobile.core.network.RejectBody
import com.xiuci.xcagi.mobile.core.network.WalletBalanceDto
import com.xiuci.xcagi.mobile.core.network.NavMenuData
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.core.network.ServerMode
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.core.network.SseChatClient
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.google.gson.Gson
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.map
import okhttp3.OkHttpClient
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.cancellation.CancellationException

internal object AuthRoutingPolicy {
    fun shouldUseEnterpriseAuthHost(isEnterprise: Boolean, configuredHost: String): Boolean =
        isEnterprise && configuredHost.isNotBlank()

    fun preferredServerModeAfterLogin(isEnterprise: Boolean, configuredHost: String): ServerMode =
        if (shouldUseEnterpriseAuthHost(isEnterprise, configuredHost)) {
            ServerMode.LAN
        } else {
            ServerMode.CLOUD
        }

    fun preferredServerModeAfterLogin(
        isEnterprise: Boolean,
        configuredHost: String,
        currentMode: String,
    ): ServerMode {
        if (isEnterprise && currentMode.trim().lowercase() == "cloud") {
            return ServerMode.CLOUD
        }
        return preferredServerModeAfterLogin(isEnterprise, configuredHost)
    }
}

@Singleton
class XcagiRepository @Inject constructor(
    private val sessionStore: SessionStore,
    private val serverRouter: ServerRouter,
    private val okHttp: OkHttpClient,
    private val sseChat: SseChatClient,
    private val lanScanner: LanScanner,
    private val imWebSocket: ImWebSocketClient,
    private val imRepo: ImRepository,
    private val db: XcagiDatabase,
    private val gson: Gson = Gson(),
) {
    private var fhdApi: FhdApi? = null
    private var modstoreApi: ModstoreApi? = null
    private var cachedFhdBase: String = ""

    suspend fun syncRouterFromStore() {
        serverRouter.fhdHost = sessionStore.fhdHostFlow.first().ifBlank { "127.0.0.1" }
        var mode = sessionStore.serverModeFlow.first()
        if (mode != "cloud" && sessionStore.fhdHostFlow.first().isBlank()) {
            mode = "cloud"
            sessionStore.setServerMode("cloud")
        }
        serverRouter.mode = if (mode == "cloud") ServerMode.CLOUD else ServerMode.LAN
    }

    /**
     * Enterprise phones may keep an old LAN host after the user leaves Wi-Fi.
     * When LAN is selected but unreachable, route product APIs through the
     * configured enterprise relay base instead of retrying 192.168.x.x forever.
     */
    suspend fun preferCloudIfLanUnreachable(): Boolean {
        syncRouterFromStore()
        if (!ProductSkuConfig.isEnterprise) return false
        if (sessionStore.serverModeFlow.first() == "cloud") return false
        val host = sessionStore.fhdHostFlow.first()
        if (host.isBlank()) {
            sessionStore.setServerMode("cloud")
            serverRouter.mode = ServerMode.CLOUD
            return true
        }
        val reachable = checkHealth(host)
        if (reachable) return false
        sessionStore.setServerMode("cloud")
        serverRouter.mode = ServerMode.CLOUD
        return true
    }

    /** 未配置电脑时默认云端独立使用，跳过「必须先连电脑」引导。 */
    suspend fun ensureStandaloneCloudIfFresh() {
        if (!sessionStore.isSetupComplete() && sessionStore.fhdHostFlow.first().isBlank()) {
            sessionStore.setSetupComplete(true)
            sessionStore.setServerMode("cloud")
            serverRouter.mode = ServerMode.CLOUD
        }
    }

    private suspend fun isPcReachable(): Boolean {
        syncRouterFromStore()
        if (sessionStore.serverModeFlow.first() == "cloud") return false
        val host = sessionStore.fhdHostFlow.first()
        return host.isNotBlank() && checkHealth(host)
    }

    private suspend fun authHeader(): String {
        val fhd = sessionStore.fhdAccessFlow.first()
        if (fhd.isNotBlank()) return "Bearer $fhd"
        val market = sessionStore.marketAccessToken()
        return if (market.isNotBlank()) "Bearer $market" else ""
    }

    private suspend fun bearer(): String = authHeader()

    /**
     * LLM 对话专用鉴权头。
     *
     * 后端 /api/ai/chat/stream 最终会调用 MODstore LLM 上游，MODstore 只认 market token。
     * 移动端默认的 FHD Mobile JWT 无法直接调用 MODstore，后端需要从 session 表查 market token，
     * 查不到会 fallback 到 latest_session_market_token()（有越权风险）。
     *
     * 因此移动端 chat 请求必须优先携带 market token，让后端走透传路径，
     * 仅在 market token 缺失时才 fallback 到 FHD JWT（后端会尝试 session 查找）。
     */
    private suspend fun authHeaderForChat(): String = refreshChatBearer()

    private suspend fun refreshFhdAccessToken(): Boolean {
        val refresh = sessionStore.fhdRefreshToken()
        if (refresh.isBlank()) return false
        return try {
            syncRouterFromStore()
            val response = fhd().mobileRefresh(MobileRefreshRequest(refresh))
            val access = response.data?.access_token?.trim().orEmpty()
            if (!response.success || access.isBlank()) {
                false
            } else {
                sessionStore.setFhdTokens(
                    access = access,
                    refresh = response.data?.refresh_token.orEmpty(),
                )
                true
            }
        } catch (_: Exception) {
            false
        }
    }

    private suspend fun refreshChatBearer(): String {
        val handoff = syncMarketSessionHandoff()
        var market = sessionStore.marketAccessToken()
        if (handoff.isSuccess && market.isNotBlank()) return "Bearer $market"

        if (refreshFhdAccessToken()) {
            val refreshedHandoff = syncMarketSessionHandoff()
            market = sessionStore.marketAccessToken()
            if (refreshedHandoff.isSuccess && market.isNotBlank()) return "Bearer $market"
        }

        if (market.isNotBlank()) return "Bearer $market"
        val fhd = sessionStore.fhdAccessFlow.first()
        return if (fhd.isNotBlank()) "Bearer $fhd" else ""
    }

    suspend fun hasNativeFhdAuth(): Boolean = sessionStore.fhdAccessFlow.first().isNotBlank()

    private suspend fun userId(): Int = sessionStore.userIdFlow.first()

    private suspend fun cachedApprovalItems(): List<ListItem> =
        db.approvalDao().all().mapNotNull { row ->
            try {
                @Suppress("UNCHECKED_CAST")
                val payload = gson.fromJson(row.json, Map::class.java) as? Map<String, Any?> ?: emptyMap()
                ListItem(
                    id = row.requestId.toString(),
                    title = row.title.ifBlank { "审批 #${row.requestId}" },
                    subtitle = listOf(row.status, "离线缓存").filter { it.isNotBlank() }.joinToString(" · "),
                    payload = payload,
                )
            } catch (_: Exception) {
                null
            }
        }

    private suspend fun cachedShipmentItems(): List<ListItem> =
        db.shipmentDao().all().mapNotNull { row ->
            try {
                @Suppress("UNCHECKED_CAST")
                val payload = gson.fromJson(row.json, Map::class.java) as? Map<String, Any?> ?: emptyMap()
                ListItem(
                    id = row.shipmentId.toString(),
                    title = row.orderNumber.ifBlank { "发货 #${row.shipmentId}" },
                    subtitle = listOf(row.status, "离线缓存").filter { it.isNotBlank() }.joinToString(" · "),
                    payload = payload,
                )
            } catch (_: Exception) {
                null
            }
        }

    private fun fhd(): FhdApi {
        val base = serverRouter.fhdBaseUrl()
        if (fhdApi == null || cachedFhdBase != base) {
            cachedFhdBase = base
            fhdApi = Retrofit.Builder().baseUrl(base).client(okHttp)
                .addConverterFactory(GsonConverterFactory.create()).build()
                .create(FhdApi::class.java)
        }
        return fhdApi!!
    }

    private fun modstore(): ModstoreApi {
        val base = serverRouter.modstoreBaseUrl()
        return modstoreApi ?: Retrofit.Builder().baseUrl(base).client(okHttp)
            .addConverterFactory(GsonConverterFactory.create()).build()
            .create(ModstoreApi::class.java).also { modstoreApi = it }
    }

    private fun fhdForBase(baseUrl: String): FhdApi {
        val normalized = baseUrl.trim().ifBlank { serverRouter.enterpriseFhdBaseUrl() }.trimEnd('/') + "/"
        return Retrofit.Builder().baseUrl(normalized).client(okHttp)
            .addConverterFactory(GsonConverterFactory.create()).build()
            .create(FhdApi::class.java)
    }

    suspend fun checkHealth(host: String? = null): Boolean {
        syncRouterFromStore()
        if (host.isNullOrBlank() && ProductSkuConfig.isEnterprise && serverRouter.mode == ServerMode.CLOUD) {
            return try {
                fhd().mobileHealth().success
            } catch (_: Exception) {
                false
            }
        }
        val h = host ?: serverRouter.fhdHost
        return lanScanner.probeHealth(h.substringBefore(':').trim())
    }

    suspend fun scanLan(prefix: String): List<String> = lanScanner.scanSubnet(prefix)

    private fun normalizeAccountKind(raw: String): String =
            raw.trim().lowercase().ifBlank { ProductSkuConfig.accountKind }

    private fun hostPortFromApiBase(apiBaseUrl: String): Pair<String, Int> {
        val raw = apiBaseUrl.trim()
        if (raw.isBlank()) return "" to 0
        val url = raw.toHttpUrlOrNull() ?: "http://${raw.trimStart('/')}".toHttpUrlOrNull()
        return if (url == null) {
            "" to 0
        } else {
            url.host to url.port
        }
    }

    private fun compactHostPort(host: String, port: Int): String {
        val clean = host.trim().removePrefix("http://").removePrefix("https://").trimEnd('/')
        val hostPart = clean.substringBefore('/').substringBefore('?')
        val bare = hostPart.substringBefore(':').trim()
        val resolvedPort = hostPart.substringAfter(':', "").toIntOrNull() ?: port
        return if (resolvedPort in 1..65535) "$bare:$resolvedPort" else bare
    }

    private fun isLoopbackHost(host: String): Boolean {
        val bare =
            host.trim()
                .removePrefix("http://")
                .removePrefix("https://")
                .substringBefore('/')
                .substringBefore('?')
                .substringBefore(':')
                .lowercase()
        return bare == "localhost" || bare == "0.0.0.0" || bare.startsWith("127.")
    }

    private suspend fun unusablePhoneLanHostMessage(): String? {
        val mode = sessionStore.serverModeFlow.first()
        val host = sessionStore.fhdHostFlow.first()
        if (mode == "cloud" || host.isBlank() || !isLoopbackHost(host)) return null
        return "手机端不能使用电脑的 ${host.substringBefore('/')}。请在电脑端重新生成绑定二维码，或填写电脑局域网 IP。"
    }

    private fun isEnterpriseAccountKind(kind: String): Boolean = when (normalizeAccountKind(kind)) {
        "enterprise", "admin", "admin_portal" -> true
        else -> false
    }

    private fun isAdminRole(raw: String): Boolean = normalizeAccountKind(raw).contains("admin")

    private suspend fun primeFhdCsrf() {
        try {
            fhd().mobileHealth()
        } catch (_: Exception) {
        }
    }

    private fun loginErrorMessage(error: Throwable, accountKind: String): String {
        val http = error as? HttpException
        return when (http?.code()) {
            403 -> "服务器拒绝登录请求。请先扫码绑定后台/电脑执行端，或确认服务器已开放移动端登录。"
            500 -> "服务器登录接口异常，请稍后重试或切换到已绑定的后台地址。"
            else -> error.message ?: if (normalizeAccountKind(accountKind) == "admin") {
                "服务器后台登录失败"
            } else {
                "登录失败"
            }
        }
    }

    private fun resolveAccountKindFromSignals(
            accountKind: String?,
            role: String? = null,
            defaultKind: String = ProductSkuConfig.accountKind,
    ): String {
        val normalized = normalizeAccountKind(accountKind.orEmpty())
        val normalizedDefault = normalizeAccountKind(defaultKind)
        return when {
            isEnterpriseAccountKind(normalized) -> if (normalized == "admin_portal") "admin" else normalized
            isAdminRole(role.orEmpty()) -> "admin"
            normalized == "enterprise" -> "enterprise"
            normalized == "personal" -> if (isAdminRole(normalizedDefault)) "admin" else "personal"
            else -> normalizedDefault
        }
    }

    private suspend fun applyMobileLoginData(
        data: MobileLoginData,
        fallbackUsername: String,
        defaultKind: String = ProductSkuConfig.accountKind,
    ): String {
        val resolvedKind = resolveAccountKindFromSignals(
            data.account_kind,
            data.user?.role,
            defaultKind,
        )
        sessionStore.setAccountKind(resolvedKind)
        sessionStore.saveFhdAuth(
            data.access_token.orEmpty(),
            data.refresh_token.orEmpty(),
            data.session_id.orEmpty(),
            data.user?.username ?: fallbackUsername,
            userId = data.user?.id ?: 0,
        )
        if (!data.market_access_token.isNullOrBlank()) {
            sessionStore.setMarketTokens(
                data.market_access_token,
                data.market_refresh_token.orEmpty(),
            )
        }
        refreshMe(resolvedKind)
        registerDeviceToken()
        syncMarketSessionHandoff()
        return data.user?.display_name?.takeIf { it.isNotBlank() } ?: fallbackUsername
    }

    suspend fun loginFhd(
            username: String,
            password: String,
            accountKind: String = ProductSkuConfig.accountKind,
    ): Result<String> = try {
        syncRouterFromStore()
        val normalizedKind = normalizeAccountKind(accountKind)
        primeFhdCsrf()
        val res = fhd().mobileLogin(
            MobileLoginRequest(username, password, normalizedKind),
        )
        if (!res.success || res.data?.access_token.isNullOrBlank()) {
            Result.failure(Exception(res.message.ifBlank { "登录失败" }))
        } else {
            val d = res.data ?: return Result.failure(Exception("登录响应为空"))
            val resolvedKind = resolveAccountKindFromSignals(
                d.account_kind,
                d.user?.role,
                normalizedKind,
            )
            sessionStore.setAccountKind(resolvedKind)
            sessionStore.saveFhdAuth(
                d.access_token!!, d.refresh_token ?: "", d.session_id ?: "", d.user?.username ?: username,
                userId = d.user?.id ?: 0,
            )
            if (!d.market_access_token.isNullOrBlank()) {
                sessionStore.setMarketTokens(
                    d.market_access_token,
                    d.market_refresh_token.orEmpty(),
                )
            }
            refreshMe(resolvedKind)
            registerDeviceToken()
            syncMarketSessionHandoff()
            Result.success(d.user?.display_name ?: username)
        }
    } catch (e: Exception) {
        Result.failure(Exception(loginErrorMessage(e, accountKind)))
    }

    /** 从 FHD 会话拉取 MODstore token，供企业端模块 WebView 注入。 */
    suspend fun syncMarketSessionHandoff(): Result<Unit> = try {
        syncRouterFromStore()
        val res = fhd().marketSessionHandoff()
        if (res["success"] == false) {
            Result.failure(Exception(res["message"]?.toString() ?: "未绑定市场账号"))
        } else {
            @Suppress("UNCHECKED_CAST")
            val data = res["data"] as? Map<String, Any?> ?: emptyMap()
            val access = data["market_access_token"]?.toString()?.trim().orEmpty()
            val refresh = data["market_refresh_token"]?.toString()?.trim().orEmpty()
            if (access.isNotBlank()) {
                sessionStore.setMarketTokens(access, refresh)
            }
            Result.success(Unit)
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun marketTokensForWeb(): Pair<String, String> {
        val access = sessionStore.marketAccessToken().ifBlank {
            sessionStore.fhdAccessFlow.first()
        }
        val refresh = sessionStore.marketRefreshToken()
        return access to refresh
    }

    suspend fun register(
        username: String,
        password: String,
        email: String,
        industryId: String = "通用",
        budgetRange: String = "",
    ): Result<String> {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val primary = registerOnFhd(username, password, email, industryId, budgetRange)
        if (primary.isSuccess) return primary
        if (!ProductSkuConfig.isEnterprise && !isPcReachable()) {
            val cloud = registerOnCloud(username, password, email)
            if (cloud.isSuccess) return Result.success(username)
        }
        return primary
    }

    private suspend fun registerOnFhd(
        username: String,
        password: String,
        email: String,
        industryId: String,
        budgetRange: String,
    ): Result<String> = try {
        val res = fhd().mobileRegister(
            RegisterRequest(
                username = username,
                password = password,
                email = email.ifBlank { null },
                industry_id = industryId.ifBlank { "通用" },
                budget_range = budgetRange.ifBlank { null },
                account_kind = ProductSkuConfig.accountKind,
            )
        )
        if (!res.success || res.data?.access_token.isNullOrBlank()) {
            Result.failure(Exception(res.message.ifBlank { "注册失败" }))
        } else {
            val data = res.data ?: return Result.failure(Exception("注册响应为空"))
            Result.success(applyMobileLoginData(data, username, ProductSkuConfig.accountKind))
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    private suspend fun registerOnCloud(username: String, password: String, email: String): Result<Unit> {
        if (email.isBlank() || !email.contains("@")) {
            return Result.failure(Exception("远程注册需填写有效邮箱；也可直接使用手机号登录"))
        }
        return try {
            val res = modstore().register(MarketRegisterBody(username, password, email.trim()))
            if (!res.isAuthenticated()) {
                val hint = res.message?.takeIf { it.isNotBlank() }
                    ?: "请先在官网获取邮箱验证码，或改用手机号登录"
                Result.failure(Exception(hint))
            } else {
                applyMarketAuth(res, username)
                Result.success(Unit)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshMe(preferredKind: String = ProductSkuConfig.accountKind): String? {
        try {
            val me = fhd().me()
            val uid = me.data?.user?.id ?: 0
            if (uid > 0) sessionStore.setUserId(uid)
            val avatarUrl = me.data?.user?.avatar_url
            val currentKind = sessionStore.accountKindFlow.first()
            if (currentKind.isNotBlank()) return avatarUrl
            val resolvedKind = resolveAccountKindFromSignals(
                me.data?.account_kind,
                me.data?.user?.role,
                preferredKind,
            )
            sessionStore.setAccountKind(resolvedKind)
            return avatarUrl
        } catch (_: Exception) {
            return null
        }
    }

    suspend fun fetchAppConfig(): Result<AppConfigResponse> = try {
        val cfg = modstore().appConfig(
            sku = BuildConfig.PRODUCT_SKU,
            currentVersionCode = BuildConfig.VERSION_CODE,
        )
        Result.success(cfg)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun deleteAccount(password: String): Result<Unit> = try {
        modstore().deleteAccount(AccountDeleteBody(password))
        logout()
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun exportAccountData(): Result<Map<String, Any?>> = try {
        Result.success(modstore().exportAccount())
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun submitFeedback(message: String, contact: String = ""): Result<Unit> = try {
        modstore().submitFeedback(
            AppFeedbackBody(
                message = message,
                contact = contact,
                app_version = BuildConfig.VERSION_NAME,
                sku = BuildConfig.PRODUCT_SKU,
            ),
        )
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun registerDeviceToken(
        pushProvider: String = "fcm",
        pushToken: String? = null,
    ) {
        val token = pushToken?.trim().orEmpty().ifBlank { sessionStore.fcmToken() }
        if (token.isBlank()) return
        sessionStore.setFcmToken(token)
        try {
            fhd().registerDevice(
                DeviceRegisterBody(
                    fcm_token = token,
                    push_provider = pushProvider,
                    push_token = token,
                    product_sku = BuildConfig.PRODUCT_SKU,
                    device_label = "Android-${Build.MODEL}",
                ),
            )
        } catch (_: Exception) {
        }
    }

    /** 自建推送后台通道：拉取未送达的离线通知（服务端已标记 delivered）。失败返回空。 */
    suspend fun fetchPendingNotifications(): List<PendingNotification> =
        try {
            fhd().pendingNotifications().data?.notifications ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }

    suspend fun pairingExchange(
        nonce: String = "",
        code: String = "",
        exchangeHost: String = "",
        exchangePort: Int = 0,
    ): Result<Pair<String, Int>> {
        val targetHost = exchangeHost.trim()
        val body = PairingExchangeBody(nonce = nonce, code = code)
        val previousHost = sessionStore.fhdHostFlow.first()
        val previousMode = sessionStore.serverModeFlow.first()
        val primary =
            try {
                if (targetHost.isNotBlank()) {
                    val hostWithPort = if (exchangePort > 0 && ":" !in targetHost) {
                        "$targetHost:$exchangePort"
                    } else {
                        targetHost
                    }
                    sessionStore.setFhdHost(hostWithPort)
                    sessionStore.setServerMode("lan")
                    serverRouter.fhdHost = hostWithPort
                    serverRouter.mode = ServerMode.LAN
                }
                syncRouterFromStore()
                completePairingExchange(fhd(), body)
            } catch (e: Exception) {
                sessionStore.setFhdHost(previousHost)
                sessionStore.setServerMode(previousMode)
                serverRouter.fhdHost = previousHost
                serverRouter.mode = if (previousMode == "cloud") ServerMode.CLOUD else ServerMode.LAN
                Result.failure(e)
            }

        if (primary.isSuccess) return primary

        if (targetHost.isBlank() && code.isNotBlank() && sessionStore.fhdHostFlow.first().isBlank()) {
            tryDebugBootstrapPairingCode(code).fold(
                onSuccess = { return Result.success(it) },
                onFailure = { /* fall through to the primary error */ },
            )
        }
        return primary
    }

    suspend fun relayPairingConfirm(
        relayId: String,
        code: String,
        relayBaseUrl: String = "",
    ): Result<Pair<String, Int>> {
        val cleanRelayId = relayId.trim()
        val cleanCode = code.trim()
        if (cleanRelayId.isBlank() || cleanCode.isBlank()) {
            return Result.failure(Exception("中继二维码缺少绑定信息"))
        }
        return try {
            serverRouter.mode = ServerMode.CLOUD
            sessionStore.setServerMode("cloud")
            sessionStore.setFhdHost("")
            val api = fhdForBase(relayBaseUrl)
            val r = api.relayConfirm(RelayConfirmBody(relay_id = cleanRelayId, code = cleanCode))
            if (!r.success) {
                Result.failure(Exception(r.message.ifBlank { "中继绑定失败" }))
            } else {
                val data = r.data ?: emptyMap()
                saveRelayAuthFromMap(data)
                persistRelayBindingMeta(cleanRelayId, data)
                sessionStore.setFhdHost("")
                sessionStore.setSetupComplete(true)
                Result.success("relay" to 0)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun relayPairingConfirmCode(
        code: String,
        relayBaseUrl: String = "",
    ): Result<Pair<String, Int>> {
        val cleanCode = code.trim()
        if (cleanCode.length != 6 || !cleanCode.all { it.isDigit() }) {
            return Result.failure(Exception("请输入 6 位设备码"))
        }
        return try {
            serverRouter.mode = ServerMode.CLOUD
            sessionStore.setServerMode("cloud")
            sessionStore.setFhdHost("")
            val api = fhdForBase(relayBaseUrl)
            val r = api.relayConfirmCode(RelayConfirmCodeBody(code = cleanCode))
            if (!r.success) {
                Result.failure(Exception(r.message.ifBlank { "设备码绑定失败" }))
            } else {
                val data = r.data ?: emptyMap()
                val relayId = data["relay_id"]?.toString().orEmpty()
                    .ifBlank {
                        @Suppress("UNCHECKED_CAST")
                        ((data["desktop"] as? Map<String, Any?>)?.get("relay_id")?.toString()).orEmpty()
                    }
                if (relayId.isBlank()) {
                    Result.failure(Exception("设备码绑定响应缺少 relay_id"))
                } else {
                    saveRelayAuthFromMap(data)
                    persistRelayBindingMeta(relayId, data)
                    sessionStore.setFhdHost("")
                    sessionStore.setSetupComplete(true)
                    Result.success("relay" to 0)
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun nestedMap(data: Map<String, Any?>, key: String): Map<String, Any?> {
        @Suppress("UNCHECKED_CAST")
        return data[key] as? Map<String, Any?> ?: emptyMap()
    }

    private fun relayIdFromBindingData(data: Map<String, Any?>): String =
        data["relay_id"]?.toString()?.trim().orEmpty()
            .ifBlank { nestedMap(data, "relay")["relay_id"]?.toString()?.trim().orEmpty() }
            .ifBlank { nestedMap(data, "desktop")["relay_id"]?.toString()?.trim().orEmpty() }

    private fun relayBaseUrlFromBindingData(data: Map<String, Any?>): String =
        data["relay_base_url"]?.toString()?.trim().orEmpty()
            .ifBlank { nestedMap(data, "relay")["relay_base_url"]?.toString()?.trim().orEmpty() }
            .ifBlank { nestedMap(data, "desktop")["relay_base_url"]?.toString()?.trim().orEmpty() }

    suspend fun bindRelayDesktopByAccount(
        relayId: String,
        relayBaseUrl: String = "",
    ): Result<String> {
        val cleanRelayId = relayId.trim()
        if (cleanRelayId.isBlank()) return Result.failure(Exception("缺少 relay_id"))
        return try {
            val api = fhdForBase(relayBaseUrl)
            val r = api.relayBindAccount(RelayBindAccountBody(relay_id = cleanRelayId))
            if (!r.success) {
                Result.failure(Exception(r.message.ifBlank { "账号绑定电脑执行端失败" }))
            } else {
                val data = r.data ?: emptyMap()
                persistRelayBindingMeta(cleanRelayId, data)
                Result.success(cleanRelayId)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun bindRelayDesktopByAccountFromMap(data: Map<String, Any?>): Boolean {
        val relayId = relayIdFromBindingData(data)
        if (relayId.isBlank()) return false
        val relayBaseUrl = relayBaseUrlFromBindingData(data)
        return bindRelayDesktopByAccount(relayId, relayBaseUrl).isSuccess
    }

    @Suppress("UNCHECKED_CAST")
    private fun relayDesktopRows(data: Map<String, Any?>?): List<Map<String, Any?>> {
        val raw = data?.get("items") ?: data?.get("desktops") ?: data?.get("results")
        return (raw as? List<*>)?.mapNotNull { it as? Map<String, Any?> } ?: emptyList()
    }

    private fun relayDesktopSortKey(row: Map<String, Any?>): String =
        row["last_seen_at"]?.toString()?.trim().orEmpty()
            .ifBlank { row["updated_at"]?.toString()?.trim().orEmpty() }
            .ifBlank { row["paired_at"]?.toString()?.trim().orEmpty() }

    private fun relayDesktopIsDispatchable(row: Map<String, Any?>): Boolean {
        val relayId = row["relay_id"]?.toString()?.trim().orEmpty()
        val status = row["status"]?.toString()?.trim()?.lowercase().orEmpty()
        return relayId.isNotBlank() && status == "paired"
    }

    private suspend fun latestAccountRelayDesktop(): Map<String, Any?>? =
        try {
            refreshFhdAccessToken()
            val response = fhd().relayDesktops()
            if (!response.success) {
                null
            } else {
                relayDesktopRows(response.data)
                    .filter { relayDesktopIsDispatchable(it) }
                    .maxByOrNull { relayDesktopSortKey(it) }
            }
        } catch (_: Exception) {
            null
        }

    private suspend fun relayIdForSuperEmployeeDispatch(): String {
        val storedRelayId = sessionStore.relayDesktopId().trim()
        val latest = latestAccountRelayDesktop() ?: return storedRelayId
        val latestRelayId = latest["relay_id"]?.toString()?.trim().orEmpty()
        if (latestRelayId.isBlank()) return storedRelayId
        if (latestRelayId != storedRelayId) {
            persistRelayBindingMeta(latestRelayId, latest)
            sessionStore.clearInflightRelayTasks()
        }
        return latestRelayId
    }

    private suspend fun saveRelayAuthFromMap(data: Map<String, Any?>) {
        val access = data["access_token"]?.toString()?.trim().orEmpty()
        if (access.isBlank()) return
        val refresh = data["refresh_token"]?.toString()?.trim().orEmpty()
        val sessionId =
            data["session_id"]?.toString()?.trim().orEmpty().ifBlank {
                data["session_token"]?.toString()?.trim().orEmpty()
            }
        val accountKind = data["account_kind"]?.toString()?.trim().orEmpty().ifBlank { "enterprise" }
        @Suppress("UNCHECKED_CAST")
        val user = data["user"] as? Map<String, Any?>
        val username =
            user?.get("username")?.toString()?.trim().orEmpty()
                .ifBlank { user?.get("display_name")?.toString()?.trim().orEmpty() }
                .ifBlank { "mobile" }
        val userId =
            when (val raw = user?.get("id")) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: 0
                else -> 0
            }
        val relayBaseUrl = data["relay_base_url"]?.toString()?.trim().orEmpty()
        val localBaseUrl = data["local_base_url"]?.toString()?.trim().orEmpty()
        val relaySessionToken =
            data["session_token"]?.toString()?.trim().orEmpty().ifBlank { sessionId }
        val accountId = data["account_id"]?.toString()?.trim().orEmpty().ifBlank { userId.toString() }
        val tenantId = data["tenant_id"]?.toString()?.trim().orEmpty()
        val pairedAt = data["paired_at"]?.toString()?.trim().orEmpty()
        sessionStore.setAccountKind(accountKind)
        if (relayBaseUrl.isNotBlank()) sessionStore.setRelayBaseUrl(relayBaseUrl)
        if (localBaseUrl.isNotBlank()) sessionStore.setLocalBaseUrl(localBaseUrl)
        if (relaySessionToken.isNotBlank()) sessionStore.setRelaySessionToken(relaySessionToken)
        if (accountId.isNotBlank()) sessionStore.setRelayAccountId(accountId)
        if (tenantId.isNotBlank()) sessionStore.setRelayTenantId(tenantId)
        if (pairedAt.isNotBlank()) sessionStore.setRelayPairedAt(pairedAt)
        sessionStore.saveFhdAuth(
            access = access,
            refresh = refresh,
            sessionId = sessionId,
            username = username,
            userId = userId,
        )
    }

    private suspend fun persistRelayBindingMeta(
        relayId: String,
        data: Map<String, Any?>,
    ) {
        @Suppress("UNCHECKED_CAST")
        val desktop = data["desktop"] as? Map<String, Any?>
        sessionStore.setRelayDesktopId(relayId)
        sessionStore.setRelayBaseUrl(
            data["relay_base_url"]?.toString()?.trim().orEmpty().ifBlank {
                desktop?.get("relay_base_url")?.toString()?.trim().orEmpty()
            },
        )
        sessionStore.setLocalBaseUrl(
            data["local_base_url"]?.toString()?.trim().orEmpty().ifBlank {
                desktop?.get("local_base_url")?.toString()?.trim().orEmpty()
            },
        )
        val relaySessionToken = data["session_token"]?.toString()?.trim().orEmpty()
        if (relaySessionToken.isNotBlank()) {
            sessionStore.setRelaySessionToken(relaySessionToken)
        }
        val accountId = data["account_id"]?.toString()?.trim().orEmpty()
        if (accountId.isNotBlank()) {
            sessionStore.setRelayAccountId(accountId)
        }
        val tenantId = data["tenant_id"]?.toString()?.trim().orEmpty()
        if (tenantId.isNotBlank()) {
            sessionStore.setRelayTenantId(tenantId)
        }
        data["paired_at"]?.toString()?.trim().orEmpty().ifBlank {
            desktop?.get("paired_at")?.toString()?.trim().orEmpty()
        }.takeIf { it.isNotBlank() }?.let {
            sessionStore.setRelayPairedAt(it)
        }
    }

    private suspend fun completePairingExchange(
        api: FhdApi,
        body: PairingExchangeBody,
    ): Result<Pair<String, Int>> {
        val r = api.pairingExchange(body)
        if (!r.success) return Result.failure(Exception(r.message.ifBlank { "设备配对失败" }))
        val d = r.data ?: return Result.failure(Exception(r.message.ifBlank { "设备配对失败" }))
        val baseUrl =
            d["api_base_url"]?.toString()?.trim().orEmpty()
                .ifBlank { d["base_url"]?.toString()?.trim().orEmpty() }
        val fromBase = hostPortFromApiBase(baseUrl)
        val host = d["host"]?.toString()?.trim().orEmpty().ifBlank { fromBase.first }
        if (host.isBlank()) return Result.failure(Exception("配对响应缺少 host"))
        val port = (d["port"] as? Number)?.toInt()
            ?: d["port"]?.toString()?.toIntOrNull()
            ?: fromBase.second.takeIf { it > 0 }
            ?: BuildConfig.FHD_DEFAULT_PORT
        val hostWithPort = compactHostPort(host, port)
        sessionStore.setRelayDesktopId("")
        sessionStore.clearInflightRelayTasks()
        val relayBound = bindRelayDesktopByAccountFromMap(d)
        sessionStore.setFhdHost(hostWithPort)
        sessionStore.setServerMode("lan")
        serverRouter.fhdHost = hostWithPort
        serverRouter.mode = ServerMode.LAN
        saveRelayAuthFromMap(d)
        if (!relayBound) {
            sessionStore.setRelayDesktopId("")
        }
        return Result.success(host to port)
    }

    private suspend fun tryDebugBootstrapPairingCode(code: String): Result<Pair<String, Int>> {
        if (!BuildConfig.DEBUG) {
            return Result.failure(Exception("未配置电脑地址"))
        }
        val candidates =
            listOf(
                "10.0.2.2:5112",
                "10.0.2.2:${BuildConfig.FHD_DEFAULT_PORT}",
            ).distinct()
        var last: Throwable? = null
        for (candidate in candidates) {
            val api =
                Retrofit.Builder()
                    .baseUrl("http://$candidate/")
                    .client(okHttp)
                    .addConverterFactory(GsonConverterFactory.create())
                    .build()
                    .create(FhdApi::class.java)
            val result = completePairingExchange(api, PairingExchangeBody(code = code))
            if (result.isSuccess) return result
            last = result.exceptionOrNull()
        }
        return Result.failure(Exception(last?.message ?: "配对码无效或已过期"))
    }

    suspend fun confirmAuthQr(
        qrId: String,
        username: String,
        password: String,
        accountKind: String = "",
    ): Result<Unit> {
        return try {
            syncRouterFromStore()
            val targetKind =
                normalizeAccountKind(
                    accountKind.ifBlank {
                        sessionStore.accountKindFlow.first().ifBlank { ProductSkuConfig.accountKind }
                    },
                )
            primeFhdCsrf()
            val r = fhd().authQrConfirm(
                AuthQrConfirmBody(
                    qr_id = qrId,
                    username = username,
                    password = password,
                    account_kind = targetKind,
                ),
            )
            if (r.success != true) {
                Result.failure(Exception(r.message ?: "扫码登录确认失败"))
            } else {
                Result.success(Unit)
            }
        } catch (e: Exception) {
            Result.failure(Exception(loginErrorMessage(e, accountKind.ifBlank { ProductSkuConfig.accountKind })))
        }
    }

    suspend fun requestLanAccess(note: String): Result<String> = try {
        syncRouterFromStore()
        fhd().lanAccessRequest(AccessRequestPayload("Android-${Build.MODEL}", note))
        Result.success("已提交 LAN 入网申请")
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun sendMarketCode(phone: String) = try {
        modstore().sendPhoneCode(MarketSendCodeBody(phone))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    private suspend fun resolveMarketUserIsEnterprise(
        accountKind: String,
        userIsEnterprise: Boolean? = null,
    ): Boolean {
        val normalized = normalizeAccountKind(accountKind)
        if (normalized == "admin" || normalized == "admin_portal") return true
        userIsEnterprise?.let { return it }
        return try {
            modstore().authMe().is_enterprise
        } catch (_: Exception) {
            false
        }
    }

    private fun validateSkuAccount(isEnterprise: Boolean): Result<Unit> {
        if (ProductSkuConfig.isEnterprise && !isEnterprise) {
            return Result.failure(Exception("该账号为个人账号，请安装并使用「XCAGI 个人版」"))
        }
        if (ProductSkuConfig.isPersonal && isEnterprise) {
            return Result.failure(Exception("该账号为企业账号，请安装并使用「XCAGI 企业版」"))
        }
        return Result.success(Unit)
    }

    private suspend fun applyMarketAuth(res: MarketAuthResponse, displayName: String): Result<String> {
        val token = res.accessToken()
        if (!res.isAuthenticated() || token.isNullOrBlank()) {
            return Result.failure(Exception(res.message ?: "登录失败"))
        }
        sessionStore.setMarketTokens(token, res.refresh_token?.trim().orEmpty())
        val resolvedKind = normalizeAccountKind(res.account_kind.orEmpty())
        val marketKind = if (resolvedKind.isBlank()) {
            when {
                res.market_is_admin -> "admin"
                res.is_enterprise -> "enterprise"
                else -> ProductSkuConfig.accountKind
            }
        } else {
            resolvedKind
        }
        val isEnterprise = resolveMarketUserIsEnterprise(
            accountKind = marketKind,
            userIsEnterprise = res.userIsEnterprise(),
        ) || isEnterpriseAccountKind(marketKind) || res.market_is_admin
        sessionStore.setAccountKind(
            when {
                res.market_is_admin -> "admin"
                isEnterprise -> "enterprise"
                else -> "personal"
            },
        )
        validateSkuAccount(isEnterprise).getOrElse { return Result.failure(it) }
        sessionStore.setDisplayName(displayName)
        sessionStore.setSetupComplete(true)
        sessionStore.setServerMode("cloud")
        serverRouter.mode = ServerMode.CLOUD
        syncRouterFromStore()
        bindMarketTokenToPcIfOnline(token)
        return Result.success("已登录 MODstore（与官网账号互通）")
    }

    /** 电脑在线时把市场 token 写入 FHD 会话，便于局域网能力共用同一账号。 */
    private suspend fun bindMarketTokenToPcIfOnline(marketToken: String) {
        if (!checkHealth()) return
        try {
            val res = fhd().marketAccountSync(mapOf("token" to marketToken))
            if (res["success"] == false) {
                return
            }
        } catch (_: Exception) {
        }
    }

    suspend fun loginMarketPhone(phone: String, code: String): Result<String> {
        return try {
            if (ProductSkuConfig.isEnterprise || isPcReachable()) {
                primeFhdCsrf()
                val res = fhd().mobileLoginWithPhone(
                    MobilePhoneLoginRequest(
                        phone = phone,
                        code = code,
                        account_kind = ProductSkuConfig.accountKind,
                    ),
                )
                if (!res.success || res.data?.access_token.isNullOrBlank()) {
                    Result.failure(Exception(res.message.ifBlank { "手机验证码登录失败" }))
                } else {
                    val d = res.data ?: return Result.failure(Exception("登录响应为空"))
                    val resolvedKind = resolveAccountKindFromSignals(
                        d.account_kind,
                        d.user?.role,
                        ProductSkuConfig.accountKind,
                    )
                    sessionStore.setAccountKind(resolvedKind)
                    sessionStore.saveFhdAuth(
                        d.access_token!!,
                        d.refresh_token ?: "",
                        d.session_id ?: "",
                        d.user?.username ?: phone,
                        userId = d.user?.id ?: 0,
                    )
                    refreshMe(resolvedKind)
                    syncMarketSessionHandoff()
                    Result.success(d.user?.display_name ?: phone)
                }
            } else {
                val res = modstore().loginWithPhoneCode(MarketLoginBody(phone, code))
                applyMarketAuth(res, phone)
            }
        } catch (e: Exception) {
            Result.failure(Exception(loginErrorMessage(e, ProductSkuConfig.accountKind)))
        }
    }

    suspend fun loginMarketPassword(
        username: String,
        password: String,
        accountKind: String = ProductSkuConfig.accountKind,
    ): Result<String> = try {
        val normalizedKind = normalizeAccountKind(accountKind)
        val res = modstore().loginWithPassword(
            MarketPasswordLoginBody(
                username = username,
                password = password,
                account_kind = normalizedKind,
            ),
        )
        applyMarketAuth(res, username)
    } catch (e: Exception) {
        Result.failure(e)
    }

    /**
     * 账号密码登录：电脑在线走 FHD（并 session-handoff 市场 token）；
     * 纯云端走 MODstore 同一套用户名密码。
     */
    suspend fun loginUnified(username: String, password: String): Result<String> {
        return loginUnified(username, password, ProductSkuConfig.accountKind)
    }

    suspend fun loginUnified(
        username: String,
        password: String,
        accountKind: String,
    ): Result<String> {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        unusablePhoneLanHostMessage()?.let { return Result.failure(Exception(it)) }
        return if (ProductSkuConfig.isEnterprise || isPcReachable()) {
            loginFhd(username, password, accountKind)
        } else {
            loginMarketPassword(username, password, accountKind)
        }
    }

    suspend fun loginUnified(username: String, password: String, isAdmin: Boolean): Result<String> {
        val targetKind = if (isAdmin) "admin" else ProductSkuConfig.accountKind
        return loginUnified(username, password, targetKind)
    }

    suspend fun preferredServerModeAfterLogin(): ServerMode =
        AuthRoutingPolicy.preferredServerModeAfterLogin(
            ProductSkuConfig.isEnterprise,
            sessionStore.fhdHostFlow.first(),
            sessionStore.serverModeFlow.first(),
        )

    suspend fun streamChat(
        message: String,
        conversationId: String? = null,
        sessionId: String = "default",
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        syncRouterFromStore()
        cacheChatMessage(sessionId = sessionId, role = "user", text = message)
        val acc = StringBuilder()

        val superEmployeeRelayKind = SuperEmployeeRoutingPolicy.relayKindForConversation(conversationId)
        if (superEmployeeRelayKind != null) {
            val isClaude = conversationId == PinnedIds.CLAUDE
            val isCursor = conversationId == PinnedIds.CURSOR
            val isTrae = conversationId == PinnedIds.TRAE
            val tokenSink: (String) -> Unit = { t -> acc.append(t); onToken(t) }
            // 捕获最终回复用于本地持久化：relay 路径真正的结果经 onDone 下发（不进 acc），
            // 必须在此截获，否则缓存到的只是"思考中…"等状态闲话。
            var finalReply = ""
            val doneSink: (String) -> Unit = { full -> finalReply = full; onDone(full) }
            // 连不到本地 PC 但已配对中继电脑 → 经服务器中继到本地电脑执行（超级员工必须本地设备）。
            val relayId = if (!isPcReachable()) relayIdForSuperEmployeeDispatch() else ""
            if (relayId.isNotBlank()) {
                streamRelayCodexTask(
                    relayId = relayId,
                    message = message,
                    kind = superEmployeeRelayKind,
                    conversationId = conversationId ?: "",
                    onToken = tokenSink,
                    onDone = doneSink,
                    onError = onError,
                )
            } else when {
                isClaude -> streamClaudeSuperEmployeeChat(message = message, onToken = tokenSink, onDone = doneSink, onError = onError)
                isCursor -> streamCursorSuperEmployeeChat(message = message, onToken = tokenSink, onDone = doneSink, onError = onError)
                isTrae -> streamTraeSuperEmployeeChat(message = message, onToken = tokenSink, onDone = doneSink, onError = onError)
                else -> streamCodexSuperEmployeeChat(message = message, onToken = tokenSink, onDone = doneSink, onError = onError)
            }
            val finalText = finalReply.ifBlank { acc.toString() }
            if (finalText.isNotBlank()) {
                cacheChatMessage(sessionId = sessionId, role = "assistant", text = finalText)
            }
            return
        }

        val useCloud = !isPcReachable()
        if (useCloud) {
            preferCloudIfLanUnreachable()
        }
        // 构造上下文：取最近6条对话（与桌面端 useChatRequest.ts slice(-6) 一致）
        val recentMessages = db.chatDao().getBySession(sessionId)
            .takeLast(6)
            .map { row ->
                mapOf(
                    "role" to (row.role.ifBlank { "user" }),
                    "content" to row.text.take(500),
                )
            }
        // industry 由后端根据 session account_kind 自动派生（单一真相源），手机端不传
        sseChat.streamChat(
            message,
            authHeaderForChat(),
            userId(),
            useCloud = useCloud,
            recentMessages = recentMessages,
            refreshBearer = { refreshChatBearer() },
            onToken = { t ->
                acc.append(t)
                onToken(t)
            },
            onDone = { full ->
                val text = full.ifBlank { acc.toString() }
                onDone(text)
            },
            onError = onError,
        )
        val finalText = acc.toString()
        if (finalText.isNotBlank()) {
            cacheChatMessage(sessionId = sessionId, role = "assistant", text = finalText)
        }
    }

    private suspend fun streamCodexSuperEmployeeChat(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        try {
            val statusPrefix = "已提交到超级员工-Codex，正在执行"
            onToken(statusPrefix)
            var emitted = statusPrefix

            val response = fhd().postCodexSuperEmployeeMessage(
                body = CodexSuperEmployeeMobileMessageBody(
                    message = message,
                    body = message,
                    context = mapOf(
                        "source" to "mobile_chat",
                        "client_surface" to "mobile",
                        "mode" to "code",
                    ),
                ),
            )
            if (!response.success) {
                onError(response.message.ifBlank { "超级员工-Codex 调用失败" })
                return
            }

            val requestId = extractDispatchRequestId(response.data)
            val taskId = extractTaskId(response.data)
            val immediate = extractCodexMessageText(response.data, requestId, taskId)
            if (immediate.isNotBlank()) {
                val immediateTrimmed = immediate.trim()
                val delta = immediateTrimmed.removePrefix(emitted)
                if (delta.isNotBlank()) {
                    onToken(delta)
                    emitted = immediateTrimmed
                }
                onDone(immediateTrimmed)
                return
            }

            var finalText = ""
            repeat(60) {
                delay(1000)
                val polled = fetchMatchingCodexMessage(requestId, taskId)
                if (polled.isNotBlank()) {
                    finalText = polled.trim()
                    if (finalText != emitted) {
                        val delta = finalText.removePrefix(emitted)
                        if (delta.isNotBlank()) {
                            onToken(delta)
                        }
                        emitted = finalText
                    }
                    onDone(finalText)
                    return
                }
                val progressText = "已提交到超级员工-Codex，正在执行 $requestId"
                if (progressText != emitted) {
                    onToken("\n$progressText")
                    emitted = progressText
                }
            }

            finalText = "已提交到超级员工-Codex，任务将在电脑端执行后回写。"
            onDone(finalText)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "超级员工-Codex 调用失败")
        }
    }

    // 超级员工-Claude：与 Codex 同构（排比 Para 多设备派工），仅工具/端点不同。
    private suspend fun streamClaudeSuperEmployeeChat(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        try {
            val statusPrefix = "已提交到超级员工-Claude，正在执行"
            onToken(statusPrefix)
            var emitted = statusPrefix

            val response = fhd().postClaudeSuperEmployeeMessage(
                body = ClaudeSuperEmployeeMobileMessageBody(
                    message = message,
                    body = message,
                    context = mapOf(
                        "source" to "mobile_chat",
                        "client_surface" to "mobile",
                        "mode" to "code",
                    ),
                ),
            )
            if (!response.success) {
                onError(response.message.ifBlank { "超级员工-Claude 调用失败" })
                return
            }

            val requestId = extractDispatchRequestId(response.data)
            val taskId = extractTaskId(response.data)
            val immediate = extractCodexMessageText(response.data, requestId, taskId)
            if (immediate.isNotBlank()) {
                val immediateTrimmed = immediate.trim()
                val delta = immediateTrimmed.removePrefix(emitted)
                if (delta.isNotBlank()) {
                    onToken(delta)
                    emitted = immediateTrimmed
                }
                onDone(immediateTrimmed)
                return
            }

            var finalText = ""
            repeat(60) {
                delay(1000)
                val polled = fetchMatchingClaudeMessage(requestId, taskId)
                if (polled.isNotBlank()) {
                    finalText = polled.trim()
                    if (finalText != emitted) {
                        val delta = finalText.removePrefix(emitted)
                        if (delta.isNotBlank()) {
                            onToken(delta)
                        }
                        emitted = finalText
                    }
                    onDone(finalText)
                    return
                }
                val progressText = "已提交到超级员工-Claude，正在执行 $requestId"
                if (progressText != emitted) {
                    onToken("\n$progressText")
                    emitted = progressText
                }
            }

            finalText = "已提交到超级员工-Claude，任务将在电脑端执行后回写。"
            onDone(finalText)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "超级员工-Claude 调用失败")
        }
    }

    // 超级员工-Cursor：与 Codex/Claude 同构（排比 Para 多设备派工），仅工具/端点不同。
    private suspend fun streamCursorSuperEmployeeChat(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        try {
            val statusPrefix = "已提交到超级员工-Cursor，正在执行"
            onToken(statusPrefix)
            var emitted = statusPrefix

            val response = fhd().postCursorSuperEmployeeMessage(
                body = CursorSuperEmployeeMobileMessageBody(
                    message = message,
                    body = message,
                    context = mapOf(
                        "source" to "mobile_chat",
                        "client_surface" to "mobile",
                        "mode" to "code",
                    ),
                ),
            )
            if (!response.success) {
                onError(response.message.ifBlank { "超级员工-Cursor 调用失败" })
                return
            }

            val requestId = extractDispatchRequestId(response.data)
            val taskId = extractTaskId(response.data)
            val immediate = extractCodexMessageText(response.data, requestId, taskId)
            if (immediate.isNotBlank()) {
                val immediateTrimmed = immediate.trim()
                val delta = immediateTrimmed.removePrefix(emitted)
                if (delta.isNotBlank()) {
                    onToken(delta)
                    emitted = immediateTrimmed
                }
                onDone(immediateTrimmed)
                return
            }

            var finalText = ""
            repeat(60) {
                delay(1000)
                val polled = fetchMatchingCursorMessage(requestId, taskId)
                if (polled.isNotBlank()) {
                    finalText = polled.trim()
                    if (finalText != emitted) {
                        val delta = finalText.removePrefix(emitted)
                        if (delta.isNotBlank()) {
                            onToken(delta)
                        }
                        emitted = finalText
                    }
                    onDone(finalText)
                    return
                }
                val progressText = "已提交到超级员工-Cursor，正在执行 $requestId"
                if (progressText != emitted) {
                    onToken("\n$progressText")
                    emitted = progressText
                }
            }

            finalText = "已提交到超级员工-Cursor，任务将在电脑端执行后回写。"
            onDone(finalText)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "超级员工-Cursor 调用失败")
        }
    }

    // 超级员工-Trae：同构接入 Trae 中继 / 派工通道。
    private suspend fun streamTraeSuperEmployeeChat(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        try {
            val statusPrefix = "已提交到超级员工-Trae，正在执行"
            onToken(statusPrefix)
            var emitted = statusPrefix

            val response = fhd().postTraeSuperEmployeeMessage(
                body = TraeSuperEmployeeMobileMessageBody(
                    message = message,
                    body = message,
                    context = mapOf(
                        "source" to "mobile_chat",
                        "client_surface" to "mobile",
                        "mode" to "code",
                    ),
                ),
            )
            if (!response.success) {
                onError(response.message.ifBlank { "超级员工-Trae 调用失败" })
                return
            }

            val requestId = extractDispatchRequestId(response.data)
            val taskId = extractTaskId(response.data)
            val immediate = extractCodexMessageText(response.data, requestId, taskId)
            if (immediate.isNotBlank()) {
                val immediateTrimmed = immediate.trim()
                val delta = immediateTrimmed.removePrefix(emitted)
                if (delta.isNotBlank()) {
                    onToken(delta)
                    emitted = immediateTrimmed
                }
                onDone(immediateTrimmed)
                return
            }

            var finalText = ""
            repeat(60) {
                delay(1000)
                val polled = fetchMatchingTraeMessage(requestId, taskId)
                if (polled.isNotBlank()) {
                    finalText = polled.trim()
                    if (finalText != emitted) {
                        val delta = finalText.removePrefix(emitted)
                        if (delta.isNotBlank()) {
                            onToken(delta)
                        }
                        emitted = finalText
                    }
                    onDone(finalText)
                    return
                }
                val progressText = "已提交到超级员工-Trae，正在执行 $requestId"
                if (progressText != emitted) {
                    onToken("\n$progressText")
                    emitted = progressText
                }
            }

            finalText = "已提交到超级员工-Trae，任务将在电脑端执行后回写。"
            onDone(finalText)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "超级员工-Trae 调用失败")
        }
    }

    private suspend fun fetchLatestCodexMessage(): String =
        fetchMatchingCodexMessage(requestId = null, taskId = null)

    private suspend fun fetchMatchingClaudeMessage(
        requestId: String?,
        taskId: String?,
    ): String {
        return try {
            val response = fhd().getClaudeSuperEmployeeMessages(80)
            if (!response.success) return ""
            extractCodexMessageFromList(response.data?.get("messages"), requestId, taskId)
        } catch (_: Exception) {
            ""
        }
    }

    private suspend fun fetchMatchingCursorMessage(
        requestId: String?,
        taskId: String?,
    ): String {
        return try {
            val response = fhd().getCursorSuperEmployeeMessages(80)
            if (!response.success) return ""
            extractCodexMessageFromList(response.data?.get("messages"), requestId, taskId)
        } catch (_: Exception) {
            ""
        }
    }

    private suspend fun fetchMatchingTraeMessage(
        requestId: String?,
        taskId: String?,
    ): String {
        return try {
            val response = fhd().getTraeSuperEmployeeMessages(80)
            if (!response.success) return ""
            extractCodexMessageFromList(response.data?.get("messages"), requestId, taskId)
        } catch (_: Exception) {
            ""
        }
    }

    private suspend fun fetchMatchingCodexMessage(
        requestId: String?,
        taskId: String?,
    ): String {
        return try {
            val response = fhd().getCodexSuperEmployeeMessages(80)
            if (!response.success) return ""
            extractCodexMessageFromList(response.data?.get("messages"), requestId, taskId)
        } catch (_: Exception) {
            ""
        }
    }

    // ── AI 群聊 ──
    suspend fun loadAiGroups(): Result<List<AiGroupDto>> = aiGroupCall {
        fhd().getAiGroups().let { if (it.success) Result.success(it.data?.groups.orEmpty()) else fail(it) }
    }

    suspend fun createAiGroup(name: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().createAiGroup(AiGroupCreateBody(name)).let {
            if (it.success) Result.success(it.data?.group) else fail(it)
        }
    }

    suspend fun loadAiGroupMessages(groupId: String): Result<List<AiGroupMessageDto>> = aiGroupCall {
        fhd().getAiGroupMessages(groupId).let {
            if (it.success) Result.success(it.data?.messages.orEmpty()) else fail(it)
        }
    }

    suspend fun loadGitBranches(): Result<List<GitBranchDto>> = aiGroupCall {
        fhd().getGitBranches().let {
            if (it.success) Result.success(it.data?.branches.orEmpty()) else fail(it)
        }
    }

    suspend fun postAiGroupMessage(
        groupId: String,
        message: String,
        mentions: List<String> = emptyList(),
        senderName: String = "我",
        dispatch: Boolean = false,
        branchContext: String = "",
        context: Map<String, String> = emptyMap(),
    ): Result<AiGroupPostData> = aiGroupCall {
        fhd().postAiGroupMessage(
            groupId,
            AiGroupMessageBody(
                message = message,
                sender_name = senderName,
                mentions = mentions,
                dispatch = dispatch,
                branch_context = branchContext,
                branch = branchContext,
                context = context,
            ),
        ).let { if (it.success) Result.success(it.data ?: AiGroupPostData()) else fail(it) }
    }

    suspend fun addAiGroupMember(
        groupId: String,
        employeeId: String,
        modId: String,
        name: String,
        avatar: String,
        summary: String,
    ): Result<AiGroupDto?> = aiGroupCall {
        fhd().addAiGroupMember(
            groupId,
            AiGroupMemberBody(
                employee_id = employeeId,
                mod_id = modId,
                name = name,
                avatar = avatar,
                summary = summary,
            ),
        ).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun removeAiGroupMember(groupId: String, employeeId: String): Result<AiGroupDto?> =
        aiGroupCall {
            fhd().removeAiGroupMember(groupId, employeeId).let {
                if (it.success) Result.success(it.data?.group) else fail(it)
            }
        }

    suspend fun toggleAiGroupPin(groupId: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().toggleAiGroupPin(groupId).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun markAiGroupUnread(groupId: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().markAiGroupUnread(groupId).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun markAiGroupRead(groupId: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().markAiGroupRead(groupId).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun toggleAiGroupFollowed(groupId: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().toggleAiGroupFollowed(groupId).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun toggleAiGroupHidden(groupId: String): Result<AiGroupDto?> = aiGroupCall {
        fhd().toggleAiGroupHidden(groupId).let { if (it.success) Result.success(it.data?.group) else fail(it) }
    }

    suspend fun deleteAiGroup(groupId: String): Result<Boolean> = aiGroupCall {
        fhd().deleteAiGroup(groupId).let { if (it.success) Result.success(true) else fail(it) }
    }

    // ── 会话状态（个人 AI 会话） ──
    suspend fun toggleConversationPin(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().toggleConversationPin(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    suspend fun markConversationUnread(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().markConversationUnread(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    suspend fun markConversationRead(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().markConversationRead(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    suspend fun toggleConversationFollowed(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().toggleConversationFollowed(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    suspend fun toggleConversationHidden(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().toggleConversationHidden(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    suspend fun deleteConversation(conversationId: String): Result<Map<String, Any?>> =
        aiGroupCall {
            val res = fhd().deleteConversation(conversationId)
            if (res.success) Result.success(res.data ?: emptyMap())
            else Result.failure(Exception(res.message.ifBlank { "操作失败" }))
        }

    private fun <T> fail(env: com.xiuci.xcagi.mobile.core.model.MobileEnvelope<*>): Result<T> =
        Result.failure(Exception(env.message.ifBlank { "群聊请求失败" }))

    private suspend fun <T> aiGroupCall(block: suspend () -> Result<T>): Result<T> =
        try {
            syncRouterFromStore()
            preferCloudIfLanUnreachable()
            block()
        } catch (e: Exception) {
            Result.failure(e)
        }

    suspend fun loadCodexSuperEmployeeMessages(limit: Int = 80): Result<List<Pair<String, String>>> =
        try {
            syncRouterFromStore()
            preferCloudIfLanUnreachable()
            val response = fhd().getCodexSuperEmployeeMessages(limit)
            if (!response.success) {
                Result.failure(Exception(response.message.ifBlank { "加载超级员工会话失败" }))
            } else {
                val rawMessages = response.data?.get("messages")
                val rows = codexMessageRows(rawMessages)
                rows
                    .mapNotNull { row ->
                        ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"])
                    }
                    .maxOrNull()
                    ?.let { latestTs ->
                        // 提取最新一条消息作为列表预览（与 timestamp 对齐）
                        val latestRow = rows.maxByOrNull { row ->
                            ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"]) ?: 0L
                        }
                        val preview = latestRow?.let { row ->
                            val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
                            val body = row["body"]?.toString()?.trim().orEmpty()
                            if (body.isNotBlank() && role in setOf("user", "assistant") && !isCodexSchedulerNotice(row)) {
                                formatMessagePreview(role, body)
                            } else ""
                        }.orEmpty()
                        markConversationActivity(PinnedIds.CODEX, latestTs, preview)
                    }
                Result.success(codexMessagesToPairs(rawMessages))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }

    suspend fun loadClaudeSuperEmployeeMessages(limit: Int = 80): Result<List<Pair<String, String>>> =
        try {
            syncRouterFromStore()
            preferCloudIfLanUnreachable()
            val response = fhd().getClaudeSuperEmployeeMessages(limit)
            if (!response.success) {
                Result.failure(Exception(response.message.ifBlank { "加载超级员工会话失败" }))
            } else {
                val rawMessages = response.data?.get("messages")
                val rows = codexMessageRows(rawMessages)
                rows
                    .mapNotNull { row ->
                        ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"])
                    }
                    .maxOrNull()
                    ?.let { latestTs ->
                        val latestRow = rows.maxByOrNull { row ->
                            ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"]) ?: 0L
                        }
                        val preview = latestRow?.let { row ->
                            val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
                            val body = row["body"]?.toString()?.trim().orEmpty()
                            if (body.isNotBlank() && role in setOf("user", "assistant") && !isCodexSchedulerNotice(row)) {
                                formatMessagePreview(role, body)
                            } else ""
                        }.orEmpty()
                        markConversationActivity(PinnedIds.CLAUDE, latestTs, preview)
                    }
                Result.success(codexMessagesToPairs(rawMessages))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }

    suspend fun loadCursorSuperEmployeeMessages(limit: Int = 80): Result<List<Pair<String, String>>> =
        try {
            syncRouterFromStore()
            preferCloudIfLanUnreachable()
            val response = fhd().getCursorSuperEmployeeMessages(limit)
            if (!response.success) {
                Result.failure(Exception(response.message.ifBlank { "加载超级员工会话失败" }))
            } else {
                val rawMessages = response.data?.get("messages")
                val rows = codexMessageRows(rawMessages)
                rows
                    .mapNotNull { row ->
                        ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"])
                    }
                    .maxOrNull()
                    ?.let { latestTs ->
                        val latestRow = rows.maxByOrNull { row ->
                            ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"]) ?: 0L
                        }
                        val preview = latestRow?.let { row ->
                            val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
                            val body = row["body"]?.toString()?.trim().orEmpty()
                            if (body.isNotBlank() && role in setOf("user", "assistant") && !isCodexSchedulerNotice(row)) {
                                formatMessagePreview(role, body)
                            } else ""
                        }.orEmpty()
                        markConversationActivity(PinnedIds.CURSOR, latestTs, preview)
                    }
                Result.success(codexMessagesToPairs(rawMessages))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }

    suspend fun loadTraeSuperEmployeeMessages(limit: Int = 80): Result<List<Pair<String, String>>> =
        try {
            syncRouterFromStore()
            preferCloudIfLanUnreachable()
            val response = fhd().getTraeSuperEmployeeMessages(limit)
            if (!response.success) {
                Result.failure(Exception(response.message.ifBlank { "加载超级员工会话失败" }))
            } else {
                val rawMessages = response.data?.get("messages")
                val rows = codexMessageRows(rawMessages)
                rows
                    .mapNotNull { row ->
                        ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"])
                    }
                    .maxOrNull()
                    ?.let { latestTs ->
                        val latestRow = rows.maxByOrNull { row ->
                            ImRepository.parseTimestampMs(row["created_at"] ?: row["timestamp"]) ?: 0L
                        }
                        val preview = latestRow?.let { row ->
                            val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
                            val body = row["body"]?.toString()?.trim().orEmpty()
                            if (body.isNotBlank() && role in setOf("user", "assistant") && !isCodexSchedulerNotice(row)) {
                                formatMessagePreview(role, body)
                            } else ""
                        }.orEmpty()
                        markConversationActivity(PinnedIds.TRAE, latestTs, preview)
                    }
                Result.success(codexMessagesToPairs(rawMessages))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }

    private fun extractCodexMessageText(
        data: Map<String, Any?>?,
        requestId: String?,
        taskId: String?,
    ): String {
        if (data == null) return ""
        val assistantMessage = data["assistant_message"] as? Map<*, *>
        val directBody = assistantMessage?.get("body")?.toString()?.trim().orEmpty()
        val directRole = assistantMessage?.get("role")?.toString()?.trim()?.lowercase().orEmpty()
        @Suppress("UNCHECKED_CAST")
        val assistantRow = assistantMessage?.let { it as? Map<String, Any?> }
        if (
            directBody.isNotBlank() &&
            (directRole.isEmpty() || directRole == "assistant") &&
            !isCodexSchedulerNotice(assistantRow ?: emptyMap())
        ) {
            return directBody
        }
        return extractCodexMessageFromList(data["messages"], requestId, taskId)
    }

    private fun extractCodexMessageFromList(
        raw: Any?,
        requestId: String? = null,
        taskId: String? = null,
    ): String {
        val rows = codexMessageRows(raw)
        if (rows.isEmpty()) return ""
        val targetRequest = requestId.orEmpty().trim()
        val targetTask = taskId.orEmpty().trim()
        val reversed = rows.asReversed()

        if (targetRequest.isNotBlank() || targetTask.isNotBlank()) {
            reversed.firstOrNull { row ->
                isAssistantCodexMessage(row) && messageMatchesTask(row, targetRequest, targetTask)
            }?.let { matched ->
                matched["body"]?.toString()?.trim()?.takeIf { it.isNotBlank() }?.let {
                    return it
                }
            }
            reversed.firstOrNull { row ->
                isAssistantMessage(row) && messageMatchesTask(row, targetRequest, targetTask)
            }?.let { matched ->
                matched["body"]?.toString()?.trim()?.takeIf { it.isNotBlank() }?.let {
                    return it
                }
            }
        }

        return reversed
            .firstOrNull { isAssistantCodexMessage(it) }
            ?.get("body")
            ?.toString()
            ?.trim()
            .orEmpty()
    }

    private fun messageMatchesTask(
        row: Map<String, Any?>,
        requestId: String,
        taskId: String,
    ): Boolean {
        if (requestId.isBlank() && taskId.isBlank()) return true
        val rowRequest = row["dispatch_request_id"]?.toString()?.trim().orEmpty()
        val rowTask = row["task_id"]?.toString()?.trim().orEmpty()
        val directRequest = row["request_id"]?.toString()?.trim().orEmpty()
        return (requestId.isNotBlank() && (rowRequest == requestId || directRequest == requestId)) ||
            (taskId.isNotBlank() && rowTask == taskId)
    }

    private fun isAssistantCodexMessage(row: Map<String, Any?>): Boolean {
        val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
        if (role != "assistant") return false
        if (isCodexSchedulerNotice(row)) return false
        val kind = row["kind"]?.toString()?.trim()?.lowercase().orEmpty()
        // 兼容 codex_result/codex_direct 与 claude_result/claude_direct（及无 kind 的直答）。
        return kind.isBlank() || kind.endsWith("_result") || kind.endsWith("_direct")
    }

    private fun isCodexSchedulerNotice(row: Map<String, Any?>): Boolean {
        val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
        if (role == "system") return true
        val kind = row["kind"]?.toString()?.trim()?.lowercase().orEmpty()
        if (kind == "dispatcher") return true
        val text = row["body"]?.toString()?.trim() ?: ""
        if (text.isBlank()) return false
        val lower = text.lowercase()
        return lower.contains("调度") || lower.contains("dispatcher") || lower.contains("任务已派发")
    }

    private fun isAssistantMessage(row: Map<String, Any?>): Boolean {
        return row["role"]?.toString()?.trim()?.lowercase().orEmpty() == "assistant"
    }

    private fun extractDispatchRequestId(data: Map<String, Any?>?): String {
        if (data == null) return ""
        @Suppress("UNCHECKED_CAST")
        val dispatch = data["dispatch"] as? Map<String, Any?>
        @Suppress("UNCHECKED_CAST")
        val assistantMessage = data["assistant_message"] as? Map<String, Any?>
        return dispatch?.get("request_id")?.toString()?.trim().orEmpty().ifBlank {
            assistantMessage?.get("dispatch_request_id")?.toString()?.trim().orEmpty().ifBlank {
                data["dispatch_request_id"]?.toString()?.trim().orEmpty().ifBlank {
                    data["request_id"]?.toString()?.trim().orEmpty()
                }
            }
        }
    }

    private fun extractTaskId(data: Map<String, Any?>?): String {
        if (data == null) return ""
        @Suppress("UNCHECKED_CAST")
        val dispatch = data["dispatch"] as? Map<String, Any?>
        @Suppress("UNCHECKED_CAST")
        val assistantMessage = data["assistant_message"] as? Map<String, Any?>
        return dispatch?.get("task_id")?.toString()?.trim().orEmpty().ifBlank {
            assistantMessage?.get("task_id")?.toString()?.trim().orEmpty().ifBlank {
                data["task_id"]?.toString()?.trim().orEmpty()
            }
        }
    }

    private fun codexMessagesToPairs(raw: Any?): List<Pair<String, String>> =
        codexMessageRows(raw).mapNotNull { row ->
            val role = row["role"]?.toString()?.trim()?.lowercase().orEmpty()
            val text = row["body"]?.toString()?.trim().orEmpty()
            if (
                isCodexSchedulerNotice(row) ||
                text.isBlank() ||
                role !in setOf("user", "assistant")
            ) {
                null
            } else {
                role to text
            }
        }

    private fun codexMessageRows(raw: Any?): List<Map<String, Any?>> {
        val payload =
            when (val data = raw) {
                is Map<*, *> -> data["messages"] ?: data
                else -> raw
            }
        return when (payload) {
            is List<*> ->
                payload.mapNotNull { row ->
                    @Suppress("UNCHECKED_CAST")
                    row as? Map<String, Any?>
                }
            else -> emptyList()
        }
    }

    private suspend fun streamRelayCodexTask(
        relayId: String,
        message: String,
        kind: String = "codex.invoke",
        conversationId: String = "",
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        try {
            val toolLabel = SuperEmployeeRoutingPolicy.toolLabelForRelayKind(kind)
            // 中继任务由 Retrofit 直接发起，不走 SSE 的 401/403 刷新重试。
            // 先用 refresh token 更新 FHD access token，避免保留登录态的手机在 token
            // 过期后只能看到“重新登录”，实际请求根本到不了电脑执行端。
            refreshFhdAccessToken()
            val created = fhd().relayCreateTask(
                RelayTaskCreateBody(
                    relay_id = relayId,
                    kind = kind,
                    payload = mapOf(
                        "message" to message,
                        "context" to mapOf(
                            "source" to "mobile_chat",
                            "client_surface" to "mobile",
                            "mode" to "code",
                        ),
                    ),
                ),
            )
            if (!created.success) {
                onError(created.message.ifBlank { "中继任务创建失败" })
                return
            }
            val task = created.data?.get("task") as? Map<*, *> ?: emptyMap<Any?, Any?>()
            val taskId = task["task_id"]?.toString().orEmpty()
            if (taskId.isBlank()) {
                onError("中继任务缺少 task_id")
                return
            }
            // 持久化在飞任务：刷新/重启后可恢复轮询，避免"任务状态丢了"。
            if (conversationId.isNotBlank()) sessionStore.setInflightRelayTask(conversationId, taskId)
            onToken("思考中...")
            pollRelayTask(taskId, toolLabel, conversationId, onToken, onDone, onError)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "中继任务失败")
        }
    }

    /** 轮询一个已存在的中继任务直到终态；终态清除在飞记录（取消/超时不清，留待恢复）。 */
    private suspend fun pollRelayTask(
        taskId: String,
        toolLabel: String,
        conversationId: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        suspend fun clearInflight() {
            if (conversationId.isNotBlank()) sessionStore.setInflightRelayTask(conversationId, "")
        }
        var lastStatus = ""
        repeat(150) {
            delay(2000)
            val status = fhd().relayTaskStatus(taskId)
            val current = status.data?.get("task") as? Map<*, *> ?: emptyMap<Any?, Any?>()
            val currentStatus = current["status"]?.toString().orEmpty()
            if (currentStatus.isNotBlank() && currentStatus != lastStatus) {
                when (currentStatus) {
                    "running", "assigned" -> onToken("\n电脑执行端正在运行 $toolLabel。")
                    "queued" -> onToken("\n任务仍在服务器队列中。")
                }
                lastStatus = currentStatus
            }
            when (currentStatus) {
                "done", "completed" -> {
                    clearInflight()
                    onDone(relayTaskResultText(current).ifBlank { "电脑执行端已完成任务。" })
                    return
                }
                "failed", "blocked", "cancelled" -> {
                    clearInflight()
                    onError(relayTaskResultText(current).ifBlank { "电脑执行端执行失败" })
                    return
                }
            }
        }
        // 超时未回写：保留在飞记录，下次进入会话可继续恢复轮询。
        onError("电脑执行端暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。")
    }

    suspend fun hasInflightRelay(conversationId: String): Boolean =
        sessionStore.inflightRelayTask(conversationId).isNotBlank()

    /** 手机底部功能键触发的 git 操作（git.merge / git.diff / git.discard），经中继到电脑执行端。 */
    suspend fun streamRelayGitOp(
        branch: String,
        op: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        val relayId = relayIdForSuperEmployeeDispatch()
        if (relayId.isBlank()) {
            onError("未绑定电脑执行端，无法执行 $op")
            return
        }
        try {
            refreshFhdAccessToken()
            val created = fhd().relayCreateTask(
                RelayTaskCreateBody(
                    relay_id = relayId,
                    kind = op,
                    payload = mapOf(
                        "branch" to branch,
                        "context" to mapOf("source" to "mobile_chat", "client_surface" to "mobile"),
                    ),
                ),
            )
            if (!created.success) {
                onError(created.message.ifBlank { "操作创建失败" })
                return
            }
            val task = created.data?.get("task") as? Map<*, *> ?: emptyMap<Any?, Any?>()
            val taskId = task["task_id"]?.toString().orEmpty()
            if (taskId.isBlank()) {
                onError("操作缺少 task_id")
                return
            }
            onToken("执行中…")
            // conversationId 传空：git 操作短小，不需要持久化为"在飞任务"。
            pollRelayTask(taskId, "Git", "", onToken, onDone, onError)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "操作失败")
        }
    }

    /** 恢复某会话上次未完成的中继任务轮询；无在飞任务返回 false。完成时把回复写入本地缓存。 */
    suspend fun resumeRelayTask(
        conversationId: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ): Boolean {
        val taskId = sessionStore.inflightRelayTask(conversationId)
        if (taskId.isBlank()) return false
        val toolLabel = when (conversationId) {
            PinnedIds.CLAUDE -> "Claude"
            PinnedIds.CURSOR -> "Cursor"
            PinnedIds.TRAE -> "Trae"
            else -> "Codex"
        }
        var reply = ""
        try {
            refreshFhdAccessToken()
            if (clearInflightIfRelayChanged(conversationId, taskId)) {
                return false
            }
            onToken("思考中...")
            pollRelayTask(
                taskId,
                toolLabel,
                conversationId,
                onToken,
                onDone = { full -> reply = full; onDone(full) },
                onError = onError,
            )
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            onError(e.message ?: "恢复中继任务失败")
        }
        if (reply.isNotBlank()) {
            cacheChatMessage(sessionId = conversationId, role = "assistant", text = reply)
        }
        return true
    }

    private suspend fun clearInflightIfRelayChanged(
        conversationId: String,
        taskId: String,
    ): Boolean {
        val currentRelayId = relayIdForSuperEmployeeDispatch()
        if (currentRelayId.isBlank()) return false
        val status = fhd().relayTaskStatus(taskId)
        val current = status.data?.get("task") as? Map<*, *> ?: status.data ?: emptyMap<Any?, Any?>()
        val taskRelayId = current["relay_id"]?.toString()?.trim().orEmpty()
        if (taskRelayId.isBlank() || taskRelayId == currentRelayId) return false
        sessionStore.setInflightRelayTask(conversationId, "")
        return true
    }

    private fun relayTaskResultText(task: Map<*, *>): String {
        val result = task["result"] as? Map<*, *> ?: return ""
        result["error"]?.toString()?.takeIf { it.isNotBlank() }?.let { return it }
        (result["codex"] as? Map<*, *>)?.let { codex ->
            (codex["assistant_message"] as? Map<*, *>)?.get("body")?.toString()
                ?.takeIf { it.isNotBlank() }
                ?.let { return it }
        }
        // git.* 等简单操作直接返回 reply 字段
        result["reply"]?.toString()?.takeIf { it.isNotBlank() }?.let { return it }
        return ""
    }

    suspend fun streamChatCloud(
        message: String,
        conversationId: String? = null,
        sessionId: String = "default",
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        streamChat(message, conversationId, sessionId, onToken, onDone, onError)
    }

    suspend fun loadCachedChat(sessionId: String = "default"): List<Pair<String, String>> =
        db.chatDao().getBySession(sessionId).map { it.role to it.text }

    fun observeCachedChat(sessionId: String = "default"): Flow<List<Pair<String, String>>> =
        db.chatDao().observeBySession(sessionId).map { rows -> rows.map { it.role to it.text } }

    fun observeConversationListTimestamps(): Flow<Map<String, Long>> =
        db.conversationListStateDao().observeAll().map { rows ->
            rows.associate { it.conversation_id to it.last_message_at }
        }

    /** 会话最新消息预览（微信风格副标题）。key=conversationId，value=预览文本。 */
    fun observeConversationListPreviews(): Flow<Map<String, String>> =
        db.conversationListStateDao().observeAll().map { rows ->
            rows.mapNotNull { row ->
                val preview = row.lastMessagePreview.trim()
                if (preview.isBlank()) null else row.conversation_id to preview
            }.toMap()
        }

    suspend fun markConversationActivity(
        conversationId: String,
        timestamp: Long = System.currentTimeMillis(),
        preview: String = "",
    ) {
        if (conversationId.isBlank() || timestamp <= 0L) return
        val dao = db.conversationListStateDao()
        val normalizedPreview = preview.trim()
        dao.insertIfAbsent(
            ConversationListStateEntity(
                conversation_id = conversationId,
                last_message_at = timestamp,
                lastMessagePreview = normalizedPreview,
            )
        )
        // 有预览时强制写入（即使时间戳不更新，也要刷新副标题）；无预览时仅在新时间戳时更新
        if (normalizedPreview.isNotBlank()) {
            dao.upsertPreview(conversationId, timestamp, normalizedPreview)
        } else {
            dao.updateIfNewer(conversationId, timestamp, "")
        }
    }

    private suspend fun cacheChatMessage(
        sessionId: String,
        role: String,
        text: String,
        timestamp: Long = System.currentTimeMillis(),
    ) {
        db.chatDao().insert(
            ChatCacheEntity(
                session_id = sessionId,
                role = role,
                text = text,
                ts = timestamp,
            )
        )
        val conversationId = if (sessionId == "default") PinnedIds.ASSISTANT else sessionId
        // 微信风格预览：自己发的消息加 "我:" 前缀，AI 回复直接显示内容
        val preview = formatMessagePreview(role, text)
        markConversationActivity(conversationId, timestamp, preview)
    }

    /** 生成会话列表副标题预览：user 消息加 "我:" 前缀，assistant 消息直接显示，多行折叠为单行。 */
    private fun formatMessagePreview(role: String, text: String): String {
        val normalized = text.trim().replace("\n", " ").replace("\r", " ")
        if (normalized.isBlank()) return ""
        return when (role.trim().lowercase()) {
            "user" -> "我: $normalized"
            else -> normalized
        }
    }

    private fun parseBridgeRequestRows(raw: Any?): List<Map<String, Any?>> {
        val payload = when (val data = raw) {
            is Map<*, *> -> data["data"] ?: data
            is List<*> -> data
            else -> null
        }
        val rows = when (payload) {
            is Map<*, *> -> payload["items"] as? List<*>
            is List<*> -> payload
            else -> null
        } ?: emptyList()
        return rows.mapNotNull { row ->
            if (row is Map<*, *>) {
                @Suppress("UNCHECKED_CAST")
                row as? Map<String, Any?>
            } else {
                null
            }
        }
    }

    private fun mapServiceBridgeRequestRows(raw: Any?): List<ListItem> =
        parseBridgeRequestRows(raw).map {
            ListItem(
                id = "${it["id"]}",
                title = "${it["title"] ?: it["name"] ?: ""}",
                subtitle = "${it["status"] ?: ""}",
                payload = it,
            )
        }

    private suspend fun bridgeRequestsFromMobile(): Result<List<ListItem>> {
        val res = fhd().mobileBridgeRequests()
        if (!res.success) {
            return Result.failure(Exception(res.message.ifBlank { "移动端服务桥接请求列表加载失败" }))
        }
        return Result.success(mapServiceBridgeRequestRows(res.data))
    }

    private suspend fun bridgeRequestsFromLegacy(): Result<List<ListItem>> {
        val res = fhd().bridgeRequests()
        return Result.success(mapServiceBridgeRequestRows(res["data"]))
    }

    suspend fun approvals(): Result<List<ListItem>> {
        val remote = parseMobileList { fhd().mobileApprovals().data }
        remote.getOrNull()?.forEach { item ->
            val rid = item.id.toIntOrNull() ?: return@forEach
            db.approvalDao().insert(
                ApprovalCacheEntity(rid, item.title, item.subtitle, gson.toJson(item.payload)),
            )
        }
        if (remote.isSuccess) return remote
        val cached = cachedApprovalItems()
        return if (cached.isNotEmpty()) Result.success(cached) else remote
    }

    suspend fun approvalDetail(id: Int): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        Result.success(fhd().approvalDetail(id))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun approve(id: Int, opinion: String): Result<Unit> = try {
        val uid = userId()
        fhd().approvalApprove(id, ApproveBody(uid, opinion))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun reject(id: Int, reason: String): Result<Unit> = try {
        val uid = userId()
        fhd().approvalReject(id, RejectBody(uid, reason))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun customers(): Result<List<ListItem>> = parseMobileList { fhd().mobileCustomers().data }

    suspend fun shipments(): Result<List<ListItem>> {
        val remote = parseMobileList { fhd().mobileShipments().data }
        remote.getOrNull()?.forEach { item ->
            val sid = item.id.toIntOrNull() ?: return@forEach
            db.shipmentDao().insert(
                ShipmentCacheEntity(sid, item.title, item.subtitle, gson.toJson(item.payload)),
            )
        }
        if (remote.isSuccess) return remote
        val cached = cachedShipmentItems()
        return if (cached.isNotEmpty()) Result.success(cached) else remote
    }
    suspend fun bridgeRequests(): Result<List<ListItem>> = try {
        syncRouterFromStore()
        bridgeRequestsFromMobile()
    } catch (e: Exception) {
        if (e is HttpException && e.code() == 404) {
            try {
                bridgeRequestsFromLegacy()
            } catch (legacyError: Exception) {
                Result.failure(legacyError)
            }
        } else {
            Result.failure(e)
        }
    }

    suspend fun bridgeRespond(id: Int, text: String): Result<Unit> = try {
        syncRouterFromStore()
        try {
            fhd().mobileBridgeRespond(id, BridgeRespondBody(text, "android"))
            Result.success(Unit)
        } catch (e: Exception) {
            if (e is HttpException && e.code() == 404) {
                fhd().bridgeRespond(id, BridgeRespondBody(text, "android"))
                Result.success(Unit)
            } else {
                Result.failure(e)
            }
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun mods(): Result<List<ListItem>> = parseMobileList {
        fhd().mobileMods().data
    }

    suspend fun loadModInfos(): Result<List<ModInfo>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val body = if (isPcReachable()) {
            val res = fhd().mobileMods()
            if (!res.success) {
                throw Exception(res.message.ifBlank { "AI 员工同步失败" })
            }
            res.data ?: emptyMap()
        } else {
            val token = sessionStore.marketAccessToken().ifBlank { sessionStore.fhdAccessFlow.first() }
            val auth = if (token.isNotBlank()) "Bearer $token" else null
            modstore().installedMods(auth)
        }
        val raw = (body["data"] as? Map<*, *>)?.let { data ->
            data["items"] ?: data["mods"] ?: data["installed"]
        } ?: body["items"] ?: body["mods"] ?: body["installed"]
        val rows = raw as? List<*> ?: emptyList<Any?>()
        Result.success(rows.mapNotNull { (it as? Map<*, *>)?.toModInfo() })
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun loadAdminMobileHome(): Result<AdminMobileHomeData> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileAdminHome()
        if (!res.success) {
            Result.failure(Exception(res.message.ifBlank { "管理端移动数据加载失败" }))
        } else {
            Result.success(res.data ?: AdminMobileHomeData())
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun loadAdminModInfos(): Result<List<ModInfo>> =
        loadAdminMobileHome().map { home ->
            AdminDutyRosterNormalizer.normalize(listOf(home.toAdminModInfo()))
        }

    /** 从 Room 缓存读取员工列表（UI 秒出用）。失败或空缓存返回空列表。 */
    suspend fun loadCachedModInfos(adminMode: Boolean): List<ModInfo> {
        return try {
            val mods = db.modInfoCacheDao().getAll().map { it.toModInfo() }
            if (adminMode) AdminDutyRosterNormalizer.normalize(mods) else mods
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** 返回最近一次缓存写入时间戳（毫秒）。无缓存返回 0。用于 TTL 判断。 */
    suspend fun cachedModInfosAt(): Long =
        try {
            val entities = db.modInfoCacheDao().getAll()
            val mods = entities.map { it.toModInfo() }
            if (!AdminDutyRosterNormalizer.isCurrent(mods)) {
                0L
            } else {
                entities.maxOfOrNull { it.cachedAt } ?: 0L
            }
        } catch (_: Exception) {
            0L
        }

    /** 网络刷新员工列表并写入 Room 缓存。网络失败或返回空列表时保留旧缓存。 */
    suspend fun refreshAndCacheModInfos(adminMode: Boolean): Result<List<ModInfo>> {
        val result = if (adminMode) loadAdminModInfos() else loadModInfos()
        if (result.isSuccess) {
            val rawMods = result.getOrThrow()
            val mods = if (adminMode) AdminDutyRosterNormalizer.normalize(rawMods) else rawMods
            // 仅当网络返回非空列表时才更新缓存；空列表通常是临时错误，不清空旧缓存
            if (mods.isNotEmpty()) {
                try {
                    db.modInfoCacheDao().clear()
                    db.modInfoCacheDao().insertAll(mods.map { it.toCacheEntity() })
                } catch (_: Exception) {
                    // 缓存写入失败不阻断 UI
                }
            }
        }
        return result
    }

    private fun ModInfo.toCacheEntity(): ModInfoCacheEntity =
        ModInfoCacheEntity(
            id = id.ifBlank { name },
            name = name,
            version = version,
            description = description,
            author = author,
            primary = primary,
            industry = industry?.let { "${it.id}|${it.name}" } ?: "",
            avatarUrl = avatar_url,
            employeesJson = gson.toJson(workflow_employees),
            cachedAt = System.currentTimeMillis(),
        )

    private fun ModInfoCacheEntity.toModInfo(): ModInfo {
        val employees: List<WorkflowEmployeeInfo> = try {
            gson.fromJson(
                employeesJson,
                com.google.gson.reflect.TypeToken.getParameterized(
                    List::class.java, WorkflowEmployeeInfo::class.java
                ).type
            ) ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        return ModInfo(
            id = id,
            name = name,
            version = version,
            description = description,
            author = author,
            primary = primary,
            industry = industry.takeIf { it.isNotBlank() }?.let { raw ->
                val parts = raw.split("|", limit = 2)
                ModIndustry(
                    id = parts.getOrNull(0) ?: "",
                    name = parts.getOrNull(1) ?: "",
                )
            },
            avatar_url = avatarUrl,
            workflow_employees = employees,
        )
    }

    /** 观察本地缓存的 Mod 列表（微信风格：DB 为唯一数据源，UI 观察 DB 变化） */
    fun observeCachedModInfos(): Flow<List<ModInfo>> =
        db.modInfoCacheDao().observeAll().map { entities ->
            AdminDutyRosterNormalizer.normalize(entities.map { it.toModInfo() })
        }

    suspend fun fetchHome(): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileHome()
        if (!res.success) Result.failure(Exception(res.message ?: "加载失败"))
        else Result.success(res.data ?: emptyMap())
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** 拉取侧栏菜单（探索 Tab 配对后与桌面端侧栏对齐）。 */
    suspend fun fetchNavMenu(): Result<NavMenuData> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileNavMenu()
        if (!res.success) Result.failure(Exception(res.message ?: "菜单加载失败"))
        else Result.success(res.data ?: NavMenuData())
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun loadAiCirclePosts(): Result<List<com.xiuci.xcagi.mobile.core.model.AiCirclePost>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().aiCirclePosts()
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "交流圈加载失败" }))
        else Result.success(res.data?.items ?: emptyList())
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun createAiCirclePost(body: String): Result<Unit> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().createAiCirclePost(com.xiuci.xcagi.mobile.core.network.AiCircleTextBody(body))
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "发布失败" }))
        else Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun toggleAiCircleLike(postId: Int): Result<Unit> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().toggleAiCircleLike(postId)
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "点赞失败" }))
        else Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun addAiCircleComment(postId: Int, body: String): Result<Unit> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().addAiCircleComment(
            postId,
            com.xiuci.xcagi.mobile.core.network.AiCircleTextBody(body),
        )
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "评论失败" }))
        else Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** 拉取市场钱包余额与会员信息（移动端"我"页面展示）。 */
    suspend fun fetchWalletBalance(): Result<WalletBalanceDto> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileWalletBalance()
        if (!res.success) Result.failure(Exception(res.message ?: "余额加载失败"))
        else Result.success(res.data ?: WalletBalanceDto())
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** 将钱包余额序列化为 JSON 写入 DataStore（冷启动秒出用）。 */
    suspend fun saveCachedWalletBalance(dto: WalletBalanceDto) {
        try {
            sessionStore.setWalletBalanceJson(gson.toJson(dto))
        } catch (_: Exception) {
            // 缓存写入失败不阻断 UI
        }
    }

    /** 从 DataStore 读取缓存的钱包余额 JSON 并反序列化。无缓存返回 null。 */
    suspend fun loadCachedWalletBalance(): WalletBalanceDto? {
        val json = sessionStore.walletBalanceJson()
        if (json.isBlank()) return null
        return try {
            gson.fromJson(json, WalletBalanceDto::class.java)
        } catch (_: Exception) {
            null
        }
    }

    private fun mapValue(row: Map<*, *>, key: String): Any? = row[key] ?: row[key.replace("_", "-")]

    private fun stringList(value: Any?): List<String> =
        (value as? List<*>)?.mapNotNull { it?.toString()?.trim()?.takeIf { s -> s.isNotBlank() } }
            ?: emptyList()

    private fun boolValue(value: Any?): Boolean =
        when (value) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            is String -> value.equals("true", ignoreCase = true) || value == "1"
            else -> false
        }

    private fun nestedDataMap(value: Map<String, Any?>): Map<String, Any?> {
        @Suppress("UNCHECKED_CAST")
        val nested = value["data"] as? Map<String, Any?>
        return nested ?: value
    }

    suspend fun validateMobileSession(): Result<Unit> = try {
        syncRouterFromStore()
        val res = fhd().mobileSessionValidate()
        if (!res.success) {
            Result.failure(Exception(res.message.ifBlank { "会话已过期" }))
        } else {
            val data = res.data ?: emptyMap()
            val access = data["market_access_token"]?.toString()?.trim().orEmpty()
            val refresh = data["market_refresh_token"]?.toString()?.trim().orEmpty()
            if (access.isNotBlank()) {
                sessionStore.setMarketTokens(access, refresh)
            }
            Result.success(Unit)
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun onboardingIndustries(): Result<List<ListItem>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileOnboardingIndustries()
        if (!res.success) {
            Result.failure(Exception(res.message.ifBlank { "行业目录加载失败" }))
        } else {
            val data = nestedDataMap(res.data ?: emptyMap())
            val packages = (data["open_packages"] as? List<*>) ?: emptyList<Any?>()
            val items = packages.mapNotNull { row ->
                val m = row as? Map<*, *> ?: return@mapNotNull null
                val industryId = mapValue(m, "industry_id")?.toString()?.trim().orEmpty()
                if (industryId.isBlank()) return@mapNotNull null
                val title = mapValue(m, "name")?.toString()?.takeIf { it.isNotBlank() }
                    ?: mapValue(m, "product_name")?.toString()?.takeIf { it.isNotBlank() }
                    ?: industryId
                val subtitle = mapValue(m, "scenario")?.toString()?.takeIf { it.isNotBlank() }
                    ?: mapValue(m, "mod_id")?.toString().orEmpty()
                ListItem(industryId, title, subtitle)
            }
            if (items.isNotEmpty()) Result.success(items)
            else Result.success(
                stringList(data["open_industry_ids"]).map { ListItem(it, it, "可选行业") }
            )
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun industryBaseline(industryId: String): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobileIndustryBaseline(industryId.ifBlank { "通用" })
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "行业基线加载失败" }))
        else Result.success(nestedDataMap(res.data ?: emptyMap()))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun bootstrapIndustry(industryId: String): Result<String> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val industry = industryId.ifBlank { "通用" }
        val host = fhd().mobileInstallHostFoundation("generic")
        if (!host.success) {
            throw Exception(host.message.ifBlank { "宿主基础包安装失败" })
        }
        val baseline = industryBaseline(industry).getOrThrow()
        if (stringList(baseline["missing_industry_mod_ids"]).isNotEmpty()) {
            val seed = fhd().mobileInstallIndustrySeed(mapOf("industry_id" to industry))
            if (!seed.success) {
                throw Exception(seed.message.ifBlank { "行业包安装失败" })
            }
        }
        for (modId in stringList(baseline["missing_account_custom_mod_ids"])) {
            val install = fhd().mobileInstallMod(mapOf("mod_id" to modId))
            if (!install.success) {
                throw Exception(install.message.ifBlank { "$modId 安装失败" })
            }
        }
        for (modId in stringList(baseline["account_custom_mod_ids"])) {
            val seed = fhd().mobileInstallCustomerDeliverySeed(
                mapOf("mod_id" to modId, "industry_id" to industry)
            )
            if (!seed.success) {
                throw Exception(seed.message.ifBlank { "$modId 交付数据安装失败" })
            }
        }
        val after = industryBaseline(industry).getOrThrow()
        val ready = boolValue(after["full_stack_ready"]) || boolValue(after["baseline_ready"])
        Result.success(if (ready) "行业能力已装齐" else "基础能力已安装，请刷新查看剩余项")
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun paymentPlans(): Result<List<ListItem>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobilePaymentPlans()
        if (!res.success) {
            Result.failure(Exception(res.message.ifBlank { "套餐加载失败" }))
        } else {
            val data = nestedDataMap(res.data ?: emptyMap())
            val raw = (data["plans"] as? List<*>)
                ?: (data["items"] as? List<*>)
                ?: emptyList<Any?>()
            Result.success(raw.mapNotNull { row ->
                val m = row as? Map<*, *> ?: return@mapNotNull null
                val id = mapValue(m, "id")?.toString()?.trim().orEmpty()
                if (id.isBlank()) return@mapNotNull null
                val title = mapValue(m, "title")?.toString()?.takeIf { it.isNotBlank() }
                    ?: mapValue(m, "name")?.toString()?.takeIf { it.isNotBlank() }
                    ?: id
                val amount = mapValue(m, "amount_cents")?.toString()
                    ?: mapValue(m, "price_cents")?.toString()
                    ?: ""
                val desc = mapValue(m, "description")?.toString()?.takeIf { it.isNotBlank() }
                    ?: if (amount.isNotBlank()) "¥${amount.toDoubleOrNull()?.div(100.0) ?: amount}" else "模型服务套餐"
                ListItem(id, title, desc, m.entries.associate { it.key.toString() to it.value })
            })
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    private fun mobilePaymentCheckoutBody(channel: String): MutableMap<String, Any?> {
        val normalized = channel.trim().ifBlank { "mobile_h5" }
        return mutableMapOf(
            "channel" to normalized,
            "client" to "android",
            "return_url" to "xcagi://payment/complete",
        )
    }

    suspend fun checkoutPaymentPlan(
        planId: String,
        channel: String = "mobile_h5",
    ): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val body = mobilePaymentCheckoutBody(channel)
        body["plan_id"] = planId
        val res = fhd().mobilePaymentCheckout(body)
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "支付下单失败" }))
        else Result.success(nestedDataMap(res.data ?: emptyMap()))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun checkoutWalletRecharge(
        amountYuan: String,
        channel: String = "mobile_h5",
    ): Result<Map<String, Any?>> = try {
        val amount = amountYuan.trim().toDoubleOrNull() ?: 0.0
        if (amount <= 0.0) throw IllegalArgumentException("请输入有效充值金额")
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val body = mobilePaymentCheckoutBody(channel)
        body["wallet_recharge"] = true
        body["total_amount"] = amount
        body["subject"] = "手机钱包充值"
        val res = fhd().mobilePaymentCheckout(body)
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "充值下单失败" }))
        else Result.success(nestedDataMap(res.data ?: emptyMap()))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun queryPayment(outTradeNo: String): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val res = fhd().mobilePaymentQuery(outTradeNo)
        if (!res.success) Result.failure(Exception(res.message.ifBlank { "订单查询失败" }))
        else Result.success(nestedDataMap(res.data ?: emptyMap()))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun marketCatalog(): Result<List<ListItem>> = try {
        val tok = sessionStore.marketTokenFlow.first().ifBlank { sessionStore.fhdAccessFlow.first() }
        val auth = if (tok.isNotBlank()) "Bearer $tok" else null
        val res = modstore().marketCatalog(auth)
        val items = (res["items"] as? List<*>) ?: emptyList<Any>()
        Result.success(items.mapNotNull { row ->
            (row as? Map<*, *>)?.let {
                ListItem("${it["id"]}", "${it["name"] ?: it["title"]}")
            }
        })
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun inventory(): Result<List<String>> = try {
        syncRouterFromStore()
        val res = fhd().inventoryItems()
        val items = (res["data"] as? List<*>) ?: (res["items"] as? List<*>) ?: emptyList<Any>()
        Result.success(items.map { it.toString() })
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun financeSummary(): Result<String> = try {
        syncRouterFromStore()
        Result.success(fhd().financeSummary().toString())
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** 当前 FHD base URL（供 AppViewModel 构建桌面端页面 URL）。 */
    fun fhdBaseUrl(): String = serverRouter.fhdBaseUrl()

    suspend fun modWebUrl(modId: String): String {
        val online = sessionStore.fhdHostFlow.first().isNotBlank() && checkHealth()
        return if (online) {
            "${serverRouter.fhdBaseUrl()}mod/$modId/"
        } else {
            val base = BuildConfig.MODSTORE_BASE_URL.trimEnd('/')
            "$base/workbench/mod/$modId?client=android"
        }
    }

    suspend fun modOpensInCloudWorkbench(): Boolean {
        val online = sessionStore.fhdHostFlow.first().isNotBlank() && checkHealth()
        return !online
    }

    suspend fun logout() {
        sessionStore.clear()
        db.chatDao().clear()
        db.approvalDao().clear()
        db.shipmentDao().clear()
        imRepo.clearAll()
    }

    val imWsEvents: SharedFlow<JSONObject> get() = imWebSocket.events

    suspend fun connectImWebSocket() {
        syncRouterFromStore()
        imRepo.attachWebSocketListener()
        val sid = sessionStore.fhdSessionId()
        if (sid.isNotBlank()) {
            imWebSocket.connect(sid)
        }
    }

    fun observeImMessages(conversationId: Int): Flow<List<ImMessageCacheEntity>> =
        imRepo.observeMessages(conversationId)

    suspend fun seedImMessages(conversationId: Int): Result<Unit> = try {
        syncRouterFromStore()
        val body = fhd().imListMessages(conversationId)
        @Suppress("UNCHECKED_CAST")
        val list = body["messages"] as? List<Map<String, Any?>> ?: emptyList()
        imRepo.seedMessagesFromNetwork(list)
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    fun disconnectImWebSocket() {
        imWebSocket.disconnect()
    }

    suspend fun imOpenDirect(peerUserId: Int): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        Result.success(fhd().imCreateDirect(ImDirectBody(peerUserId)))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun imListMessages(conversationId: Int): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        Result.success(fhd().imListMessages(conversationId))
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun imSendMessage(conversationId: Int, text: String): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        val body = fhd().imSendMessage(conversationId, ImSendBody(text))
        @Suppress("UNCHECKED_CAST")
        val msg = body["message"] as? Map<String, Any?>
        if (msg != null) {
            imRepo.cacheSentMessage(msg)
        }
        Result.success(body)
    } catch (e: Exception) {
        Result.failure(e)
    }

    private suspend fun parseMobileList(
        loader: suspend () -> Map<String, Any?>?,
    ): Result<List<ListItem>> = try {
        syncRouterFromStore()
        preferCloudIfLanUnreachable()
        val data = loader() ?: emptyMap()
        val items = (data["items"] as? List<*>) ?: emptyList<Any>()
        Result.success(items.mapNotNull { row ->
            when (row) {
                is Map<*, *> -> ListItem(
                    id = "${row["id"]}",
                    title = "${row["title"] ?: row["name"] ?: row["order_number"]}",
                    subtitle = "${row["status"] ?: ""}",
                    payload = @Suppress("UNCHECKED_CAST") (row as? Map<String, Any?>) ?: emptyMap(),
                )
                else -> null
            }
        })
    } catch (e: Exception) {
        Result.failure(e)
    }

    private fun Map<*, *>.toModInfo(): ModInfo {
        val industryMap = this["industry"] as? Map<*, *>
        val menus = ((this["frontend_menu"] ?: this["menu"] ?: this["menus"]) as? List<*>)
            ?.mapNotNull { row -> (row as? Map<*, *>)?.toModMenuItem() }
            ?: emptyList()
        val overrides = (this["menu_overrides"] as? List<*>)
            ?.mapNotNull { row -> (row as? Map<*, *>)?.toModMenuOverride() }
            ?: emptyList()
        val manifest = this["manifest"] as? Map<*, *>
        val workflowEmployees = ((this["workflow_employees"] ?: manifest?.get("workflow_employees")) as? List<*>)
            ?.mapNotNull { row -> (row as? Map<*, *>)?.toWorkflowEmployeeInfo() }
            ?: emptyList()
        return ModInfo(
            id = textValue("id"),
            name = textValue("name").ifBlank { textValue("title") },
            version = textValue("version"),
            description = textValue("description"),
            author = textValue("author"),
            primary = this["primary"] as? Boolean ?: false,
            industry = industryMap?.let {
                ModIndustry(
                    id = it.textValue("id"),
                    name = it.textValue("name").ifBlank { it.textValue("label") },
                )
            },
            avatar_url = textValue("avatar_url").ifBlank { null },
            frontend_menu = menus,
            menu_overrides = overrides,
            workflow_employees = workflowEmployees,
        )
    }

    private fun Map<*, *>.toWorkflowEmployeeInfo(): WorkflowEmployeeInfo {
        return WorkflowEmployeeInfo(
            id = textValue("id"),
            label = textValue("label").ifBlank { textValue("name") },
            panel_title = textValue("panel_title"),
            panel_summary = textValue("panel_summary"),
            api_base_path = textValue("api_base_path"),
            phone_channel = textValue("phone_channel"),
            workflow_placeholder = this["workflow_placeholder"] as? Boolean ?: false,
            profile_source = textValue("profile_source"),
            market_connected = this["market_connected"] as? Boolean ?: false,
            market_pkg_id = textValue("market_pkg_id"),
            market_name = textValue("market_name"),
            market_description = textValue("market_description"),
            market_version = textValue("market_version"),
            market_author = textValue("market_author"),
            market_industry = textValue("market_industry"),
            market_material_category = textValue("market_material_category"),
            market_license_scope = textValue("market_license_scope"),
            market_security_level = textValue("market_security_level"),
            market_avatar = textValue("market_avatar").ifBlank { null },
        )
    }

    private fun Map<*, *>.toModMenuItem(): ModMenuItem {
        return ModMenuItem(
            id = textValue("id").ifBlank { textValue("key") },
            label = textValue("label").ifBlank { textValue("name") },
            icon = textValue("icon"),
            path = textValue("path").ifBlank { textValue("route") },
        )
    }

    private fun Map<*, *>.toModMenuOverride(): ModMenuOverride {
        return ModMenuOverride(
            key = textValue("key").ifBlank { textValue("id") },
            label = optionalTextValue("label"),
            icon = optionalTextValue("icon"),
            hidden = this["hidden"] as? Boolean,
        )
    }

    private fun AdminMobileHomeData.toAdminModInfo(): ModInfo {
        val count = if (employee_count > 0) employee_count else employees.size
        return ModInfo(
            id = "admin-duty-employees",
            name = "管理端 AI 员工",
            version = "10.0",
            description = "${count} 位管理端 duty AI 员工与 ${features.size} 个管理功能入口",
            author = "XCAGI 管理端",
            primary = true,
            industry = ModIndustry(id = "admin", name = "管理端"),
            frontend_menu =
                features.map { feature ->
                    ModMenuItem(
                        id = feature.id,
                        label = feature.title,
                        icon = feature.category,
                        path = feature.api_path,
                    )
                },
            workflow_employees =
                employees.map { employee ->
                    val name =
                        employee.name
                            .ifBlank { employee.label }
                            .ifBlank { employee.title }
                            .ifBlank { employee.id }
                    WorkflowEmployeeInfo(
                        id = employee.id,
                        label = name,
                        panel_title = employee.title.ifBlank { name },
                        panel_summary =
                            employee.description
                                .ifBlank { employee.panel_summary }
                                .ifBlank { "管理端 ${employee.yuangon_area.ifBlank { "duty" }} 员工" },
                        api_base_path = employee.api_base_path,
                        phone_channel = employee.phone_channel.ifBlank { "admin-duty" },
                        workflow_placeholder = false,
                        profile_source = employee.profile_source.ifBlank { "admin" },
                        market_connected = employee.market_connected,
                        market_pkg_id = employee.market_pkg_id,
                        market_name = employee.market_name,
                        market_description = employee.market_description,
                        market_version = employee.market_version,
                        market_author = employee.market_author,
                        market_industry = employee.market_industry,
                        market_material_category = employee.market_material_category,
                        market_license_scope = employee.market_license_scope,
                        market_security_level = employee.market_security_level,
                        market_avatar = employee.market_avatar,
                    )
                },
        )
    }

    private fun Map<*, *>.textValue(key: String): String = this[key]?.toString()?.trim().orEmpty()

    private fun Map<*, *>.optionalTextValue(key: String): String? =
        this[key]?.toString()?.trim()?.takeIf { it.isNotBlank() }
}
