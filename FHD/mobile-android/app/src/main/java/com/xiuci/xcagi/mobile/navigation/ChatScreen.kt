package com.xiuci.xcagi.mobile.navigation

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.ChatSuggestion
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeCapsule
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBarAvatarAction
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

// ── 微信风格色值（保留作为装饰性常量，未在新设计系统中使用） ──
// 已迁移至 XcagiTheme.extra.weChatGreen / MaterialTheme.colorScheme
private val WeChatBubbleBg = Color(0xFFF5F5F5)    // AI 气泡灰底（保留兼容）

data class ChatTopProfileAvatar(
    val text: String,
    val containerColor: Color,
    val contentColor: Color = Color.White,
)

private data class EmployeeConversationRef(
    val modId: String,
    val employeeId: String,
)

private fun parseEmployeeConversationRef(conversationId: String?): EmployeeConversationRef? {
    val raw = conversationId?.trim().orEmpty()
    if (!raw.startsWith("employee:")) return null
    val parts = raw.split(":")
    if (parts.size != 3) return null
    return EmployeeConversationRef(modId = parts[1], employeeId = parts[2])
}

private val chatModes = listOf(
    WeModeOption("fast", "快速", Icons.Default.Bolt, "即时响应"),
    WeModeOption("expert", "深度", Icons.Default.AutoAwesome, "深度分析"),
    WeModeOption("vision", "识图", Icons.Default.PhotoCamera, "图片识别"),
)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: AppViewModel,
    conversationId: String? = null,          // 新增：会话 ID，null 表示 AI 对话模式
    conversationTitle: String = "小C助理",   // 新增：顶部栏标题，默认"小C助理"
    onBack: (() -> Unit)? = null,
    onOpenMod: (String) -> Unit = {},
    onOpenOcr: () -> Unit = {},
    profileAvatar: ChatTopProfileAvatar? = null,
    onOpenProfile: (() -> Unit)? = null,
    onOpenEmployeeProfile: (String, String) -> Unit = { _, _ -> },
) {
    val messages by vm.chatMessages.collectAsState()
    val streaming by vm.streaming.collectAsState()
    val connectionChip by vm.chatConnectionChip.collectAsState()
    val isAgent by vm.isAgentControlActive.collectAsState()
    val isCloud by vm.isCloudMode.collectAsState()
    val suggestions by vm.chatSuggestions.collectAsState()
    val syncStale by vm.syncStaleHint.collectAsState()
    val chatAction by vm.chatAction.collectAsState()
    var input by remember { mutableStateOf("") }
    var chatMode by remember { mutableStateOf("fast") }
    var deepThinking by remember { mutableStateOf(false) }
    var smartSearch by remember { mutableStateOf(false) }
    var showMoreSheet by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    val employeeRef = remember(conversationId) { parseEmployeeConversationRef(conversationId) }
    val employeeProfile =
        remember(employeeRef, employees) {
            employeeRef?.let { employees.findEmployee(it.modId, it.employeeId) }
        }
    val resolvedTitle = employeeProfile?.name ?: conversationTitle
    val resolvedProfileAvatar =
        employeeProfile?.let {
            ChatTopProfileAvatar(
                text = it.avatarText,
                containerColor = aiEmployeeAvatarColor(it.key),
            )
        } ?: profileAvatar

    LaunchedEffect(chatMode) { deepThinking = chatMode == "expert" }

    LaunchedEffect(Unit) {
        vm.loadChatCache()
        if (suggestions.isEmpty()) vm.loadHomeHub()
    }

    LaunchedEffect(employeeRef?.modId, employeeRef?.employeeId) {
        if (employeeRef != null) {
            vm.refreshModInfos()
        }
    }

    LaunchedEffect(messages.size, streaming) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    fun submitMessage() {
        val text = input.trim()
        if (text.isBlank() && !streaming) return
        if (streaming) { vm.stopChat(); return }
        when (chatMode) {
            "vision" -> { onOpenOcr(); return }
            else -> {
                val prefix = buildString {
                    if (deepThinking) append("[深度思考] ")
                    if (smartSearch) append("[智能搜索] ")
                }
                vm.sendChat(prefix + text)
                input = ""
            }
        }
    }

    // ── 更多能力 BottomSheet ──
    if (showMoreSheet) {
        ModalBottomSheet(
            onDismissRequest = { showMoreSheet = false },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.padding(bottom = Spacing.xxl)) {
                Text(
                    "更多能力",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                )
                HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
                WeCellGroup {
                    WeCell(
                        title = "深度思考",
                        subtitle = if (deepThinking) "已开启" else "关闭",
                        showArrow = false,
                        trailing = {
                            androidx.compose.material3.Switch(
                                checked = deepThinking,
                                onCheckedChange = { deepThinking = it; if (it) chatMode = "expert" },
                            )
                        },
                        onClick = { deepThinking = !deepThinking; if (deepThinking) chatMode = "expert" },
                    )
                    WeCell(
                        title = "OCR 拍照识别",
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = { showMoreSheet = false; onOpenOcr() },
                    )
                }
            }
        }
    }

    // ── 提示条 ──
    Scaffold(
        containerColor = MaterialTheme.colorScheme.surface,
        topBar = {
            WeTopBar(
                title = resolvedTitle,
                onBack = onBack,
                customActions = {
                    val clickAction = when {
                        employeeProfile != null -> {
                            { onOpenEmployeeProfile(employeeProfile.modId, employeeProfile.employeeId) }
                        }
                        resolvedProfileAvatar != null && onOpenProfile != null -> onOpenProfile
                        else -> null
                    }
                    if (resolvedProfileAvatar != null && clickAction != null) {
                        WeTopBarAvatarAction(
                            text = resolvedProfileAvatar.text,
                            onClick = clickAction,
                            containerColor = resolvedProfileAvatar.containerColor,
                            contentColor = resolvedProfileAvatar.contentColor,
                        )
                    }
                },
            )
        },
        bottomBar = {
            WeChatStyleInputBar(
                value = input,
                onValueChange = { input = it },
                placeholder = when {
                    deepThinking -> "深度思考模式，输入复杂问题..."
                    smartSearch -> "智能搜索，输入关键词..."
                    else -> "发消息"
                },
                onSend = { submitMessage() },
                onStop = { vm.stopChat() },
                streaming = streaming,
                onVoice = { vm.snack("语音输入功能即将上线，敬请期待") },
                onMore = { showMoreSheet = true },
                onDeepThinking = { deepThinking = !deepThinking; if (deepThinking) chatMode = "expert" },
                deepThinking = deepThinking,
                onSmartSearch = { smartSearch = !smartSearch },
                smartSearch = smartSearch,
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .background(MaterialTheme.colorScheme.background), // 微信聊天背景灰
        ) {
            // ── 提示条 ──
            if (syncStale) {
                Surface(
                    color = XcagiTheme.extra.warning.copy(alpha = 0.1f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "数据同步中，部分内容可能延迟。",
                        style = MaterialTheme.typography.bodySmall,
                        color = XcagiTheme.extra.warning,
                        modifier = Modifier.padding(horizontal = Spacing.lg, vertical = 6.dp),
                    )
                }
            }

            // ── 快捷操作条 ──
            chatAction?.let { action ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = Spacing.md, vertical = Spacing.xs),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    when (action.type) {
                        "mod" -> Button(
                            onClick = { vm.clearChatAction(); onOpenMod(action.targetId) },
                            shape = MaterialTheme.shapes.small,
                            colors = ButtonDefaults.buttonColors(containerColor = XcagiTheme.extra.brandBlue),
                        ) { Text("打开 ${action.label}", style = MaterialTheme.typography.labelMedium) }
                    }
                }
            }

            // ── 消息区 ──
            if (messages.isEmpty()) {
                ChatEmptyState(
                    chatMode = chatMode,
                    onModeSelect = { chatMode = it },
                    modeHint = chatModes.firstOrNull { it.id == chatMode }?.hint.orEmpty(),
                    suggestions = suggestions,
                    streaming = streaming,
                    onSuggestionClick = { prompt -> input = prompt; vm.sendChat(prompt) },
                )
            } else {
                LazyColumn(
                    Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = Spacing.md, vertical = Spacing.sm),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(messages) { (role, text) ->
                        val isLastAssistant = messages.lastIndex == messages.indexOfFirst { it.first == "assistant" && it.second == text }
                        WeChatBubble(
                            role = role,
                            text = text,
                            isStreaming = streaming && isLastAssistant && role == "assistant",
                        )
                    }

                }
            }
        }
    }
}

