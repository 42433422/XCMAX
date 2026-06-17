package com.xiuci.xcagi.mobile.core.repository

import android.os.Build
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.db.ApprovalCacheEntity
import com.xiuci.xcagi.mobile.core.db.ChatCacheEntity
import com.xiuci.xcagi.mobile.core.db.ShipmentCacheEntity
import com.xiuci.xcagi.mobile.core.db.XcagiDatabase
import com.xiuci.xcagi.mobile.core.model.AccessRequestPayload
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.core.model.MarketAuthResponse
import com.xiuci.xcagi.mobile.core.model.MarketLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketPasswordLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketRegisterBody
import com.xiuci.xcagi.mobile.core.model.MarketSendCodeBody
import com.xiuci.xcagi.mobile.core.model.ModIndustry
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import com.xiuci.xcagi.mobile.core.model.ModMenuOverride
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
import com.xiuci.xcagi.mobile.core.network.PairingExchangeBody
import com.xiuci.xcagi.mobile.core.network.RegisterRequest
import com.xiuci.xcagi.mobile.core.network.RejectBody
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.core.network.ServerMode
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.core.network.SseChatClient
import com.google.gson.Gson
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.SharedFlow
import okhttp3.OkHttpClient
import org.json.JSONObject
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

internal object AuthRoutingPolicy {
    fun shouldUseEnterpriseAuthHost(isEnterprise: Boolean, configuredHost: String): Boolean =
        isEnterprise && configuredHost.isNotBlank()

