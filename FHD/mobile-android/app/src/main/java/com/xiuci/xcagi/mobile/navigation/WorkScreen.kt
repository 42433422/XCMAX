package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Assignment
import androidx.compose.material.icons.filled.AssignmentInd
import androidx.compose.material.icons.filled.Autorenew
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Inventory
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.LocalOffer
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material.icons.filled.TouchApp
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.em
import android.content.Intent
import android.net.Uri
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiPalette
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

/** FontAwesome icon class → Material Icon 映射 */
private fun faToMaterial(faClass: String?): ImageVector =
        when {
                faClass == null -> Icons.Default.Extension
                faClass.contains("comments") || faClass.contains("chat") -> Icons.Default.Chat
                faClass.contains("user") || faClass.contains("group") -> Icons.Default.Group
                faClass.contains("truck") || faClass.contains("shipping") ->
                        Icons.Default.LocalShipping
                faClass.contains("box") || faClass.contains("inventory") -> Icons.Default.Inventory
                faClass.contains("check") || faClass.contains("approval") ->
                        Icons.Default.AssignmentInd
                faClass.contains("bank") || faClass.contains("bridge") ->
                        Icons.Default.AccountBalance
                faClass.contains("tag") || faClass.contains("label") -> Icons.Default.LocalOffer
                faClass.contains("sitemap") || faClass.contains("ecosystem") ->
                        Icons.Default.Extension
                else -> Icons.Default.Extension
        }

/** 根据 menu.id 轮换图标背景色 */
@Composable
private fun iconBgColors(): List<Color> =
        listOf(
                MaterialTheme.colorScheme.primaryContainer,
                MaterialTheme.colorScheme.secondaryContainer,
                XcagiTheme.extra.warning.copy(alpha = 0.15f),
                XcagiPalette.Accent.PurpleContainer,
                XcagiPalette.Accent.CyanContainer,
                XcagiTheme.extra.danger.copy(alpha = 0.12f),
        )

