package com.xiuci.xcagi.mobile.navigation

import android.net.Uri
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.LocalPrintshop
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.TravelExplore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.connectivity.NetworkMonitor
import com.xiuci.xcagi.mobile.core.media.SoundHelper
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.core.work.LanProbeWorker
import com.xiuci.xcagi.mobile.feature.legal.LegalConsentScreen
import com.xiuci.xcagi.mobile.feature.modhost.ModWebViewScreen
import com.xiuci.xcagi.mobile.feature.web.DesktopToolWebView
import com.xiuci.xcagi.mobile.feature.settings.SettingsScreen
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.WeDialog
import com.xiuci.xcagi.mobile.ui.components.mobile.SnackData
import com.xiuci.xcagi.mobile.ui.components.mobile.SnackType
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavBar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavItem
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeFadeTransition
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSnackBar
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import com.xiuci.xcagi.mobile.feature.about.AboutScreen
import com.xiuci.xcagi.mobile.feature.auth.RegisterScreen
import com.xiuci.xcagi.mobile.feature.bridge.BridgeScreen
import com.xiuci.xcagi.mobile.feature.finance.LongTailScreen
import com.xiuci.xcagi.mobile.feature.list.ListScreen
import com.xiuci.xcagi.mobile.feature.market.MarketListScreen
import com.xiuci.xcagi.mobile.feature.ocr.OcrScreen
import com.xiuci.xcagi.mobile.feature.onboarding.MobileOnboardingScreen

@EntryPoint
@InstallIn(SingletonComponent::class)
interface NetworkEntryPoint {
    fun networkMonitor(): NetworkMonitor
}