// ── 微信风格消息气泡 ──
@Composable
private fun WeChatBubble(role: String, text: String, isStreaming: Boolean = false) {
    val isUser = role == "user"
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        // AI 头像
        if (!isUser) {
            Box(
                Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(XcagiTheme.extra.brandBlue),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(24.dp),
                    tint = Color.White,
                )
            }
            Spacer(Modifier.size(Spacing.sm))
        }

        // 气泡
        Box(
            Modifier
                .widthIn(max = 260.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 8.dp,
                        topEnd = 8.dp,
                        bottomStart = if (isUser) 8.dp else 2.dp,
                        bottomEnd = if (isUser) 2.dp else 8.dp,
                    )
                )
                .background(if (isUser) XcagiTheme.extra.weChatGreen else MaterialTheme.colorScheme.surface),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                Modifier.padding(horizontal = Spacing.md, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (isStreaming && !isUser) {
                    val infiniteTransition = rememberInfiniteTransition(label = "cursor")
                    val cursorAlpha by infiniteTransition.animateFloat(
                        initialValue = 0f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(530),
                            repeatMode = RepeatMode.Reverse,
                        ),
                    )
                    Text(
                        "▌",
                        style = MaterialTheme.typography.bodyMedium,
                        color = XcagiTheme.extra.brandBlue.copy(alpha = cursorAlpha),
                    )
                }
            }
        }

        // 用户头像
        if (isUser) {
            Spacer(Modifier.size(Spacing.sm))
            Box(
                Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "我",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Medium,
                    color = Color.White,
                )
            }
        }
    }
}

