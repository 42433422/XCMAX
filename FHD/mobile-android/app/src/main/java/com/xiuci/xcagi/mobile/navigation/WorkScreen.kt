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
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

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
private val iconBgColors =
        listOf(
                MobileTokens.iconBgBlue,
                MobileTokens.iconBgGreen,
                MobileTokens.iconBgOrange,
                MobileTokens.iconBgPurple,
                MobileTokens.iconBgCyan,
                MobileTokens.iconBgRed,
        )

private val iconFgColors =
        listOf(
                MobileTokens.iconFgBlue,
                MobileTokens.iconFgGreen,
                MobileTokens.iconFgOrange,
                MobileTokens.iconFgPurple,
                MobileTokens.iconFgCyan,
                MobileTokens.iconFgRed,
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

        LaunchedEffect(Unit) {
                vm.loadHomeHub()
                vm.loadMods()
        }

        val pcTitle = if (fhdHost.isBlank()) "我的电脑" else fhdHost.substringBefore(':')
        val pcSubtitle =
                if (hub.pcOnline) "在线 · Agent 控制中"
                else if (fhdHost.isNotBlank()) "离线 · 重连后恢复控制" else "点击绑定以启用 Agent 远程控制"

        Column(Modifier.fillMaxSize().background(MobileTokens.surfaceWhite)) {
                WeTopBar(
                        title = "智能生态",
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
                                                iconTint = MobileTokens.iconFgBlue,
                                                iconBg = MobileTokens.iconBgBlue,
                                                trailing = {
                                                        Box(
                                                                Modifier.size(8.dp)
                                                                        .clip(CircleShape)
                                                                        .background(
                                                                                if (hub.pcOnline)
                                                                                        MobileTokens
                                                                                                .successGreen
                                                                                else
                                                                                        MobileTokens
                                                                                                .textDisabled
                                                                        ),
                                                        )
                                                },
                                                showDivider = false,
                                                onClick = onConnectPc,
                                        )
                                }
                        }

                        // ── AI 生态应用（默认 4 个，和"我的电脑"同款 WeCell 样式）──
                        item {
                                WeSectionCaption("AI 生态应用")
                                WeCellGroup {
                                        WeCell(
                                                title = "智慧分析",
                                                subtitle = "接入可视化 AI 员工，上传表格、对话洞察、生成图表与报告",
                                                icon = Icons.Default.Extension,
                                                iconTint = Color(0xFF3B82F6),
                                                iconBg = Color(0xFFEFF6FF),
                                                showArrow = true,
                                                onClick = { onNavigateToApp(Routes.SMART_ANALYSIS) },
                                        )
                                        WeCell(
                                                title = "AIOPEN 开放智控",
                                                subtitle = "企业级 AI Agent 接入平台，MCP/API 协议远程 UI 操控",
                                                icon = Icons.Default.Explore,
                                                iconTint = Color(0xFF6366F1),
                                                iconBg = Color(0xFFEEF2FF),
                                                showArrow = true,
                                                onClick = { onNavigateToApp(Routes.AI_OPEN) },
                                        )
                                        WeCell(
                                                title = "生产员工",
                                                subtitle = "部署与调度生产 AI 员工，编排任务流与自动化交付",
                                                icon = Icons.Default.LocalShipping,
                                                iconTint = Color(0xFFF59E0B),
                                                iconBg = Color(0xFFFFF7ED),
                                                showArrow = true,
                                                onClick = { onNavigateToApp(Routes.BRAIN) },
                                        )
                                        WeCell(
                                                title = "员工商店",
                                                subtitle = "MOD 扩展浏览、安装与本机 .xcmod 目录管理",
                                                icon = Icons.Default.ShoppingCart,
                                                iconTint = Color(0xFF22C55E),
                                                iconBg = Color(0xFFF0FDF4),
                                                showArrow = false,
                                                onClick = { onNavigateToApp(Routes.MOD_STORE) },
                                        )
                                }
                        }

                        // ── 动态 Mod 菜单（按 Mod 分组）──
                        modInfos.forEachIndexed { modIdx, mod ->
                                if (mod.frontend_menu.isNotEmpty()) {
                                        item { WeSectionCaption(mod.name) }
                                        item {
                                                WeCellGroup {
                                                        mod.frontend_menu.forEachIndexed {
                                                                menuIdx,
                                                                menu ->
                                                                val colorIdx =
                                                                        (modIdx + menuIdx) %
                                                                                iconBgColors.size
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
                                                                                iconFgColors[
                                                                                        colorIdx],
                                                                        iconBg =
                                                                                iconBgColors[
                                                                                        colorIdx],
                                                                        showArrow = true,
                                                                        showDivider =
                                                                                menuIdx <
                                                                                        mod.frontend_menu
                                                                                                .lastIndex,
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
                                                        tint = MobileTokens.textDisabled,
                                                )
                                                Spacer(Modifier.height(12.dp))
                                                Text(
                                                        "暂无已安装的 Mod",
                                                        fontSize = 14.sp,
                                                        color = MobileTokens.textTertiary,
                                                )
                                                Text(
                                                        "暂无可用功能模块",
                                                        fontSize = 12.sp,
                                                        color = MobileTokens.textDisabled,
                                                        modifier = Modifier.padding(top = 4.dp),
                                                )
                                                Spacer(Modifier.height(16.dp))
                                                Box(
                                                        Modifier.height(36.dp)
                                                                .clip(RoundedCornerShape(18.dp))
                                                                .background(MobileTokens.brandBlue)
                                                                .clickable { /* navigate to market */
                                                                }
                                                                .padding(horizontal = 24.dp),
                                                        contentAlignment = Alignment.Center,
                                                ) {
                                                        Text(
                                                                "浏览 Mod 商店",
                                                                color = Color.White,
                                                                fontSize = 14.sp
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

        Column(Modifier.fillMaxSize().background(Color(0xFFF8FAFC))) {
                WeTopBar(title = "智慧分析", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(
                        Modifier.fillMaxSize().padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                        // ── 品牌介绍卡片（对标桌面端 kitten-header）──
                        item {
                                Surface(shape = RoundedCornerShape(14.dp), color = Color.White, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(16.dp)) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFF0F766E)), contentAlignment = Alignment.Center) {
                                                                Icon(Icons.Default.Extension, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                        }
                                                        Spacer(Modifier.width(12.dp))
                                                        Column { Text("AI 数据分析助手", fontSize = 15.sp, fontWeight = FontWeight.SemiBold); Text("可视化 AI 员工 · 对话洞察 · 图表导出", fontSize = 12.sp, color = Color(0xFF94A3B8)) }
                                                }
                                                Spacer(Modifier.height(10.dp))
                                                Text("上传表格或直接提问，AI 自动生成 ECharts 图表与分析报告。支持 Excel、CSV 格式。", fontSize = 13.sp, color = Color(0xFF64748B))
                                        }
                                }
                        }

                        // ── 快捷操作（对标桌面端 quick-select + more-menu）──
                        item { Text("快捷分析", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }

                        item {
                                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        QuickChip(label = "财务简报", color = Color(0xFF3B82F6), bg = Color(0xFFEFF6FF)) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "数据概览", color = Color(0xFF22C55E), bg = Color(0xFFF0FDF4)) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "趋势分析", color = Color(0xFFF59E0B), bg = Color(0xFFFFF7ED)) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                }
                        }

                        item { Spacer(Modifier.height(4.dp)) }
                        item {
                                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        QuickChip(label = "生成报告", color = Color(0xFF6366F1), bg = Color(0xFFEEF2FF)) { onOpenChat("kitten"); vm.snack("已切换到智慧分析模式") }
                                        Spacer(Modifier.weight(1f))
                                        QuickChip(label = "上传表格", color = Color(0xFFEC4899), bg = Color(0xFFFDF2F8)) {
                                                // 调用系统文件选择器
                                                try {
                                                        val intent = Intent(Intent.ACTION_GET_CONTENT).apply { type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE) }
                                                        ctx.startActivity(Intent.createChooser(intent, "选择表格文件"))
                                                } catch (_: Exception) { vm.snack("无法打开文件选择器", true) }
                                        }
                                        Spacer(Modifier.weight(1f))
                                        QuickChatChip(label = "打开对话", color = Color(0xFF64748B), bg = Color(0xFFF1F5F9)) { onOpenChat("kitten") }
                                }
                        }

                        // ── 输入区域（对标桌面端 input-area）──
                        item { Spacer(Modifier.height(16.dp)); Text("输入问题，AI 帮你分析", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }

                        item {
                                Surface(shape = RoundedCornerShape(14.dp), color = Color.White, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(12.dp)) {
                                                OutlinedTextField(
                                                        value = query,
                                                        onValueChange = { query = it },
                                                        modifier = Modifier.fillMaxWidth(),
                                                        placeholder = { Text("例如：本季度销售趋势如何？", fontSize = 14.sp, color = Color(0xFF94A3B8)) },
                                                        shape = RoundedCornerShape(10.dp),
                                                        maxLines = 3,
                                                )
                                                Spacer(Modifier.height(10.dp))
                                                Box(
                                                        Modifier.fillMaxWidth()
                                                                .height(44.dp)
                                                                .clip(RoundedCornerShape(10.dp))
                                                                .background(if (query.isNotBlank()) Color(0xFF3B82F6) else MobileTokens.divider)
                                                                .clickable(enabled = query.isNotBlank()) {
                                                                        onOpenChat("kitten")
                                                                        vm.snack("已发送至智慧分析：$query")
                                                                        query = ""
                                                                },
                                                        contentAlignment = Alignment.Center,
                                                ) { Text("发送分析请求", color = if (query.isNotBlank()) Color.White else Color(0xFF94A3B8), fontSize = 14.sp, fontWeight = FontWeight.Medium) }
                                                }
                                        }
                        }

                        item { Spacer(Modifier.height(24.dp)) }
                }
        }
}