    fun preferredServerModeAfterLogin(isEnterprise: Boolean, configuredHost: String): ServerMode =
        if (shouldUseEnterpriseAuthHost(isEnterprise, configuredHost)) {
            ServerMode.LAN
        } else {
            ServerMode.CLOUD
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

    private fun isEnterpriseAccountKind(kind: String): Boolean = when (normalizeAccountKind(kind)) {
        "enterprise", "admin", "admin_portal" -> true
        else -> false
    }

    private fun isAdminRole(raw: String): Boolean = normalizeAccountKind(raw).contains("admin")

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

    suspend fun loginFhd(
            username: String,
            password: String,
            accountKind: String = ProductSkuConfig.accountKind,
    ): Result<String> = try {
        syncRouterFromStore()
        val normalizedKind = normalizeAccountKind(accountKind)
        val res = fhd().mobileLogin(
            MobileLoginRequest(username, password, normalizedKind),
        )
        if (!res.success || res.data?.access_token.isNullOrBlank()) {
            Result.failure(Exception(res.message.ifBlank { "登录失败" }))
        } else {
            val d = res.data!!
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
            refreshMe(resolvedKind)
            registerDeviceToken()
            syncMarketSessionHandoff()
            Result.success(d.user?.display_name ?: username)
        }
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** 从 FHD 会话拉取 MODstore token，供工作台 WebView 注入。 */
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

    suspend fun register(username: String, password: String, email: String): Result<Unit> {
        syncRouterFromStore()
        return if (isPcReachable()) registerOnPc(username, password, email) else registerOnCloud(username, password, email)
    }

    private suspend fun registerOnPc(username: String, password: String, email: String): Result<Unit> = try {
        val r = fhd().register(RegisterRequest(username, password, email.ifBlank { null }))
        if (r["success"] == false) Result.failure(Exception(r["message"]?.toString() ?: "注册失败"))
        else Result.success(Unit)
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

    suspend fun refreshMe(preferredKind: String = ProductSkuConfig.accountKind) {
        try {
            val me = fhd().me()
            val uid = me.data?.user?.id ?: 0
            if (uid > 0) sessionStore.setUserId(uid)
            val currentKind = sessionStore.accountKindFlow.first()
            if (currentKind.isNotBlank()) return
            val resolvedKind = resolveAccountKindFromSignals(
                me.data?.account_kind,
                me.data?.user?.role,
                preferredKind,
            )
            sessionStore.setAccountKind(resolvedKind)
        } catch (_: Exception) {
        }
    }

    suspend fun fetchAppConfig(): Result<AppConfigResponse> = try {
        val cfg = modstore().appConfig(sku = BuildConfig.PRODUCT_SKU)
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

    suspend fun pairingExchange(
        nonce: String = "",
        code: String = "",
        exchangeHost: String = "",
        exchangePort: Int = 0,
    ): Result<Pair<String, Int>> {
        return try {
            val targetHost = exchangeHost.trim()
            if (targetHost.isBlank() && code.isNotBlank() && sessionStore.fhdHostFlow.first().isBlank()) {
                return Result.failure(Exception("请扫描电脑端二维码完成首次绑定"))
            }
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
            val r = fhd().pairingExchange(PairingExchangeBody(nonce = nonce, code = code))
            val d = r.data ?: return Result.failure(Exception(r.message))
            val host = d["host"]?.toString() ?: return Result.failure(Exception("无 host"))
            val port = (d["port"] as? Number)?.toInt() ?: 5000
            val hostWithPort = if (":" in host) host else "$host:$port"
            sessionStore.setFhdHost(hostWithPort)
            serverRouter.fhdHost = hostWithPort
            Result.success(host to port)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun confirmAuthQr(qrId: String, username: String, password: String): Result<Unit> {
        return try {
            syncRouterFromStore()
            val r = fhd().authQrConfirm(
                AuthQrConfirmBody(qr_id = qrId, username = username, password = password),
            )
            if (r.success != true) {
                Result.failure(Exception(r.message ?: "扫码登录确认失败"))
            } else {
                Result.success(Unit)
            }
        } catch (e: Exception) {
            Result.failure(e)
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
                    val d = res.data!!
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
            Result.failure(e)
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
        )

    suspend fun streamChat(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        syncRouterFromStore()
        db.chatDao().insert(ChatCacheEntity(role = "user", text = message))
        val acc = StringBuilder()
        val useCloud = !isPcReachable()
        sseChat.streamChat(
            message,
            authHeader(),
            userId(),
            useCloud = useCloud,
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
            db.chatDao().insert(ChatCacheEntity(role = "assistant", text = finalText))
        }
    }

    suspend fun streamChatCloud(
        message: String,
        onToken: (String) -> Unit,
        onDone: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        streamChat(message, onToken, onDone, onError)
    }

    suspend fun loadCachedChat(): List<Pair<String, String>> =
        db.chatDao().all().map { it.role to it.text }

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
        val res = fhd().bridgeRequests()
        val items = (res["data"] as? List<*>) ?: emptyList<Any>()
        Result.success(items.mapNotNull { row ->
            (row as? Map<*, *>)?.let {
                ListItem(
                    id = "${it["id"]}",
                    title = "${it["title"] ?: ""}",
                    subtitle = "${it["status"] ?: ""}",
                )
            }
        })
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun bridgeRespond(id: Int, text: String): Result<Unit> = try {
        fhd().bridgeRespond(id, BridgeRespondBody(text, "android"))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    suspend fun mods(): Result<List<ListItem>> = parseMobileList {
        fhd().mobileMods().data
    }

    suspend fun loadModInfos(): Result<List<ModInfo>> = try {
        syncRouterFromStore()
        val body = if (isPcReachable()) {
            fhd().modsList()
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

    suspend fun fetchHome(): Result<Map<String, Any?>> = try {
        syncRouterFromStore()
        val res = fhd().mobileHome()
        if (!res.success) Result.failure(Exception(res.message ?: "加载失败"))
        else Result.success(res.data ?: emptyMap())
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

    private fun Map<*, *>.textValue(key: String): String = this[key]?.toString()?.trim().orEmpty()

    private fun Map<*, *>.optionalTextValue(key: String): String? =
        this[key]?.toString()?.trim()?.takeIf { it.isNotBlank() }
}