// ── 微信风格输入栏 ──
@Composable
private fun WeChatStyleInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    modifier: Modifier = Modifier,
    onVoice: (() -> Unit)? = null,
    onMore: (() -> Unit)? = null,
    onDeepThinking: (() -> Unit)? = null,
    deepThinking: Boolean = false,
    onSmartSearch: (() -> Unit)? = null,
    smartSearch: Boolean = false,
) {
    val dividerColor = MaterialTheme.colorScheme.outlineVariant
    Column(
        modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .drawBehind {
                drawLine(dividerColor, Offset(0f, 0f), Offset(size.width, 0f), strokeWidth = 0.5.dp.toPx())
            },
    ) {
        // ── 功能标签行 ──
        if (onDeepThinking != null || onSmartSearch != null) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = Spacing.md, vertical = Spacing.xs),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (onDeepThinking != null) {
                    WeInputChip(
                        label = "深度思考",
                        selected = deepThinking,
                        onClick = onDeepThinking,
                    )
                }
                if (onSmartSearch != null) {
                    WeInputChip(
                        label = "智能搜索",
                        selected = smartSearch,
                        onClick = onSmartSearch,
                    )
                }
            }
        }

        // ── 输入行 ──
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.sm, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // 语音按钮
            if (onVoice != null) {
                Box(
                    Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .clickable(onClick = onVoice),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = "语音",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(22.dp),
                    )
                }
            }

            // 输入框（weight 必须在 Row 直接子元素 Surface 上）
            Surface(
                shape = MaterialTheme.shapes.extraSmall,
                color = MaterialTheme.colorScheme.background,
                border = androidx.compose.foundation.BorderStroke(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.weight(1f),
            ) {
                androidx.compose.foundation.text.BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = Spacing.sm),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                    ),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                            if (value.isEmpty()) {
                                Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                            }
                            inner()
                        }
                    },
                )
            }

            // 发送/停止按钮（始终显示蓝圆）
            Surface(
                shape = CircleShape,
                color = XcagiTheme.extra.brandBlue,
                modifier = Modifier
                    .size(36.dp)
                    .clickable { if (streaming) onStop() else onSend() },
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        if (streaming) Icons.Default.Stop else Icons.AutoMirrored.Filled.Send,
                        contentDescription = if (streaming) "停止" else "发送",
                        tint = Color.White,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            // 更多按钮
            if (onMore != null) {
                Box(
                    Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .clickable(onClick = onMore),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.MoreHoriz,
                        contentDescription = "更多",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(22.dp),
                    )
                }
            }
        }
    }
}

// ── 功能标签 Chip ──
@Composable
private fun WeInputChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val bg by animateColorAsState(
        if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.background,
        animationSpec = tween(200),
    )
    val fg by animateColorAsState(
        if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outline,
        animationSpec = tween(200),
    )
    Surface(
        shape = MaterialTheme.shapes.medium,
        color = bg,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = Spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            if (selected) {
                Icon(
                    Icons.Default.Bolt,
                    contentDescription = null,
                    modifier = Modifier.size(12.dp),
                    tint = fg,
                )
            }
            Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Medium, color = fg)
            if (selected) {
                Icon(
                    Icons.Default.Close,
                    contentDescription = null,
                    modifier = Modifier
                        .size(10.dp)
                        .clickable(onClick = onClick),
                    tint = fg,
                )
            }
        }
    }
}