@Composable
fun XcagiNavHost(
        vm: AppViewModel,
        pendingDeepLink: String? = null,
        onDeepLinkHandled: () -> Unit = {},
) {
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    var currentSnack by remember { mutableStateOf<SnackData?>(null) }
    val msg by vm.message.collectAsState()
    val loggedIn by vm.isLoggedIn.collectAsState()
    val setupComplete by vm.isSetupComplete.collectAsState()
    val autoLanProbe by vm.autoLanProbe.collectAsState()
    val navReady by vm.navReady.collectAsState()
    val startRoute by vm.startRoute.collectAsState()
    val updatePrompt by vm.updatePrompt.collectAsState()
    val updateInstallState by vm.updateInstallState.collectAsState()
    val ctx = LocalContext.current
    val networkMonitor =
            androidx.compose.runtime.remember(ctx) {
                EntryPointAccessors.fromApplication(
                                ctx.applicationContext,
                                NetworkEntryPoint::class.java
                        )
                        .networkMonitor()
            }
    val online by networkMonitor.online.collectAsState(initial = true)

    LaunchedEffect(pendingDeepLink, loggedIn, backStack != null) {
        if (loggedIn && backStack != null && !pendingDeepLink.isNullOrBlank()) {
            vm.handleDeepLink(pendingDeepLink) { route ->
                nav.navigate(route) { launchSingleTop = true }
            }
            onDeepLinkHandled()
        }
    }

    updatePrompt?.let { prompt ->
        val updateMessage =
                buildString {
                    append("最新版本 ${prompt.versionName}，将下载完整安装包并交给系统安装器安装。")
                    val status = updateInstallState.message.trim()
                    if (status.isNotBlank()) {
                        append("\n")
                        append(status)
                    }
                }
        WeDialog(
                onDismiss = { if (!prompt.force) vm.dismissUpdatePrompt() },
                title = if (prompt.force) "需要更新" else "发现新版本",
                message = updateMessage,
                confirmText = if (updateInstallState.downloading) "下载中" else "去更新",
                dismissText = if (prompt.force) null else "稍后",
                onConfirm = {
                    if (!updateInstallState.downloading) {
                        vm.startPackageUpdate(prompt)
                    }
                },
        )
    }

    LaunchedEffect(autoLanProbe) {
        try {
            val wm = WorkManager.getInstance(ctx)
            if (autoLanProbe) {
                val req = PeriodicWorkRequestBuilder<LanProbeWorker>(15, TimeUnit.MINUTES).build()
                wm.enqueueUniquePeriodicWork(
                        "xcagi_lan_probe",
                        ExistingPeriodicWorkPolicy.UPDATE,
                        req,
                )
            } else {
                wm.cancelUniqueWork("xcagi_lan_probe")
            }
        } catch (_: Exception) {
            /* WorkManager 未初始化时不影响主流程 */
        }
    }

    LaunchedEffect(msg) {
        msg?.let {
            val snackType = if (it.isError) SnackType.ERROR else SnackType.SUCCESS
            currentSnack = SnackData(it.text, snackType)
            // 播放提示音
            if (it.isError) SoundHelper.playError() else SoundHelper.playSuccess()
            vm.clearSnack()
        }
    }

    LaunchedEffect(loggedIn) {
        if (loggedIn) {
            val r = nav.currentDestination?.route
            if (r == Routes.AUTH || r == Routes.AUTH_AUTO_LOGIN || r == Routes.REGISTER) {
                nav.navigate(Routes.ONBOARDING) {
                    popUpTo(nav.graph.findStartDestination().id) { inclusive = true }
                }
            }
        }
    }

    val current = backStack?.destination?.route?.substringBefore("?")
    val bottomNavRoutes = setOf(Routes.CHAT, Routes.WORK, Routes.DISCOVER, Routes.PROFILE)
    val showBar = loggedIn && current in bottomNavRoutes

    if (!navReady) {
        Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.Center) {
            CircularProgressIndicator()
        }
        return
    }

    Box(Modifier.fillMaxSize()) {
        Scaffold(
                topBar = {
                    if (!online) {
                        androidx.compose.material3.Surface(
                                color = MaterialTheme.colorScheme.errorContainer
                        ) {
                            Text(
                                    "当前无网络连接",
                                    modifier = Modifier.fillMaxWidth().padding(8.dp),
                                    color = MaterialTheme.colorScheme.onErrorContainer,
                                    style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                },
                bottomBar = {
                    if (showBar) {
                        WeBottomNavBar(
                                items =
                                        listOf(
                                                WeBottomNavItem(
                                                        Routes.CHAT,
                                                        "消息",
                                                        Icons.Default.Forum
                                                ),
                                                WeBottomNavItem(
                                                        Routes.WORK,
                                                        "AI员工",
                                                        Icons.Default.Badge
                                                ),
                                                WeBottomNavItem(
                                                        Routes.DISCOVER,
                                                        "探索",
                                                        Icons.Default.TravelExplore
                                                ),
                                                WeBottomNavItem(
                                                        Routes.PROFILE,
                                                        "我",
                                                        Icons.Default.AccountCircle
                                                ),
                                        ),
                                currentRoute = current,
                                onSelect = { route ->
                                    nav.navigate(route) {
                                        popUpTo(nav.graph.findStartDestination().id) {
                                            saveState = true
                                        }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                },
                        )
                    }
                },
        ) { padding ->
            NavHost(
                    nav,
                    startDestination = startRoute,
                    Modifier.padding(padding),
            ) {
                composable(Routes.LEGAL) {
                    LegalConsentScreen(
                            vm,
                            onAccepted = {
                                nav.navigate(Routes.AUTH) {
                                    popUpTo(Routes.LEGAL) { inclusive = true }
                                }
                            },
                            onAbout = { nav.navigate(Routes.ABOUT) },
                    )
                }
                composable(Routes.CONNECT) {
                    ConnectScreen(
                            vm,
                            fromProfile = false,
                            onNext = {
                                nav.navigate(Routes.AUTH) {
                                    popUpTo(Routes.CONNECT) { inclusive = true }
                                }
                            },
                            onScan = { nav.navigate(Routes.SCAN_QR) },
                            onSkipCloud = {
                                nav.navigate(Routes.AUTH) {
                                    popUpTo(Routes.CONNECT) { inclusive = true }
                                }
                            },
                            onBack = null,
                    )
                }
                composable(Routes.CONNECT_PC) {
                    ConnectScreen(
                            vm,
                            fromProfile = true,
                            onNext = { nav.popBackStack() },
                            onScan = { nav.navigate(Routes.SCAN_QR) },
                            onSkipCloud = { nav.popBackStack() },
                            onBack = { nav.popBackStack() },
                    )
                }
                composable(Routes.SCAN_QR) {
                    com.xiuci.xcagi.mobile.feature.scan.ScanQrScreen(vm) { nav.popBackStack() }
                }
                composable(Routes.SETTINGS) { SettingsScreen(vm) { nav.popBackStack() } }
                composable(Routes.AUTH) {
                    AuthScreen(
                            vm,
                            { nav.navigate(Routes.REGISTER) },
                            { nav.navigate(Routes.ONBOARDING) },
                            { nav.navigate(Routes.SCAN_QR) },
                    )
                }
                composable(Routes.AUTH_AUTO_LOGIN) {
                    // 自动登录路由：显示登录页同时自动尝试用保存的凭证登录
                    AuthScreen(
                            vm,
                            { nav.navigate(Routes.REGISTER) },
                            { nav.navigate(Routes.ONBOARDING) },
                            { nav.navigate(Routes.SCAN_QR) },
                    )
                    LaunchedEffect(Unit) { vm.tryAutoLogin() }
                }
                composable(Routes.REGISTER) {
                    RegisterScreen(
                            onOpenWebForm = {
                                val url =
                                        vm.desktopPageUrl(
                                                "/login/register?redirect=%2Fapp%2Fmobile-register-complete"
                                        )
                                nav.navigate(Routes.webView(url, "注册"))
                            },
                            onLogin = { nav.popBackStack() },
                    )
                }
                composable(Routes.ONBOARDING) {
                    val finishOnboarding = {
                        vm.completeSetup()
                        nav.navigate(Routes.CHAT) {
                            popUpTo(Routes.ONBOARDING) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                    MobileOnboardingScreen(
                            vm,
                            onFinish = finishOnboarding,
                            onBack = finishOnboarding,
                    )
                }
                composable(Routes.HOME_HUB) {
                    LaunchedEffect(Unit) {
                        nav.navigate(Routes.CHAT) {
                            popUpTo(Routes.HOME_HUB) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                }
                composable(
                        Routes.PROFILE,
                        enterTransition = { fadeIn(tween(250)) + slideInHorizontally(tween(300)) { it / 6 } },
                        exitTransition = { fadeOut(tween(200)) },
                        popEnterTransition = { fadeIn(tween(250)) + slideInHorizontally(tween(300)) { -it / 6 } },
                        popExitTransition = { fadeOut(tween(200)) + slideOutHorizontally(tween(300)) { it / 4 } },
                ) {
                    ProfileScreen(
                            vm,
                            onConnectPc = { nav.navigate(Routes.CONNECT_PC) },
                            onAbout = { nav.navigate(Routes.ABOUT) },
                            onSettings = { nav.navigate(Routes.SETTINGS) },
                            onLogout = {
                                val dest = if (setupComplete) Routes.AUTH else Routes.CONNECT
                                vm.logout { nav.navigate(dest) { popUpTo(0) { inclusive = true } } }
                            },
                    )
                }
                composable(
                        Routes.WORK,
                        enterTransition = { fadeIn(tween(250)) + slideInHorizontally(tween(300)) { it / 6 } },
                        exitTransition = { fadeOut(tween(200)) },
                        popEnterTransition = { fadeIn(tween(250)) + slideInHorizontally(tween(300)) { -it / 6 } },
                        popExitTransition = { fadeOut(tween(200)) + slideOutHorizontally(tween(300)) { it / 4 } },
                ) {
                    AiEmployeeListScreen(
                            vm,
                            onSelect = { modId, employeeId ->
                                nav.navigate(Routes.aiEmployeeProfile(modId, employeeId))
                            },
                            onScan = { nav.navigate(Routes.SCAN_QR) },
                    )
                }
                composable(
                        Routes.DISCOVER,
                        enterTransition = { WeFadeTransition.enter() },
                        exitTransition = { WeFadeTransition.exit() },
                        popEnterTransition = { WeFadeTransition.enter() },
                        popExitTransition = { WeFadeTransition.exit() },
                ) {
                    DiscoverScreen(
                        vm = vm,
                        onScan = { nav.navigate(Routes.SCAN_QR) },
                        onOcr = { nav.navigate(Routes.OCR) },
                        onAiCircle = { nav.navigate(Routes.AI_CIRCLE) },
                        onNotifications = { nav.navigate(Routes.NOTIFICATIONS) },
                        onNavigate = { route -> nav.navigate(route) },
                        onOpenWebView = { path, title ->
                            val url = vm.desktopPageUrl(path)
                            nav.navigate(Routes.webView(url, title))
                        },
                    )
                }
                composable(
                        Routes.CHAT,
                        enterTransition = { WeFadeTransition.enter() },
                        exitTransition = { WeFadeTransition.exit() },
                        popEnterTransition = { WeFadeTransition.enter() },
                        popExitTransition = { WeFadeTransition.exit() },
                ) {
                    ConversationListScreen(
                            vm = vm,
                            onOpenAssistant = { nav.navigate(Routes.AI_CHAT) },
                            onOpenCustomerService = { nav.navigate(Routes.CS_CHAT) },
                            onOpenConversation = { conversationId ->
                                nav.navigate(Routes.conversationChat(conversationId))
                            },
                            onOpenScan = { nav.navigate(Routes.SCAN_QR) },
                            onOpenEmployees = {
                                vm.loadMods()
                                nav.navigate(Routes.AI_EMPLOYEES)
                            },
                            onOpenContacts = {
                                nav.navigate(Routes.WORK) {
                                    popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            onOpenDiscover = {
                                nav.navigate(Routes.DISCOVER) {
                                    popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            onStartGroupChat = { nav.navigate(Routes.AI_GROUP_CREATE) },
                            onOpenGroups = { nav.navigate(Routes.AI_GROUPS) },
                            onOpenGroup = { group ->
                                vm.openAiGroup(group)
                                nav.navigate(Routes.AI_GROUP_CHAT)
                            },
                    )
                }
                // AI 对话 — 小C助理，走 /api/ai/chat/stream（与桌面端智能对话一致）
                composable(
                        Routes.AI_CHAT,
                        enterTransition = { slideInHorizontally(tween(300)) { it } },
                        exitTransition = { slideOutHorizontally(tween(300)) { -it / 3 } },
                        popEnterTransition = { slideInHorizontally(tween(300)) { -it / 3 } },
                        popExitTransition = { slideOutHorizontally(tween(300)) { it } },
                ) {
                    ChatScreen(
                            vm,
                            onBack = { nav.popBackStack() },
                            onOpenProfile = {
                                nav.navigate(
                                        Routes.fixedPartnerProfile(FixedPartnerKinds.ASSISTANT)
                                )
                            },
                            onOpenMod = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            },
                            onOpenOcr = { nav.navigate(Routes.OCR) },
                    )
                }
                // 普通会话对话 — 复用 ChatScreen（带 conversationId）
                composable(
                        route = Routes.CONVERSATION_CHAT + "/{conversationId}",
                        arguments = listOf(navArgument("conversationId") { type = NavType.StringType }),
                        enterTransition = { slideInHorizontally(tween(300)) { it } },
                        exitTransition = { slideOutHorizontally(tween(300)) { -it / 3 } },
                        popEnterTransition = { slideInHorizontally(tween(300)) { -it / 3 } },
                        popExitTransition = { slideOutHorizontally(tween(300)) { it } },
                ) { backStackEntry ->
                    val conversationId = backStackEntry.arguments?.getString("conversationId") ?: ""
                    val pinnedPartnerKind = when (conversationId) {
                        PinnedIds.CODEX -> FixedPartnerKinds.CODEX
                        PinnedIds.CURSOR -> FixedPartnerKinds.CURSOR
                        PinnedIds.CLAUDE -> FixedPartnerKinds.CLAUDE
                        else -> null
                    }
                    ChatScreen(
                            vm,
                            conversationId = conversationId,
                            onBack = { nav.popBackStack() },
                            onOpenProfile = pinnedPartnerKind?.let { kind ->
                                { nav.navigate(Routes.fixedPartnerProfile(kind)) }
                            },
                            onOpenMod = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            },
                            onOpenOcr = { nav.navigate(Routes.OCR) },
                            onOpenEmployeeProfile = { modId, employeeId ->
                                nav.navigate(Routes.aiEmployeeProfile(modId, employeeId))
                            },
                            onSwitchCliModel = pinnedPartnerKind?.let {
                                { targetId ->
                                    if (targetId != conversationId) {
                                        nav.navigate(Routes.conversationChat(targetId)) {
                                            popUpTo(Routes.conversationChat(conversationId)) {
                                                inclusive = true
                                            }
                                            launchSingleTop = true
                                        }
                                    }
                                }
                            },
                    )
                }
                // 专属客服对话
                composable(
                        Routes.CS_CHAT,
                        enterTransition = { slideInHorizontally(tween(300)) { it } },
                        exitTransition = { slideOutHorizontally(tween(300)) { -it / 3 } },
                        popEnterTransition = { slideInHorizontally(tween(300)) { -it / 3 } },
                        popExitTransition = { slideOutHorizontally(tween(300)) { it } },
                ) {
                    CsChatScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenProfile = {
                                nav.navigate(
                                        Routes.fixedPartnerProfile(
                                                FixedPartnerKinds.CUSTOMER_SERVICE
                                        )
                                )
                            },
                    )
                }
                composable(Routes.AI_EMPLOYEES) {
                    AiEmployeeListScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onSelect = { modId, employeeId ->
                                nav.navigate(Routes.aiEmployeeProfile(modId, employeeId))
                            },
                            onScan = { nav.navigate(Routes.SCAN_QR) },
                    )
                }
                composable(Routes.AI_CIRCLE) {
                    AiCircleScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenEmployee = { modId, employeeId ->
                                nav.navigate(Routes.aiEmployeeProfile(modId, employeeId))
                            },
                    )
                }
                composable(Routes.AI_GROUPS) {
                    AiGroupListScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenGroup = { group ->
                                vm.openAiGroup(group)
                                nav.navigate(Routes.AI_GROUP_CHAT)
                            },
                    )
                }
                composable(Routes.AI_GROUP_CHAT) {
                    AiGroupChatScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                    )
                }
                composable(Routes.AI_GROUP_CREATE) {
                    AiGroupCreateScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onCreated = {
                                nav.navigate(Routes.AI_GROUP_CHAT) {
                                    popUpTo(Routes.AI_GROUP_CREATE) { inclusive = true }
                                }
                            },
                    )
                }
                composable(
                        route = Routes.AI_EMPLOYEE_PROFILE,
                        arguments =
                                listOf(
                                        navArgument("modId") { type = NavType.StringType },
                                        navArgument("employeeId") { type = NavType.StringType },
                                ),
                ) { backStackEntry ->
                    val modId = backStackEntry.arguments?.getString("modId").orEmpty()
                    val employeeId = backStackEntry.arguments?.getString("employeeId").orEmpty()
                    AiEmployeeProfileScreen(
                            vm = vm,
                            modId = modId,
                            employeeId = employeeId,
                            onBack = { nav.popBackStack() },
                            onOpenCircle = { nav.navigate(Routes.AI_CIRCLE) },
                            onOpenChat = { conversationId ->
                                nav.navigate(Routes.conversationChat(conversationId))
                            },
                    )
                }
                composable(
                        route = Routes.FIXED_PARTNER_PROFILE,
                        arguments =
                                listOf(
                                        navArgument("partnerKind") { type = NavType.StringType }
                                ),
                ) { backStackEntry ->
                    val partnerKind = backStackEntry.arguments?.getString("partnerKind").orEmpty()
                    FixedPartnerProfileScreen(
                            vm = vm,
                            partnerKind = partnerKind,
                            onBack = { nav.popBackStack() },
                            onOpenCircle = { nav.navigate(Routes.AI_CIRCLE) },
                            onOpenChat = {
                                val target =
                                        when (partnerKind) {
                                            FixedPartnerKinds.CUSTOMER_SERVICE -> Routes.CS_CHAT
                                            FixedPartnerKinds.CODEX -> Routes.conversationChat(PinnedIds.CODEX)
                                            FixedPartnerKinds.CURSOR -> Routes.conversationChat(PinnedIds.CURSOR)
                                            FixedPartnerKinds.CLAUDE -> Routes.conversationChat(PinnedIds.CLAUDE)
                                            else -> Routes.AI_CHAT
                                        }
                                nav.navigate(target) { launchSingleTop = true }
                            },
                    )
                }
                composable(Routes.SMART_ANALYSIS) {
                    SmartAnalysisScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenChat = { mode ->
                                nav.popBackStack()
                                nav.navigate(Routes.CHAT)
                            },
                    )
                }
                composable(Routes.AI_OPEN) {
                    AiOpenScreen(vm = vm, onBack = { nav.popBackStack() })
                }
                composable(Routes.BRAIN) {
                    BrainScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenMod = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            }
                    )
                }
                composable(Routes.MOD_STORE) {
                    ModStoreScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onOpenMod = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            },
                    )
                }
                composable(Routes.APPROVAL) {
                    ApprovalListScreen(
                            vm,
                            onItemClick = { id -> nav.navigate("approval/$id") },
                    )
                }
                composable(
                        Routes.APPROVAL_DETAIL,
                        arguments = listOf(navArgument("id") { type = NavType.IntType })
                ) { e ->
                    ApprovalDetailScreen(vm, e.arguments?.getInt("id") ?: 0) { nav.popBackStack() }
                }
                composable(Routes.IM) { ImMessengerScreen(vm) { nav.popBackStack() } }
                composable(Routes.ERP) { ErpScreen(vm) }
                composable(Routes.ERP_OVERVIEW) { ErpScreen(vm) }
                composable(
                        Routes.ERP_TAB,
                        arguments = listOf(navArgument("tabIndex") { type = NavType.IntType }),
                ) { entry ->
                    ErpTabListScreen(
                            tabIndex = entry.arguments?.getInt("tabIndex") ?: 0,
                            vm = vm,
                            onBack = { nav.popBackStack() },
                    )
                }
                composable(Routes.OCR) { OcrScreen(vm = vm, onBack = { nav.popBackStack() }) }
                composable(Routes.BRIDGE) { BridgeScreen(vm) }
                composable(Routes.MARKET) {
                    MarketListScreen(
                            vm,
                            onUse = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            },
                            onBack = { nav.popBackStack() },
                    )
                }
                composable(Routes.MODS) {
                    ListScreen("Mod", vm, vm::loadMods, { id -> nav.navigate("mod/$id") }) {
                        nav.popBackStack()
                    }
                }
                composable(
                        Routes.MOD_WEB,
                        arguments = listOf(navArgument("modId") { type = NavType.StringType })
                ) { e ->
                    val modId = e.arguments?.getString("modId") ?: ""
                    var bearer by remember { mutableStateOf("") }
                    var url by remember { mutableStateOf("") }
                    val access by vm.marketAccess.collectAsState()
                    val refresh by vm.marketRefresh.collectAsState()
                    val fhdAccess by vm.fhdAccess.collectAsState()
                    LaunchedEffect(modId) {
                        bearer = vm.bearerToken()
                        url = vm.modUrl(modId)
                    }
                    if (url.isNotBlank()) {
                        ModWebViewScreen(url, bearer, access, refresh, fhdAccess)
                    }
                }
                composable(
                        Routes.WEB_VIEW,
                        arguments = listOf(
                                navArgument("url") { type = NavType.StringType },
                                navArgument("title") { type = NavType.StringType },
                        )
                ) { e ->
                    val url = e.arguments?.getString("url") ?: ""
                    val title = e.arguments?.getString("title") ?: "桌面工具"
                    var bearer by remember { mutableStateOf("") }
                    val access by vm.marketAccess.collectAsState()
                    val refresh by vm.marketRefresh.collectAsState()
                    val fhdAccess by vm.fhdAccess.collectAsState()
                    LaunchedEffect(url) {
                        bearer = vm.bearerToken()
                    }
                    if (url.isNotBlank()) {
                        val isRegisterFlow = url.contains("/login/register")
                        DesktopToolWebView(
                                url,
                                title,
                                bearer,
                                access,
                                refresh,
                                fhdAccess,
                                onUrlOverride = { nextUrl ->
                                    val path = runCatching { Uri.parse(nextUrl).path.orEmpty() }.getOrDefault("")
                                    if (isRegisterFlow && path == "/app/mobile-register-complete") {
                                        vm.snack("注册完成，请使用新账号登录")
                                        nav.navigate(Routes.AUTH) {
                                            popUpTo(Routes.AUTH) { inclusive = false }
                                            launchSingleTop = true
                                        }
                                        true
                                    } else {
                                        false
                                    }
                                },
                        ) {
                            nav.popBackStack()
                        }
                    }
                }
                composable(Routes.LONGTAIL) { LongTailScreen(vm) }
                composable(Routes.NOTIFICATIONS) {
                    NotificationListScreen(onBack = { nav.popBackStack() })
                }
                composable(Routes.ABOUT) {
                    val cfg by vm.appConfig.collectAsState()
                    AboutScreen(
                            { nav.popBackStack() },
                            cfg,
                            onCheckUpdate = { vm.checkForUpdate(manual = true) }
                    )
                }
            }
        }

        // 消息提示条（浮在 Scaffold 上层）
        WeSnackBar(
                message = currentSnack,
                onDismiss = { currentSnack = null },
                modifier = Modifier.align(Alignment.TopCenter).padding(top = 48.dp),
        )
    }
}