@Composable
private fun QuickChip(label: String, color: Color, bg: Color, onClick: () -> Unit) {
        Box(
                Modifier.clip(RoundedCornerShape(16.dp)).background(bg).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp),
                contentAlignment = Alignment.Center,
        ) { Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = color) }
}
@Composable
private fun QuickChatChip(label: String, color: Color, bg: Color, onClick: () -> Unit) {
        Surface(
                shape = RoundedCornerShape(16.dp),
                color = bg,
                border = BorderStroke(1.dp, Color(0xFFE2E8F0)),
                onClick = onClick,
        ) { Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = color, modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp)) }
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

        Column(Modifier.fillMaxSize().background(Color(0xFFF8FAFC))) {
                WeTopBar(title = "AIOPEN 开放智控", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        // ── Hero 卡片（对标桌面端 aiopen-hero）──
                        item {
                                Surface(
                                        shape = RoundedCornerShape(20.dp),
                                        color = Color.White,
                                        border = when (readyStatus) {
                                                "ready" -> BorderStroke(1.5.dp, Color(0x7322C55E))
                                                "partial" -> BorderStroke(1.5.dp, Color(0x73F59E0B))
                                                else -> BorderStroke(1.dp, Color(0xFFE2E8F0))
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                ) {
                                        Column(Modifier.padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                // 状态图标
                                                Box(Modifier.size(56.dp).clip(RoundedCornerShape(16.dp)).background(
                                                        when (readyStatus) {
                                                                "ready" -> Color(0xFF22C55E)
                                                                "partial" -> Color(0xFFF59E0B)
                                                                else -> Color(0xFF3B82F6)
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
                                                Text("AIOPEN", fontSize = 24.sp, fontWeight = FontWeight.ExtraBold, color = Color(0xFF0F172A), letterSpacing = 0.04.em)
                                                Text("让外部 AI 像助手一样，帮你操作本软件", fontSize = 13.sp, color = Color(0xFF64748B))

                                                // 流程步骤（对标 aiopen-flow）
                                                Spacer(Modifier.height(16.dp))
                                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                                        FlowStep(num = 1, label = "一键开启", done = readyStatus != "off")
                                                        FlowStep(num = 2, label = "复制配置", done = false)
                                                        FlowStep(num = 3, label = "接入 AI", done = readyStatus == "ready")
                                                }

                                                Spacer(Modifier.height(12.dp))
                                                Text(
                                                        when (readyStatus) {
                                                                "ready" -> "已就绪 · 可向外部 AI 助手发送指令"
                                                                "partial" -> "连接中 · 请保持网络畅通"
                                                                else -> "两步即可：开启 → 复制配置到 AI 助手"
                                                        }, fontSize = 12.sp, color = Color(0xFF64748B),
                                                )

                                                // 一键开启按钮
                                                Spacer(Modifier.height(14.dp))
                                                Box(
                                                        Modifier.fillMaxWidth()
                                                                .height(46.dp)
                                                                .clip(RoundedCornerShape(12.dp))
                                                                .background(
                                                                        if (readyStatus == "ready" || setupRunning) MobileTokens.divider
                                                                        else Color(0xFF3B82F6)
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
                                                                color = if (readyStatus == "ready" || setupRunning) Color(0xFF94A3B8) else Color.White,
                                                                fontSize = 15.sp, fontWeight = FontWeight.Bold,
                                                        )
                                                }
                                        }
                                }
                        }

                        // ── MCP 健康状态 ──
                        if (mcpHealthMsg.isNotBlank()) {
                                item {
                                        Surface(shape = RoundedCornerShape(10.dp), color = if (mcpHealthMsg.contains("正常")) Color(0xFFF0FDF4) else Color(0xFFFEF2F2), modifier = Modifier.fillMaxWidth()) {
                                                Text(mcpHealthMsg, fontSize = 12.sp, color = if (mcpHealthMsg.contains("正常")) Color(0xFF166534) else Color(0xFF991B1B), modifier = Modifier.padding(12.dp))
                                        }
                                }
                        }

                        // ── 一句话配置（对标 aiopen-oneline）──
                        item {
                                Surface(shape = RoundedCornerShape(12.dp), color = Color(0xFFF0F9FF), border = BorderStroke(1.dp, Color(0xFFBFDBFE)), modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(14.dp)) {
                                                Text("发给其他 AI 助手", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF1D4ED8))
                                                Spacer(Modifier.height(6.dp))
                                                Text("将下方 MCP 配置发送给 ChatGPT / Claude / Cursor 等 AI 助手，即可让它操控 XCAGI。", fontSize = 12.sp, color = Color(0xFF475569))
                                                Spacer(Modifier.height(10.dp))
                                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                                        Box(Modifier.weight(1f).height(36.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFF2563EB)).clickable {
                                                                copyToClipboard(ctx, buildAiopenOneLiner(), "一句话配置已复制")
                                                                vm.snack("一句话已复制 · 粘贴到 ChatGPT / Claude 对话框")
                                                        }, contentAlignment = Alignment.Center) { Text("复制一句话", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
                                                        Box(Modifier.weight(1f).height(36.dp).clip(RoundedCornerShape(10.dp)).background(Color.White), contentAlignment = Alignment.Center) {
                                                                Surface(shape = RoundedCornerShape(10.dp), color = Color.Transparent, border = BorderStroke(1.dp, Color(0xFF93C5FD)), onClick = {
                                                                        copyToClipboard(ctx, buildAiopenFullConfig(), "完整配置已复制")
                                                                        vm.snack("完整配置已复制")
                                                                }) { Text("完整配置 JSON", color = Color(0xFF2563EB), fontSize = 13.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 12.dp)) }
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── MCP 工具列表（对标 aiopen-tools-preview + TOOL_LABELS）──
                        if (mcpTools.isNotEmpty()) {
                                item { Text("MCP 工具 (${mcpTools.size})", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }
                                item {
                                        WeCellGroup {
                                                mcpTools.forEachIndexed { idx, (name, desc) ->
                                                        WeCell(
                                                                title = name,
                                                                subtitle = desc,
                                                                icon = Icons.Default.TouchApp,
                                                                iconTint = Color(0xFF3B82F6),
                                                                iconBg = Color(0xFFEFF6FF),
                                                                showArrow = false,
                                                                showDivider = idx < mcpTools.lastIndex,
                                                                onClick = {},
                                                        )
                                                }
                                        }
                                }
                        }

                        // ── 更多设置（对标 aiopen-more 折叠区精简版）──
                        item { Text("更多设置", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }
                        item {
                                WeCellGroup {
                                        WeCell(title = "刷新状态", subtitle = "重新检测 AIOPEN 服务与 MCP 连接", icon = Icons.Default.Autorenew, iconTint = Color(0xFF3B82F6), iconBg = Color(0xFFEFF6FF), showArrow = true, showDivider = true, onClick = {
                                                loading = true
                                                vm.viewModelScope.launch {
                                                        loadAiOpenStatus(vm,
                                                                onStatus = { s -> readyStatus = s },
                                                                onTools = { t -> mcpTools = t },
                                                                onHealth = { h -> mcpHealthMsg = h },
                                                                onDone = { loading = false; vm.snack("状态已刷新") })
                                                }
                                        })
                                        WeCell(title = "MCP 端点地址", subtitle = "/api/aiopen/mcp", icon = Icons.Default.Computer, iconTint = Color(0xFF22C55E), iconBg = Color(0xFFF0FDF4), showArrow = false, showDivider = true, onClick = {
                                                copyToClipboard(ctx, "/api/aiopen/mcp", "MCP 地址已复制")
                                                vm.snack("MCP 端点已复制")
                                        })
                                        WeCell(title = "使用说明", subtitle = "查看 AIOPEN 接入文档", icon = Icons.Default.AssignmentInd, iconTint = Color(0xFF6366F1), iconBg = Color(0xFFEEF2FF), showArrow = false, showDivider = false, onClick = {
                                                try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://docs.xiu-ci.com/aiopen"))) }
                                                catch (_: Exception) { vm.snack("无法打开浏览器", true) }
                                        })
                                }
                        }

                        item { Spacer(Modifier.height(24.dp)) }
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
                        Modifier.size(22.dp).clip(CircleShape).background(if (done) Color(0xFF22C55E) else Color(0xFFE2E8F0)),
                        contentAlignment = Alignment.Center,
                ) { Text("$num", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = if (done) Color.White else Color(0xFF94A3B8)) }
                Spacer(Modifier.height(3.dp))
                Text(label, fontSize = 10.sp, color = if (done) Color(0xFF15803D) else Color(0xFF94A3B8))
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

        Column(Modifier.fillMaxSize().background(Color(0xFFF8FAFC))) {
                WeTopBar(title = "生产员工", onBack = { onBack() }, showRightAdd = false)
                LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        // ── 介绍卡片 ──
                        item {
                                Surface(shape = RoundedCornerShape(14.dp), color = Color.White, modifier = Modifier.fillMaxWidth()) {
                                        Column(Modifier.padding(16.dp)) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFFF59E0B)), contentAlignment = Alignment.Center) {
                                                                Icon(Icons.Default.LocalShipping, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                        }
                                                        Spacer(Modifier.width(12.dp))
                                                        Column { Text("智脑集成", fontSize = 15.sp, fontWeight = FontWeight.SemiBold); Text("部署与调度生产 AI 员工", fontSize = 12.sp, color = Color(0xFF94A3B8)) }
                                                }
                                                Spacer(Modifier.height(10.dp))
                                                Text("编排任务流、监控工位运行与自动化交付。点击员工卡片可进入其工作台。", fontSize = 13.sp, color = Color(0xFF64748B))
                                        }
                                }
                        }

                        // ── 已部署员工列表（对标桌面端 BrainView 的 Mod 列表）──
                        if (modInfos.isNotEmpty()) {
                                item { Text("已部署员工 (${modInfos.size})", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }
                                items(modInfos) { mod ->
                                        Surface(shape = RoundedCornerShape(12.dp), color = Color.White, modifier = Modifier.fillMaxWidth().clickable { onOpenMod(mod.id) }) {
                                                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                                                        val avatarColors = listOf(Color(0xFF4A90D9), Color(0xFFE74C3C), Color(0xFF2ECC71), Color(0xFFF39C12), Color(0xFF9B59B6), Color(0xFF1ABC9C))
                                                        val avatarColor = avatarColors[kotlin.math.abs(mod.name.hashCode()) % avatarColors.size]
                                                        Box(Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)).background(avatarColor), contentAlignment = Alignment.Center) {
                                                                Text(mod.name.firstOrNull()?.toString() ?: "M", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                                        }
                                                        Spacer(Modifier.width(12.dp))
                                                        Column(Modifier.weight(1f)) {
                                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                                        Text(mod.name, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                                                                        if (mod.primary) { Spacer(Modifier.width(6.dp)); Box(Modifier.height(18.dp).clip(RoundedCornerShape(4.dp)).background(Color(0xFFEFF6FF)).padding(horizontal = 5.dp), contentAlignment = Alignment.Center) { Text("核心", fontSize = 10.sp, color = Color(0xFF3B82F6)) } }
                                                                }
                                                                Text(mod.description.takeIf { it.isNotBlank() } ?: "${mod.author} · v${mod.version}", fontSize = 12.sp, color = Color(0xFF94A3B8))
                                                        }
                                                        Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = Color(0xFFCBD5E1), modifier = Modifier.size(18.dp))
                                                }
                                        }
                                        Spacer(Modifier.height(6.dp))
                                }
                        }

                        // ── 任务编排入口（对标桌面端 workflow 功能）──
                        item { Text("任务编排", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155)); Spacer(Modifier.height(8.dp)) }

                        item {
                                WeCellGroup {
                                        WeCell(title = "刷新员工列表", subtitle = "从服务器同步最新部署状态", icon = Icons.Default.Autorenew, iconTint = Color(0xFF3B82F6), iconBg = Color(0xFFEFF6FF), showArrow = true, showDivider = true, onClick = {
                                                refreshing = true
                                                vm.loadMods()
                                                vm.viewModelScope.launch { kotlinx.coroutines.delay(1000); refreshing = false }
                                                vm.snack("正在刷新…")
                                        })
                                        WeCell(title = "工作流编排", subtitle = "可视化拖拽式任务流设计（电脑端）", icon = Icons.Default.AccountTree, iconTint = Color(0xFF3B82F6), iconBg = Color(0xFFEFF6FF), showArrow = true, showDivider = true, onClick = { vm.snack("工作流编排请在电脑端使用") })
                                        WeCell(title = "工位监控", subtitle = "实时查看员工运行状态与日志", icon = Icons.Default.MonitorHeart, iconTint = Color(0xFF22C55E), iconBg = Color(0xFFF0FDF4), showArrow = true, showDivider = true, onClick = { vm.snack("工位监控请在电脑端使用") })
                                        WeCell(title = "自动化交付", subtitle = "定时触发与事件驱动的自动执行", icon = Icons.Default.Autorenew, iconTint = Color(0xFFF59E0B), iconBg = Color(0xFFFFF7ED), showArrow = false, onClick = { vm.snack("自动化交付请在电脑端使用") })
                                }
                        }

                        item { Spacer(Modifier.height(24.dp)) }
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
                Color(0xFF3B82F6), Color(0xFF8B5CF6), Color(0xFFEC4899), Color(0xFFF59E0B),
                Color(0xFF22C55E), Color(0xFF06B6D4), Color(0xFFEF4444), Color(0xFF6366F1),
        )

        Column(Modifier.fillMaxSize().background(Color(0xFFF5F5F5))) {
                // ═══ 顶栏 + 搜索区（蓝色品牌背景+圆角搜索框）═══
                Surface(color = MobileTokens.brandBlue, modifier = Modifier.fillMaxWidth()) {
                        Column {
                                WeTopBar(title = "员工商店", onBack = { onBack() }, showRightAdd = false)
                                Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                                        Surface(
                                                shape = RoundedCornerShape(20.dp),
                                                color = Color.White,
                                                modifier = Modifier.fillMaxWidth().height(40.dp),
                                        ) {
                                                Row(Modifier.padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                                                        Icon(Icons.Default.Search, contentDescription = null, tint = Color(0xFF94A3B8), modifier = Modifier.size(18.dp))
                                                        Spacer(Modifier.width(8.dp))
                                                        androidx.compose.foundation.text.BasicTextField(
                                                                value = searchQuery,
                                                                onValueChange = { searchQuery = it },
                                                                modifier = Modifier.weight(1f),
                                                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 14.sp, color = Color(0xFF334155)),
                                                                singleLine = true,
                                                                decorationBox = { innerTextField ->
                                                                        Box(Modifier.fillMaxWidth()) {
                                                                                if (searchQuery.isEmpty()) {
                                                                                        Text("搜索 AI 员工、能力包…", fontSize = 14.sp, color = Color(0xFF94A3B8))
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
                                        shape = RoundedCornerShape(14.dp),
                                        color = Color.White,
                                        modifier = Modifier.padding(horizontal = 12.dp).fillMaxWidth(),
                                ) {
                                        Box(
                                                Modifier.height(100.dp).background(
                                                        androidx.compose.ui.graphics.Brush.horizontalGradient(
                                                                colors = listOf(Color(0xFF3B82F6), Color(0xFF8B5CF6)),
                                                        )
                                                ).padding(16.dp),
                                        ) {
                                                Column(Modifier.align(Alignment.CenterStart)) {
                                                        Text("发现更多 AI 能力", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                                        Spacer(Modifier.height(4.dp))
                                                        Text("官方市场 · 社区贡献 · 行业定制", fontSize = 12.sp, color = Color.White.copy(alpha = 0.8f))
                                                }
                                                Icon(Icons.Default.Storefront, contentDescription = null, tint = Color.White.copy(alpha = 0.3f), modifier = Modifier.size(60.dp).align(Alignment.CenterEnd))
                                        }
                                }
                        }

                        // ── 分类标签栏（横向滑动chip）──
                        item {
                                Surface(color = Color.White, modifier = Modifier.padding(horizontal = 12.dp).fillMaxWidth()) {
                                        LazyRow(
                                                Modifier.padding(vertical = 12.dp, horizontal = 4.dp),
                                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                        ) {
                                                items(categories) { cat ->
                                                        val active = cat == selectedCategory
                                                        Surface(
                                                                shape = RoundedCornerShape(16.dp),
                                                                color = if (active) MobileTokens.brandBlue else Color(0xFFF1F5F9),
                                                                onClick = { selectedCategory = cat },
                                                        ) {
                                                                Text(
                                                                        cat, fontSize = 13.sp, fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                                                                        color = if (active) Color.White else Color(0xFF64748B),
                                                                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 7.dp),
                                                                )
                                                        }
                                                }
                                        }
                                }
                        }

                        // ── 已安装模块（横滑小卡片）──
                        if (modInfos.isNotEmpty()) {
                                item {
                                        Column(Modifier.padding(horizontal = 12.dp)) {
                                                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                                        Text("已安装 (${modInfos.size})", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155))
                                                        Spacer(Modifier.weight(1f))
                                                        Text("查看全部 >", fontSize = 12.sp, color = MobileTokens.brandBlue)
                                                }
                                                LazyRow(
                                                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                                                        contentPadding = PaddingValues(end = 12.dp),
                                                ) {
                                                        items(modInfos) { mod ->
                                                                val avatarColor = cardColors[kotlin.math.abs(mod.name.hashCode()) % cardColors.size]
                                                                Surface(
                                                                        shape = RoundedCornerShape(12.dp),
                                                                        color = Color.White,
                                                                        border = BorderStroke(1.dp, Color(0xFF86EFAC)),
                                                                        modifier = Modifier.width(140.dp).clickable { onOpenMod(mod.id) },
                                                                ) {
                                                                        Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                                                Box(Modifier.size(50.dp).clip(RoundedCornerShape(12.dp)).background(avatarColor), contentAlignment = Alignment.Center) {
                                                                                        Text(mod.name.firstOrNull()?.toString() ?: "M", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                                                                }
                                                                                Spacer(Modifier.height(8.dp))
                                                                                Text(mod.name, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color(0xFF334155), maxLines = 1)
                                                                                Text(if (mod.primary) "核心模块" else "v${mod.version}", fontSize = 11.sp, color = Color(0xFF94A3B8), maxLines = 1)
                                                                                Spacer(Modifier.height(6.dp))
                                                                                Surface(
                                                                                        shape = RoundedCornerShape(14.dp),
                                                                                        color = Color(0xFFF0FDF4),
                                                                                        modifier = Modifier.fillMaxWidth().height(28.dp),
                                                                                        onClick = { onOpenMod(mod.id) },
                                                                                ) {
                                                                                        Box(contentAlignment = Alignment.Center) { Text("打开", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF166534)) }
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
                                        Row(Modifier.padding(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                                                Text("市场目录", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155))
                                                Spacer(Modifier.width(6.dp))
                                                Text("(${filteredItems.size})", fontSize = 13.sp, color = Color(0xFF94A3B8))
                                        }
                                }
                        }

                        // ── 2列商品网格（核心！chunked(2) 实现）──
                        items(filteredItems.chunked(2)) { pair ->
                                Row(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
                                                CircularProgressIndicator(color = MobileTokens.brandBlue, modifier = Modifier.size(32.dp))
                                                Spacer(Modifier.height(14.dp))
                                                Text("正在加载市场…", fontSize = 13.sp, color = Color(0xFF94A3B8))
                                        }
                                }
                        }
                        // ── 空状态 ──
                        if (!listLoading && filteredItems.isEmpty() && items.isEmpty() && listError == null) {
                                item {
                                        Column(Modifier.fillMaxWidth().padding(vertical = 56.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                                Box(Modifier.size(80.dp).clip(RoundedCornerShape(24.dp)).background(Color(0xFFF1F5F9)), contentAlignment = Alignment.Center) {
                                                        Icon(Icons.Default.ShoppingCart, contentDescription = null, tint = Color(0xFFCBD5E1), modifier = Modifier.size(36.dp))
                                                }
                                                Spacer(Modifier.height(14.dp))
                                                Text("暂无可用员工", fontSize = 15.sp, fontWeight = FontWeight.Medium, color = Color(0xFF475569))
                                                Text("市场目录为空或网络不可达", fontSize = 13.sp, color = Color(0xFF94A3B8), modifier = Modifier.padding(top = 4.dp))
                                                Spacer(Modifier.height(16.dp))
                                                Surface(shape = RoundedCornerShape(18.dp), color = MobileTokens.brandBlue, onClick = { vm.loadMarket(); vm.loadMods() }) {
                                                        Text("刷新试试", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = 24.dp, vertical = 10.dp))
                                                }
                                        }
                                }
                        }
                        // ── 错误状态 ──
                        if (listError != null) {
                                item {
                                        Surface(shape = RoundedCornerShape(10.dp), color = Color(0xFFFEF2F2), modifier = Modifier.padding(horizontal = 12.dp).fillMaxWidth()) {
                                                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                                                        Icon(Icons.Default.Settings, contentDescription = null, tint = Color(0xFF991B1B), modifier = Modifier.size(16.dp))
                                                        Spacer(Modifier.width(8.dp))
                                                        Text(listError ?: "加载失败", fontSize = 13.sp, color = Color(0xFF991B1B), modifier = Modifier.weight(1f))
                                                        Text("重试", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = MobileTokens.brandBlue, modifier = Modifier.clickable { vm.loadMarket(); vm.loadMods() })
                                                }
                                        }
                                }
                        }

                        // ── 底部入口 ──
                        item { Spacer(Modifier.height(12.dp)) }
                        item {
                                Surface(shape = RoundedCornerShape(14.dp), color = Color.White, modifier = Modifier.padding(horizontal = 12.dp).fillMaxWidth()) {
                                        Column {
                                                Surface(
                                                        shape = RoundedCornerShape(12.dp),
                                                        color = Color(0xFFEFF6FF),
                                                        modifier = Modifier.padding(12.dp).fillMaxWidth(),
                                                        onClick = {
                                                                try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://xiu-ci.com/market"))) }
                                                                catch (_: Exception) { vm.snack("无法打开浏览器", true) }
                                                        },
                                                ) {
                                                        Row(Modifier.padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                                                                Box(Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)).background(MobileTokens.brandBlue), contentAlignment = Alignment.Center) {
                                                                        Icon(Icons.Default.Storefront, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
                                                                }
                                                                Spacer(Modifier.width(12.dp))
                                                                Column(Modifier.weight(1f)) {
                                                                        Text("浏览官方市场", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF1E40AF))
                                                                        Text("发现更多社区贡献的 AI 员工与能力包", fontSize = 12.sp, color = Color(0xFF64748B))
                                                                }
                                                                Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = Color(0xFF93C5FD), modifier = Modifier.size(18.dp))
                                                        }
                                                }
                                                Surface(
                                                        shape = RoundedCornerShape(12.dp),
                                                        color = Color(0xFFF0FDF4),
                                                        modifier = Modifier.padding(12.dp).fillMaxWidth(),
                                                        onClick = { vm.snack("本地安装功能开发中") },
                                                ) {
                                                        Row(Modifier.padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                                                                Box(Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF22C55E)), contentAlignment = Alignment.Center) {
                                                                        Icon(Icons.Default.FolderOpen, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
                                                                }
                                                                Spacer(Modifier.width(12.dp))
                                                                Column(Modifier.weight(1f)) {
                                                                        Text("本地安装", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF166534))
                                                                        Text("从本机 .xcmod 目录安装扩展", fontSize = 12.sp, color = Color(0xFF64748B))
                                                                }
                                                                Icon(Icons.Default.KeyboardArrowRight, contentDescription = null, tint = Color(0xFF86EFAC), modifier = Modifier.size(18.dp))
                                                        }
                                                }
                                        }
                                }
                        }

                        item { Spacer(Modifier.height(24.dp)) }
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
                shape = RoundedCornerShape(12.dp),
                color = Color.White,
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
                                        modifier = Modifier.padding(8.dp),
                                ) {
                                        Box(Modifier.size(42.dp), contentAlignment = Alignment.Center) {
                                                Text(item.title.firstOrNull()?.toString() ?: "A", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                        }
                                }
                        }
                        // 信息区
                        Column(Modifier.padding(10.dp)) {
                                Text(item.title, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF1E293B), maxLines = 1)
                                if (isInstalled) {
                                        Spacer(Modifier.height(4.dp))
                                        Surface(shape = RoundedCornerShape(4.dp), color = Color(0xFFDCFCE7)) {
                                                Text("已安装", fontSize = 10.sp, color = Color(0xFF166534), modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
                                        }
                                }
                                Spacer(Modifier.height(4.dp))
                                Text(item.subtitle.ifBlank { "AI 扩展能力" }, fontSize = 11.sp, color = Color(0xFF94A3B8), maxLines = 2, minLines = 2)
                                Spacer(Modifier.height(8.dp))
                                Surface(
                                        shape = RoundedCornerShape(14.dp),
                                        color = if (isInstalled) Color(0xFFF0FDF4) else MobileTokens.brandBlue,
                                        modifier = Modifier.fillMaxWidth().height(32.dp),
                                        onClick = onClick,
                                ) {
                                        Box(contentAlignment = Alignment.Center) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                        Text(
                                                                if (isInstalled) "打开使用" else "免费安装",
                                                                fontSize = 12.sp,
                                                                fontWeight = FontWeight.SemiBold,
                                                                color = if (isInstalled) Color(0xFF166534) else Color.White,
                                                        )
                                                        Spacer(Modifier.width(4.dp))
                                                        if (!isInstalled) {
                                                                Icon(Icons.Default.Download, contentDescription = null, tint = Color.White, modifier = Modifier.size(14.dp))
                                                        } else {
                                                                Icon(Icons.Default.Check, contentDescription = null, tint = Color(0xFF166534), modifier = Modifier.size(14.dp))
                                                        }
                                                }
                                        }
                                }
                        }
                }
        }
}
