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
import com.xiuci.xcagi.mobile.core.model.ApprovalDetail
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import com.xiuci.xcagi.mobile.core.network.PairingQrCodec
import com.xiuci.xcagi.mobile.core.network.ServerMode
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.core.observability.XcagiAnalytics
import com.xiuci.xcagi.mobile.core.push.PushRegistrar
import com.xiuci.xcagi.mobile.core.repository.XcagiRepository
import com.xiuci.xcagi.mobile.core.sync.MobileSyncRepository
import com.xiuci.xcagi.mobile.core.work.MobileSyncWorker
import com.xiuci.xcagi.mobile.model.AvatarType
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.ConversationType
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.model.CsMessageItemDto
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.navigation.Routes
import com.xiuci.xcagi.mobile.navigation.aiEmployeeAvatarColor
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
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

data class UiMessage(val text: String, val isError: Boolean = false)

data class UpdatePrompt(
        val force: Boolean,
        val versionName: String,
        val downloadUrl: String,
)

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

    private val _approvalPendingCount = MutableStateFlow(0)
    val approvalPendingCount: StateFlow<Int> = _approvalPendingCount.asStateFlow()

    private val _chatSuggestions = MutableStateFlow<List<ChatSuggestion>>(emptyList())
    val chatSuggestions: StateFlow<List<ChatSuggestion>> = _chatSuggestions.asStateFlow()

    private val _conversations = MutableStateFlow<List<ConversationItem>>(emptyList())
    val conversations: StateFlow<List<ConversationItem>> = _conversations.asStateFlow()

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

    private val _modInfos = MutableStateFlow<List<ModInfo>>(emptyList())
    val modInfos: StateFlow<List<ModInfo>> = _modInfos.asStateFlow()

    // 用户头像 URL（从登录响应或本地存储获取）
    private val _userAvatarUrl = MutableStateFlow<String?>(null)
    val userAvatarUrl: StateFlow<String?> = _userAvatarUrl.asStateFlow()

    fun refreshUserAvatar() {
        viewModelScope.launch {
            _userAvatarUrl.value = repo.refreshMe()
        }
    }

    val dynamicMenuItems: StateFlow<List<ModMenuItem>> =
            _modInfos
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

    /** 构建会话列表：固定入口 + 当前账号生态里的 workflow_employees。 */
    fun loadConversations(isEnterprise: Boolean) {
        // 去重：取消上一次未完成的加载，避免并发竞相更新 _conversations 造成瞬间闪烁
        conversationsLoadJob?.cancel()
        conversationsLoadJob = viewModelScope.launch {
            rebuildConversationItems(isEnterprise)
        }
    }

    private suspend fun rebuildConversationItems(isEnterprise: Boolean): Int {
        val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
        val fixedItems =
                fixedConversationItems(
                        showCodex = isEnterprise || adminMode,
                        showCustomerService = isEnterprise && !adminMode,
                )
        val badgeText = if (adminMode) "管理端" else "已安装"
        val badgeColor =
                if (adminMode) androidx.compose.ui.graphics.Color(0xFFED7B2F)
                else androidx.compose.ui.graphics.Color(0xFF3370FF)

        // 1. 仅当当前列表没有员工项时，才用缓存填充（避免刷新时用旧缓存覆盖当前显示）
        val currentHasEmployees = _conversations.value.any { it.type == ConversationType.AI_TASK }
        if (!currentHasEmployees) {
            val cached = repo.loadCachedModInfos(adminMode)
            if (cached.isNotEmpty()) {
                _modInfos.value = cached
                val cachedEmployees = employeeConversationItems(cached, badgeText, badgeColor)
                _conversations.value = fixedItems + cachedEmployees
            }
        }

        // 非企业且非管理端：不发起网络刷新
        if (!adminMode && !isEnterprise) return 0

        // 2. 后台网络刷新；失败或返回空时保持当前显示不清空
        val mods = repo.refreshAndCacheModInfos(adminMode).getOrElse {
            // 网络失败：保持当前显示
            return _conversations.value.count { it.type == ConversationType.AI_TASK }
        }
        // 网络成功但返回空列表：保持当前显示，不用空列表覆盖
        if (mods.isEmpty()) {
            return _conversations.value.count { it.type == ConversationType.AI_TASK }
        }
        _modInfos.value = mods
        val employees = employeeConversationItems(mods, badgeText, badgeColor)
        _conversations.value = fixedItems + employees
        return employees.size
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
        refreshApprovalCount()
        registerPushWithHint()
        return employeeCount
    }

    private fun employeeConversationItems(
            mods: List<ModInfo>,
            badgeText: String,
            badgeColor: androidx.compose.ui.graphics.Color,
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
                        ConversationItem(
                                id = "employee:${mod.id}:$employeeId",
                                type = ConversationType.AI_TASK,
                                title = title,
                                subtitle =
                                        employee.contactSubtitle(source),
                                timestamp = System.currentTimeMillis(),
                                avatarType = if (avatarUrl != null) AvatarType.URL else AvatarType.LETTER,
                                avatarLetter = title.firstOrNull { !it.isWhitespace() } ?: 'A',
                                avatarColor = aiEmployeeAvatarColor("${mod.id}:$employeeId"),
                                avatarUrl = avatarUrl,
                        )
                    }
                }
            }.distinctBy { it.id } // 防止后端返回重复 employee id 导致 LazyColumn key 冲突崩溃

    private fun com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo.contactSubtitle(
            source: String?,
    ): String {
        val channel = phone_channel.contactChannelLabel()
        val aiNo = id.takeIf { it.isNotBlank() }?.let { "AI号 $it" }.orEmpty()
        val summary =
                panel_summary.ifBlank {
                    source?.let { "来自 $it" }.orEmpty()
                }
        return listOf(channel, aiNo, summary).filter { it.isNotBlank() }.joinToString(" · ")
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
            showCustomerService: Boolean,
    ): List<ConversationItem> {
        val items = mutableListOf<ConversationItem>()

        // 1. 小C助理（始终显示）
        items.add(
            ConversationItem(
                id = PinnedIds.ASSISTANT,
                type = ConversationType.PINNED_ASSISTANT,
                title = "小C助理",
                subtitle = "有什么可以帮您？",
                timestamp = System.currentTimeMillis(),
                avatarType = AvatarType.ICON,
                isPinned = true,
            )
        )

        if (showCodex) {
                items.add(
                    ConversationItem(
                            id = PinnedIds.CODEX,
                            type = ConversationType.PINNED_CODEX,
                            title = "超级员工-Codex",
                            subtitle = "全设备协同",
                            timestamp = System.currentTimeMillis(),
                            avatarType = AvatarType.ICON,
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
                    subtitle = "您好，我是您的专属客服",
                    timestamp = System.currentTimeMillis() - 3600_000,
                    avatarType = AvatarType.ICON,
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

    private fun csItemsToChat(items: List<CsMessageItemDto>): List<Pair<String, String>> =
            items.mapNotNull { msg ->
                val body = msg.body.trim()
                if (body.isBlank()) {
                    null
                } else {
                    (if (msg.sender == "user") "user" else "assistant") to body
                }
            }

    fun loadChatCache(conversationId: String? = null) =
            viewModelScope.launch {
                if (conversationId == PinnedIds.CODEX) {
                    repo.loadCodexSuperEmployeeMessages()
                            .onSuccess { _chatMessages.value = it }
                            .onFailure {
                                snack("超级员工-Codex 历史加载失败", true)
                                _chatMessages.value = emptyList()
                            }
                    return@launch
                }
                val sessionId = conversationId ?: "default"
                _chatMessages.value = repo.loadCachedChat(sessionId)
            }

    fun loadAssistantCustomerServiceHistory() =
            viewModelScope.launch {
                csRepository.loadCsInfo()
                csRepository
                        .loadMessages()
                        .onSuccess { _chatMessages.value = csItemsToChat(csRepository.messages.value) }
                        .onFailure {
                            snack(it.message ?: "小C助理历史加载失败", true)
                            _chatMessages.value = emptyList()
                        }
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

    fun sendChat(text: String, conversationId: String? = null) {
        chatJob?.cancel()
        _chatAction.value = null
        _chatMessages.value = _chatMessages.value + ("user" to text) + ("assistant" to "")
        _streaming.value = true
        var acc = ""
        val sessionId = conversationId ?: "default"
        chatJob =
                viewModelScope.launch {
                    if (repo.hasNativeFhdAuth()) {
                        // 有本地 FHD 认证，走局域网
                        repo.streamChat(
                                text,
                                conversationId,
                                sessionId,
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

    fun sendAssistantCustomerServiceMessage(text: String) {
        chatJob?.cancel()
        _chatAction.value = null
        _chatMessages.value = _chatMessages.value + ("user" to text)
        _streaming.value = true
        chatJob =
                viewModelScope.launch {
                    csRepository
                            .sendMessage(text)
                            .onSuccess { response ->
                                val reply =
                                        response.reply.ifBlank {
                                            csRepository.messages.value
                                                    .lastOrNull { it.sender != "user" }
                                                    ?.body
                                                    .orEmpty()
                                        }
                                if (reply.isNotBlank()) {
                                    _chatMessages.value =
                                            _chatMessages.value + ("assistant" to reply)
                                } else {
                                    _chatMessages.value = csItemsToChat(csRepository.messages.value)
                                }
                            }
                            .onFailure {
                                val message = it.message ?: "小C助理暂时无法连接企业智能客服"
                                _chatMessages.value =
                                        _chatMessages.value + ("assistant" to "处理失败：$message")
                                snack(message, true)
                            }
                    _streaming.value = false
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
                // 缓存优先：先读 Room 缓存避免列表闪空
                val cached = repo.loadCachedModInfos(adminMode)
                if (cached.isNotEmpty()) _modInfos.value = cached
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
                    repo.loadAdminModInfos().onSuccess {
                        // 网络返回非空才更新；空列表通常是临时错误，保持缓存
                        if (it.isNotEmpty()) _modInfos.value = it
                    }.onFailure {
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
                repo.loadModInfos().onSuccess {
                    // 网络返回非空才更新；空列表通常是临时错误，保持缓存
                    if (it.isNotEmpty()) _modInfos.value = it
                }.onFailure {
                    /* modInfos 加载失败时静默，不干扰用户 */
                }
            }

    fun refreshModInfos(showError: Boolean = false) =
            viewModelScope.launch {
                val adminMode = isAdminAccountKind(sessionStore.accountKindFlow.first())
                // 1. 先读缓存（UI 秒出）
                val cached = repo.loadCachedModInfos(adminMode)
                if (cached.isNotEmpty()) _modInfos.value = cached
                // 2. 后台刷新
                val result = repo.refreshAndCacheModInfos(adminMode)
                result
                        .onSuccess {
                            // 网络返回非空才更新；空列表通常是临时错误，保持缓存
                            if (it.isNotEmpty()) _modInfos.value = it
                        }
                        .onFailure {
                            // 网络失败时保持缓存数据，不清空；仅无缓存且失败时才提示
                            if (showError && cached.isEmpty()) {
                                snack(productErrorMessage(it.message, "AI 员工同步失败，请重新绑定后台"), true)
                            }
                        }
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
    suspend fun sendCsMessage(body: String) =
            csRepository.sendMessage(body).onFailure {
                snack(it.message ?: "客服消息发送失败", true)
            }

    /** 加载客服历史消息 */
    suspend fun loadCsMessages(since: String? = null) = csRepository.loadMessages(since)

    /** 停止客服流式响应 */
    fun stopCsStream() = csRepository.stopStream()
}
