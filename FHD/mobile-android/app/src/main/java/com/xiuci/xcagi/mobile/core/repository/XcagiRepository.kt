package com.xiuci.xcagi.mobile.core.repository

import android.os.Build
import com.google.gson.Gson
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.db.ApprovalCacheEntity
import com.xiuci.xcagi.mobile.core.db.ChatCacheEntity
import com.xiuci.xcagi.mobile.core.db.ImMessageCacheEntity
import com.xiuci.xcagi.mobile.core.db.ShipmentCacheEntity
import com.xiuci.xcagi.mobile.core.db.XcagiDatabase
import com.xiuci.xcagi.mobile.core.im.ImRepository
import com.xiuci.xcagi.mobile.core.im.ImWebSocketClient
import com.xiuci.xcagi.mobile.core.model.AccessRequestPayload
import com.xiuci.xcagi.mobile.core.model.AccountDeleteBody
import com.xiuci.xcagi.mobile.core.model.AppConfigResponse
import com.xiuci.xcagi.mobile.core.model.AppFeedbackBody
import com.xiuci.xcagi.mobile.core.model.DeviceRegisterBody
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
import com.xiuci.xcagi.mobile.core.network.ApproveBody
import com.xiuci.xcagi.mobile.core.network.AuthQrConfirmBody
import com.xiuci.xcagi.mobile.core.network.BridgeRespondBody
import com.xiuci.xcagi.mobile.core.network.FhdApi
import com.xiuci.xcagi.mobile.core.network.ImDirectBody
import com.xiuci.xcagi.mobile.core.network.ImSendBody
import com.xiuci.xcagi.mobile.core.network.LanScanner
import com.xiuci.xcagi.mobile.core.network.MobileLoginRequest
import com.xiuci.xcagi.mobile.core.network.MobilePhoneLoginRequest
import com.xiuci.xcagi.mobile.core.network.ModstoreApi
import com.xiuci.xcagi.mobile.core.network.PairingExchangeBody
import com.xiuci.xcagi.mobile.core.network.PairingQrCodec
import com.xiuci.xcagi.mobile.core.network.RegisterRequest
import com.xiuci.xcagi.mobile.core.network.RejectBody
import com.xiuci.xcagi.mobile.core.network.ServerMode
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.core.network.SseChatClient
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import org.json.JSONObject
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