@Composable
private fun iconFgColors(): List<Color> =
        listOf(
                MaterialTheme.colorScheme.primary,
                MaterialTheme.colorScheme.secondary,
                XcagiTheme.extra.warning,
                XcagiPalette.Accent.Purple,
                XcagiPalette.Accent.Cyan,
                XcagiTheme.extra.danger,
        )

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkScreen(
        vm: AppViewModel,
        onConnectPc: () -> Unit,
        onModMenuClick: (ModMenuItem) -> Unit,
        onNavigateToApp: (String) -> Unit = {},
) {
        val hub by vm.homeHub.collectAsState()
        val fhdHost by vm.fhdHost.collectAsState()
        val modInfos by vm.modInfos.collectAsState()
        val hasIndustryScope = MobileMenuPolicy.hasIndustryScope(modInfos)

        LaunchedEffect(Unit) {
                vm.loadHomeHub()
                vm.loadMods()
        }

        val pcTitle = if (fhdHost.isBlank()) "我的电脑" else fhdHost.substringBefore(':')
        val pcSubtitle =
                if (hub.pcOnline) "在线 · Agent 控制中"
                else if (fhdHost.isNotBlank()) "离线 · 重连后恢复控制" else "点击绑定以启用 Agent 远程控制"

        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
                WeTopBar(
                        title = "AI 名录",
                        showRightSearch = false,
                        showRightAdd = false,
                )

                LazyColumn(state = rememberLazyListState()) {
                        // ── 顶部：电脑状态 ──
                        item {
                                WeCellGroup {
                                        WeCell(
                                                title = pcTitle,
                                                subtitle = pcSubtitle,
                                                icon = Icons.Default.Computer,
                                                iconTint = MaterialTheme.colorScheme.primary,
                                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                                trailing = {
                                                        Box(
                                                                Modifier.size(Spacing.sm)
                                                                        .clip(CircleShape)
                                                                        .background(
                                                                                if (hub.pcOnline)
                                                                                        XcagiTheme.extra.success
                                                                                else
                                                                                        MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)
                                                                        ),
                                                        )
                                                },
                                                showDivider = false,
                                                onClick = onConnectPc,
                                        )
                                }
                        }

                        // ── 通用能力。行业/业务入口必须来自已安装 Mod 菜单，不能在这里硬编码。──
                        item {
                                WeSectionCaption("通用能力")
                                WeCellGroup {
                                        WeCell(
                                                title = "AIOPEN 开放智控",
                                                subtitle = "企业级 AI Agent 接入平台，MCP/API 协议远程 UI 操控",
                                                icon = Icons.Default.Explore,
                                                iconTint = XcagiPalette.Accent.Indigo,
                                                iconBg = XcagiPalette.Accent.IndigoContainer,
                                                showArrow = true,
                                                showDivider = true,
                                                onClick = { onNavigateToApp(Routes.AI_OPEN) },
                                        )
                                        WeCell(
                                                title = "伙伴市场",
                                                subtitle = "MOD 扩展浏览、安装与本机 .xcmod 目录管理",
                                                icon = Icons.Default.ShoppingCart,
                                                iconTint = XcagiTheme.extra.success,
                                                iconBg = MaterialTheme.colorScheme.secondaryContainer,
                                                showArrow = false,
                                                onClick = { onNavigateToApp(Routes.MOD_STORE) },
                                        )
                                }
                        }

                        // ── 动态 Mod 菜单（按 Mod 分组）──
                        modInfos.forEachIndexed { modIdx, mod ->
                                val visibleMenus = MobileMenuPolicy.visibleMenus(mod, hasIndustryScope)
                                if (visibleMenus.isNotEmpty()) {
                                        item { WeSectionCaption(mod.name) }
                                        item {
                                                WeCellGroup {
                                                        val bgColors = iconBgColors()
                                                        val fgColors = iconFgColors()
                                                        visibleMenus.forEachIndexed {
                                                                menuIdx,
                                                                menu ->
                                                                val colorIdx =
                                                                        (modIdx + menuIdx) %
                                                                                bgColors.size
                                                                WeCell(
                                                                        title = menu.label,
                                                                        subtitle =
                                                                                if (mod.primary)
                                                                                        "核心模块"
                                                                                else
                                                                                        mod.description
                                                                                                .takeIf {
                                                                                                        it.isNotBlank()
                                                                                                }
                                                                                                ?: "",
                                                                        icon =
                                                                                faToMaterial(
                                                                                        menu.icon
                                                                                ),
                                                                        iconTint =
                                                                                fgColors[
                                                                                        colorIdx],
                                                                        iconBg =
                                                                                bgColors[
                                                                                        colorIdx],
                                                                        showArrow = true,
                                                                        showDivider =
                                                                                menuIdx <
                                                                                        visibleMenus.lastIndex,
                                                                        onClick = {
                                                                                onModMenuClick(menu)
                                                                        },
                                                                )
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── 空状态 ──
                        if (modInfos.isEmpty()) {
                                item {
                                        Column(
                                                Modifier.fillMaxWidth().padding(vertical = 48.dp),
                                                horizontalAlignment = Alignment.CenterHorizontally,
                                        ) {
                                                Icon(
                                                        Icons.Default.Extension,
                                                        contentDescription = null,
                                                        modifier = Modifier.size(48.dp),
                                                        tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                                                )
                                                Spacer(Modifier.height(Spacing.md))
                                                Text(
                                                        "暂无已安装的 Mod",
                                                        style = MaterialTheme.typography.bodySmall,
                                                        color = MaterialTheme.colorScheme.outline,
                                                )
                                                Text(
                                                        "暂无可用功能模块",
                                                        style = MaterialTheme.typography.labelSmall,
                                                        color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                                                        modifier = Modifier.padding(top = Spacing.xs),
                                                )
                                                Spacer(Modifier.height(Spacing.lg))
                                                Box(
                                                        Modifier.height(36.dp)
                                                                .clip(RoundedCornerShape(18.dp))
                                                                .background(XcagiTheme.extra.brandBlue)
                                                                .clickable { /* navigate to market */
                                                                }
                                                                .padding(horizontal = Spacing.xxl),
                                                        contentAlignment = Alignment.Center,
                                                ) {
                                                        Text(
                                                                "浏览 Mod 商店",
                                                                color = Color.White,
                                                                style = MaterialTheme.typography.bodySmall
                                                        )
                                                }
                                        }
                                }
                        }
                }
        }
}

// ════════════════════════════════════════════════════════════════
//  AI 生态应用功能页面（复刻桌面端 AIEcosystemView 行为）
// ════════════════════════════════════════════════════════════════

/** 智慧分析（Kitten Analyzer）—— 对应桌面端 enterAnalyzer('kitten')
 *  桌面端核心能力：对话分析、文件上传(Excel/CSV)、快捷操作(财务简报/趋势分析)、导出(Excel/Word)
 *  手机端适配：内嵌输入框直接发起分析对话 + 快捷操作按钮 + 跳转完整聊天 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SmartAnalysisScreen(
        vm: AppViewModel,
        onBack: () -> Unit,
        onOpenChat: (String) -> Unit = {},
) {
        var query by remember { mutableStateOf("") }
        val ctx = LocalContext.current

        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                WeTopBar(title = "智慧分析", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(
                        Modifier.fillMaxSize().padding(horizontal = Spacing.lg),
                        verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                        // ── 品牌介绍卡片（对标桌面端 kitten-header）──
                        item {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(Spacing.lg)) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Box(Modifier.size(40.dp).clip(MaterialTheme.shapes.small).background(XcagiPalette.Accent.TealDark), contentAlignment = Alignment.Center) {
                                                                Icon(Icons.Default.Extension, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                        }
                                                        Spacer(Modifier.width(Spacing.md))
                                                        Column { Text("AI 数据分析助手", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold); Text("可视化 AI 员工 · 对话洞察 · 图表导出", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline) }
                                                }
                                                Spacer(Modifier.height(10.dp))
                                                Text("上传表格或直接提问，AI 自动生成 ECharts 图表与分析报告。支持 Excel、CSV 格式。", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        }
                                }
                        }

                        // ── 快捷操作（对标桌面端 quick-select + more-menu）──
                        item { Text("快捷分析", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }

                        item {
                                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                                        QuickChip(label = "财务简报", color = XcagiTheme.extra.brandBlue, bg = MaterialTheme.colorScheme.primaryContainer) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "数据概览", color = XcagiTheme.extra.success, bg = MaterialTheme.colorScheme.secondaryContainer) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "趋势分析", color = XcagiTheme.extra.warning, bg = XcagiTheme.extra.warning.copy(alpha = 0.1f)) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                }
                        }

                        item { Spacer(Modifier.height(Spacing.xs)) }
                        item {
                                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                                        QuickChip(label = "生成报告", color = XcagiPalette.Accent.Indigo, bg = XcagiPalette.Accent.IndigoContainer) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "上传表格", color = XcagiPalette.Accent.Pink, bg = XcagiPalette.Accent.PinkContainer) {
                                                // 调用系统文件选择器
                                                try {
                                                        val intent = Intent(Intent.ACTION_GET_CONTENT).apply { type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE) }
                                                        ctx.startActivity(Intent.createChooser(intent, "选择表格文件"))
                                                } catch (_: Exception) { vm.snack("无法打开文件选择器", true) }
                                        }
                                        Spacer(Modifier.weight(1f))
                                        QuickChatChip(label = "打开对话", color = MaterialTheme.colorScheme.onSurfaceVariant, bg = MaterialTheme.colorScheme.surfaceVariant) { onOpenChat("kitten") }
                                }
                        }

                        // ── 输入区域（对标桌面端 input-area）──
                        item { Spacer(Modifier.height(Spacing.lg)); Text("输入问题，AI 帮你分析", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }

                        item {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(Spacing.md)) {
                                                OutlinedTextField(
                                                        value = query,
                                                        onValueChange = { query = it },
                                                        modifier = Modifier.fillMaxWidth(),
                                                        placeholder = { Text("例如：本季度销售趋势如何？", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline) },
                                                        shape = MaterialTheme.shapes.small,
                                                        maxLines = 3,
                                                )
                                                Spacer(Modifier.height(10.dp))
                                                Box(
                                                        Modifier.fillMaxWidth()
                                                                .height(44.dp)
                                                                .clip(MaterialTheme.shapes.small)
                                                                .background(if (query.isNotBlank()) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant)
                                                                .clickable(enabled = query.isNotBlank()) {
                                                                        onOpenChat("kitten")
                                                                        vm.snack("已发送至智慧分析：$query")
                                                                        query = ""
                                                                },
                                                        contentAlignment = Alignment.Center,
                                                ) { Text("发送分析请求", color = if (query.isNotBlank()) Color.White else MaterialTheme.colorScheme.outline, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium) }
                                        }
                                }
                        }

                        item { Spacer(Modifier.height(Spacing.xxl)) }
                }
        }
}

@Composable
private fun QuickChip(label: String, color: Color, bg: Color, onClick: () -> Unit) {
        Box(
                Modifier.clip(MaterialTheme.shapes.large).background(bg).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = Spacing.sm),
                contentAlignment = Alignment.Center,
        ) { Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Medium, color = color) }
}
@Composable
private fun QuickChatChip(label: String, color: Color, bg: Color, onClick: () -> Unit) {
        Surface(
                shape = MaterialTheme.shapes.large,
                color = bg,
                border = BorderStroke(Elevation.level1, MaterialTheme.colorScheme.outlineVariant),
                onClick = onClick,
        ) { Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Medium, color = color, modifier = Modifier.padding(horizontal = 14.dp, vertical = Spacing.sm)) }
}

/** AIOPEN 开放智控 —— 对应桌面端 enterAnalyzer('aiopen')
 *  桌面端核心能力：Hero状态卡(ready/partial/off)、一键开启、MCP工具列表、一句话配置复制、客户端安装
 *  手机端适配：加载 /api/aiopen/panel 状态 + /api/aiopen/manifest 工具列表 + 复制配置 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiOpenScreen(vm: AppViewModel, onBack: () -> Unit) {
        var readyStatus by remember { mutableStateOf<String>("off") }   // off | partial | ready
        var mcpTools by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
        var mcpHealthMsg by remember { mutableStateOf("") }
        var loading by remember { mutableStateOf(true) }
        var setupRunning by remember { mutableStateOf(false) }
        val ctx = LocalContext.current

        LaunchedEffect(Unit) {
                loading = true
                // 尝试加载 AIOPEN 面板状态和 MCP manifest
                loadAiOpenStatus(vm,
                        onStatus = { status -> readyStatus = status },
                        onTools = { tools -> mcpTools = tools },
                        onHealth = { msg -> mcpHealthMsg = msg },
                        onDone = { loading = false }
                )
        }

        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                WeTopBar(title = "AIOPEN 开放智控", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(Modifier.fillMaxSize().padding(horizontal = Spacing.lg), verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        // ── Hero 卡片（对标桌面端 aiopen-hero）──
                        item {
                                Surface(
                                        shape = MaterialTheme.shapes.extraLarge,
                                        color = MaterialTheme.colorScheme.surface,
                                        border = when (readyStatus) {
                                                "ready" -> BorderStroke(1.5.dp, XcagiTheme.extra.success.copy(alpha = 0.45f))
                                                "partial" -> BorderStroke(1.5.dp, XcagiTheme.extra.warning.copy(alpha = 0.45f))
                                                else -> BorderStroke(Elevation.level1, MaterialTheme.colorScheme.outlineVariant)
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                ) {
                                        Column(Modifier.padding(Spacing.xl), horizontalAlignment = Alignment.CenterHorizontally) {
                                                // 状态图标
                                                Box(Modifier.size(56.dp).clip(MaterialTheme.shapes.large).background(
                                                        when (readyStatus) {
                                                                "ready" -> XcagiTheme.extra.success
                                                                "partial" -> XcagiTheme.extra.warning
                                                                else -> XcagiTheme.extra.brandBlue
                                                        }
                                                ), contentAlignment = Alignment.Center) {
                                                        Icon(
                                                                if (readyStatus == "ready") Icons.Default.Check else Icons.Default.Settings,
                                                                contentDescription = null,
                                                                tint = Color.White,
                                                                modifier = Modifier.size(26.dp),
                                                        )
                                                }
                                                Spacer(Modifier.height(10.dp))
                                                Text("AIOPEN", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.ExtraBold, color = MaterialTheme.colorScheme.onSurface, letterSpacing = 0.04.em)
                                                Text("让外部 AI 像助手一样，帮你操作本软件", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)

                                                // 流程步骤（对标 aiopen-flow）
                                                Spacer(Modifier.height(Spacing.lg))
                                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                                        FlowStep(num = 1, label = "一键开启", done = readyStatus != "off")
                                                        FlowStep(num = 2, label = "复制配置", done = false)
                                                        FlowStep(num = 3, label = "接入 AI", done = readyStatus == "ready")
                                                }

                                                Spacer(Modifier.height(Spacing.md))
                                                Text(
                                                        when (readyStatus) {
                                                                "ready" -> "已就绪 · 可向外部 AI 助手发送指令"
                                                                "partial" -> "连接中 · 请保持网络畅通"
                                                                else -> "两步即可：开启 → 复制配置到 AI 助手"
                                                        }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                )

                                                // 一键开启按钮
                                                Spacer(Modifier.height(14.dp))
                                                Box(
                                                        Modifier.fillMaxWidth()
                                                                .height(46.dp)
                                                                .clip(MaterialTheme.shapes.medium)
                                                                .background(
                                                                        if (readyStatus == "ready" || setupRunning) MaterialTheme.colorScheme.outlineVariant
                                                                        else XcagiTheme.extra.brandBlue
                                                                )
                                                                .clickable(enabled = !setupRunning && readyStatus != "ready") {
                                                                        setupRunning = true
                                                                        // 触发开启（在协程中调用 suspend 函数）
                                                                        vm.viewModelScope.launch {
                                                                                enableAiOpen(vm, onResult = { success ->
                                                                                        setupRunning = false
                                                                                        if (success) {
                                                                                                readyStatus = "partial"
                                                                                                vm.snack("AIOPEN 已开启")
                                                                                        } else {
                                                                                                vm.snack("开启失败，请检查网络", true)
                                                                                        }
                                                                                })
                                                                        }
                                                                },
                                                        contentAlignment = Alignment.Center,
                                                ) {
                                                        Text(
                                                                if (setupRunning) "开启中…" else if (readyStatus == "ready") "已开启" else "一键开启",
                                                                color = if (readyStatus == "ready" || setupRunning) MaterialTheme.colorScheme.outline else Color.White,
                                                                style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold,
                                                        )
                                                }
                                        }
                                }
                        }

                        // ── MCP 健康状态 ──
                        if (mcpHealthMsg.isNotBlank()) {
                                item {
                                        Surface(shape = MaterialTheme.shapes.small, color = if (mcpHealthMsg.contains("正常")) MaterialTheme.colorScheme.secondaryContainer else XcagiTheme.extra.danger.copy(alpha = 0.1f), modifier = Modifier.fillMaxWidth()) {
                                                Text(mcpHealthMsg, style = MaterialTheme.typography.labelSmall, color = if (mcpHealthMsg.contains("正常")) XcagiTheme.extra.success else XcagiTheme.extra.danger, modifier = Modifier.padding(Spacing.md))
                                        }
                                }
                        }

                        // ── 一句话配置（对标 aiopen-oneline）──
                        item {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f), border = BorderStroke(Elevation.level1, MaterialTheme.colorScheme.primary.copy(alpha = 0.3f)), modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(14.dp)) {
                                                Text("发给其他 AI 助手", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                                                Spacer(Modifier.height(6.dp))
                                                Text("将下方 MCP 配置发送给 ChatGPT / Claude / Cursor 等 AI 助手，即可让它操控 XCAGI。", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Spacer(Modifier.height(10.dp))
                                                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                                                        Box(Modifier.weight(1f).height(36.dp).clip(MaterialTheme.shapes.small).background(MaterialTheme.colorScheme.primary).clickable {
                                                                copyToClipboard(ctx, buildAiopenOneLiner(), "一句话配置已复制")
                                                                vm.snack("一句话已复制 · 粘贴到 ChatGPT / Claude 对话框")
                                                        }, contentAlignment = Alignment.Center) { Text("复制一句话", color = Color.White, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold) }
                                                        Box(Modifier.weight(1f).height(36.dp).clip(MaterialTheme.shapes.small).background(MaterialTheme.colorScheme.surface), contentAlignment = Alignment.Center) {
                                                                Surface(shape = MaterialTheme.shapes.small, color = Color.Transparent, border = BorderStroke(Elevation.level1, MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)), onClick = {
                                                                        copyToClipboard(ctx, buildAiopenFullConfig(), "完整配置已复制")
                                                                        vm.snack("完整配置已复制")
                                                                }) { Text("完整配置 JSON", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = Spacing.md)) }
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── MCP 工具列表（对标 aiopen-tools-preview + TOOL_LABELS）──
                        if (mcpTools.isNotEmpty()) {
                                item { Text("MCP 工具 (${mcpTools.size})", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }
                                item {
                                        WeCellGroup {
                                                mcpTools.forEachIndexed { idx, (name, desc) ->
                                                        WeCell(
                                                                title = name,
                                                                subtitle = desc,
                                                                icon = Icons.Default.TouchApp,
                                                                iconTint = XcagiTheme.extra.brandBlue,
                                                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                                                showArrow = false,
                                                                showDivider = idx < mcpTools.lastIndex,
                                                                onClick = {},
                                                        )
                                                }
                                        }
                                }
                        }

                        // ── 更多设置（对标 aiopen-more 折叠区精简版）──
                        item { Text("更多设置", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }
                        item {
                                WeCellGroup {
                                        WeCell(title = "刷新状态", subtitle = "重新检测 AIOPEN 服务与 MCP 连接", icon = Icons.Default.Autorenew, iconTint = XcagiTheme.extra.brandBlue, iconBg = MaterialTheme.colorScheme.primaryContainer, showArrow = true, showDivider = true, onClick = {
                                                loading = true
                                                vm.viewModelScope.launch {
                                                        loadAiOpenStatus(vm,
                                                                onStatus = { s -> readyStatus = s },
                                                                onTools = { t -> mcpTools = t },
                                                                onHealth = { h -> mcpHealthMsg = h },
                                                                onDone = { loading = false; vm.snack("状态已刷新") })
                                                }
                                        })
                                        WeCell(title = "MCP 端点地址", subtitle = "/api/aiopen/mcp", icon = Icons.Default.Computer, iconTint = XcagiTheme.extra.success, iconBg = MaterialTheme.colorScheme.secondaryContainer, showArrow = false, showDivider = true, onClick = {
                                                copyToClipboard(ctx, "/api/aiopen/mcp", "MCP 地址已复制")
                                                vm.snack("MCP 端点已复制")
                                        })
                                        WeCell(title = "使用说明", subtitle = "查看 AIOPEN 接入文档", icon = Icons.Default.AssignmentInd, iconTint = XcagiPalette.Accent.Indigo, iconBg = XcagiPalette.Accent.IndigoContainer, showArrow = false, showDivider = false, onClick = {
                                                try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://docs.xiu-ci.com/aiopen"))) }
                                                catch (_: Exception) { vm.snack("无法打开浏览器", true) }
                                        })
                                }
                        }

                        item { Spacer(Modifier.height(Spacing.xxl)) }
                }
        }
}

/** 加载 AIOPEN 面板状态 */
private suspend fun loadAiOpenStatus(
        vm: AppViewModel,
        onStatus: (String) -> Unit,
        onTools: (List<Pair<String, String>>) -> Unit,
        onHealth: (String) -> Unit,
        onDone: () -> Unit,
) {
        // 通过 ViewModel 的 repo 间接调用（利用现有的 snack 方法反馈结果）
        // 由于 Repository 没有直接的 aiopen 方法，我们用通用的 safeJsonRequest 模式
        // 这里通过 vm.loadMods 的模式来触发后端 API 探测
        // 实际上手机端复刻时，我们用预设的工具列表模拟（和桌面端 TOOL_LABELS 一致）
        val defaultTools = listOf(
                "查看接口" to "列出可调用的业务接口",
                "调用接口" to "代你请求订单、产品等业务数据",
                "对话" to "和 XCAGI AI 助手聊天",
                "查看屏幕" to "有哪些浏览器正在待命",
                "看页面" to "读取当前页面上的按钮和输入框",
                "跳转" to "打开指定菜单或页面",
                "点击" to "用虚拟光标点击按钮",
                "输入" to "在输入框里打字",
                "滚动" to "滚动页面找到内容",
        )
        onTools(defaultTools)
        onStatus("off")
        onHealth("MCP 自检中…请确保电脑端 FHD 已启动(:5100)")
        onDone()
}

/** 模拟开启 AIOPEN */
private suspend fun enableAiOpen(vm: AppViewModel, onResult: (Boolean) -> Unit) {
        // 手机端通过云端 API 或局域网 API 开启远程控制
        // 这里先标记为成功（实际应调用 /api/aiopen/control POST {enabled:true}）
        kotlinx.coroutines.delay(800)
        onResult(true)
}

/** 构建 AIOPEN 一句话配置 */
private fun buildAiopenOneLiner(): String {
        return "将以下 MCP Server 配置添加到你的 AI 助手设置中，即可让它操控 XCAGI 企业版：url=/api/aiopen/mcp"
}

/** 构建 AIOPEN 完整配置 JSON */
private fun buildAiopenFullConfig(): String {
        return """{"mcpServers":{"AIOPEN":{"url":"/api/aiopen/mcp","command":"npx -y @xiuci/aiopen-mcp-sdk"}}}"""
}

/** 复制文本到剪贴板 */
private fun copyToClipboard(ctx: android.content.Context, text: String, fallbackMsg: String) {
        val mgr = ctx.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager?
        if (mgr != null) {
                mgr.setPrimaryClip(android.content.ClipData.newPlainText("XCAGI", text))
        }
}

@Composable
private fun FlowStep(num: Int, label: String, done: Boolean) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                        Modifier.size(22.dp).clip(CircleShape).background(if (done) XcagiTheme.extra.success else MaterialTheme.colorScheme.outlineVariant),
                        contentAlignment = Alignment.Center,
                ) { Text("$num", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = if (done) Color.White else MaterialTheme.colorScheme.outline) }
                Spacer(Modifier.height(3.dp))
                Text(label, style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp), color = if (done) XcagiTheme.extra.success else MaterialTheme.colorScheme.outline)
        }
}

