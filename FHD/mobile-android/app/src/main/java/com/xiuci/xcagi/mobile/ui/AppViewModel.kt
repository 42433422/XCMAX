package com.xiuci.xcagi.mobile.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.core.cs.CsRepository
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.model.AppConfigResponse
import com.xiuci.xcagi.mobile.core.model.AiCirclePost
import com.xiuci.xcagi.mobile.core.model.ApprovalDetail
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.core.model.MeetingLevelDef
import com.xiuci.xcagi.mobile.core.model.MeetingMinuteData
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import com.xiuci.xcagi.mobile.core.network.PairingQrCodec
import com.xiuci.xcagi.mobile.core.network.ServerMode
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.core.network.WalletBalanceDto
import com.xiuci.xcagi.mobile.core.network.NavMenuItem
import com.xiuci.xcagi.mobile.core.observability.XcagiAnalytics
import com.xiuci.xcagi.mobile.core.push.PushRegistrar
import com.xiuci.xcagi.mobile.core.im.ImRepository
import com.xiuci.xcagi.mobile.core.repository.XcagiRepository
import com.xiuci.xcagi.mobile.core.sync.MobileSyncRepository
import com.xiuci.xcagi.mobile.core.update.ApkUpdater
import com.xiuci.xcagi.mobile.core.work.MobileSyncWorker
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.ConversationType
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.navigation.Routes
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.time.Instant
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

private val BadgeAdminColor = androidx.compose.ui.graphics.Color(0xFFED7B2F)     // 管理端徽标：警示橙
private val BadgeInstalledColor = androidx.compose.ui.graphics.Color(0xFF3370FF) // 已安装徽标：品牌蓝

data class UiMessage(val text: String, val isError: Boolean = false)

data class UpdatePrompt(
        val force: Boolean,
        val versionName: String,
        val downloadUrl: String,
)

/** 应用内自更新下载状态，驱动更新弹窗 UI。 */
sealed interface UpdateDownload {
    /** 未开始 / 已重置。 */
    data object Idle : UpdateDownload
    /** 下载中，[percent] 为 0..100。 */
    data class Downloading(val percent: Int) : UpdateDownload
    /** 下载完成，APK 落盘在 [apkPath]，等待安装。 */
    data class Ready(val apkPath: String) : UpdateDownload
    /** 下载失败，[reason] 为简短原因。 */
    data class Failed(val reason: String) : UpdateDownload
}

internal fun cachedConversationTimestamp(
        conversationId: String,
        timestamps: Map<String, Long>,
): Long = timestamps[conversationId]?.takeIf { it > 0L } ?: 0L

/** 从预览 Map 中取会话最新消息预览；无预览时返回空字符串（由调用方回退到介绍词）。 */
internal fun cachedConversationPreview(
        conversationId: String,
        previews: Map<String, String>,
): String = previews[conversationId]?.trim().orEmpty()