@Singleton
class XcagiRepository
@Inject
constructor(
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
                    val payload =
                            gson.fromJson(row.json, Map::class.java) as? Map<String, Any?>
                                    ?: emptyMap()
                    ListItem(
                            id = row.requestId.toString(),
                            title = row.title.ifBlank { "审批 #${row.requestId}" },
                            subtitle =
                                    listOf(row.status, "离线缓存")
                                            .filter { it.isNotBlank() }
                                            .joinToString(" · "),
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
                    val payload =
                            gson.fromJson(row.json, Map::class.java) as? Map<String, Any?>
                                    ?: emptyMap()
                    ListItem(
                            id = row.shipmentId.toString(),
                            title = row.orderNumber.ifBlank { "发货 #${row.shipmentId}" },
                            subtitle =
                                    listOf(row.status, "离线缓存")
                                            .filter { it.isNotBlank() }
                                            .joinToString(" · "),
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
            fhdApi =
                    Retrofit.Builder()
                            .baseUrl(base)
                            .client(okHttp)
                            .addConverterFactory(GsonConverterFactory.create())
                            .build()
                            .create(FhdApi::class.java)
        }
        return fhdApi!!
    }

    private fun modstore(): ModstoreApi {
        val base = serverRouter.modstoreBaseUrl()
        return modstoreApi
                ?: Retrofit.Builder()
                        .baseUrl(base)
                        .client(okHttp)
                        .addConverterFactory(GsonConverterFactory.create())
                        .build()
                        .create(ModstoreApi::class.java)
                        .also { modstoreApi = it }
    }

    suspend fun checkHealth(host: String? = null): Boolean {
        syncRouterFromStore()
        val h = (host ?: serverRouter.fhdHost).trim()
        val bare = h.substringBefore(':').trim()
        val port =
            h.substringAfter(':', "").toIntOrNull()
                ?: BuildConfig.FHD_DEFAULT_PORT
        return lanScanner.probeHealth(bare, port)
    }

    suspend fun scanLan(prefix: String): List<String> = lanScanner.scanSubnet(prefix)

    suspend fun loginFhd(username: String, password: String): Result<String> =
            try {
                syncRouterFromStore()
                val res =
                        fhd().mobileLogin(
                                        MobileLoginRequest(
                                                username,
                                                password,
                                                ProductSkuConfig.accountKind
                                        ),
                                )
                if (!res.success || res.data?.access_token.isNullOrBlank()) {
                    Result.failure(Exception(res.message.ifBlank { "登录失败" }))
                } else {
                    val d = res.data!!
                    sessionStore.saveFhdAuth(
                            d.access_token!!,
                            d.refresh_token ?: "",
                            d.session_id ?: "",
                            d.user?.username ?: username,
                            userId = d.user?.id ?: 0,
                    )
                    refreshMe()
                    registerDeviceToken()
                    syncMarketSessionHandoff()
                    Result.success(d.user?.display_name ?: username)
                }
            } catch (e: Exception) {
                Result.failure(e)
            }

    /** 从 FHD 会话拉取 MODstore token，供工作台 WebView 注入。 */
    suspend fun syncMarketSessionHandoff(): Result<Unit> =
            try {
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

    fun workbenchHomeUrl(): String {
        val base = BuildConfig.MODSTORE_BASE_URL.trimEnd('/')
        val sku = BuildConfig.PRODUCT_SKU
        return "$base/workbench/home?client=android&sku=$sku"
    }

    suspend fun marketTokensForWeb(): Pair<String, String> {
        val access = sessionStore.marketAccessToken().ifBlank { sessionStore.fhdAccessFlow.first() }
        val refresh = sessionStore.marketRefreshToken()
        return access to refresh
    }

    suspend fun register(username: String, password: String, email: String): Result<Unit> {
        syncRouterFromStore()
        return if (isPcReachable()) registerOnPc(username, password, email)
        else registerOnCloud(username, password, email)
    }

    private suspend fun registerOnPc(
            username: String,
            password: String,
            email: String
    ): Result<Unit> =
            try {
                val r = fhd().register(RegisterRequest(username, password, email.ifBlank { null }))
                if (r["success"] == false)
                        Result.failure(Exception(r["message"]?.toString() ?: "注册失败"))
                else Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    private suspend fun registerOnCloud(
            username: String,
            password: String,
            email: String
    ): Result<Unit> {
        if (email.isBlank() || !email.contains("@")) {
            return Result.failure(Exception("云端注册需填写有效邮箱；也可直接使用手机号登录"))
        }
        return try {
            val res = modstore().register(MarketRegisterBody(username, password, email.trim()))
            if (!res.isAuthenticated()) {
                val hint = res.message?.takeIf { it.isNotBlank() } ?: "请先在官网获取邮箱验证码，或改用手机号登录"
                Result.failure(Exception(hint))
            } else {
                applyMarketAuth(res, username)
                Result.success(Unit)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun refreshMe() {
        try {
            val me = fhd().me()
            val uid = me.data?.user?.id ?: 0
            if (uid > 0) sessionStore.setUserId(uid)
        } catch (_: Exception) {}
    }

    suspend fun fetchAppConfig(): Result<AppConfigResponse> =
            try {
                val cfg = modstore().appConfig(sku = BuildConfig.PRODUCT_SKU)
                Result.success(cfg)
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun deleteAccount(password: String): Result<Unit> =
            try {
                modstore().deleteAccount(AccountDeleteBody(password))
                logout()
                Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun exportAccountData(): Result<Map<String, Any?>> =
            try {
                Result.success(modstore().exportAccount())
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun submitFeedback(message: String, contact: String = ""): Result<Unit> =
            try {
                modstore()
                        .submitFeedback(
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
        } catch (_: Exception) {}
    }

    /** 配对交换：v1 直连电脑，v2 通过 token/配对码云端查询后获取连接信息。 */
    suspend fun pairingExchange(
        nonce: String = "",
        code: String = "",
        exchangeHost: String = "",
        exchangePort: Int = 0,
    ): Result<Pair<String, Int>> {
        return try {
            syncRouterFromStore()

            // v2 模式：通过配对码（6位数字）或 token 走云端查询
            val trimmedCode = code.trim()
            if (trimmedCode.length == 6 && trimmedCode.all { it.isDigit() }) {
                // 纯数字配对码 → 用默认云端 API 做 exchange（后端会自动 lookup+consume）
                val api = fhd()
                val r = api.pairingExchange(PairingExchangeBody(code = trimmedCode))
                val d = r.data ?: return Result.failure(Exception(r.message.ifBlank { "配对失败" }))
                return extractHostPort(d)
            }

            // v1 或 fallback：nonce 模式
            val trimmedNonce = nonce.trim()
            if (trimmedNonce.length < 8) {
                return Result.failure(Exception("配对码无效"))
            }

            val targetHost =
                exchangeHost.trim().removePrefix("http://").removePrefix("https://").substringBefore(':').trim()
            val targetPort =
                when {
                    exchangePort in 1..65535 -> exchangePort
                    exchangeHost.contains(":") ->
                        exchangeHost.substringAfter(':').toIntOrNull() ?: BuildConfig.FHD_DEFAULT_PORT
                    else -> 0
                }

            val api =
                if (targetHost.isNotBlank() && targetPort in 1..65535) {
                    fhdApiForBase("http://$targetHost:$targetPort/")
                } else {
                    fhd()
                }

            val r = api.pairingExchange(PairingExchangeBody(nonce = trimmedNonce))
            val d = r.data ?: return Result.failure(Exception(r.message.ifBlank { "配对失败" }))
            extractHostPort(d, fallbackHost = targetHost, fallbackPort = targetPort)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** 从 exchange 响应中提取 host:port 并持久化。 */
    private suspend fun extractHostPort(
        d: Map<String, Any?>,
        fallbackHost: String = "",
        fallbackPort: Int = 0,
    ): Result<Pair<String, Int>> {
        val host =
            d["host"]?.toString()?.trim()?.removePrefix("http://")?.removePrefix("https://")
                ?: fallbackHost.ifBlank { null }
                ?: return Result.failure(Exception("无 host"))
        val port = (d["port"] as? Number)?.toInt()
            ?: fallbackPort.takeIf { it > 0 }
            ?: BuildConfig.FHD_DEFAULT_PORT
        val bareHost = host.substringBefore(':').trim()
        val hostWithPort = PairingQrCodec.formatHostPort(bareHost, port)
        sessionStore.setFhdHost(hostWithPort)
        sessionStore.setServerMode("lan")
        serverRouter.mode = ServerMode.LAN
        serverRouter.fhdHost = hostWithPort
        fhdApi = null
        cachedFhdBase = ""
        return Result.success(bareHost to port)
    }

    private fun fhdApiForBase(base: String): FhdApi {
        val normalized = if (base.endsWith("/")) base else "$base/"
        return Retrofit.Builder()
            .baseUrl(normalized)
            .client(okHttp)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(FhdApi::class.java)
    }

    suspend fun confirmAuthQr(qrId: String, username: String, password: String): Result<Unit> {
        return try {
            syncRouterFromStore()
            val r =
                    fhd().authQrConfirm(
                                    AuthQrConfirmBody(
                                            qr_id = qrId,
                                            username = username,
                                            password = password
                                    ),
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

    suspend fun requestLanAccess(note: String): Result<String> =
            try {
                syncRouterFromStore()
                fhd().lanAccessRequest(AccessRequestPayload("Android-${Build.MODEL}", note))
                Result.success("已提交 LAN 入网申请")
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun sendMarketCode(phone: String) =
            try {
                modstore().sendPhoneCode(MarketSendCodeBody(phone))
                Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    private suspend fun resolveMarketUserIsEnterprise(res: MarketAuthResponse): Boolean {
        res.userIsEnterprise()?.let {
            return it
        }
        return try {
            modstore().authMe().is_enterprise
        } catch (_: Exception) {
            false
        }
    }

    private fun validateSkuAccount(isEnterprise: Boolean, isAdmin: Boolean = false): Result<Unit> {
        if (isAdmin) return Result.success(Unit)
        if (ProductSkuConfig.isEnterprise && !isEnterprise) {
            return Result.failure(Exception("该账号为个人账号，请安装并使用「XCAGI 个人版」"))
        }
        if (ProductSkuConfig.isPersonal && isEnterprise) {
            return Result.failure(Exception("该账号为企业账号，请安装并使用「XCAGI 企业版」"))
        }
        return Result.success(Unit)
    }

    private suspend fun applyMarketAuth(
            res: MarketAuthResponse,
            displayName: String,
            isAdmin: Boolean = false
    ): Result<String> {
        val token = res.accessToken()
        if (!res.isAuthenticated() || token.isNullOrBlank()) {
            return Result.failure(Exception(res.message ?: "登录失败"))
        }
        sessionStore.setMarketTokens(token, res.refresh_token?.trim().orEmpty())
        val isEnterprise = resolveMarketUserIsEnterprise(res)
        validateSkuAccount(isEnterprise, isAdmin).getOrElse {
            return Result.failure(it)
        }
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
        } catch (_: Exception) {}
    }

    suspend fun loginMarketPhone(phone: String, code: String): Result<String> {
        return try {
            if (isPcReachable()) {
                val res =
                        fhd().mobileLoginWithPhone(
                                        MobilePhoneLoginRequest(
                                                phone = phone,
                                                code = code,
                                                account_kind = ProductSkuConfig.accountKind
                                        ),
                                )
                if (!res.success || res.data?.access_token.isNullOrBlank()) {
                    Result.failure(Exception(res.message.ifBlank { "手机验证码登录失败" }))
                } else {
                    val d = res.data!!
                    sessionStore.saveFhdAuth(
                            d.access_token!!,
                            d.refresh_token ?: "",
                            d.session_id ?: "",
                            d.user?.username ?: phone,
                            userId = d.user?.id ?: 0,
                    )
                    refreshMe()
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
            isAdmin: Boolean = false
    ): Result<String> =
            try {
                val res = modstore().loginWithPassword(MarketPasswordLoginBody(username, password))
                applyMarketAuth(res, username, isAdmin)
            } catch (e: Exception) {
                Result.failure(e)
            }

    /** 账号密码登录：电脑在线走 FHD（并 session-handoff 市场 token）； 纯云端走 MODstore 同一套用户名密码。 */
    suspend fun loginUnified(
            username: String,
            password: String,
            isAdmin: Boolean = false
    ): Result<String> {
        syncRouterFromStore()
        return if (isPcReachable()) loginFhd(username, password)
        else loginMarketPassword(username, password, isAdmin)
    }

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

    /** 云端对话：无本地 FHD 认证时使用 MODstore 云端 API。 */
    suspend fun streamChatCloud(
            message: String,
            onToken: (String) -> Unit,
            onDone: (String) -> Unit,
            onError: (String) -> Unit,
    ) {
        syncRouterFromStore()
        db.chatDao().insert(ChatCacheEntity(role = "user", text = message))
        val acc = StringBuilder()
        val marketToken = sessionStore.marketAccessToken()
        val bearer = if (marketToken.isNotBlank()) "Bearer $marketToken" else ""
        sseChat.streamChat(
                message,
                bearer,
                userId(),
                useCloud = true,
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

    suspend fun loadCachedChat(): List<Pair<String, String>> =
            db.chatDao().all().map { it.role to it.text }

    suspend fun approvals(): Result<List<ListItem>> {
        val remote = parseMobileList { fhd().mobileApprovals().data }
        remote.getOrNull()?.forEach { item ->
            val rid = item.id.toIntOrNull() ?: return@forEach
            db.approvalDao()
                    .insert(
                            ApprovalCacheEntity(
                                    rid,
                                    item.title,
                                    item.subtitle,
                                    gson.toJson(item.payload)
                            ),
                    )
        }
        if (remote.isSuccess) return remote
        val cached = cachedApprovalItems()
        return if (cached.isNotEmpty()) Result.success(cached) else remote
    }

    suspend fun approvalDetail(id: Int): Result<Map<String, Any?>> =
            try {
                syncRouterFromStore()
                Result.success(fhd().approvalDetail(id))
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun approve(id: Int, opinion: String): Result<Unit> =
            try {
                val uid = userId()
                fhd().approvalApprove(id, ApproveBody(uid, opinion))
                Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun reject(id: Int, reason: String): Result<Unit> =
            try {
                val uid = userId()
                fhd().approvalReject(id, RejectBody(uid, reason))
                Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun customers(): Result<List<ListItem>> {
        val result = parseMobileList { fhd().mobileCustomers().data }
        return if (result.isSuccess) result else Result.success(emptyList())
    }

    suspend fun shipments(): Result<List<ListItem>> {
        val remote = parseMobileList { fhd().mobileShipments().data }
        remote.getOrNull()?.forEach { item ->
            val sid = item.id.toIntOrNull() ?: return@forEach
            db.shipmentDao()
                    .insert(
                            ShipmentCacheEntity(
                                    sid,
                                    item.title,
                                    item.subtitle,
                                    gson.toJson(item.payload)
                            ),
                    )
        }
        if (remote.isSuccess) return remote
        val cached = cachedShipmentItems()
        return if (cached.isNotEmpty()) Result.success(cached) else remote
    }
    suspend fun bridgeRequests(): Result<List<ListItem>> =
            try {
                syncRouterFromStore()
                val res = fhd().bridgeRequests()
                val items = (res["data"] as? List<*>) ?: emptyList<Any>()
                Result.success(
                        items.mapNotNull { row ->
                            (row as? Map<*, *>)?.let {
                                ListItem(
                                        id = "${it["id"]}",
                                        title = "${it["title"] ?: ""}",
                                        subtitle = "${it["status"] ?: ""}",
                                )
                            }
                        }
                )
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun bridgeRespond(id: Int, text: String): Result<Unit> =
            try {
                fhd().bridgeRespond(id, BridgeRespondBody(text, "android"))
                Result.success(Unit)
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun mods(): Result<List<ListItem>> = parseMobileList { fhd().mobileMods().data }

    /** 加载完整 ModInfo 列表：局域网优先，云端 fallback。 */
    suspend fun loadModInfos(): Result<List<ModInfo>> =
            try {
                syncRouterFromStore()
                val items: List<*> =
                        try {
                            // 局域网：使用桌面端完整 API
                            val res = fhd().modsList()
                            @Suppress("UNCHECKED_CAST")
                            (res["items"] as? List<*>)
                                    ?: (res["mods"] as? List<*>) ?: emptyList<Any?>()
                        } catch (_: Exception) {
                            // 云端 fallback
                            try {
                                val token = sessionStore.marketAccessToken()
                                val auth = if (token.isNotBlank()) "Bearer $token" else null
                                val res = modstore().installedMods(auth)
                                @Suppress("UNCHECKED_CAST")
                                (res["items"] as? List<*>)
                                        ?: (res["mods"] as? List<*>) ?: emptyList<Any?>()
                            } catch (_: Exception) {
                                emptyList<Any?>()
                            }
                        }
                val modInfos =
                        items.mapNotNull { row -> (row as? Map<*, *>)?.let { parseModInfo(it) } }
                Result.success(modInfos)
            } catch (e: Exception) {
                Result.failure(e)
            }

    @Suppress("UNCHECKED_CAST")
    private fun parseModInfo(map: Map<*, *>): ModInfo? {
        val id = map["id"] as? String ?: return null
        val name = map["name"] as? String ?: id
        val version = map["version"] as? String ?: ""
        val description = map["description"] as? String ?: ""
        val author = map["author"] as? String ?: ""
        val primary = map["primary"] as? Boolean ?: false
        val industryMap = map["industry"] as? Map<String, Any?>
        val industry =
                industryMap?.let {
                    ModIndustry(id = it["id"] as? String ?: "", name = it["name"] as? String ?: "")
                }
        val menuList =
                (map["frontend_menu"] as? List<Map<String, Any?>>)
                        ?: (map["menu"] as? List<Map<String, Any?>>) ?: emptyList()
        val frontendMenu =
                menuList.map { m ->
                    ModMenuItem(
                            id = m["id"] as? String ?: "",
                            label = m["label"] as? String ?: "",
                            icon = m["icon"] as? String ?: "",
                            path = m["path"] as? String ?: "",
                    )
                }
        val overridesList = (map["menu_overrides"] as? List<Map<String, Any?>>) ?: emptyList()
        val menuOverrides =
                overridesList.map { m ->
                    ModMenuOverride(
                            key = m["key"] as? String ?: "",
                            label = m["label"] as? String?,
                            icon = m["icon"] as? String?,
                            hidden = m["hidden"] as? Boolean,
                    )
                }
        return ModInfo(
                id = id,
                name = name,
                version = version,
                description = description,
                author = author,
                primary = primary,
                industry = industry,
                frontend_menu = frontendMenu,
                menu_overrides = menuOverrides,
        )
    }

    suspend fun fetchHome(): Result<Map<String, Any?>> =
            try {
                syncRouterFromStore()
                val res = fhd().mobileHome()
                if (!res.success) Result.failure(Exception(res.message ?: "加载失败"))
                else Result.success(res.data ?: emptyMap())
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun marketCatalog(): Result<List<ListItem>> =
            try {
                val tok =
                        sessionStore.marketTokenFlow.first().ifBlank {
                            sessionStore.fhdAccessFlow.first()
                        }
                val auth = if (tok.isNotBlank()) "Bearer $tok" else null
                val res = modstore().marketCatalog(auth)
                val items = (res["items"] as? List<*>) ?: emptyList<Any>()
                Result.success(
                        items.mapNotNull { row ->
                            (row as? Map<*, *>)?.let {
                                val desc =
                                        (it["description"] ?: it["summary"] ?: it["tagline"] ?: "")
                                                .toString()
                                                .trim()
                                ListItem(
                                        id = "${it["id"]}",
                                        title = "${it["name"] ?: it["title"]}",
                                        subtitle = desc,
                                )
                            }
                        }
                )
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun inventory(): Result<List<String>> =
            try {
                syncRouterFromStore()
                val res = fhd().inventoryItems()
                val items =
                        (res["data"] as? List<*>) ?: (res["items"] as? List<*>) ?: emptyList<Any>()
                Result.success(items.map { it.toString() })
            } catch (_: Exception) {
                Result.success(emptyList())
            }

    suspend fun financeSummary(): Result<String> =
            try {
                syncRouterFromStore()
                Result.success(fhd().financeSummary().toString())
            } catch (_: Exception) {
                Result.success("数据同步中")
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

    val imWsEvents: SharedFlow<JSONObject>
        get() = imWebSocket.events

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

    suspend fun seedImMessages(conversationId: Int): Result<Unit> =
            try {
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

    suspend fun imOpenDirect(peerUserId: Int): Result<Map<String, Any?>> =
            try {
                syncRouterFromStore()
                Result.success(fhd().imCreateDirect(ImDirectBody(peerUserId)))
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun imListMessages(conversationId: Int): Result<Map<String, Any?>> =
            try {
                syncRouterFromStore()
                Result.success(fhd().imListMessages(conversationId))
            } catch (e: Exception) {
                Result.failure(e)
            }

    suspend fun imSendMessage(conversationId: Int, text: String): Result<Map<String, Any?>> =
            try {
                syncRouterFromStore()
                val body = fhd().imSendMessage(conversationId, ImSendBody(text))
                @Suppress("UNCHECKED_CAST") val msg = body["message"] as? Map<String, Any?>
                if (msg != null) {
                    imRepo.cacheSentMessage(msg)
                }
                Result.success(body)
            } catch (e: Exception) {
                Result.failure(e)
            }

    private suspend fun parseMobileList(
            loader: suspend () -> Map<String, Any?>?,
    ): Result<List<ListItem>> =
            try {
                syncRouterFromStore()
                val data = loader() ?: emptyMap()
                val items = (data["items"] as? List<*>) ?: emptyList<Any>()
                Result.success(
                        items.mapNotNull { row ->
                            when (row) {
                                is Map<*, *> ->
                                        ListItem(
                                                id = "${row["id"]}",
                                                title =
                                                        "${row["title"] ?: row["name"] ?: row["order_number"]}",
                                                subtitle = "${row["status"] ?: ""}",
                                                payload =
                                                        @Suppress("UNCHECKED_CAST")
                                                        (row as? Map<String, Any?>)
                                                                ?: emptyMap(),
                                        )
                                else -> null
                            }
                        }
                )
            } catch (e: Exception) {
                Result.failure(e)
            }
}