// ── 空状态（微信风格居中 + 桌面端快捷建议） ──
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChatEmptyState(
    chatMode: String,
    onModeSelect: (String) -> Unit,
    modeHint: String,
    suggestions: List<ChatSuggestion>,
    streaming: Boolean,
    onSuggestionClick: (String) -> Unit,
) {
    val modeLabel = chatModes.firstOrNull { it.id == chatMode }?.label ?: "快速"
    val displaySuggestions = suggestions.take(4)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = Spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.weight(1f))

        // Logo
        Box(
            Modifier
                .size(56.dp)
                .clip(CircleShape)
                .background(XcagiTheme.extra.brandBlue.copy(alpha = 0.1f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                painter = painterResource(R.mipmap.ic_launcher_foreground),
                contentDescription = null,
                modifier = Modifier.size(36.dp),
                tint = XcagiTheme.extra.brandBlue,
            )
        }
        Spacer(Modifier.height(Spacing.md))
        Text(
            "智能对话 · ${modeLabel}模式",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(Spacing.xs))
        Text(
            modeHint.ifBlank { "输入问题开始对话" },
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(Spacing.xl))

        // 模式切换
        WeModeCapsule(
            options = chatModes,
            selectedId = chatMode,
            onSelect = onModeSelect,
        )

        // 快捷建议（桌面端风格）
        if (displaySuggestions.isNotEmpty()) {
            Spacer(Modifier.height(Spacing.xxl))
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                displaySuggestions.forEach { s ->
                    Surface(
                        modifier = Modifier
                            .clip(MaterialTheme.shapes.large)
                            .clickable { if (!streaming) onSuggestionClick(s.prompt) },
                        color = MaterialTheme.colorScheme.surface,
                        border = androidx.compose.foundation.BorderStroke(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Text(
                            text = s.label,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = Spacing.sm),
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        Spacer(Modifier.weight(1f))
    }
}

// ── AI 员工列表页（微信聊天列表风格，独立页面） ──
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiEmployeeListScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onSelect: (String, String) -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }

    LaunchedEffect(Unit) { vm.refreshModInfos() }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            androidx.compose.material3.TopAppBar(
                title = {
                    Text(
                        "AI 员工${employees.size.takeIf { it > 0 }?.let { "($it)" }.orEmpty()}",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                colors = androidx.compose.material3.TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
            )
        },
    ) { padding ->
        if (employees.isEmpty()) {
            Box(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(vertical = 48.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Default.SmartToy,
                        contentDescription = null,
                        modifier = Modifier.size(48.dp),
                        tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                    )
                    Spacer(Modifier.height(Spacing.md))
                    Text("暂无 AI 员工", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                items(employees, key = { it.key }) { employee ->
                    Surface(
                        color = MaterialTheme.colorScheme.surface,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(employee.modId, employee.employeeId) },
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(horizontal = Spacing.md, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // 彩色头像（首字）
                            val avatarColors = listOf(
                                Color(0xFF4A90D9), Color(0xFFE74C3C), Color(0xFF2ECC71),
                                Color(0xFFF39C12), Color(0xFF9B59B6), Color(0xFF1ABC9C),
                                Color(0xFFE67E22), Color(0xFF3498DB),
                            )
                            val avatarColor = avatarColors[kotlin.math.abs(employee.key.hashCode()) % avatarColors.size]
                            Box(
                                Modifier
                                    .size(48.dp)
                                    .clip(MaterialTheme.shapes.extraSmall)
                                    .background(avatarColor),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    employee.avatarText,
                                    style = MaterialTheme.typography.headlineSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = Color.White,
                                )
                            }
                            Spacer(Modifier.width(Spacing.md))

                            // 名称 + 描述
                            Column(Modifier.weight(1f)) {
                                Text(
                                    employee.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.Medium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                    maxLines = 1,
                                )
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    employee.summary,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.outline,
                                    maxLines = 1,
                                )
                            }

                            // 右箭头
                            Icon(
                                Icons.Default.ChevronRight,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                    HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(start = 72.dp))
                }
            }
        }
    }
}