@HiltViewModel
class AppViewModel
@Inject
constructor(
        @ApplicationContext private val appContext: Context,
        private val repo: XcagiRepository,
        private val sessionStore: SessionStore,
        private val serverRouter: ServerRouter,
        private val syncRepo: MobileSyncRepository,
        private val pushRegistrar: PushRegistrar,
        private val analytics: XcagiAnalytics,
        private val csRepository: CsRepository,
) : ViewModel() {
    /** 缓存 TTL：超过此时间（毫秒）后再次进入页面会触发静默刷新。5 分钟。 */
    private val modInfoCacheTtlMs: Long = 5 * 60 * 1000L

    val isLoggedIn =
            sessionStore.isLoggedInFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    false
            )
    val isSetupComplete =
            sessionStore.isSetupCompleteFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    false
            )
    val autoLanProbe =
            sessionStore.autoLanProbeFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    false
            )
    val fhdHost =
            sessionStore.fhdHostFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    ""
            )

    val displayName =
            sessionStore.fhdUsernameFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    "",
            )

    val avatarUri =
            sessionStore.avatarUriFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    "",
            )

    val serverModeLabel =
            combine(
                    sessionStore.serverModeFlow,
                    sessionStore.fhdHostFlow,
                    sessionStore.relayDesktopIdFlow,
            ) { mode, host, relayId ->
                        when {
                            relayId.isNotBlank() -> "服务器中继 · 电脑执行端"
                            host.isNotBlank() -> "Agent 控制 · $host"
                            mode == "cloud" -> "远程同步可用"
                            else -> "本地连通待启"
                        }
                    }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "远程同步可用")

    val accountKindLabel =
            combine(sessionStore.accountKindFlow, isLoggedIn) { kind, loggedIn ->
                        when (val normalized = kind.trim().lowercase()) {
                            "admin", "admin_portal" -> "管理员账号"
                            "enterprise" -> "企业账号"
                            "personal" -> "个人账号"
                            else -> if (ProductSkuConfig.isEnterprise) "企业账号" else "个人账号"
                        }.let { if (loggedIn) it else "未登录" }
                    }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "未登录")

    private fun isAdminAccountKind(kind: String): Boolean =
            kind.trim().lowercase() in setOf("admin", "admin_portal")

    /**
     * 企业态有效判定（与 conversations 构建逻辑一致）：
     * 编译期企业 SKU 或运行时管理端账号命中其一即可。
     * 用于消息页 AI 群聊加载等场景，避免 admin 账号在 personal flavor 上漏加载 6 个部门群。
     */
    val isEnterpriseEffective =
            sessionStore.accountKindFlow
                    .map { ProductSkuConfig.showsEnterpriseNav || isAdminAccountKind(it) }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ProductSkuConfig.showsEnterpriseNav)

    private val _marketAccess = MutableStateFlow("")
    val marketAccess: StateFlow<String> = _marketAccess.asStateFlow()

    private val _marketRefresh = MutableStateFlow("")
    val marketRefresh: StateFlow<String> = _marketRefresh.asStateFlow()

    val fhdAccess =
            sessionStore.fhdAccessFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    "",
            )

    private fun registerPushWithHint() {
        viewModelScope.launch {
            val result = pushRegistrar.registerAll()
            if (!result.fcmRegistered && !result.jpushRegistered && result.hint != null) {
                // Push is optional. Do not show SDK/API-key diagnostics as a blocking login error.
                snack("消息提醒未开启，不影响登录和员工同步")
            }
        }
    }

    private suspend fun refreshConversationRuntime() {
        val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
        rebuildConversationItems(ProductSkuConfig.showsEnterpriseNav || adminMode)
    }

    private val _navReady = MutableStateFlow(false)
    val navReady: StateFlow<Boolean> = _navReady.asStateFlow()

    private val _startRoute = MutableStateFlow(Routes.LEGAL)
    val startRoute: StateFlow<String> = _startRoute.asStateFlow()

    private val _message = MutableStateFlow<UiMessage?>(null)
    val message: StateFlow<UiMessage?> = _message.asStateFlow()

    private val _chatMessages = MutableStateFlow<List<Pair<String, String>>>(emptyList())
    val chatMessages: StateFlow<List<Pair<String, String>>> = _chatMessages.asStateFlow()

    // 超级员工派工模式三态控件：auto=按内容自动判断 / chat=单设备直答 / code=多设备派工。
    // 仅对超级员工会话（Codex/Claude/Cursor）生效，替代后端 _TASK_MARKERS 关键词自动判断。
    private val _superMode = MutableStateFlow("auto")
    val superMode: StateFlow<String> = _superMode.asStateFlow()
    fun setSuperMode(mode: String) {
        _superMode.value = when (mode.trim().lowercase()) {
            "chat", "code" -> mode.trim().lowercase()
            else -> "auto"
        }
    }

    // ── 会议纪要 SSOT（三级派生） ──────────────────────────────────────────
    private val _meetingLevels = MutableStateFlow<List<MeetingLevelDef>>(
        listOf(
            MeetingLevelDef("level1_script", "剧本式实录", "剧本", "raw"),
            MeetingLevelDef("level2_architecture", "架构图式总结", "架构图", "level1_script", "mermaid"),
            MeetingLevelDef("level3_plain", "说人话", "说人话", "level2_architecture"),
        ),
    )
    val meetingLevels: StateFlow<List<MeetingLevelDef>> = _meetingLevels.asStateFlow()

    private val _meetingResult = MutableStateFlow<MeetingMinuteData?>(null)
    val meetingResult: StateFlow<MeetingMinuteData?> = _meetingResult.asStateFlow()

    private val _meetingGenerating = MutableStateFlow(false)
    val meetingGenerating: StateFlow<Boolean> = _meetingGenerating.asStateFlow()

    private val _meetingTranscribing = MutableStateFlow(false)
    val meetingTranscribing: StateFlow<Boolean> = _meetingTranscribing.asStateFlow()

    private val _meetingError = MutableStateFlow("")
    val meetingError: StateFlow<String> = _meetingError.asStateFlow()

    fun loadMeetingLevels() {
        viewModelScope.launch {
            repo.meetingLevels().onSuccess { cfg ->
                if (cfg.levels.isNotEmpty()) _meetingLevels.value = cfg.levels
            }
        }
    }

    /** 录音字节转写 → 返回文本（screen 负责把文本追加到原文）。 */
    fun transcribeMeeting(audio: ByteArray, mime: String, onText: (String) -> Unit) {
        _meetingError.value = ""
        _meetingTranscribing.value = true
        viewModelScope.launch {
            repo.transcribeMeetingAudio(audio, mime)
                .onSuccess { onText(it) }
                .onFailure { _meetingError.value = it.message?.take(60) ?: "转写失败" }
            _meetingTranscribing.value = false
        }
    }

    /** 一次性生成三级会议纪要。 */
    fun generateMeetingMinutes(transcript: String) {
        val text = transcript.trim()
        if (text.isEmpty() || _meetingGenerating.value) return
        _meetingError.value = ""
        _meetingGenerating.value = true
        viewModelScope.launch {
            repo.generateMeetingMinutes(text)
                .onSuccess { _meetingResult.value = it }
                .onFailure {
                    _meetingError.value = it.message?.take(80) ?: "生成失败"
                    _meetingResult.value = MeetingMinuteData(
                        status = "failed",
                        error_message = it.message,
                    )
                }
            _meetingGenerating.value = false
        }
    }

    private val _items = MutableStateFlow<List<ListItem>>(emptyList())
    val items: StateFlow<List<ListItem>> = _items.asStateFlow()

    private val _scanResults = MutableStateFlow<List<String>>(emptyList())
    val scanResults: StateFlow<List<String>> = _scanResults.asStateFlow()

    private val _detailJson = MutableStateFlow("")
    val detailJson: StateFlow<String> = _detailJson.asStateFlow()

    private val _approvalDetail = MutableStateFlow<ApprovalDetail?>(null)
    val approvalDetail: StateFlow<ApprovalDetail?> = _approvalDetail.asStateFlow()

    private val _approvalDetailLoading = MutableStateFlow(false)
    val approvalDetailLoading: StateFlow<Boolean> = _approvalDetailLoading.asStateFlow()

    private val _streaming = MutableStateFlow(false)
    val streaming: StateFlow<Boolean> = _streaming.asStateFlow()

    private val _listLoading = MutableStateFlow(false)
    val listLoading: StateFlow<Boolean> = _listLoading.asStateFlow()

    private val _listError = MutableStateFlow<String?>(null)
    val listError: StateFlow<String?> = _listError.asStateFlow()

    val isCloudMode =
            sessionStore
                    .serverModeFlow
                    .map { it == "cloud" }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), true)

    val chatConnectionChip =
            combine(
                    sessionStore.serverModeFlow,
                    sessionStore.fhdHostFlow,
                    sessionStore.relayDesktopIdFlow,
            ) { mode, host, relayId ->
                        when {
                            relayId.isNotBlank() -> "中继"
                            host.isNotBlank() -> "Agent"
                            mode == "cloud" -> "远程"
                            else -> "本地"
                        }
                    }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "远程")

    val isAgentControlActive =
            combine(sessionStore.fhdHostFlow, sessionStore.relayDesktopIdFlow) { host, relayId ->
                        host.isNotBlank() || relayId.isNotBlank()
                    }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    private val _homeHub = MutableStateFlow(HomeHubState())
    val homeHub: StateFlow<HomeHubState> = _homeHub.asStateFlow()

    /** 侧栏菜单（探索 Tab 配对后与桌面端侧栏对齐） */
    private val _navMenu = MutableStateFlow<List<NavMenuItem>>(emptyList())
    val navMenu: StateFlow<List<NavMenuItem>> = _navMenu.asStateFlow()

    // ── AI 群聊 ──
    private val _aiGroups = MutableStateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupDto>>(emptyList())
    val aiGroups: StateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupDto>> = _aiGroups.asStateFlow()
    private val _groupMessages = MutableStateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto>>(emptyList())
    val groupMessages: StateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto>> = _groupMessages.asStateFlow()
    private val _currentGroup = MutableStateFlow<com.xiuci.xcagi.mobile.core.model.AiGroupDto?>(null)
    val currentGroup: StateFlow<com.xiuci.xcagi.mobile.core.model.AiGroupDto?> = _currentGroup.asStateFlow()
    private val _groupSending = MutableStateFlow(false)
    val groupSending: StateFlow<Boolean> = _groupSending.asStateFlow()
    // 群成员候选(普通员工 + 超级员工),来自后端 SSOT 候选端点。
    private val _groupMemberCandidates =
            MutableStateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupCandidateDto>>(emptyList())
    val groupMemberCandidates:
            StateFlow<List<com.xiuci.xcagi.mobile.core.model.AiGroupCandidateDto>> =
            _groupMemberCandidates.asStateFlow()

    private val _walletBalance = MutableStateFlow<WalletBalanceDto?>(null)
    val walletBalance: StateFlow<WalletBalanceDto?> = _walletBalance.asStateFlow()

    private val _aiCirclePosts = MutableStateFlow<List<AiCirclePost>>(emptyList())
    val aiCirclePosts: StateFlow<List<AiCirclePost>> = _aiCirclePosts.asStateFlow()

    private val _aiCircleLoading = MutableStateFlow(false)
    val aiCircleLoading: StateFlow<Boolean> = _aiCircleLoading.asStateFlow()

    private val _approvalPendingCount = MutableStateFlow(0)
    val approvalPendingCount: StateFlow<Int> = _approvalPendingCount.asStateFlow()

    private val _chatSuggestions = MutableStateFlow<List<ChatSuggestion>>(emptyList())
    val chatSuggestions: StateFlow<List<ChatSuggestion>> = _chatSuggestions.asStateFlow()

    /** 会话列表后台刷新中（用于下拉刷新指示器与 UI 反馈） */
    private val _conversationsRefreshing = MutableStateFlow(false)
    val conversationsRefreshing: StateFlow<Boolean> = _conversationsRefreshing.asStateFlow()

    // 微信风格：conversations 从本地 DB Flow 派生，网络请求只写入 DB，不直接操作 UI 状态
    val conversations: StateFlow<List<ConversationItem>> =
            combine(
                    repo.observeCachedModInfos(),
                    sessionStore.accountKindFlow,
                    repo.observeConversationListTimestamps(),
                    repo.observeConversationListPreviews(),
            ) { mods, kind, timestamps, previews ->
                val adminMode = isAdminAccountKind(kind)
                val isEnterprise = ProductSkuConfig.showsEnterpriseNav || adminMode
                val fixedItems = fixedConversationItems(
                        showCodex = isEnterprise || adminMode,
                        showCursor = isEnterprise || adminMode,
                        showClaude = isEnterprise || adminMode,
                        showCustomerService = isEnterprise && !adminMode,
                        timestamps = timestamps,
                        previews = previews,
                )
                val badgeText = if (adminMode) "管理端" else "已安装"
                val badgeColor = if (adminMode) BadgeAdminColor else BadgeInstalledColor
                val employees = employeeConversationItems(mods, badgeText, badgeColor, timestamps, previews)
                fixedItems + employees
            }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    private val _chatAction = MutableStateFlow<ChatAction?>(null)
    val chatAction: StateFlow<ChatAction?> = _chatAction.asStateFlow()

    val syncStaleHint =
            combine(
                    sessionStore.lastSyncAtFlow,
                    sessionStore.fhdHostFlow,
                    sessionStore.relayDesktopIdFlow,
            ) { last, host, relayId ->
                        (host.isNotBlank() || relayId.isNotBlank()) && last.isBlank()
                    }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    val canUseNativeChat =
            sessionStore
                    .fhdAccessFlow
                    .map { it.isNotBlank() }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), false)

    val autoSync =
            sessionStore.autoSyncFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    true,
            )

    private val _appConfig = MutableStateFlow<AppConfigResponse?>(null)
    val appConfig: StateFlow<AppConfigResponse?> = _appConfig.asStateFlow()

    private val _updatePrompt = MutableStateFlow<UpdatePrompt?>(null)
    private val _autoLoggingIn = MutableStateFlow(false)
    val autoLoggingIn: StateFlow<Boolean> = _autoLoggingIn.asStateFlow()
    val updatePrompt: StateFlow<UpdatePrompt?> = _updatePrompt.asStateFlow()

    private val _updateDownload = MutableStateFlow<UpdateDownload>(UpdateDownload.Idle)
    val updateDownload: StateFlow<UpdateDownload> = _updateDownload.asStateFlow()
    private var updateDownloadJob: Job? = null

    // 微信风格：modInfos 也从 DB Flow 派生，与 conversations 共享同一数据源，彻底消除头像不一致
    val modInfos: StateFlow<List<ModInfo>> =
            repo.observeCachedModInfos()
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    // 用户头像 URL（从登录响应或本地存储获取）
    private val _userAvatarUrl = MutableStateFlow<String?>(null)
    val userAvatarUrl: StateFlow<String?> = _userAvatarUrl.asStateFlow()
    val userAvatarSource: StateFlow<String> =
            combine(avatarUri, userAvatarUrl) { localUri, remoteUrl ->
                localUri.ifBlank { remoteUrl.orEmpty() }
            }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    fun refreshUserAvatar() {
        viewModelScope.launch {
            _userAvatarUrl.value = repo.refreshMe()
        }
    }

    val dynamicMenuItems: StateFlow<List<ModMenuItem>> =
            modInfos
                    .map { mods -> mods.flatMap { it.frontend_menu } }
                    .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val biometricEnabled =
            sessionStore.biometricEnabledFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    false,
            )

    val themeMode =
            sessionStore.themeModeFlow.stateIn(
                    viewModelScope,
                    SharingStarted.WhileSubscribed(5_000),
                    "system",
            )

    private var chatJob: Job? = null
    private var conversationsLoadJob: Job? = null

    init {
        pushRegistrar.initSdk()
        analytics.log("app_open")
        viewModelScope.launch {
            // 冷启动：先从本地缓存恢复钱包余额（秒出，避免"—"闪烁）
            try {
                repo.loadCachedWalletBalance()?.let { _walletBalance.value = it }
            } catch (_: Exception) {
            }
            repo.fetchAppConfig().onSuccess {
                _appConfig.value = it
                ProductSkuConfig.remoteSku = it.sku
                refreshStartRoute()
            }
            checkForUpdate(manual = false)
            try {
                repo.ensureStandaloneCloudIfFresh()
                val host = sessionStore.fhdHost()
                if (host.isNotBlank()) serverRouter.fhdHost = host
                val mode = sessionStore.serverModeFlow.first()
                serverRouter.mode = if (mode == "cloud") ServerMode.CLOUD else ServerMode.LAN
                if (_appConfig.value == null) refreshStartRoute()
                val (access, refresh) = repo.marketTokensForWeb()
                _marketAccess.value = access
                _marketRefresh.value = refresh
            } catch (_: Exception) {
                refreshStartRoute()
            } finally {
                _navReady.value = true
            }
            try {
                withTimeout(8_000) { refreshMarketTokens() }
            } catch (_: Exception) {
                /* 离线或电脑未开：不阻塞进入 App */
            }
            updateSyncWork(sessionStore.autoSyncFlow.first())
            // 已登录用户：冷启动后台静默刷新余额（缓存已秒出，此处更新最新值）
            if (sessionStore.isLoggedInFlow.first()) {
                loadWalletBalance()
            }
        }
    }

    fun refreshStartRoute() =
            viewModelScope.launch {
                val cfg = _appConfig.value
                val accepted = sessionStore.legalAcceptedVersion()
                val needLegal = cfg != null && accepted != cfg.legal_version
                if (needLegal) {
                    _startRoute.value = Routes.LEGAL
                    return@launch
                }
                val loggedIn = sessionStore.isLoggedInFlow.first()
                _startRoute.value =
                        when {
                            needLegal -> Routes.LEGAL
                            !loggedIn && sessionStore.canAutoLogin() -> Routes.AUTH_AUTO_LOGIN
                            !loggedIn -> Routes.AUTH
                            else -> Routes.CHAT
                        }
            }

    /** 免登录：使用已保存的凭证自动登录 */
    fun tryAutoLogin() =
            viewModelScope.launch {
                val u = sessionStore.savedUsername()
                val p = sessionStore.savedPassword()
                if (u.isBlank() || p.isBlank()) return@launch
                _autoLoggingIn.value = true
                repo.loginUnified(u, p)
                        .onSuccess {
                            sessionStore.setSetupComplete(true)
                            val mode = repo.preferredServerModeAfterLogin()
                            sessionStore.setServerMode(if (mode == ServerMode.LAN) "lan" else "cloud")
                            serverRouter.mode = mode
                            snack("欢迎回来，$it")
                            refreshMarketTokens()
                            refreshConversationRuntime()
                            refreshUserAvatar()
                            loadWalletBalance()
                            registerPushWithHint()
                            _startRoute.value = Routes.CHAT
                        }
                        .onFailure { snack("自动登录失败，请手动登录", true) }
                        .also { _autoLoggingIn.value = false }
            }

    fun acceptLegal(onDone: () -> Unit) =
            viewModelScope.launch {
                val ver = _appConfig.value?.legal_version ?: "1"
                sessionStore.setLegalAcceptedVersion(ver)
                refreshStartRoute()
                onDone()
            }

    fun checkForUpdate(manual: Boolean) =
            viewModelScope.launch {
                val cfg =
                        _appConfig.value
                                ?: repo.fetchAppConfig().getOrNull().also {
                                    _appConfig.value = it
                                    ProductSkuConfig.remoteSku = it?.sku ?: ""
                                }
                                        ?: return@launch
                val cur = BuildConfig.VERSION_CODE
                val devOrLan = BuildConfig.DEBUG || sessionStore.serverModeFlow.first() != "cloud"
                val forceRequired =
                        cur < cfg.min_android_version ||
                                (cfg.force_update && cur < cfg.latest_android_version)
                if (forceRequired && devOrLan && !manual) return@launch
                if (forceRequired) {
                    _updatePrompt.value =
                            UpdatePrompt(
                                    force = true,
                                    versionName = cfg.latest_android_version_name,
                                    downloadUrl = cfg.apk_download_url,
                            )
                } else if (manual && cur < cfg.latest_android_version) {
                    _updatePrompt.value =
                            UpdatePrompt(
                                    force = false,
                                    versionName = cfg.latest_android_version_name,
                                    downloadUrl = cfg.apk_download_url,
                            )
                } else if (manual) {
                    snack("已是最新版本")
                }
            }

    fun dismissUpdatePrompt() {
        _updatePrompt.value = null
        // 重置终态下载状态，避免下次打开弹窗显示陈旧的「已完成 / 失败」；下载中不动。
        if (_updateDownload.value !is UpdateDownload.Downloading) {
            _updateDownload.value = UpdateDownload.Idle
        }
    }

    /** 应用内自更新：流式下载整包 APK，完成后自动尝试拉起系统安装器。 */
    fun startInAppUpdate(url: String) {
        if (updateDownloadJob?.isActive == true) return
        if (url.isBlank()) {
            snack("暂无应用内下载地址，请前往官网更新", isError = true)
            return
        }
        updateDownloadJob =
                viewModelScope.launch {
                    _updateDownload.value = UpdateDownload.Downloading(0)
                    ApkUpdater.download(appContext, url) { pct ->
                                _updateDownload.value = UpdateDownload.Downloading(pct)
                            }
                            .onSuccess { file ->
                                _updateDownload.value = UpdateDownload.Ready(file.absolutePath)
                                launchInstall(file)
                            }
                            .onFailure { e ->
                                _updateDownload.value =
                                        UpdateDownload.Failed(e.message?.take(120) ?: "下载失败")
                            }
                }
    }

    /** 安装已下载完成的更新包（用户在弹窗点「立即安装」时调用）。 */
    fun installDownloadedUpdate() {
        val state = _updateDownload.value
        if (state is UpdateDownload.Ready) launchInstall(File(state.apkPath))
    }

    /** 取消进行中的下载并复位状态。 */
    fun cancelUpdateDownload() {
        updateDownloadJob?.cancel()
        updateDownloadJob = null
        _updateDownload.value = UpdateDownload.Idle
    }

    private fun launchInstall(file: File) {
        if (!ApkUpdater.canInstall(appContext)) {
            snack("请在系统设置中允许「安装未知应用」后重试", isError = true)
            ApkUpdater.requestInstallPermission(appContext)
            return
        }
        runCatching { ApkUpdater.install(appContext, file) }
                .onFailure { snack("启动安装失败：${it.message}", isError = true) }
    }

    fun setBiometricEnabled(enabled: Boolean) =
            viewModelScope.launch { sessionStore.setBiometricEnabled(enabled) }

    fun setThemeMode(mode: String) = viewModelScope.launch { sessionStore.setThemeMode(mode) }

    fun updateProfileName(name: String) =
            viewModelScope.launch {
                val clean = name.trim()
                if (clean.isBlank()) {
                    snack("昵称不能为空", true)
                    return@launch
                }
                sessionStore.setDisplayName(clean.take(32))
                snack("资料已保存")
            }

    fun updateAvatarUri(uri: String) =
            viewModelScope.launch {
                sessionStore.setAvatarUri(uri)
                snack("头像已更新")
            }

    fun clearAvatar() =
            viewModelScope.launch {
                sessionStore.setAvatarUri("")
                snack("头像已移除")
            }

    fun submitFeedback(message: String, onDone: () -> Unit = {}) =
            viewModelScope.launch {
                repo.submitFeedback(message)
                        .onSuccess {
                            snack("感谢您的反馈，我们会尽快处理")
                            onDone()
                        }
                        .onFailure { snack(it.message ?: "反馈提交失败，请稍后重试", true) }
            }

    fun deleteAccount(password: String, onDone: () -> Unit) =
            viewModelScope.launch {
                repo.deleteAccount(password)
                        .onSuccess {
                            pushRegistrar.unregisterAll()
                            snack("账号已成功注销")
                            refreshStartRoute()
                            onDone()
                        }
                        .onFailure { snack(it.message ?: "注销失败，请检查网络后重试", true) }
            }

    fun exportAccount(onPath: (String) -> Unit) =
            viewModelScope.launch {
                repo.exportAccountData().onSuccess { snack("数据导出完成") }.onFailure {
                    snack(it.message ?: "导出失败，请稍后重试", true)
                }
            }

    fun loadHomeHub() =
            viewModelScope.launch {
                try {
                    _homeHub.value = _homeHub.value.copy(loading = true)
                    repo.preferCloudIfLanUnreachable()
                    val host = sessionStore.fhdHostFlow.first()
                    val relayId = sessionStore.relayDesktopId()
                    val online =
                            if (relayId.isNotBlank()) {
                                repo.checkHealth()
                            } else {
                                host.isNotBlank() && repo.checkHealth(host)
                            }
                    val syncLabel = syncRepo.statusLabel(online)
                    val (mods, fromCloud) =
                            if (online) {
                                val list =
                                        repo.fetchHome().getOrNull()?.let { data ->
                                            @Suppress("UNCHECKED_CAST")
                                            val raw =
                                                    (data["mods"] as? List<Map<String, Any?>>)
                                                            ?: emptyList()
                                            raw.mapNotNull { row ->
                                                val id = row["id"]?.toString()?.trim().orEmpty()
                                                val name = row["name"]?.toString()?.trim().orEmpty()
                                                if (id.isNotBlank()) ListItem(id, name.ifBlank { id })
                                                else null
                                            }
                                        }
                                                ?: repo.mods().getOrElse { emptyList() }
                                list to false
                            } else {
                                repo.marketCatalog().getOrElse { emptyList() } to true
                            }
                    _homeHub.value =
                            HomeHubState(
                                    loading = false,
                                    pcOnline = online,
                                    mods = mods,
                                    modsFromCloud = fromCloud,
                                    syncLabel = syncLabel,
                            )
                    rebuildChatSuggestions(mods, online)
                } catch (_: Exception) {
                    _homeHub.value =
                            _homeHub.value.copy(
                                    loading = false,
                                    pcOnline = false,
                                    syncLabel = "同步状态待刷新",
                            )
                    rebuildChatSuggestions(emptyList(), false)
                }
            }

    /** 拉取侧栏菜单（探索 Tab 配对后与桌面端侧栏对齐）。失败时保留旧值。 */
    fun loadNavMenu() =
            viewModelScope.launch {
                try {
                    val res = repo.fetchNavMenu().getOrNull()
                    if (res != null) {
                        _navMenu.value = res.items
                    }
                } catch (_: Exception) {
                    // 静默失败，保留旧值
                }
            }

    fun loadAiGroups() =
            viewModelScope.launch {
                // 静默失败（消息页常驻加载，不打扰；个人版无权限时也不弹错）
                repo.loadAiGroups().onSuccess { _aiGroups.value = it }
            }

    /** 拉取群成员候选(普通员工 + 超级员工)。静默失败,屏幕侧用 aiEmployeeProfiles() 兜底。 */
    fun loadGroupMemberCandidates() =
            viewModelScope.launch {
                repo.loadGroupMemberCandidates().onSuccess { _groupMemberCandidates.value = it }
            }

    fun createAiGroup(name: String) =
            viewModelScope.launch {
                repo.createAiGroup(name)
                    .onSuccess { loadAiGroups() }
                    .onFailure { snack(it.message ?: "建群失败", true) }
            }

    /** 微信式发起群聊：建群 + 批量拉入所选 AI 成员,完成后回调新群(用于导航进群)。 */
    fun createGroupWithMembers(
        name: String,
        members: List<com.xiuci.xcagi.mobile.core.model.AiGroupMemberDraft>,
        onDone: (com.xiuci.xcagi.mobile.core.model.AiGroupDto?) -> Unit,
    ) = viewModelScope.launch {
        val created = repo.createAiGroup(name).getOrNull()
        if (created == null) {
            snack("建群失败", true)
            onDone(null)
            return@launch
        }
        var current = created
        members.forEach { m ->
            repo.addAiGroupMember(created.id, m.employeeId, m.modId, m.name, m.avatar, m.summary)
                .getOrNull()?.let { current = it }
        }
        _currentGroup.value = current
        _groupMessages.value = emptyList()
        loadAiGroups()
        onDone(current)
    }

    /** 打开群聊：载入成员与历史消息。 */
    fun openAiGroup(group: com.xiuci.xcagi.mobile.core.model.AiGroupDto) {
        _currentGroup.value = group
        _groupMessages.value = emptyList()
        loadAiGroupMessages(group.id)
    }

    fun loadAiGroupMessages(groupId: String) =
            viewModelScope.launch {
                repo.loadAiGroupMessages(groupId)
                    .onSuccess { _groupMessages.value = it }
                    .onFailure { snack("群消息加载失败", true) }
            }

    fun sendGroupMessage(groupId: String, text: String, mentions: List<String> = emptyList()) {
        val body = text.trim()
        if (body.isBlank() || _groupSending.value) return
        // 本地先回显用户消息
        _groupMessages.value = _groupMessages.value + com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto(
            id = "local-${System.currentTimeMillis()}",
            group_id = groupId,
            role = "user",
            sender_id = "user",
            sender_name = "我",
            body = body,
        )
        _groupSending.value = true
        viewModelScope.launch {
            repo.postAiGroupMessage(groupId, body, mentions)
                .onSuccess { data ->
                    // 用服务端权威消息替换尾部（去掉本地回显，拼接服务端返回的 user+ai）
                    val withoutLocalTail = _groupMessages.value.dropLastWhile { it.id.startsWith("local-") }
                    _groupMessages.value = withoutLocalTail + data.messages
                    data.group?.let { g -> _currentGroup.value = g }
                }
                .onFailure { snack(it.message ?: "发送失败", true) }
            _groupSending.value = false
        }
    }

    fun addGroupMember(
        groupId: String,
        employeeId: String,
        modId: String,
        name: String,
        avatar: String,
        summary: String,
    ) =
            viewModelScope.launch {
                repo.addAiGroupMember(
                    groupId = groupId,
                    employeeId = employeeId,
                    modId = modId,
                    name = name,
                    avatar = avatar,
                    summary = summary,
                )
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "添加成员失败", true) }
            }

    fun removeGroupMember(groupId: String, employeeId: String) =
            viewModelScope.launch {
                repo.removeAiGroupMember(groupId, employeeId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "移除成员失败", true) }
            }

    fun toggleGroupPin(groupId: String) =
            viewModelScope.launch {
                repo.toggleAiGroupPin(groupId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun markGroupUnread(groupId: String) =
            viewModelScope.launch {
                repo.markAiGroupUnread(groupId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun markGroupRead(groupId: String) =
            viewModelScope.launch {
                repo.markAiGroupRead(groupId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun toggleGroupFollowed(groupId: String) =
            viewModelScope.launch {
                repo.toggleAiGroupFollowed(groupId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun toggleGroupHidden(groupId: String) =
            viewModelScope.launch {
                repo.toggleAiGroupHidden(groupId)
                    .onSuccess { g -> g?.let { _currentGroup.value = it }; loadAiGroups() }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun deleteGroup(groupId: String) =
            viewModelScope.launch {
                repo.deleteAiGroup(groupId)
                    .onSuccess { loadAiGroups() }
                    .onFailure { snack(it.message ?: "删除失败", true) }
            }

    // ── 会话状态（个人 AI 会话） ──
    fun toggleConversationUnread(conversationId: String) =
            viewModelScope.launch {
                repo.markConversationUnread(conversationId)
                    .onSuccess {
                        refreshConversationUiState(conversationId)
                        loadConversations(currentIsEnterprise())
                    }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun toggleConversationPin(conversationId: String) =
            viewModelScope.launch {
                repo.toggleConversationPin(conversationId)
                    .onSuccess { loadConversations(currentIsEnterprise()) }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun toggleConversationFollowed(conversationId: String) =
            viewModelScope.launch {
                repo.toggleConversationFollowed(conversationId)
                    .onSuccess { loadConversations(currentIsEnterprise()) }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun toggleConversationHidden(conversationId: String) =
            viewModelScope.launch {
                repo.toggleConversationHidden(conversationId)
                    .onSuccess { loadConversations(currentIsEnterprise()) }
                    .onFailure { snack(it.message ?: "操作失败", true) }
            }

    fun deleteConversation(conversationId: String) =
            viewModelScope.launch {
                repo.deleteConversation(conversationId)
                    .onSuccess { loadConversations(currentIsEnterprise()) }
                    .onFailure { snack(it.message ?: "删除失败", true) }
            }

    private fun currentIsEnterprise(): Boolean = isEnterpriseEffective.value

    private fun refreshConversationUiState(conversationId: String) {
        // 本地刷新 —— 下次加载会同步；此处仅做保留以便扩展。
    }

    /** 拉取钱包余额（移动端"我"页面展示）。失败时保留旧值，不弹错误。成功后写入缓存。 */
    fun loadWalletBalance() =
            viewModelScope.launch {
                try {
                    val result = repo.fetchWalletBalance()
                    result.onSuccess {
                        _walletBalance.value = it
                        repo.saveCachedWalletBalance(it)
                    }
                } catch (_: Exception) {
                    // 静默失败，保留旧值
                }
            }

    private fun rebuildChatSuggestions(mods: List<ListItem>, pcOnline: Boolean) {
        val base =
                mutableListOf(
                        ChatSuggestion("企业同步", "同步企业端已安装的智能伙伴和能力"),
                        ChatSuggestion("今日待办", "总结我今天的待办和审批"),
                )
        if (pcOnline) {
            base.add(ChatSuggestion("同步状态", "我的手机和电脑数据同步了吗？"))
        }
        mods.take(6).forEach { m -> base.add(ChatSuggestion(m.title, "打开 Mod ${m.id} 并说明能做什么")) }
        _chatSuggestions.value = base
    }

    /**
     * 网络刷新员工列表并写入 DB；conversations 由 DB Flow 自动驱动更新。
     *
     * @param isEnterprise 当前是否企业版（用于决定是否拉取员工列表）
     * @param force true 时强制刷新（如下拉刷新）；false 时按 TTL 判断是否需要刷新
     *
     * 注意：只有 force=true（用户主动下拉）才显示 refreshing 指示器；
     * 静默刷新（force=false）完全无感知，不触发 UI 状态变化。
     */
    fun loadConversations(isEnterprise: Boolean, force: Boolean = false) {
        conversationsLoadJob?.cancel()
        conversationsLoadJob = viewModelScope.launch {
            val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
            // 个人账号也允许刷新（用于拉取个人 Mod 列表），不再提前 return
            if (!adminMode && !isEnterprise && !force) return@launch
            // TTL 判断：非强制刷新且缓存未过期时跳过
            if (!force) {
                val cachedAt = repo.cachedModInfosAt()
                if (cachedAt > 0 && System.currentTimeMillis() - cachedAt < modInfoCacheTtlMs) {
                    return@launch
                }
            }
            // 只有用户主动下拉才显示 loading 指示器；静默刷新完全无感知
            if (force) {
                _conversationsRefreshing.value = true
            }
            try {
                // 只写入 DB，conversations 会自动从 DB Flow 更新
                repo.refreshAndCacheModInfos(adminMode)
            } finally {
                if (force) {
                    _conversationsRefreshing.value = false
                }
            }
        }
    }

    private suspend fun rebuildConversationItems(isEnterprise: Boolean): Int {
        val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
        if (!adminMode && !isEnterprise) return 0
        // 写入 DB，modInfos 和 conversations 都由 DB Flow 自动驱动
        val mods = repo.refreshAndCacheModInfos(adminMode).getOrElse { return 0 }
        return mods.flatMap { it.workflow_employees }.size
    }

    private suspend fun refreshBoundRuntimeAfterPairing(): Int {
        refreshStartRoute()
        repo.preferCloudIfLanUnreachable()
        if (repo.hasNativeFhdAuth()) {
            try {
                withTimeout(5_000) { repo.refreshMe(sessionStore.accountKindFlow.first()) }
            } catch (_: Exception) {
            }
            try {
                withTimeout(5_000) { repo.syncMarketSessionHandoff() }
            } catch (_: Exception) {
            }
        }
        val (access, refresh) = repo.marketTokensForWeb()
        _marketAccess.value = access
        _marketRefresh.value = refresh
        val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
        val employeeCount = rebuildConversationItems(ProductSkuConfig.showsEnterpriseNav || adminMode)
        val syncSummary = try {
            withTimeout(6_000) { syncRepo.pullAndCache().getOrNull() }
        } catch (_: Exception) {
            null
        }
        if (syncSummary == null) {
            sessionStore.setLastSyncAt(Instant.now().toString())
        }
        loadHomeHub()
        loadNavMenu()
        refreshApprovalCount()
        loadWalletBalance()
        registerPushWithHint()
        return employeeCount
    }

    private fun employeeConversationItems(
            mods: List<ModInfo>,
            badgeText: String,
            badgeColor: androidx.compose.ui.graphics.Color,
            timestamps: Map<String, Long>,
            previews: Map<String, String>,
    ): List<ConversationItem> =
            mods.flatMap { mod ->
                mod.workflow_employees.mapNotNull { employee ->
                    val employeeId = employee.id.trim()
                    val title =
                            employee.label.ifBlank { employee.panel_title }.ifBlank { employeeId }.trim()
                    if (employeeId.isBlank() || title.isBlank()) {
                        null
                    } else {
                        val source = mod.name.ifBlank { mod.id }.trim().takeIf { it.isNotBlank() }
                        val avatarUrl = employee.market_avatar?.takeIf { it.isNotBlank() }
                            ?: mod.avatar_url?.takeIf { it.isNotBlank() }
                        val conversationId = "employee:${mod.id}:$employeeId"
                        // 微信风格：有最新消息预览时显示预览，否则显示介绍词
                        val subtitle = cachedConversationPreview(conversationId, previews)
                            .ifBlank { employee.contactSubtitle(source) }
                        ConversationItem(
                                id = conversationId,
                                type = ConversationType.AI_TASK,
                                title = title,
                                subtitle = subtitle,
                                timestamp = cachedConversationTimestamp(conversationId, timestamps),
                                avatarUrl = avatarUrl,
                        )
                    }
                }
            }.distinctBy { it.id } // 防止后端返回重复 employee id 导致 LazyColumn key 冲突崩溃

    private fun com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo.contactSubtitle(
            source: String?,
    ): String {
        // 微信式：副标题只显示员工简介，不堆"管理端工作台 · AI号 xxx · …"这类后台技术串。
        return panel_summary.trim().ifBlank {
            (source?.let { "来自 $it" } ?: phone_channel.contactChannelLabel()).trim()
        }
    }

    private fun String.contactChannelLabel(): String =
            when (trim()) {
                "admin-duty" -> "管理端工作台"
                "mobile", "mobile-chat" -> "手机端会话"
                "" -> ""
                else -> trim()
            }

    private fun fixedConversationItems(
            showCodex: Boolean,
            showCursor: Boolean,
            showClaude: Boolean,
            showCustomerService: Boolean,
            timestamps: Map<String, Long>,
            previews: Map<String, String>,
    ): List<ConversationItem> {
        val items = mutableListOf<ConversationItem>()

        // 1. 小C助理（始终显示）
        items.add(
            ConversationItem(
                id = PinnedIds.ASSISTANT,
                type = ConversationType.PINNED_ASSISTANT,
                title = "小C助理",
                subtitle = cachedConversationPreview(PinnedIds.ASSISTANT, previews)
                    .ifBlank { "有什么可以帮您？" },
                timestamp = cachedConversationTimestamp(PinnedIds.ASSISTANT, timestamps),
                isPinned = true,
            )
        )

        if (showCodex) {
                items.add(
                    ConversationItem(
                            id = PinnedIds.CODEX,
                            type = ConversationType.PINNED_CODEX,
                            title = "超级员工-Codex",
                            subtitle = cachedConversationPreview(PinnedIds.CODEX, previews)
                                .ifBlank { "全设备协同" },
                            timestamp = cachedConversationTimestamp(PinnedIds.CODEX, timestamps),
                            isOnline = true,
                            isPinned = true,
                    )
                )
        }

        if (showCursor) {
                items.add(
                    ConversationItem(
                            id = PinnedIds.CURSOR,
                            type = ConversationType.PINNED_CURSOR,
                            title = "超级员工-Cursor",
                            subtitle = cachedConversationPreview(PinnedIds.CURSOR, previews)
                                .ifBlank { "全设备协同 · Agent" },
                            timestamp = cachedConversationTimestamp(PinnedIds.CURSOR, timestamps),
                            isOnline = true,
                            isPinned = true,
                    )
                )
        }

        if (showClaude) {
                items.add(
                    ConversationItem(
                            id = PinnedIds.CLAUDE,
                            type = ConversationType.PINNED_CLAUDE,
                            title = "超级员工-Claude",
                            subtitle = cachedConversationPreview(PinnedIds.CLAUDE, previews)
                                .ifBlank { "全设备协同 · 排比派工" },
                            timestamp = cachedConversationTimestamp(PinnedIds.CLAUDE, timestamps),
                            isOnline = true,
                            isPinned = true,
                    )
                )
        }

        // 3. 专属客服（仅企业客户账号；管理端账号不显示客服）
        if (showCustomerService) {
            items.add(
                ConversationItem(
                    id = PinnedIds.CS,
                    type = ConversationType.PINNED_CS,
                    title = "专属客服",
                    subtitle = cachedConversationPreview(PinnedIds.CS, previews)
                        .ifBlank { "您好，我是您的专属客服" },
                    timestamp = cachedConversationTimestamp(PinnedIds.CS, timestamps),
                    isOnline = true,
                    isPinned = true,
                )
            )
        }

        return items
    }

    fun runSyncNow() =
            viewModelScope.launch {
                _homeHub.value = _homeHub.value.copy(syncing = true)
                repo.preferCloudIfLanUnreachable()
                syncRepo.pullAndCache()
                        .onSuccess { summary ->
                            snack("数据同步完成")
                            _homeHub.value =
                                    _homeHub.value.copy(
                                            syncing = false,
                                            syncLabel = summary.label,
                                    )
                        }
                        .onFailure {
                            val relayId = sessionStore.relayDesktopId()
                            if (relayId.isNotBlank()) {
                                sessionStore.setLastSyncAt(Instant.now().toString())
                                snack("中继已连接，业务数据将在电脑端在线后继续同步")
                                _homeHub.value =
                                        _homeHub.value.copy(
                                                syncing = false,
                                                syncLabel = "中继已连接",
                                        )
                            } else {
                                snack(it.message ?: "同步失败，请检查网络连接", true)
                                _homeHub.value = _homeHub.value.copy(syncing = false)
                            }
                        }
                loadHomeHub()
            }

    fun setAutoSync(enabled: Boolean) =
            viewModelScope.launch {
                sessionStore.setAutoSync(enabled)
                updateSyncWork(enabled)
            }

    private fun updateSyncWork(enabled: Boolean) {
        val wm =
                try {
                    WorkManager.getInstance(appContext)
                } catch (_: Exception) {
                    return
                }
        if (enabled) {
            val constraints =
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            val req =
                    PeriodicWorkRequestBuilder<MobileSyncWorker>(15, TimeUnit.MINUTES)
                            .setConstraints(constraints)
                            .build()
            wm.enqueueUniquePeriodicWork(
                    "xcagi_mobile_sync",
                    ExistingPeriodicWorkPolicy.UPDATE,
                    req,
            )
        } else {
            wm.cancelUniqueWork("xcagi_mobile_sync")
        }
    }

    fun refreshMarketTokens() =
            viewModelScope.launch {
                val cloudFirst = sessionStore.serverModeFlow.first() == "cloud"
                if (!cloudFirst && repo.hasNativeFhdAuth()) {
                    try {
                        kotlinx.coroutines.withTimeout(5_000) { repo.syncMarketSessionHandoff() }
                    } catch (_: Exception) {}
                }
                val (access, refresh) = repo.marketTokensForWeb()
                _marketAccess.value = access
                _marketRefresh.value = refresh
            }

    fun completeSetup() =
            viewModelScope.launch {
                sessionStore.setSetupComplete(true)
                refreshStartRoute()
            }

    fun skipToCloud(onDone: () -> Unit) =
            viewModelScope.launch {
                sessionStore.setSetupComplete(true)
                sessionStore.setServerMode("cloud")
                serverRouter.mode = ServerMode.CLOUD
                snack("已切换至远程模式")
                refreshStartRoute()
                onDone()
            }

    fun setAutoLanProbe(enabled: Boolean) =
            viewModelScope.launch { sessionStore.setAutoLanProbe(enabled) }

    fun snack(text: String, isError: Boolean = false) {
        _message.value = UiMessage(text, isError)
    }

    private fun productErrorMessage(raw: String?, fallback: String): String {
        val msg = raw.orEmpty()
        return when {
            msg.contains("401", ignoreCase = true) || msg.contains("未授权") ->
                    "登录已过期，请重新登录或重新扫码绑定"
            msg.contains("403", ignoreCase = true) || msg.contains("拒绝") ->
                    "当前账号没有权限，请切换到管理员账号或重新绑定后台"
            msg.contains("failed to connect", ignoreCase = true) ||
                    msg.contains("timeout", ignoreCase = true) ||
                    msg.contains("connect", ignoreCase = true) ->
                    "连接不到电脑执行端，已尝试通过服务器中继，请稍后重试"
            msg.contains("Firebase", ignoreCase = true) ||
                    msg.contains("FCM", ignoreCase = true) ||
                    msg.contains("JPUSH", ignoreCase = true) ||
                    msg.contains("极光", ignoreCase = true) ->
                    "消息提醒未开启，不影响登录和员工同步"
            msg.isBlank() -> fallback
            msg.length > 80 -> fallback
            else -> msg
        }
    }

    fun clearSnack() {
        _message.value = null
    }

    fun setHost(host: String, markSetup: Boolean = false) =
            viewModelScope.launch {
                sessionStore.setFhdHost(host)
                serverRouter.fhdHost = host
                if (markSetup) {
                    sessionStore.setSetupComplete(true)
                    refreshStartRoute()
                }
            }

    fun setMode(cloud: Boolean) =
            viewModelScope.launch {
                sessionStore.setServerMode(if (cloud) "cloud" else "lan")
                serverRouter.mode = if (cloud) ServerMode.CLOUD else ServerMode.LAN
            }

    fun probeHealth(host: String, onResult: (Boolean) -> Unit) =
            viewModelScope.launch { onResult(repo.checkHealth(host)) }

    fun scanSubnet(prefix: String) =
            viewModelScope.launch {
                _scanResults.value = repo.scanLan(prefix)
                snack("已发现 ${_scanResults.value.size} 台设备")
            }

    fun loginFhd(
            u: String,
            p: String,
            isAdmin: Boolean = false,
            rememberPass: Boolean = false,
            autoLogin: Boolean = false,
            onDone: (Boolean, String?) -> Unit
    ) =
            viewModelScope.launch {
                repo.loginUnified(u, p, isAdmin)
                        .onSuccess {
                            // 登录成功后自动完成设置，并回到与账号源一致的后端模式
                            sessionStore.setSetupComplete(true)
                            val mode = repo.preferredServerModeAfterLogin()
                            sessionStore.setServerMode(if (mode == ServerMode.LAN) "lan" else "cloud")
                            serverRouter.mode = mode
                            if (rememberPass) sessionStore.saveCredentials(u, p)
                            else sessionStore.clearSavedCredentials()
                            sessionStore.setAutoLogin(autoLogin)
                            snack("欢迎回来，$it")
                            analytics.log("login_success", mapOf("method" to "password"))
                            refreshMarketTokens()
                            refreshConversationRuntime()
                            refreshUserAvatar()
                            loadWalletBalance()
                            registerPushWithHint()
                            onDone(true, null)
                        }
                        .onFailure {
                            analytics.log("login_fail", mapOf("method" to "password"))
                            snack(it.message ?: "登录失败，请检查账号密码", true)
                            onDone(false, it.message)
                        }
            }

    fun register(u: String, p: String, e: String, onDone: (Boolean) -> Unit) =
            viewModelScope.launch {
                repo.register(u, p, e)
                        .onSuccess {
                            snack("注册成功，请登录")
                            onDone(true)
                        }
                        .onFailure {
                            snack(it.message ?: "注册失败，请稍后重试", true)
                            onDone(false)
                        }
            }

    fun sendCode(phone: String, onDone: (() -> Unit)? = null) =
            viewModelScope.launch {
                repo.sendMarketCode(phone).onSuccess { snack("验证码已发送至手机") }.onFailure {
                    snack(it.message ?: "验证码发送失败", true)
                }
                onDone?.invoke()
            }

    fun loginPhone(phone: String, code: String, onDone: (Boolean) -> Unit) =
            viewModelScope.launch {
                repo.loginMarketPhone(phone, code)
                        .onSuccess {
                            sessionStore.setSetupComplete(true)
                            val mode = repo.preferredServerModeAfterLogin()
                            sessionStore.setServerMode(if (mode == ServerMode.LAN) "lan" else "cloud")
                            serverRouter.mode = mode
                            snack(it)
                            analytics.log("login_success", mapOf("method" to "phone"))
                            refreshMarketTokens()
                            refreshConversationRuntime()
                            loadWalletBalance()
                            registerPushWithHint()
                            onDone(true)
                        }
                        .onFailure {
                            analytics.log("login_fail", mapOf("method" to "phone"))
                            snack(it.message ?: "操作失败，请稍后重试", true)
                            onDone(false)
                        }
            }

    fun exchangeQr(
            raw: String,
            targetHost: String = "",
            targetPort: Int = 0,
            onDone: (Boolean) -> Unit,
    ) =
            viewModelScope.launch {
                val parsed = PairingQrCodec.parse(raw)
                if (parsed != null) {
                    if (parsed.version >= 3 && parsed.relayId.isNotBlank()) {
                        repo.relayPairingConfirm(
                                relayId = parsed.relayId,
                                code = parsed.token,
                                relayBaseUrl = parsed.relayBaseUrl,
                        )
                    } else if (
                            parsed.token.length == 6 &&
                                    parsed.token.all { it.isDigit() } &&
                                    parsed.host.isBlank() &&
                                    targetHost.isBlank()
                    ) {
                        val relayResult = repo.relayPairingConfirmCode(parsed.token)
                        if (relayResult.isSuccess) {
                            relayResult
                        } else if (parsed.host.isNotBlank() || targetHost.isNotBlank()) {
                            repo.pairingExchange(
                                    code = parsed.token,
                                    exchangeHost = parsed.host.ifBlank { targetHost },
                                    exchangePort = parsed.port.takeIf { it > 0 } ?: targetPort,
                            )
                        } else {
                            relayResult
                        }
                    } else if (
                            parsed.token.length == 6 &&
                                    parsed.token.all { it.isDigit() }
                    ) {
                        repo.pairingExchange(
                                code = parsed.token,
                                exchangeHost = parsed.host.ifBlank { targetHost },
                                exchangePort = parsed.port.takeIf { it > 0 } ?: targetPort,
                        )
                    } else if (parsed.version >= 2 && parsed.token.isNotBlank()) {
                        repo.pairingExchange(
                                nonce = parsed.nonce.ifBlank { parsed.token },
                                exchangeHost = parsed.host.ifBlank { targetHost },
                                exchangePort = parsed.port.takeIf { it > 0 } ?: targetPort,
                        )
                    } else {
                        repo.pairingExchange(
                                nonce = parsed.nonce,
                                exchangeHost = parsed.host.ifBlank { targetHost },
                                exchangePort = parsed.port.takeIf { it > 0 } ?: targetPort,
                        )
                    }
                } else {
                    repo.pairingExchange(nonce = raw.trim())
                }
                        .onSuccess { (_, _) ->
                            sessionStore.setSetupComplete(true)
                            val employeeCount = refreshBoundRuntimeAfterPairing()
                            if (employeeCount > 0) {
                                snack("设备绑定成功，已同步 ${employeeCount} 位 AI 员工")
                            } else {
                                snack("设备绑定成功")
                            }
                            onDone(true)
                        }
                        .onFailure {
                            snack(
                                    productErrorMessage(
                                            it.message,
                                            "设备配对失败，请刷新二维码或输入设备码",
                                    ),
                                    true,
                            )
                            onDone(false)
                        }
            }

    fun confirmAuthQr(
            qrId: String,
            username: String,
            password: String,
            accountKind: String = "",
            onDone: (Boolean) -> Unit,
    ) =
            viewModelScope.launch {
                repo.confirmAuthQr(qrId, username, password, accountKind)
                        .onSuccess {
                            snack("已确认登录")
                            onDone(true)
                        }
                        .onFailure {
                            snack(productErrorMessage(it.message, "扫码登录失败，请重试"), true)
                            onDone(false)
                        }
            }

    fun lanRequest(note: String) =
            viewModelScope.launch {
                repo.requestLanAccess(note).onSuccess { snack(it) }.onFailure {
                    snack(it.message ?: "请求失败", true)
                }
            }

    private fun latestCsMessageTimestamp(): Long? =
            csRepository.messages.value
                    .mapNotNull { ImRepository.parseTimestampMs(it.timestamp) }
                    .maxOrNull()

    /** 客服会话最新一条消息（用于列表副标题预览）。 */
    private fun latestCsMessagePreview(): String? {
        val msgs = csRepository.messages.value
        if (msgs.isEmpty()) return null
        val latest = msgs.maxByOrNull { ImRepository.parseTimestampMs(it.timestamp) ?: 0L }
            ?: return null
        val body = latest.body.trim()
        if (body.isBlank()) return null
        // sender="user" 是自己发的，加 "我:" 前缀；sender="cs" 是客服回复，直接显示
        return if (latest.sender.trim().lowercase() == "user") "我: $body" else body
    }

    /** 将客服最新消息预览写入 DB，驱动会话列表副标题更新（微信风格）。 */
    private suspend fun persistCsConversationPreview() {
        val ts = latestCsMessageTimestamp() ?: return
        val preview = latestCsMessagePreview().orEmpty()
        repo.markConversationActivity(PinnedIds.CS, ts, preview)
    }

    fun loadChatCache(conversationId: String? = null) =
            viewModelScope.launch {
                // 切换会话：取消上一个会话仍在进行的流式任务并清空，避免消息串台到当前会话。
                chatJob?.cancel()
                _chatMessages.value = emptyList()
                if (conversationId == PinnedIds.CODEX || conversationId == PinnedIds.CURSOR || conversationId == PinnedIds.CLAUDE) {
                    // relay/直答的回复存在本地缓存，云端历史接口里没有(且登录过期会 401)，
                    // 故 super-employee 会话以本地缓存为准；本地为空才取云端历史兜底。
                    val local = repo.loadCachedChat(conversationId)
                    if (local.isNotEmpty()) {
                        _chatMessages.value = local
                    } else {
                        val remote =
                                when (conversationId) {
                                    PinnedIds.CLAUDE -> repo.loadClaudeSuperEmployeeMessages()
                                    PinnedIds.CURSOR -> repo.loadCursorSuperEmployeeMessages()
                                    else -> repo.loadCodexSuperEmployeeMessages()
                                }
                        remote.onSuccess { _chatMessages.value = it }
                                .onFailure { _chatMessages.value = emptyList() }
                    }
                    // 恢复上次未完成的中继任务：刷新/重进后续轮询，避免"任务状态丢了"。
                    resumeRelayChat(conversationId)
                    return@launch
                }
                val sessionId = conversationId ?: "default"
                _chatMessages.value = repo.loadCachedChat(sessionId)
            }

    fun clearChat() {
        chatJob?.cancel()
        _streaming.value = false
        _chatMessages.value = emptyList()
        _chatAction.value = null
    }

    fun refreshApprovalCount() =
            viewModelScope.launch {
                if (!ProductSkuConfig.showsEnterpriseNav) {
                    _approvalPendingCount.value = 0
                    return@launch
                }
                repo.approvals().onSuccess { _approvalPendingCount.value = it.size }
            }

    /** 进入超级员工会话时，若有上次未完成的中继任务，恢复轮询并把结果续到界面+缓存。 */
    private fun resumeRelayChat(conversationId: String) {
        chatJob?.cancel()
        chatJob =
                viewModelScope.launch {
                    if (!repo.hasInflightRelay(conversationId)) return@launch
                    _streaming.value = true
                    _chatMessages.value = _chatMessages.value + ("assistant" to "")
                    var acc = ""
                    repo.resumeRelayTask(
                            conversationId,
                            onToken = { t ->
                                acc += t
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) + ("assistant" to acc)
                            },
                            onDone = { full ->
                                _streaming.value = false
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) +
                                                ("assistant" to full.ifBlank { acc })
                            },
                            onError = { e ->
                                _streaming.value = false
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) + ("assistant" to "（$e）")
                            },
                    )
                }
    }

    /** 底部功能键：对某分支执行 git 操作（合并/diff/丢弃），结果作为一条助手消息续到会话。 */
    fun gitMerge(branch: String, conversationId: String?) = runGitOp(branch, "git.merge", conversationId)
    fun gitDiff(branch: String, conversationId: String?) = runGitOp(branch, "git.diff", conversationId)
    fun gitDiscard(branch: String, conversationId: String?) = runGitOp(branch, "git.discard", conversationId)

    private fun runGitOp(branch: String, op: String, conversationId: String?) {
        if (branch.isBlank()) return
        chatJob?.cancel()
        _chatMessages.value = _chatMessages.value + ("assistant" to "")
        _streaming.value = true
        var acc = ""
        chatJob =
                viewModelScope.launch {
                    repo.streamRelayGitOp(
                            branch,
                            op,
                            onToken = { t ->
                                acc += t
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) + ("assistant" to acc)
                            },
                            onDone = { full ->
                                _streaming.value = false
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) +
                                                ("assistant" to full.ifBlank { acc })
                            },
                            onError = { e ->
                                _streaming.value = false
                                _chatMessages.value =
                                        _chatMessages.value.dropLast(1) + ("assistant" to "（$e）")
                            },
                    )
                }
    }

    fun sendChat(text: String, conversationId: String? = null) {
        chatJob?.cancel()
        _chatAction.value = null
        _chatMessages.value = _chatMessages.value + ("user" to text) + ("assistant" to "")
        _streaming.value = true
        var acc = ""
        val sessionId = conversationId ?: "default"
        // 派工模式仅对超级员工会话生效；其他会话恒为 auto，避免把控件状态泄漏到普通对话。
        val effectiveMode =
                if (conversationId == PinnedIds.CODEX || conversationId == PinnedIds.CLAUDE)
                        _superMode.value
                else "auto"
        chatJob =
                viewModelScope.launch {
                    if (repo.hasNativeFhdAuth()) {
                        // 有本地 FHD 认证，走局域网
                        repo.streamChat(
                                text,
                                conversationId,
                                sessionId,
                                superMode = effectiveMode,
                                onToken = { t ->
                                    acc += t
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to acc)
                                },
	                                onDone = { full ->
	                                    _streaming.value = false
	                                    val reply = full.ifBlank { acc }
	                                    _chatMessages.value =
	                                            _chatMessages.value.dropLast(1) + ("assistant" to reply)
	                                    inferChatAction(text, reply)
	                                },
	                                onError = { e ->
	                                    // 保留原始错误到 logcat，便于排查 LLM 上游 401/SSL 超时等真实根因，
	                                    // UI 层仍显示 productErrorMessage 改写后的友好文案。
	                                    android.util.Log.e(
	                                        "AppViewModel",
	                                        "streamChat error (lan): $e",
	                                        Exception(e),
	                                    )
	                                    _streaming.value = false
	                                    _chatMessages.value =
	                                            _chatMessages.value.dropLast(1) +
	                                                        ("assistant" to productErrorMessage(
	                                                                e,
	                                                                "对话暂不可用，请稍后重试",
	                                                        ))
	                                },
	                        )
                    } else {
                        // 无本地认证，走云端 API
                        repo.streamChatCloud(
                                text,
                                conversationId,
                                sessionId,
                                superMode = effectiveMode,
                                onToken = { t ->
                                    acc += t
                                    _chatMessages.value =
                                            _chatMessages.value.dropLast(1) + ("assistant" to acc)
                                },
	                                onDone = { full ->
	                                    _streaming.value = false
	                                    val reply = full.ifBlank { acc }
	                                    _chatMessages.value =
	                                            _chatMessages.value.dropLast(1) + ("assistant" to reply)
	                                    inferChatAction(text, reply)
	                                },
	                                onError = { e ->
	                                    // 保留原始错误到 logcat，便于排查 LLM 上游 401/SSL 超时等真实根因，
	                                    // UI 层仍显示 productErrorMessage 改写后的友好文案。
	                                    android.util.Log.e(
	                                        "AppViewModel",
	                                        "streamChatCloud error: $e",
	                                        Exception(e),
	                                    )
	                                    _streaming.value = false
	                                    _chatMessages.value =
	                                            _chatMessages.value.dropLast(1) +
	                                                    ("assistant" to productErrorMessage(
	                                                                e,
	                                                                "当前离线同步不可用，请连接电脑或稍后重试。",
	                                                        ))
	                                },
                        )
                    }
                }
    }

    private fun inferChatAction(userText: String, reply: String) {
        val lower = (userText + " " + reply).lowercase()
        when {
            lower.contains("审批") -> _chatAction.value = ChatAction("approval", label = "审批")
            else -> {
                val mod =
                        _homeHub.value.mods.firstOrNull { m ->
                            lower.contains(m.id.lowercase()) || lower.contains(m.title.lowercase())
                        }
                if (mod != null) {
                    _chatAction.value = ChatAction("mod", mod.id, mod.title)
                }
            }
        }
    }

    fun clearChatAction() {
        _chatAction.value = null
    }

    fun stopChat() {
        chatJob?.cancel()
        _streaming.value = false
    }

    private fun loadEnterpriseList(block: suspend () -> Result<List<ListItem>>) =
            viewModelScope.launch {
                _listLoading.value = true
                _listError.value = null
                block()
                        .onSuccess { list ->
                            _items.value = list
                            if (list.any { it.subtitle.contains("离线缓存") }) {
                                _listError.value = "网络不可用，已显示本地缓存"
                            }
                        }
                        .onFailure { err -> _listError.value = err.message ?: "加载失败" }
                _listLoading.value = false
            }

    fun loadApprovals() = loadEnterpriseList { repo.approvals() }

    fun loadApprovalDetail(id: Int) =
            viewModelScope.launch {
                _approvalDetailLoading.value = true
                _approvalDetail.value = null
                repo.approvalDetail(id)
                        .onSuccess { raw ->
                            _approvalDetail.value = ApprovalDetail.fromResponse(raw)
                            if (_approvalDetail.value == null) {
                                _detailJson.value = raw.toString()
                            }
                        }
                        .onFailure { snack(it.message ?: "加载失败", true) }
                _approvalDetailLoading.value = false
            }

    fun approve(id: Int, opinion: String, onDone: () -> Unit) =
            viewModelScope.launch {
                repo.approve(id, opinion)
                        .onSuccess {
                            snack("审批已通过")
                            onDone()
                        }
                        .onFailure { snack(it.message ?: "审批失败", true) }
            }

    fun reject(id: Int, reason: String, onDone: () -> Unit) =
            viewModelScope.launch {
                repo.reject(id, reason)
                        .onSuccess {
                            snack("审批已驳回")
                            onDone()
                        }
                        .onFailure { snack(it.message ?: "驳回失败", true) }
            }

    fun loadCustomers() = loadEnterpriseList { repo.customers() }

    fun loadShipments() = loadEnterpriseList { repo.shipments() }

    fun loadBridge() =
            viewModelScope.launch {
                repo.bridgeRequests().onSuccess { _items.value = it }.onFailure {
                    snack(it.message ?: "加载失败", true)
                }
            }

    fun loadMods() =
            viewModelScope.launch {
                val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
                if (adminMode) {
                    repo.loadAdminMobileHome()
                            .onSuccess { home ->
                                _items.value =
                                        home.features.map { feature ->
                                            ListItem(
                                                    feature.id,
                                                    feature.title,
                                                    feature.description,
                                            )
                                        }
                            }
                            .onFailure {
                                if ((it.message ?: "").contains("403")) {
                                    snack("需要管理端管理员账号", true)
                                }
                            }
                    // 管理端员工：写入 DB，modInfos 由 DB Flow 自动驱动
                    repo.refreshAndCacheModInfos(adminMode).onFailure {
                        /* 管理端员工加载失败时静默，不阻断页面 */
                    }
                    return@launch
                }
                repo.mods().onSuccess { _items.value = it }.onFailure {
                    val msg = it.message ?: ""
                        when {
                            msg.contains("connect", ignoreCase = true) ||
                                    msg.contains("refused", ignoreCase = true) ||
                                    msg.contains("timeout", ignoreCase = true) ->
                                snack("生态功能加载中，请稍候", true)
                        msg.contains("401", ignoreCase = true) ||
                                msg.contains("403", ignoreCase = true) -> snack("登录已过期，请重新登录", true)
                        else -> snack("生态功能暂不可用，同步中", true)
                    }
                }
                // 普通模式员工：写入 DB，modInfos 由 DB Flow 自动驱动
                repo.refreshAndCacheModInfos(adminMode).onFailure {
                    /* modInfos 加载失败时静默，不干扰用户 */
                }
            }

    fun refreshModInfos(showError: Boolean = false) =
            viewModelScope.launch {
                val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
                // 后台刷新写入 DB，modInfos 由 DB Flow 自动驱动
                val result = repo.refreshAndCacheModInfos(adminMode)
                result
                        .onFailure {
                            // 网络失败时保持缓存数据，不清空；仅无缓存且失败时才提示
                            if (showError) {
                                val cached = repo.loadCachedModInfos(adminMode)
                                if (cached.isEmpty()) {
                                    snack(productErrorMessage(it.message, "AI 员工同步失败，请重新绑定后台"), true)
                                }
                            }
                        }
            }

    fun loadAiCirclePosts(showError: Boolean = false) =
            viewModelScope.launch {
                _aiCircleLoading.value = true
                repo.loadAiCirclePosts()
                        .onSuccess { _aiCirclePosts.value = it }
                        .onFailure {
                            if (showError || _aiCirclePosts.value.isEmpty()) {
                                snack(productErrorMessage(it.message, "交流圈加载失败"), true)
                            }
                        }
                _aiCircleLoading.value = false
            }

    fun createAiCirclePost(body: String, onSuccess: () -> Unit = {}) =
            viewModelScope.launch {
                repo.createAiCirclePost(body)
                        .onSuccess {
                            onSuccess()
                            loadAiCirclePosts()
                        }
                        .onFailure { snack(productErrorMessage(it.message, "发布失败"), true) }
            }

    fun toggleAiCircleLike(postId: Int) =
            viewModelScope.launch {
                // 乐观更新：先本地翻转点赞态与计数，失败再回滚，保证按一下即时反馈
                val before = _aiCirclePosts.value
                _aiCirclePosts.value = before.map { p ->
                    if (p.id == postId) {
                        val liked = !p.liked_by_me
                        p.copy(
                            liked_by_me = liked,
                            like_count = (p.like_count + if (liked) 1 else -1).coerceAtLeast(0),
                        )
                    } else {
                        p
                    }
                }
                repo.toggleAiCircleLike(postId)
                        .onSuccess { loadAiCirclePosts() }
                        .onFailure {
                            _aiCirclePosts.value = before // 回滚
                            snack(productErrorMessage(it.message, "点赞失败"), true)
                        }
            }

    fun addAiCircleComment(postId: Int, body: String, onSuccess: () -> Unit = {}) =
            viewModelScope.launch {
                repo.addAiCircleComment(postId, body)
                        .onSuccess {
                            onSuccess()
                            loadAiCirclePosts()
                        }
                        .onFailure { snack(productErrorMessage(it.message, "评论失败"), true) }
            }

    fun loadMarket() = loadEnterpriseList { repo.marketCatalog() }

    fun loadInventory() =
            viewModelScope.launch {
                _listLoading.value = true
                _listError.value = null
                repo.inventory()
                        .onSuccess { lines -> _items.value = lines.map { ListItem(it, it) } }
                        .onFailure { err -> _listError.value = err.message ?: "加载失败" }
                _listLoading.value = false
            }

    fun loadFinance() =
            viewModelScope.launch {
                repo.financeSummary().onSuccess { _detailJson.value = it }.onFailure {
                    snack(it.message ?: "加载失败", true)
                }
            }

    suspend fun modUrl(modId: String) = repo.modWebUrl(modId)

    /** 构建桌面端页面完整 URL（探索 Tab 桌面工具入口用）。 */
    fun desktopPageUrl(path: String): String {
        val base = repo.fhdBaseUrl()
        val cleanPath = if (path.startsWith("/")) path else "/$path"
        return "${base.trimEnd('/')}$cleanPath?shell=1"
    }

    suspend fun modOpensInCloudWorkbench() = repo.modOpensInCloudWorkbench()

    fun requestModOpen(modId: String, onCloud: () -> Unit, onNative: () -> Unit) =
            viewModelScope.launch { if (modOpensInCloudWorkbench()) onCloud() else onNative() }

    suspend fun bearerToken(): String {
        val t = sessionStore.fhdAccessFlow.first()
        return if (t.isBlank()) "" else "Bearer $t"
    }

    fun bridgeRespond(id: Int, text: String, onDone: () -> Unit) =
            viewModelScope.launch {
                repo.bridgeRespond(id, text)
                        .onSuccess {
                            snack("回复发送成功")
                            onDone()
                        }
                        .onFailure { snack(it.message ?: "回复失败", true) }
            }

    fun connectImWebSocket() = viewModelScope.launch { repo.connectImWebSocket() }

    fun disconnectImWebSocket() = repo.disconnectImWebSocket()

    suspend fun imOpenDirect(peerUserId: Int): Result<Map<String, Any?>> =
            repo.imOpenDirect(peerUserId)

    fun observeImMessages(conversationId: Int) = repo.observeImMessages(conversationId)

    suspend fun seedImMessages(conversationId: Int): Result<Unit> =
            repo.seedImMessages(conversationId)

    suspend fun imSendMessage(conversationId: Int, text: String): Result<Map<String, Any?>> =
            repo.imSendMessage(conversationId, text)

    fun logout(onDone: () -> Unit) =
            viewModelScope.launch {
                pushRegistrar.unregisterAll()
                repo.logout()
                refreshStartRoute()
                onDone()
            }

    fun handleDeepLink(route: String, nav: (String) -> Unit) {
        val normalized = route.trim().trimStart('/')
        when {
            normalized.startsWith(Routes.AI_EMPLOYEES) || normalized == Routes.WORK -> nav(Routes.AI_EMPLOYEES)
            normalized.startsWith(Routes.AI_CIRCLE) || normalized == Routes.DISCOVER -> nav(Routes.AI_CIRCLE)
            normalized.startsWith("ai_employee/") -> nav(normalized)
            normalized.startsWith(Routes.SCAN_QR) -> nav(Routes.SCAN_QR)
            normalized.contains("chat") -> nav(Routes.CHAT)
            normalized.contains("approval") -> {
                val id = Regex("approval/(\\d+)").find(normalized)?.groupValues?.getOrNull(1)
                if (id != null) nav("approval/$id") else nav(Routes.APPROVAL)
            }
            normalized.contains("home") || normalized.contains("home_hub") -> nav(Routes.CHAT)
            else -> nav(Routes.CHAT)
        }
    }

    // ── 专属客服 ──

    val csMessages = csRepository.messages
    val csStreaming = csRepository.streaming
    val csInfo = csRepository.csInfo

    /** 加载专属客服信息 */
    suspend fun loadCsInfo() = csRepository.loadCsInfo()

    /** 发送客服消息 */
    suspend fun sendCsMessage(body: String) {
        repo.markConversationActivity(PinnedIds.CS)
        csRepository.sendMessage(body)
            .onSuccess { persistCsConversationPreview() }
            .onFailure {
                snack(it.message ?: "客服消息发送失败", true)
            }
    }

    /** 加载客服历史消息 */
    suspend fun loadCsMessages(since: String? = null): Result<Unit> =
            csRepository.loadMessages(since).onSuccess {
                persistCsConversationPreview()
            }

    /** 停止客服流式响应 */
    fun stopCsStream() = csRepository.stopStream()
}
