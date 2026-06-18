package com.xiuci.xcagi.mobile.navigation

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
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
import com.xiuci.xcagi.mobile.core.work.LanProbeWorker
import com.xiuci.xcagi.mobile.feature.legal.LegalConsentScreen
import com.xiuci.xcagi.mobile.feature.modhost.ModWebViewScreen
import com.xiuci.xcagi.mobile.feature.settings.SettingsScreen
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
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
        AlertDialog(
                onDismissRequest = { if (!prompt.force) vm.dismissUpdatePrompt() },
                title = { Text(if (prompt.force) "需要更新" else "发现新版本") },
                text = { Text("最新版本 ${prompt.versionName}，请更新以获得完整功能与安全修复。") },
                confirmButton = {
                    TextButton({
                        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(prompt.downloadUrl)))
                        if (!prompt.force) vm.dismissUpdatePrompt()
                    }) { Text("去更新") }
                },
                dismissButton =
                        if (!prompt.force) {
                            { TextButton({ vm.dismissUpdatePrompt() }) { Text("稍后") } }
                        } else {
                            null
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
            if (r == Routes.AUTH || r == Routes.REGISTER) {
                nav.navigate(Routes.CHAT) {
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
                            { nav.navigate(Routes.CHAT) },
                            { nav.navigate(Routes.SCAN_QR) },
                    )
                }
                composable(Routes.AUTH_AUTO_LOGIN) {
                    // 自动登录路由：显示登录页同时自动尝试用保存的凭证登录
                    AuthScreen(
                            vm,
                            { nav.navigate(Routes.REGISTER) },
                            { nav.navigate(Routes.CHAT) },
                            { nav.navigate(Routes.SCAN_QR) },
                    )
                    LaunchedEffect(Unit) { vm.tryAutoLogin() }
                }
                composable(Routes.REGISTER) { RegisterScreen(vm) { nav.popBackStack() } }
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
                        enterTransition = { fadeIn(tween(250)) },
                        exitTransition = { fadeOut(tween(250)) },
                        popEnterTransition = { fadeIn(tween(250)) },
                        popExitTransition = { fadeOut(tween(250)) },
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
                        enterTransition = { fadeIn(tween(250)) },
                        exitTransition = { fadeOut(tween(250)) },
                        popEnterTransition = { fadeIn(tween(250)) },
                        popExitTransition = { fadeOut(tween(250)) },
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
                            onScan = { nav.navigate(Routes.SCAN_QR) },
                            onOcr = { nav.navigate(Routes.OCR) },
                            onAiCircle = { nav.navigate(Routes.AI_CIRCLE) },
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
                    )
                }
                // AI 对话 — 复用现有 ChatScreen
                composable(Routes.AI_CHAT) {
                    ChatScreen(
                            vm,
                            useCustomerServiceBackend = true,
                            onBack = { nav.popBackStack() },
                            profileAvatar =
                                    ChatTopProfileAvatar(
                                            text = "C",
                                            containerColor = XcagiTheme.extra.brandBlue,
                                    ),
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
                ) { backStackEntry ->
                    val conversationId = backStackEntry.arguments?.getString("conversationId") ?: ""
                    ChatScreen(
                            vm,
                            conversationId = conversationId,
                            onBack = { nav.popBackStack() },
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
                    )
                }
                // 专属客服对话
                composable(Routes.CS_CHAT) {
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
                            onOpenChat = {
                                val target =
                                        when (partnerKind) {
                                            FixedPartnerKinds.CUSTOMER_SERVICE -> Routes.CS_CHAT
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
                composable(Routes.LONGTAIL) { LongTailScreen(vm) }
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

@Composable
fun RegisterScreen(vm: AppViewModel, onBack: () -> Unit) {
    var u by remember { mutableStateOf("") }
    var p by remember { mutableStateOf("") }
    var e by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val canSubmit = u.isNotBlank() && p.isNotBlank() && e.isNotBlank() && agreed

    Column(
            Modifier.fillMaxSize()
                    .background(Color.White)
                    .padding(horizontal = 24.dp)
                    .padding(top = 60.dp),
    ) {
        Text(
                "创建账号",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(6.dp))
        Text(
                "注册 XCAGI 企业平台账号",
                fontSize = 14.sp,
                color = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(32.dp))

        // 用户名
        OutlinedTextField(
                value = u,
                onValueChange = { u = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("用户名") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
        )
        Spacer(Modifier.height(12.dp))

        // 密码
        OutlinedTextField(
                value = p,
                onValueChange = { p = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("密码") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        )
        Spacer(Modifier.height(12.dp))

        // 邮箱
        OutlinedTextField(
                value = e,
                onValueChange = { e = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("邮箱") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
        )
        Spacer(Modifier.height(24.dp))

        // 协议勾选
        Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clip(RoundedCornerShape(4.dp)).clickable { agreed = !agreed },
        ) {
            Box(
                    Modifier.size(16.dp)
                            .clip(RoundedCornerShape(3.dp))
                            .background(
                                    if (agreed) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant
                            ),
                    contentAlignment = Alignment.Center,
            ) {
                if (agreed)
                        Icon(Icons.Default.Check, null, Modifier.size(12.dp), tint = Color.White)
            }
            Spacer(Modifier.size(6.dp))
            Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(color = MaterialTheme.colorScheme.outline, fontSize = 12.sp)) {
                            append("我已阅读并同意")
                        }
                        withStyle(
                                SpanStyle(
                                        color = XcagiTheme.extra.brandBlue,
                                        fontSize = 12.sp,
                                        textDecoration = TextDecoration.Underline
                                )
                        ) { append("《用户协议》") }
                        withStyle(SpanStyle(color = MaterialTheme.colorScheme.outline, fontSize = 12.sp)) {
                            append("和")
                        }
                        withStyle(
                                SpanStyle(
                                        color = XcagiTheme.extra.brandBlue,
                                        fontSize = 12.sp,
                                        textDecoration = TextDecoration.Underline
                                )
                        ) { append("《隐私政策》") }
                    }
            )
        }
        Spacer(Modifier.height(24.dp))

        // 注册按钮
        Box(
                Modifier.fillMaxWidth()
                        .height(48.dp)
                        .clip(RoundedCornerShape(24.dp))
                        .background(if (canSubmit) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant)
                        .clickable(enabled = canSubmit) {
                            vm.register(u, p, e) { if (it) onBack() }
                        },
                contentAlignment = Alignment.Center,
        ) { Text("注册", fontSize = 16.sp, fontWeight = FontWeight.Medium, color = Color.White) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MarketListScreen(
        vm: AppViewModel,
        onUse: (String) -> Unit,
        onBack: () -> Unit,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()
    LaunchedEffect(Unit) { vm.loadMarket() }

    com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold(
            title = "MODstore",
            onBack = onBack,
            onRefresh = vm::loadMarket,
            loading = loading,
            error = error,
            empty = items.isEmpty(),
            emptyMessage = "暂无 Mod",
            onRetry = vm::loadMarket,
    ) { _ ->
        LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption("可用能力") }
            item {
                WeCellGroup {
                    items.forEachIndexed { idx, item ->
                        WeCell(
                                title = item.title,
                                subtitle = item.subtitle.ifBlank { "从企业端同步的能力包" },
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                                showDivider = idx < items.lastIndex,
                                trailing = {
                                    TextButton(onClick = { onUse(item.id) }) {
                                        Text("使用", color = XcagiTheme.extra.brandBlue)
                                    }
                                },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun MarketModCard(item: ListItem, onUse: () -> Unit) {
    Row(
            Modifier.fillMaxWidth()
                    .clip(MaterialTheme.shapes.medium)
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
                Modifier.size(44.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.secondaryContainer),
                contentAlignment = Alignment.Center,
        ) {
            Icon(
                    Icons.Default.Extension,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.secondary
            )
        }
        Column(
                Modifier.weight(1f).padding(horizontal = 12.dp),
        ) {
            Text(
                    item.title,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
            )
            Text(
                    item.subtitle.ifBlank { "浏览并安装行业 Mod" },
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
            )
        }
        Button(onClick = onUse, shape = MaterialTheme.shapes.medium) { Text("使用") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListScreen(
        title: String,
        vm: AppViewModel,
        load: () -> Unit,
        onClick: ((String) -> Unit)?,
        onBack: (() -> Unit)? = null,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()
    LaunchedEffect(Unit) { load() }

    com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold(
            title = title,
            onBack = onBack,
            onRefresh = load,
            loading = loading,
            error = error,
            empty = items.isEmpty(),
            emptyMessage = "暂无数据",
            onRetry = load,
    ) { _ ->
        LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption(title) }
            item {
                WeCellGroup {
                    items.forEachIndexed { idx, item ->
                        WeCell(
                                title = item.title,
                                subtitle = item.subtitle,
                                showArrow = onClick != null,
                                showDivider = idx < items.lastIndex,
                                onClick = onClick?.let { cb -> { cb(item.id) } },
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BridgeScreen(vm: AppViewModel) {
    val items by vm.items.collectAsState()
    var reply by remember { mutableStateOf("") }
    var selectedId by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { vm.loadBridge() }

    com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen(
            title = "服务桥接",
            scrollable = false,
    ) {
        LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption("待处理工单") }
            item {
                WeCellGroup {
                    if (items.isEmpty()) {
                        WeCell(
                                title = "暂无工单",
                                subtitle = "企业端有新工单后会同步到这里",
                                icon = Icons.Default.Forum,
                                iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
                                iconBg = MaterialTheme.colorScheme.surfaceVariant,
                                showArrow = false,
                                showDivider = false,
                        )
                    } else {
                        items.forEachIndexed { idx, item ->
                            val id = item.id.toIntOrNull() ?: 0
                            WeCell(
                                    title = item.title,
                                    subtitle = item.subtitle.ifBlank { "等待处理" },
                                    icon = Icons.Default.Forum,
                                    iconTint =
                                            if (selectedId == id) XcagiTheme.extra.brandBlue
                                            else MaterialTheme.colorScheme.onSurfaceVariant,
                                    iconBg =
                                            if (selectedId == id) MaterialTheme.colorScheme.primaryContainer
                                            else MaterialTheme.colorScheme.surfaceVariant,
                                    showArrow = true,
                                    showDivider = idx < items.lastIndex,
                                    onClick = { selectedId = id },
                            )
                        }
                    }
                }
            }
        }

        WeSectionCaption(if (selectedId > 0) "回复 #$selectedId" else "回复")
        WeCellGroup {
            OutlinedTextField(
                    value = reply,
                    onValueChange = { reply = it },
                    modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                    placeholder = { Text("输入处理意见或补充说明") },
                    minLines = 2,
                    maxLines = 4,
                    shape = RoundedCornerShape(8.dp),
                    colors =
                            androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = Color.Transparent,
                                    unfocusedBorderColor = Color.Transparent,
                            ),
            )
        }
        Spacer(Modifier.height(12.dp))
        WeBlockButton(
                text = "发送回复",
                onClick = {
                    vm.bridgeRespond(selectedId, reply) {
                        reply = ""
                        vm.loadBridge()
                    }
                },
                enabled = selectedId > 0 && reply.isNotBlank(),
        )
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
fun LongTailScreen(vm: AppViewModel) {
    val detail by vm.detailJson.collectAsState()
    LaunchedEffect(Unit) { vm.loadFinance() }

    com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen(title = "财务摘要") {
        WeSectionCaption("概览")
        WeCellGroup {
            WeCell(
                    title = if (detail.isBlank()) "暂无财务数据" else "财务看板已同步",
                    subtitle = financePreview(detail),
                    icon = Icons.Default.Analytics,
                    iconTint = XcagiTheme.extra.brandBlue,
                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                    showArrow = false,
                    showDivider = false,
            )
        }
        Spacer(Modifier.height(16.dp))
        WeSectionCaption("操作")
        WeCellGroup {
            WeCell(
                    title = "凭证与收支",
                    subtitle = "查看应收、应付与交易记录",
                    icon = Icons.AutoMirrored.Filled.ReceiptLong,
                    iconTint = MaterialTheme.colorScheme.secondary,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("请在电脑端打开完整财务看板") },
            )
            WeCell(
                    title = "标签打印",
                    subtitle = "打印商品标签和条码模板",
                    icon = Icons.Default.LocalPrintshop,
                    iconTint = XcagiTheme.extra.warning,
                    iconBg = XcagiTheme.extra.warning.copy(alpha = 0.12f),
                    showArrow = true,
                    showDivider = false,
                    onClick = { vm.snack("请在电脑端完成标签打印") },
            )
        }
    }
}

private fun financePreview(raw: String): String {
    if (raw.isBlank()) return "连接企业后端后显示收入、成本、毛利与应付摘要"
    return raw
            .replace("{", "")
            .replace("}", "")
            .replace("success=true,", "")
            .replace("data=", "")
            .split(",")
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .take(3)
            .joinToString(" · ")
            .take(120)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OcrScreen(vm: AppViewModel, onBack: () -> Unit) {
    WeScreen(title = "拍照识别", onBack = onBack) {
        WeSectionCaption("入口")
        WeCellGroup {
            WeCell(
                    title = "拍照识别",
                    subtitle = "调用企业端 OCR 引擎处理图片文字",
                    icon = Icons.Default.CameraAlt,
                    iconTint = XcagiTheme.extra.brandBlue,
                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("移动端拍照上传正在接入，请先使用电脑端 OCR") },
            )
            WeCell(
                    title = "从相册选择",
                    subtitle = "识别票据、表格截图与文档图片",
                    icon = Icons.Default.PhotoLibrary,
                    iconTint = MaterialTheme.colorScheme.secondary,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("移动端相册识别正在接入，请先使用电脑端 OCR") },
            )
            WeCell(
                    title = "批量识别",
                    subtitle = "完整批量处理请使用电脑端",
                    icon = Icons.AutoMirrored.Filled.InsertDriveFile,
                    iconTint = XcagiTheme.extra.warning,
                    iconBg = XcagiTheme.extra.warning.copy(alpha = 0.12f),
                    showArrow = false,
                    showDivider = false,
            )
        }
        Spacer(Modifier.height(16.dp))
        WeSectionCaption("状态")
        WeCellGroup {
            WeCell(
                    title = "企业 OCR",
                    subtitle = "等待移动端上传链路接入",
                    icon = Icons.Default.CloudDone,
                    iconTint = XcagiTheme.extra.success,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = false,
                    showDivider = false,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutScreen(
        onBack: () -> Unit,
        appConfig: com.xiuci.xcagi.mobile.core.model.AppConfigResponse? = null,
        onCheckUpdate: () -> Unit = {}
) {
    val ctx = LocalContext.current
    com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen(title = "关于", onBack = onBack) {
        Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(32.dp))
            Image(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(72.dp),
                    contentScale = ContentScale.Fit,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                    "XCAGI",
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                    "v${com.xiuci.xcagi.mobile.BuildConfig.VERSION_NAME}",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.outline
            )
        }
        Spacer(Modifier.height(24.dp))
        WeSectionCaption("信息")
        WeCellGroup {
            WeCell(
                    title = "公司",
                    subtitle = stringResource(R.string.company_name),
                    showArrow = false,
                    showDivider = true,
            )
            WeCell(
                    title = "官网",
                    subtitle = stringResource(R.string.brand_url),
                    showArrow = true,
                    showDivider = true,
                    onClick = {
                        ctx.startActivity(
                                Intent(Intent.ACTION_VIEW, Uri.parse("https://xiu-ci.com"))
                        )
                    },
            )
            WeCell(
                    title = "检查更新",
                    subtitle = "v${com.xiuci.xcagi.mobile.BuildConfig.VERSION_NAME}",
                    showArrow = true,
                    showDivider = false,
                    onClick = onCheckUpdate,
            )
        }
        Spacer(Modifier.height(16.dp))
        ComplianceFooter(appConfig)
    }
}
