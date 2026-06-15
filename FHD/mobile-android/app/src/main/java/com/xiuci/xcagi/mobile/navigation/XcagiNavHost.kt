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
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Work
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
import com.xiuci.xcagi.mobile.feature.workbench.WorkbenchWebViewScreen
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.SnackData
import com.xiuci.xcagi.mobile.ui.components.mobile.SnackType
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavBar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavItem
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeFadeTransition
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSnackBar
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
fun XcagiNavHost(vm: AppViewModel, pendingDeepLink: String? = null) {
    val nav = rememberNavController()
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

    LaunchedEffect(pendingDeepLink, loggedIn) {
        if (loggedIn && !pendingDeepLink.isNullOrBlank()) {
            vm.handleDeepLink(pendingDeepLink) { route ->
                nav.navigate(route) { launchSingleTop = true }
            }
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

    val approvalCount by vm.approvalPendingCount.collectAsState()

    val backStack by nav.currentBackStackEntryAsState()
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
                                                        "对话",
                                                        Icons.Default.Chat
                                                ),
                                                WeBottomNavItem(
                                                        Routes.WORK,
                                                        "生态",
                                                        Icons.Default.Work,
                                                        approvalCount
                                                ),
                                                WeBottomNavItem(
                                                        Routes.DISCOVER,
                                                        "发现",
                                                        Icons.Default.Explore
                                                ),
                                                WeBottomNavItem(
                                                        Routes.PROFILE,
                                                        "我的",
                                                        Icons.Default.Person
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
                    AuthScreen(vm, { nav.navigate(Routes.REGISTER) }, { nav.navigate(Routes.CHAT) })
                }
                composable(Routes.AUTH_AUTO_LOGIN) {
                    // 自动登录路由：显示登录页同时自动尝试用保存的凭证登录
                    AuthScreen(vm, { nav.navigate(Routes.REGISTER) }, { nav.navigate(Routes.CHAT) })
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
                            onWorkbench = { nav.navigate(Routes.WORKBENCH) },
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
                    WorkScreen(
                            vm,
                            onConnectPc = { nav.navigate(Routes.CONNECT_PC) },
                            onModMenuClick = { menu ->
                                // 已知 Mod 的原生路由映射
                                when (menu.id) {
                                    "approval", "approvals" -> nav.navigate(Routes.APPROVAL)
                                    "erp", "customers" -> nav.navigate("${Routes.ERP}?tab=0")
                                    "shipments" -> nav.navigate("${Routes.ERP}?tab=1")
                                    "inventory" -> nav.navigate("${Routes.ERP}?tab=2")
                                    "im" -> nav.navigate(Routes.IM)
                                    "bridge", "service-bridge" -> nav.navigate(Routes.BRIDGE)
                                    "finance", "long-tail" -> nav.navigate(Routes.LONGTAIL)
                                    else -> {
                                        // 未知 Mod 走 WebView
                                        nav.navigate("mod/${menu.id}")
                                    }
                                }
                            },
                            onNavigateToApp = { route -> nav.navigate(route) },
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
                            onWorkbench = { nav.navigate(Routes.WORKBENCH) },
                    )
                }
                composable(
                        Routes.CHAT,
                        enterTransition = { WeFadeTransition.enter() },
                        exitTransition = { WeFadeTransition.exit() },
                        popEnterTransition = { WeFadeTransition.enter() },
                        popExitTransition = { WeFadeTransition.exit() },
                ) {
                    ChatScreen(
                            vm,
                            onOpenMod = { id ->
                                vm.requestModOpen(
                                        id,
                                        onCloud = { vm.snack("该功能需在电脑端使用") },
                                        onNative = { nav.navigate("mod/$id") },
                                )
                            },
                            onOpenOcr = { nav.navigate(Routes.OCR) },
                            onNavigateToEmployees = { nav.navigate(Routes.AI_EMPLOYEES) },
                    )
                }
                composable(Routes.WORKBENCH) {
                    val access by vm.marketAccess.collectAsState()
                    val refresh by vm.marketRefresh.collectAsState()
                    val fhdAccess by vm.fhdAccess.collectAsState()
                    WorkbenchWebViewScreen(
                            url = vm.workbenchUrl(),
                            accessToken = access,
                            refreshToken = refresh,
                            fhdAccessToken = fhdAccess,
                            onReloadTokens = { vm.refreshMarketTokens() },
                    )
                }
                composable(Routes.AI_EMPLOYEES) {
                    AiEmployeeListScreen(
                            vm = vm,
                            onBack = { nav.popBackStack() },
                            onSelect = { name ->
                                nav.popBackStack()
                                vm.snack("已选择：$name")
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
                composable(Routes.OCR) { OcrScreen(onBack = { nav.popBackStack() }) }
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
                color = MobileTokens.textPrimary,
        )
        Spacer(Modifier.height(6.dp))
        Text(
                "注册 XCAGI 企业平台账号",
                fontSize = 14.sp,
                color = MobileTokens.textTertiary,
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
                                    if (agreed) MobileTokens.brandBlue else MobileTokens.divider
                            ),
                    contentAlignment = Alignment.Center,
            ) {
                if (agreed)
                        Icon(Icons.Default.Check, null, Modifier.size(12.dp), tint = Color.White)
            }
            Spacer(Modifier.size(6.dp))
            Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(color = MobileTokens.textTertiary, fontSize = 12.sp)) {
                            append("我已阅读并同意")
                        }
                        withStyle(
                                SpanStyle(
                                        color = MobileTokens.brandBlue,
                                        fontSize = 12.sp,
                                        textDecoration = TextDecoration.Underline
                                )
                        ) { append("《用户协议》") }
                        withStyle(SpanStyle(color = MobileTokens.textTertiary, fontSize = 12.sp)) {
                            append("和")
                        }
                        withStyle(
                                SpanStyle(
                                        color = MobileTokens.brandBlue,
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
                        .background(if (canSubmit) MobileTokens.brandBlue else MobileTokens.divider)
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
        Column(
                Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
        ) { items.forEach { item -> MarketModCard(item = item, onUse = { onUse(item.id) }) } }
    }
}

@Composable
private fun MarketModCard(item: ListItem, onUse: () -> Unit) {
    Row(
            Modifier.fillMaxWidth()
                    .clip(MobileTokens.cornerCard)
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
                Modifier.size(44.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(MobileTokens.iconBgOrange),
                contentAlignment = Alignment.Center,
        ) {
            Icon(
                    Icons.Default.Extension,
                    contentDescription = null,
                    tint = MobileTokens.iconFgOrange
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
        Button(onClick = onUse, shape = MobileTokens.cornerCard) { Text("使用") }
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BridgeScreen(vm: AppViewModel) {
    val items by vm.items.collectAsState()
    var reply by remember { mutableStateOf("") }
    var selectedId by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { vm.loadBridge() }

    com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen(
            title = "Service Bridge",
            onBack = { /* handled by WeScreen */},
    ) {
        LazyColumn(Modifier.weight(1f)) {
            item { WeSectionCaption("工单列表") }
            item {
                WeCellGroup {
                    items.forEachIndexed { idx, item ->
                        WeCell(
                                title = item.title,
                                subtitle = item.subtitle.ifBlank { "暂无描述" },
                                icon = Icons.Default.Extension,
                                iconTint = MobileTokens.iconFgBlue,
                                iconBg = MobileTokens.iconBgBlue,
                                showArrow = true,
                                showDivider = idx < items.lastIndex,
                                onClick = { selectedId = item.id.toIntOrNull() ?: 0 },
                        )
                    }
                }
            }
        }

        if (selectedId > 0) {
            Spacer(Modifier.height(8.dp))
            Text(
                    "回复工单 #$selectedId",
                    fontSize = 13.sp,
                    color = MobileTokens.textTertiary,
                    modifier = Modifier.padding(horizontal = 16.dp)
            )
        }
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
                reply,
                { reply = it },
                Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                label = { Text("输入回复内容") },
                shape = RoundedCornerShape(8.dp),
        )
        Spacer(Modifier.height(8.dp))
        Box(
                Modifier.fillMaxWidth()
                        .height(44.dp)
                        .padding(horizontal = 16.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(
                                if (selectedId > 0 && reply.isNotBlank()) MobileTokens.brandBlue
                                else MobileTokens.divider
                        )
                        .clickable(enabled = selectedId > 0 && reply.isNotBlank()) {
                            vm.bridgeRespond(selectedId, reply) { vm.loadBridge() }
                        },
                contentAlignment = Alignment.Center,
        ) { Text("发送回复", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Medium) }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
fun LongTailScreen(vm: AppViewModel) {
    val detail by vm.detailJson.collectAsState()
    LaunchedEffect(Unit) { vm.loadFinance() }

    com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen(title = "财务摘要") {
        WeSectionCaption("财务概览")
        WeCellGroup {
            WeCell(
                    title = "财务数据",
                    subtitle = if (detail.isNotBlank()) detail.take(100) else "暂无数据",
                    icon = Icons.Default.Extension,
                    iconTint = MobileTokens.iconFgGreen,
                    iconBg = MobileTokens.iconBgGreen,
                    showArrow = false,
                    showDivider = false,
            )
        }
        Spacer(Modifier.height(16.dp))
        WeSectionCaption("快捷操作")
        WeCellGroup {
            WeCell(
                    title = "标签打印",
                    subtitle = "打印商品标签和条码",
                    icon = Icons.Default.Extension,
                    iconTint = MobileTokens.iconFgOrange,
                    iconBg = MobileTokens.iconBgOrange,
                    showArrow = true,
                    showDivider = false,
                    onClick = { vm.snack("标签打印功能即将上线") },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OcrScreen(onBack: () -> Unit) {
    WeScreen(title = "OCR 拍照识别", onBack = onBack) {
        Column(
                Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                    Modifier.size(64.dp)
                            .clip(RoundedCornerShape(16.dp))
                            .background(MobileTokens.iconBgCyan),
                    contentAlignment = Alignment.Center,
            ) {
                Icon(
                        Icons.Default.Extension,
                        null,
                        tint = MobileTokens.iconFgCyan,
                        modifier = Modifier.size(32.dp)
                )
            }
            Spacer(Modifier.height(16.dp))
            Text(
                    "OCR 拍照识别",
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Medium,
                    color = MobileTokens.textPrimary
            )
            Spacer(Modifier.height(8.dp))
            Text(
                    "手机端即将支持相机拍照识别，当前可在电脑端使用完整 OCR 与批量识别功能",
                    fontSize = 14.sp,
                    color = MobileTokens.textTertiary,
                    textAlign = TextAlign.Center,
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
                    color = MobileTokens.textPrimary
            )
            Text(
                    "v${com.xiuci.xcagi.mobile.BuildConfig.VERSION_NAME}",
                    fontSize = 13.sp,
                    color = MobileTokens.textTertiary
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
