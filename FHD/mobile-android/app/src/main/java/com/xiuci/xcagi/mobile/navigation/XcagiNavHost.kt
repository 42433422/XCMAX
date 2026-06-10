package com.xiuci.xcagi.mobile.navigation

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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Work
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.xiuci.xcagi.mobile.core.work.LanProbeWorker
import java.util.concurrent.TimeUnit
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.connectivity.NetworkMonitor
import com.xiuci.xcagi.mobile.feature.legal.LegalConsentScreen
import com.xiuci.xcagi.mobile.feature.modhost.ModWebViewScreen
import com.xiuci.xcagi.mobile.feature.settings.SettingsScreen
import com.xiuci.xcagi.mobile.feature.workbench.WorkbenchWebViewScreen
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavBar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBottomNavItem
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import android.content.Intent
import android.net.Uri
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@EntryPoint
@InstallIn(SingletonComponent::class)
interface NetworkEntryPoint {
    fun networkMonitor(): NetworkMonitor
}

@Composable
fun XcagiNavHost(vm: AppViewModel, pendingDeepLink: String? = null) {
    val nav = rememberNavController()
    val snack = remember { SnackbarHostState() }
    val msg by vm.message.collectAsState()
    val loggedIn by vm.isLoggedIn.collectAsState()
    val setupComplete by vm.isSetupComplete.collectAsState()
    val autoLanProbe by vm.autoLanProbe.collectAsState()
    val navReady by vm.navReady.collectAsState()
    val startRoute by vm.startRoute.collectAsState()
    val updatePrompt by vm.updatePrompt.collectAsState()
    val ctx = LocalContext.current
    val networkMonitor = androidx.compose.runtime.remember(ctx) {
        EntryPointAccessors.fromApplication(ctx.applicationContext, NetworkEntryPoint::class.java)
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
            dismissButton = if (!prompt.force) {
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
        msg?.let { snack.showSnackbar(it.text); vm.clearSnack() }
    }

    LaunchedEffect(loggedIn) {
        if (loggedIn) {
            val r = nav.currentDestination?.route
            if (r == Routes.AUTH || r == Routes.CONNECT || r == Routes.REGISTER) {
                nav.navigate(Routes.CHAT) { popUpTo(nav.graph.findStartDestination().id) { inclusive = true } }
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

    Scaffold(
        snackbarHost = { SnackbarHost(snack) },
        topBar = {
            if (!online) {
                androidx.compose.material3.Surface(color = MaterialTheme.colorScheme.errorContainer) {
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
                    items = listOf(
                        WeBottomNavItem(Routes.CHAT, "对话", Icons.Default.Chat),
                        WeBottomNavItem(Routes.WORK, "工作", Icons.Default.Work, approvalCount),
                        WeBottomNavItem(Routes.DISCOVER, "发现", Icons.Default.Explore),
                        WeBottomNavItem(Routes.PROFILE, "我的", Icons.Default.Person),
                    ),
                    currentRoute = current,
                    onSelect = { route ->
                        nav.navigate(route) {
                            popUpTo(nav.graph.findStartDestination().id) { saveState = true }
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
                        nav.navigate(Routes.CONNECT) {
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
                        vm.completeSetup()
                        nav.navigate(Routes.AUTH) { popUpTo(Routes.CONNECT) { inclusive = true } }
                    },
                    onScan = { nav.navigate(Routes.SCAN_QR) },
                    onSkipCloud = {
                        vm.skipToCloud {
                            nav.navigate(Routes.AUTH) { popUpTo(Routes.CONNECT) { inclusive = true } }
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
            composable(Routes.SETTINGS) {
                SettingsScreen(vm) { nav.popBackStack() }
            }
            composable(Routes.AUTH) {
                AuthScreen(vm, { nav.navigate(Routes.REGISTER) }, { nav.navigate(Routes.CHAT) })
            }
            composable(Routes.REGISTER) { RegisterScreen(vm) { nav.popBackStack() } }
            composable(Routes.HOME_HUB) {
                HomeHubScreen(
                    vm,
                    onChat = { nav.navigate(Routes.CHAT) },
                    onWorkbench = { nav.navigate(Routes.WORKBENCH) },
                    onConnectPc = { nav.navigate(Routes.CONNECT_PC) },
                    onModClick = { id ->
                        vm.requestModOpen(
                            id,
                            onCloud = { nav.navigate(Routes.WORKBENCH) },
                            onNative = { nav.navigate("mod/$id") },
                        )
                    },
                )
            }
            composable(Routes.WORKBENCH) {
                val access by vm.marketAccess.collectAsState()
                val refresh by vm.marketRefresh.collectAsState()
                LaunchedEffect(Unit) { vm.refreshMarketTokens() }
                WorkbenchWebViewScreen(
                    url = vm.workbenchUrl(),
                    accessToken = access,
                    refreshToken = refresh,
                    onReloadTokens = { vm.refreshMarketTokens() },
                )
            }
            composable(Routes.PROFILE) {
                ProfileScreen(
                    vm,
                    onConnectPc = { nav.navigate(Routes.CONNECT_PC) },
                    onAbout = { nav.navigate(Routes.ABOUT) },
                    onSettings = { nav.navigate(Routes.SETTINGS) },
                    onLogout = {
                        val dest = if (setupComplete) Routes.AUTH else Routes.CONNECT
                        vm.logout {
                            nav.navigate(dest) { popUpTo(0) { inclusive = true } }
                        }
                    },
                )
            }
            composable(Routes.WORK) {
                WorkScreen(
                    vm,
                    onApproval = { nav.navigate(Routes.APPROVAL) },
                    onErpTab = { tab -> nav.navigate(Routes.erpTab(tab)) },
                    onIm = { nav.navigate(Routes.IM) },
                    onBridge = { nav.navigate(Routes.BRIDGE) },
                    onLongTail = { nav.navigate(Routes.LONGTAIL) },
                    onConnectPc = { nav.navigate(Routes.CONNECT_PC) },
                )
            }
            composable(Routes.DISCOVER) {
                DiscoverScreen(
                    onWorkbench = { nav.navigate(Routes.WORKBENCH) },
                    onMods = { nav.navigate(Routes.MODS) },
                    onMarket = { nav.navigate(Routes.MARKET) },
                    onScan = { nav.navigate(Routes.SCAN_QR) },
                    onOcr = { nav.navigate(Routes.OCR) },
                )
            }
            composable(Routes.CHAT) {
                ChatScreen(
                    vm,
                    onOpenWorkbench = { nav.navigate(Routes.WORKBENCH) },
                    onOpenMod = { id ->
                        vm.requestModOpen(
                            id,
                            onCloud = { nav.navigate(Routes.WORKBENCH) },
                            onNative = { nav.navigate("mod/$id") },
                        )
                    },
                    onOpenOcr = { nav.navigate(Routes.OCR) },
                )
            }
            composable(Routes.APPROVAL) {
                ApprovalListScreen(
                    vm,
                    onItemClick = { id -> nav.navigate("approval/$id") },
                )
            }
            composable(Routes.APPROVAL_DETAIL, arguments = listOf(navArgument("id") { type = NavType.IntType })) { e ->
                ApprovalDetailScreen(vm, e.arguments?.getInt("id") ?: 0) { nav.popBackStack() }
            }
            composable(Routes.IM) {
                ImMessengerScreen(vm) { nav.popBackStack() }
            }
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
                ListScreen("MODstore", vm, vm::loadMarket, null) { nav.popBackStack() }
            }
            composable(Routes.MODS) {
                ListScreen("Mod", vm, vm::loadMods, { id -> nav.navigate("mod/$id") }) { nav.popBackStack() }
            }
            composable(Routes.MOD_WEB, arguments = listOf(navArgument("modId") { type = NavType.StringType })) { e ->
                val modId = e.arguments?.getString("modId") ?: ""
                var bearer by remember { mutableStateOf("") }
                var url by remember { mutableStateOf("") }
                val access by vm.marketAccess.collectAsState()
                val refresh by vm.marketRefresh.collectAsState()
                LaunchedEffect(modId) {
                    bearer = vm.bearerToken()
                    url = vm.modUrl(modId)
                }
                if (url.isNotBlank()) {
                    ModWebViewScreen(url, bearer, access, refresh)
                }
            }
            composable(Routes.LONGTAIL) { LongTailScreen(vm) }
            composable(Routes.ABOUT) { AboutScreen { nav.popBackStack() } }
        }
    }
}

@Composable
fun RegisterScreen(vm: AppViewModel, onBack: () -> Unit) {
    var u by remember { mutableStateOf("") }
    var p by remember { mutableStateOf("") }
    var e by remember { mutableStateOf("") }
    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("注册")
        OutlinedTextField(u, { u = it }, Modifier.fillMaxWidth(), label = { Text("用户名") })
        OutlinedTextField(p, { p = it }, Modifier.fillMaxWidth(), label = { Text("密码") })
        OutlinedTextField(e, { e = it }, Modifier.fillMaxWidth(), label = { Text("邮箱") })
        Button({ vm.register(u, p, e) { if (it) onBack() } }, Modifier.fillMaxWidth()) { Text("提交") }
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
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Service Bridge") })
        LazyColumn(Modifier.weight(1f).padding(12.dp)) {
            items(items) { item ->
                Card(Modifier.fillMaxWidth().padding(4.dp).clickable { selectedId = item.id.toIntOrNull() ?: 0 }) {
                    Text("${item.title} [${item.subtitle}]", Modifier.padding(12.dp))
                }
            }
        }
        OutlinedTextField(reply, { reply = it }, Modifier.fillMaxWidth().padding(12.dp), label = { Text("回复") })
        Button(
            {
                if (selectedId > 0 && reply.isNotBlank()) {
                    vm.bridgeRespond(selectedId, reply) { vm.loadBridge() }
                }
            },
            Modifier.padding(12.dp),
        ) { Text("回复 #$selectedId") }
    }
}

@Composable
fun LongTailScreen(vm: AppViewModel) {
    val detail by vm.detailJson.collectAsState()
    LaunchedEffect(Unit) { vm.loadFinance() }
    Column(Modifier.padding(20.dp)) {
        Text("财务摘要", style = MaterialTheme.typography.titleLarge)
        Text(detail)
        Spacer(Modifier.height(16.dp))
        Text("标签打印 / 工作流可视化请在 PC 端操作。", style = MaterialTheme.typography.bodyMedium)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OcrScreen(onBack: () -> Unit) {
    WeScreen(title = "OCR 拍照识别", onBack = onBack) {
        Text(
            "请在已连接电脑的局域网模式下，通过电脑端 FHD 使用完整 OCR 与批量识别；手机端将在后续版本接入相机上传。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
        Spacer(Modifier.height(12.dp))
        Text(
            "工作台内部分 Mod 已支持图片上传与识别，可直接在「发现 → 工作台」使用。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutScreen(onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("关于") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, null) } },
        )
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.company_name), style = MaterialTheme.typography.titleLarge)
            Text(stringResource(R.string.company_icp))
            Text(stringResource(R.string.brand_url))
        }
    }
}