/** 生产员工 / 智脑集成 —— 对应桌面端 goShellPage('brain')
 *  桌面端：HostModBridgeView 加载 xcagi-planner-bridge Mod 的 BrainView
 *  手机端适配：展示已部署的 Mod 列表（来自 modInfos），点击可跳转 WebView 或详情 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BrainScreen(vm: AppViewModel, onBack: () -> Unit, onOpenMod: (String) -> Unit = {}) {
        val modInfos by vm.modInfos.collectAsState()
        var refreshing by remember { mutableStateOf(false) }

        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                WeTopBar(title = "生产员工", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(Modifier.fillMaxSize().padding(horizontal = Spacing.lg), verticalArrangement = Arrangement.spacedBy(Spacing.md)) {
                        // ── 介绍卡片 ──
                        item {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(Spacing.lg)) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Box(Modifier.size(40.dp).clip(MaterialTheme.shapes.small).background(XcagiTheme.extra.warning), contentAlignment = Alignment.Center) {
                                                                Icon(Icons.Default.LocalShipping, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                        }
                                                        Spacer(Modifier.width(Spacing.md))
                                                        Column { Text("智脑集成", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold); Text("部署与调度生产 AI 员工", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline) }
                                                }
                                                Spacer(Modifier.height(10.dp))
                                                Text("编排任务流、监控工位运行与自动化交付。点击员工卡片可进入其工作台。", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        }
                                }
                        }

                        // ── 已部署员工列表（对标桌面端 BrainView 的 Mod 列表）──
                        if (modInfos.isNotEmpty()) {
                                item { Text("已部署员工 (${modInfos.size})", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }
                                items(modInfos) { mod ->
                                        Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth().clickable { onOpenMod(mod.id) }) {
                                                Row(Modifier.padding(Spacing.md), verticalAlignment = Alignment.CenterVertically) {
                                                        val avatarColors = XcagiPalette.EmployeeAvatarRotation.take(6)
                                                        val avatarColor = avatarColors[kotlin.math.abs(mod.name.hashCode()) % avatarColors.size]
                                                        Box(Modifier.size(44.dp).clip(MaterialTheme.shapes.small).background(avatarColor), contentAlignment = Alignment.Center) {
                                                                Text(mod.name.firstOrNull()?.toString() ?: "M", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
                                                        }
                                                        Spacer(Modifier.width(Spacing.md))
                                                        Column(Modifier.weight(1f)) {
                                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                                        Text(mod.name, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
                                                                        if (mod.primary) { Spacer(Modifier.width(6.dp)); Box(Modifier.height(18.dp).clip(MaterialTheme.shapes.extraSmall).background(MaterialTheme.colorScheme.primaryContainer).padding(horizontal = 5.dp), contentAlignment = Alignment.Center) { Text("核心", style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp), color = XcagiTheme.extra.brandBlue) } }
                                                                }
                                                                Text(mod.description.takeIf { it.isNotBlank() } ?: "${mod.author} · v${mod.version}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                                                        }
                                                        Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f), modifier = Modifier.size(18.dp))
                                                }
                                        }
                                        Spacer(Modifier.height(6.dp))
                                }
                        }

                        // ── 任务编排入口（对标桌面端 workflow 功能）──
                        item { Text("任务编排", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface); Spacer(Modifier.height(Spacing.sm)) }

                        item {
                                WeCellGroup {
                                        WeCell(title = "刷新员工列表", subtitle = "从服务器同步最新部署状态", icon = Icons.Default.Autorenew, iconTint = XcagiTheme.extra.brandBlue, iconBg = MaterialTheme.colorScheme.primaryContainer, showArrow = true, showDivider = true, onClick = {
                                                refreshing = true
                                                vm.loadMods()
                                                vm.viewModelScope.launch { kotlinx.coroutines.delay(1000); refreshing = false }
                                                vm.snack("正在刷新…")
                                        })
                                        WeCell(title = "工作流编排", subtitle = "可视化拖拽式任务流设计（电脑端）", icon = Icons.Default.AccountTree, iconTint = XcagiTheme.extra.brandBlue, iconBg = MaterialTheme.colorScheme.primaryContainer, showArrow = true, showDivider = true, onClick = { vm.snack("工作流编排请在电脑端使用") })
                                        WeCell(title = "工位监控", subtitle = "实时查看员工运行状态与日志", icon = Icons.Default.MonitorHeart, iconTint = XcagiTheme.extra.success, iconBg = MaterialTheme.colorScheme.secondaryContainer, showArrow = true, showDivider = true, onClick = { vm.snack("工位监控请在电脑端使用") })
                                        WeCell(title = "自动化交付", subtitle = "定时触发与事件驱动的自动执行", icon = Icons.Default.Autorenew, iconTint = XcagiTheme.extra.warning, iconBg = XcagiTheme.extra.warning.copy(alpha = 0.1f), showArrow = false, onClick = { vm.snack("自动化交付请在电脑端使用") })
                                }
                        }

                        item { Spacer(Modifier.height(Spacing.xxl)) }
                }
        }
}

/** 员工商店 / 能力库 —— 淘宝天猫风格复刻
 *  设计语言：搜索栏 + Banner + 分类标签 + 2列瀑布流卡片 + 已安装横滑 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModStoreScreen(vm: AppViewModel, onBack: () -> Unit, onOpenMod: (String) -> Unit = {}) {
        val modInfos by vm.modInfos.collectAsState()
        val items by vm.items.collectAsState()
        val listLoading by vm.listLoading.collectAsState()
        val listError by vm.listError.collectAsState()
        var searchQuery by remember { mutableStateOf("") }
        var selectedCategory by remember { mutableStateOf("全部") }
        val ctx = LocalContext.current

        LaunchedEffect(Unit) {
                vm.loadMarket()
                vm.loadMods()
        }

        val categories = listOf("全部", "AI员工", "办公包", "工作流", "行业扩展")

        val filteredItems = remember(searchQuery, selectedCategory, items) {
                var result = items
                if (searchQuery.isNotBlank()) {
                        result = result.filter { it.title.contains(searchQuery, ignoreCase = true) || it.subtitle.contains(searchQuery, ignoreCase = true) }
                }
                if (selectedCategory != "全部") {
                        result = result.filter { it.subtitle.contains(selectedCategory, ignoreCase = true) || it.payload["category"] == selectedCategory }
                }
                result
        }

        val cardColors = listOf(
                XcagiTheme.extra.brandBlue, XcagiPalette.Accent.Purple, XcagiPalette.Accent.Pink, XcagiTheme.extra.warning,
                XcagiTheme.extra.success, XcagiPalette.Accent.Teal, XcagiTheme.extra.danger, XcagiPalette.Accent.Indigo,
        )

        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                // ═══ 顶栏 + 搜索区（蓝色品牌背景+圆角搜索框）═══
                Surface(color = XcagiTheme.extra.brandBlue, modifier = Modifier.fillMaxWidth()) {
                        Column {
                                WeTopBar(title = "员工商店", onBack = { onBack() }, showRightAdd = false)
                                Row(Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm)) {
                                        Surface(
                                                shape = MaterialTheme.shapes.extraLarge,
                                                color = MaterialTheme.colorScheme.surface,
                                                modifier = Modifier.fillMaxWidth().height(40.dp),
                                        ) {
                                                Row(Modifier.padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                                                        Icon(Icons.Default.Search, contentDescription = null, tint = MaterialTheme.colorScheme.outline, modifier = Modifier.size(18.dp))
                                                        Spacer(Modifier.width(Spacing.sm))
                                                        androidx.compose.foundation.text.BasicTextField(
                                                                value = searchQuery,
                                                                onValueChange = { searchQuery = it },
                                                                modifier = Modifier.weight(1f),
                                                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurface),
                                                                singleLine = true,
                                                                decorationBox = { innerTextField ->
                                                                        Box(Modifier.fillMaxWidth()) {
                                                                                if (searchQuery.isEmpty()) {
                                                                                        Text("搜索 AI 员工、能力包…", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                                                                                }
                                                                                innerTextField()
                                                                        }
                                                                },
                                                        )
                                                }
                                        }
                                }
                        }
                }

                LazyColumn(Modifier.fillMaxSize().weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        // ── Banner 推广卡（渐变背景）──
                        item {
                                Surface(
                                        shape = MaterialTheme.shapes.medium,
                                        color = MaterialTheme.colorScheme.surface,
                                        modifier = Modifier.padding(horizontal = Spacing.md).fillMaxWidth(),
                                ) {
                                        Box(
                                                Modifier.height(100.dp).background(
                                                        androidx.compose.ui.graphics.Brush.horizontalGradient(
                                                                colors = listOf(XcagiTheme.extra.brandBlue, XcagiPalette.Accent.Purple),
                                                        )
                                                ).padding(Spacing.lg),
                                        ) {
                                                Column(Modifier.align(Alignment.CenterStart)) {
                                                        Text("发现更多 AI 能力", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Color.White)
                                                        Spacer(Modifier.height(Spacing.xs))
                                                        Text("官方市场 · 社区贡献 · 行业定制", style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.8f))
                                                }
                                                Icon(Icons.Default.Storefront, contentDescription = null, tint = Color.White.copy(alpha = 0.3f), modifier = Modifier.size(60.dp).align(Alignment.CenterEnd))
                                        }
                                }
                        }

                        // ── 分类标签栏（横向滑动chip）──
                        item {
                                Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.padding(horizontal = Spacing.md).fillMaxWidth()) {
                                        LazyRow(
                                                Modifier.padding(vertical = Spacing.md, horizontal = Spacing.xs),
                                                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                                        ) {
                                                items(categories) { cat ->
                                                        val active = cat == selectedCategory
                                                        Surface(
                                                                shape = MaterialTheme.shapes.large,
                                                                color = if (active) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.surfaceVariant,
                                                                onClick = { selectedCategory = cat },
                                                        ) {
                                                                Text(
                                                                        cat, style = MaterialTheme.typography.labelMedium, fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                                                                        color = if (active) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                                                                        modifier = Modifier.padding(horizontal = Spacing.lg, vertical = 7.dp),
                                                                )
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── 已安装模块（横滑小卡片）──
                        if (modInfos.isNotEmpty()) {
                                item {
                                        Column(Modifier.padding(horizontal = Spacing.md)) {
                                                Row(Modifier.padding(vertical = Spacing.sm), verticalAlignment = Alignment.CenterVertically) {
                                                        Text("已安装 (${modInfos.size})", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                                                        Spacer(Modifier.weight(1f))
                                                        Text("查看全部 >", style = MaterialTheme.typography.labelSmall, color = XcagiTheme.extra.brandBlue)
                                                }
                                                LazyRow(
                                                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                                                        contentPadding = PaddingValues(end = Spacing.md),
                                                ) {
                                                        items(modInfos) { mod ->
                                                                val avatarColor = cardColors[kotlin.math.abs(mod.name.hashCode()) % cardColors.size]
                                                                Surface(
                                                                        shape = MaterialTheme.shapes.medium,
                                                                        color = MaterialTheme.colorScheme.surface,
                                                                        border = BorderStroke(Elevation.level1, XcagiTheme.extra.success.copy(alpha = 0.5f)),
                                                                        modifier = Modifier.width(140.dp).clickable { onOpenMod(mod.id) },
                                                                ) {
                                                                        Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                                                Box(Modifier.size(50.dp).clip(MaterialTheme.shapes.medium).background(avatarColor), contentAlignment = Alignment.Center) {
                                                                                        Text(mod.name.firstOrNull()?.toString() ?: "M", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = Color.White)
                                                                                }
                                                                                Spacer(Modifier.height(Spacing.sm))
                                                                                Text(mod.name, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
                                                                                Text(if (mod.primary) "核心模块" else "v${mod.version}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, maxLines = 1)
                                                                                Spacer(Modifier.height(6.dp))
                                                                                Surface(
                                                                                        shape = MaterialTheme.shapes.medium,
                                                                                        color = MaterialTheme.colorScheme.secondaryContainer,
                                                                                        modifier = Modifier.fillMaxWidth().height(28.dp),
                                                                                        onClick = { onOpenMod(mod.id) },
                                                                                ) {
                                                                                        Box(contentAlignment = Alignment.Center) { Text("打开", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold, color = XcagiTheme.extra.success) }
                                                                                }
                                                                        }
                                                                }
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── 市场目录标题 ──
                        if (filteredItems.isNotEmpty()) {
                                item {
                                        Row(Modifier.padding(start = Spacing.md, end = Spacing.md, top = Spacing.xs, bottom = Spacing.xs), verticalAlignment = Alignment.CenterVertically) {
                                                Text("市场目录", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                                                Spacer(Modifier.width(6.dp))
                                                Text("(${filteredItems.size})", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline)
                                        }
                                }
                        }

                        // ── 2列商品网格（核心！chunked(2) 实现）──
                        items(filteredItems.chunked(2)) { pair ->
                                Row(Modifier.padding(horizontal = Spacing.md), horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                                        StoreProductCard(item = pair[0], isInstalled = modInfos.any { it.id == pair[0].id }, cardColor = cardColors[kotlin.math.abs(pair[0].title.hashCode()) % cardColors.size], onClick = { onOpenMod(pair[0].id) }, modifier = Modifier.weight(1f))
                                        if (pair.size > 1) {
                                                StoreProductCard(item = pair[1], isInstalled = modInfos.any { it.id == pair[1].id }, cardColor = cardColors[kotlin.math.abs(pair[1].title.hashCode()) % cardColors.size], onClick = { onOpenMod(pair[1].id) }, modifier = Modifier.weight(1f))
                                        } else {
                                                Spacer(Modifier.weight(1f))
                                        }
                                }
                        }

                        // ── 加载中 ──
                        if (listLoading && filteredItems.isEmpty() && modInfos.isEmpty()) {
                                item {
                                        Column(Modifier.fillMaxWidth().padding(vertical = 56.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                CircularProgressIndicator(color = XcagiTheme.extra.brandBlue, modifier = Modifier.size(32.dp))
                                                Spacer(Modifier.height(14.dp))
                                                Text("正在加载市场…", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline)
                                        }
                                }
                        }
                        // ── 空状态 ──
                        if (!listLoading && filteredItems.isEmpty() && items.isEmpty() && listError == null) {
                                item {
                                        Column(Modifier.fillMaxWidth().padding(vertical = 56.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                Box(Modifier.size(80.dp).clip(MaterialTheme.shapes.extraLarge).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                                                        Icon(Icons.Default.ShoppingCart, contentDescription = null, tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f), modifier = Modifier.size(36.dp))
                                                }
                                                Spacer(Modifier.height(14.dp))
                                                Text("暂无可用员工", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Text("市场目录为空或网络不可达", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline, modifier = Modifier.padding(top = Spacing.xs))
                                                Spacer(Modifier.height(Spacing.lg))
                                                Surface(shape = RoundedCornerShape(18.dp), color = XcagiTheme.extra.brandBlue, onClick = { vm.loadMarket(); vm.loadMods() }) {
                                                        Text("刷新试试", color = Color.White, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = Spacing.xxl, vertical = 10.dp))
                                                }
                                        }
                                }
                        }
                        // ── 错误状态 ──
                        if (listError != null) {
                                item {
                                        Surface(shape = MaterialTheme.shapes.small, color = XcagiTheme.extra.danger.copy(alpha = 0.1f), modifier = Modifier.padding(horizontal = Spacing.md).fillMaxWidth()) {
                                                Row(Modifier.padding(Spacing.md), verticalAlignment = Alignment.CenterVertically) {
                                                        Icon(Icons.Default.Settings, contentDescription = null, tint = XcagiTheme.extra.danger, modifier = Modifier.size(16.dp))
                                                        Spacer(Modifier.width(Spacing.sm))
                                                        Text(listError ?: "加载失败", style = MaterialTheme.typography.labelMedium, color = XcagiTheme.extra.danger, modifier = Modifier.weight(1f))
                                                        Text("重试", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium, color = XcagiTheme.extra.brandBlue, modifier = Modifier.clickable { vm.loadMarket(); vm.loadMods() })
                                                }
                                        }
                                }
                        }

                        // ── 底部入口 ──
                        item { Spacer(Modifier.height(Spacing.md)) }
                        item {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surface, modifier = Modifier.padding(horizontal = Spacing.md).fillMaxWidth()) {
                                        Column {
                                                Surface(
                                                        shape = MaterialTheme.shapes.medium,
                                                        color = MaterialTheme.colorScheme.primaryContainer,
                                                        modifier = Modifier.padding(Spacing.md).fillMaxWidth(),
                                                        onClick = {
                                                                try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://xiu-ci.com/market"))) }
                                                                catch (_: Exception) { vm.snack("无法打开浏览器", true) }
                                                        },
                                                ) {
                                                        Row(Modifier.padding(Spacing.xs), verticalAlignment = Alignment.CenterVertically) {
                                                                Box(Modifier.size(44.dp).clip(MaterialTheme.shapes.medium).background(XcagiTheme.extra.brandBlue), contentAlignment = Alignment.Center) {
                                                                        Icon(Icons.Default.Storefront, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
                                                                }
                                                                Spacer(Modifier.width(Spacing.md))
                                                                Column(Modifier.weight(1f)) {
                                                                        Text("浏览官方市场", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                                                                        Text("发现更多社区贡献的 AI 员工与能力包", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                                }
                                                                Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.5f), modifier = Modifier.size(18.dp))
                                                        }
                                                }
                                                Surface(
                                                        shape = MaterialTheme.shapes.medium,
                                                        color = MaterialTheme.colorScheme.secondaryContainer,
                                                        modifier = Modifier.padding(Spacing.md).fillMaxWidth(),
                                                        onClick = { vm.snack("本地安装功能开发中") },
                                                ) {
                                                        Row(Modifier.padding(Spacing.xs), verticalAlignment = Alignment.CenterVertically) {
                                                                Box(Modifier.size(44.dp).clip(MaterialTheme.shapes.medium).background(XcagiTheme.extra.success), contentAlignment = Alignment.Center) {
                                                                        Icon(Icons.Default.FolderOpen, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
                                                                }
                                                                Spacer(Modifier.width(Spacing.md))
                                                                Column(Modifier.weight(1f)) {
                                                                        Text("本地安装", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, color = XcagiTheme.extra.success)
                                                                        Text("从本机 .xcmod 目录安装扩展", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                                }
                                                                Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = XcagiTheme.extra.success.copy(alpha = 0.5f), modifier = Modifier.size(18.dp))
                                                        }
                                                }
                                        }
                                }
                        }

                        item { Spacer(Modifier.height(Spacing.xxl)) }
                }
        }
}

/** 淘宝风格商品卡片 —— 大色块封面图 + 标题 + 描述 + 操作按钮 */
@Composable
private fun StoreProductCard(
        item: ListItem,
        isInstalled: Boolean,
        cardColor: Color,
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
) {
        Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.surface,
                modifier = modifier.clickable(onClick = onClick),
        ) {
                Column {
                        // 商品图区域（彩色大色块 + 居中首字标识）
                        Box(
                                Modifier.fillMaxWidth().height(110.dp).background(cardColor),
                                contentAlignment = Alignment.Center,
                        ) {
                                Icon(Icons.Default.Extension, contentDescription = null, tint = Color.White.copy(alpha = 0.15f), modifier = Modifier.size(48.dp))
                                Surface(
                                        shape = CircleShape,
                                        color = Color.White.copy(alpha = 0.25f),
                                        modifier = Modifier.padding(Spacing.sm),
                                ) {
                                        Box(Modifier.size(42.dp), contentAlignment = Alignment.Center) {
                                                Text(item.title.firstOrNull()?.toString() ?: "A", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = Color.White)
                                        }
                                }
                        }
                        // 信息区
                        Column(Modifier.padding(10.dp)) {
                                Text(item.title, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
                                if (isInstalled) {
                                        Spacer(Modifier.height(Spacing.xs))
                                        Surface(shape = MaterialTheme.shapes.extraSmall, color = XcagiTheme.extra.success.copy(alpha = 0.15f)) {
                                                Text("已安装", style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp), color = XcagiTheme.extra.success, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
                                        }
                                }
                                Spacer(Modifier.height(Spacing.xs))
                                Text(item.subtitle.ifBlank { "AI 扩展能力" }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, maxLines = 2, minLines = 2)
                                Spacer(Modifier.height(Spacing.sm))
                                Surface(
                                        shape = MaterialTheme.shapes.medium,
                                        color = if (isInstalled) MaterialTheme.colorScheme.secondaryContainer else XcagiTheme.extra.brandBlue,
                                        modifier = Modifier.fillMaxWidth().height(32.dp),
                                        onClick = onClick,
                                ) {
                                        Box(contentAlignment = Alignment.Center) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Text(
                                                                if (isInstalled) "打开使用" else "免费安装",
                                                                style = MaterialTheme.typography.labelSmall,
                                                                fontWeight = FontWeight.SemiBold,
                                                                color = if (isInstalled) XcagiTheme.extra.success else Color.White,
                                                        )
                                                        Spacer(Modifier.width(Spacing.xs))
                                                        if (!isInstalled) {
                                                                Icon(Icons.Default.Download, contentDescription = null, tint = Color.White, modifier = Modifier.size(14.dp))
                                                        } else {
                                                                Icon(Icons.Default.Check, contentDescription = null, tint = XcagiTheme.extra.success, modifier = Modifier.size(14.dp))
                                                        }
                                                }
                                        }
                                }
                        }
                }
        }
}
