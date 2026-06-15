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
import androidx.compose.material.icons.filled.ArrowBack
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
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeCapsule
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

// ── 微信风格色值 ──
private val WeChatGreen = Color(0xFF95EC69)       // 微信绿气泡
private val WeChatBubbleBg = Color(0xFFF5F5F5)    // AI 气泡灰底
private val WeChatInputBg = Color(0xFFF7F7F7)     // 输入区背景
private val WeChatDivider = Color(0xFFE5E5E5)

private val chatModes = listOf(
    WeModeOption("fast", "快速", Icons.Default.Bolt, "即时响应"),
    WeModeOption("expert", "深度", Icons.Default.AutoAwesome, "深度分析"),
    WeModeOption("vision", "识图", Icons.Default.PhotoCamera, "图片识别"),
)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: AppViewModel,
    onOpenMod: (String) -> Unit,
    onOpenOcr: () -> Unit = {},
    onNavigateToEmployees: () -> Unit = {},
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

    LaunchedEffect(chatMode) { deepThinking = chatMode == "expert" }

    LaunchedEffect(Unit) {
        vm.loadChatCache()
        if (suggestions.isEmpty()) vm.loadHomeHub()
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
            containerColor = Color.White,
        ) {
            Column(Modifier.padding(bottom = 24.dp)) {
                Text(
                    "更多能力",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
                HorizontalDivider(thickness = 0.5.dp, color = MobileTokens.divider)
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
                        iconTint = MobileTokens.iconFgGreen,
                        iconBg = MobileTokens.iconBgGreen,
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
        containerColor = Color.White,
        topBar = {
            WeTopBar(
                title = "智能对话",
                showRightAdd = true,
                onRightAdd = onNavigateToEmployees,
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
                .background(MobileTokens.surfaceBg), // 微信聊天背景灰
        ) {
            // ── 提示条 ──
            if (syncStale) {
                Surface(
                    color = Color(0xFFFFF8E1),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "数据同步中，部分内容可能延迟。",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFFF57F17),
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                    )
                }
            }

            // ── 快捷操作条 ──
            chatAction?.let { action ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    when (action.type) {
                        "mod" -> Button(
                            onClick = { vm.clearChatAction(); onOpenMod(action.targetId) },
                            shape = RoundedCornerShape(8.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = MobileTokens.brandBlue),
                        ) { Text("打开 ${action.label}", fontSize = 13.sp) }
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
                        .padding(horizontal = 12.dp, vertical = 8.dp),
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
                    .background(MobileTokens.brandBlue),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(24.dp),
                    tint = Color.White,
                )
            }
            Spacer(Modifier.size(8.dp))
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
                .background(if (isUser) WeChatGreen else Color.White),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text,
                    fontSize = 15.sp,
                    lineHeight = 22.sp,
                    color = if (isUser) MobileTokens.textPrimary else MobileTokens.textPrimary,
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
                        fontSize = 15.sp,
                        color = MobileTokens.brandBlue.copy(alpha = cursorAlpha),
                    )
                }
            }
        }

        // 用户头像
        if (isUser) {
            Spacer(Modifier.size(8.dp))
            Box(
                Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(Color(0xFFCCCCCC)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "我",
                    fontSize = 14.sp,
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
    Column(
        modifier
            .fillMaxWidth()
            .background(Color.White)
            .drawBehind {
                drawLine(WeChatDivider, Offset(0f, 0f), Offset(size.width, 0f), strokeWidth = 0.5.dp.toPx())
            },
    ) {
        // ── 功能标签行 ──
        if (onDeepThinking != null || onSmartSearch != null) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
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
                .padding(horizontal = 8.dp, vertical = 6.dp),
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
                        tint = MobileTokens.textSecondary,
                        modifier = Modifier.size(22.dp),
                    )
                }
            }

            // 输入框（weight 必须在 Row 直接子元素 Surface 上）
            Surface(
                shape = RoundedCornerShape(6.dp),
                color = WeChatInputBg,
                border = androidx.compose.foundation.BorderStroke(0.5.dp, WeChatDivider),
                modifier = Modifier.weight(1f),
            ) {
                androidx.compose.foundation.text.BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = MobileTokens.textPrimary,
                    ),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                            if (value.isEmpty()) {
                                Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MobileTokens.textDisabled)
                            }
                            inner()
                        }
                    },
                )
            }

            // 发送/停止按钮（始终显示蓝圆）
            Surface(
                shape = CircleShape,
                color = MobileTokens.brandBlue,
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
                        tint = MobileTokens.textSecondary,
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
        if (selected) MobileTokens.brandBlueLight else MobileTokens.surfaceBg,
        animationSpec = tween(200),
    )
    val fg by animateColorAsState(
        if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
        animationSpec = tween(200),
    )
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = bg,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
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
            Text(label, fontSize = 11.sp, fontWeight = FontWeight.Medium, color = fg)
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
            .padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.weight(1f))

        // Logo
        Box(
            Modifier
                .size(56.dp)
                .clip(CircleShape)
                .background(MobileTokens.brandBlue.copy(alpha = 0.1f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                painter = painterResource(R.mipmap.ic_launcher_foreground),
                contentDescription = null,
                modifier = Modifier.size(36.dp),
                tint = MobileTokens.brandBlue,
            )
        }
        Spacer(Modifier.height(12.dp))
        Text(
            "智能对话 · ${modeLabel}模式",
            fontSize = 17.sp,
            fontWeight = FontWeight.SemiBold,
            color = MobileTokens.textPrimary,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            modeHint.ifBlank { "输入问题开始对话" },
            fontSize = 13.sp,
            color = MobileTokens.textTertiary,
        )
        Spacer(Modifier.height(20.dp))

        // 模式切换
        WeModeCapsule(
            options = chatModes,
            selectedId = chatMode,
            onSelect = onModeSelect,
        )

        // 快捷建议（桌面端风格）
        if (displaySuggestions.isNotEmpty()) {
            Spacer(Modifier.height(24.dp))
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                displaySuggestions.forEach { s ->
                    Surface(
                        modifier = Modifier
                            .clip(RoundedCornerShape(16.dp))
                            .clickable { if (!streaming) onSuggestionClick(s.prompt) },
                        color = Color.White,
                        border = androidx.compose.foundation.BorderStroke(0.5.dp, WeChatDivider),
                    ) {
                        Text(
                            text = s.label,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                            fontSize = 13.sp,
                            color = MobileTokens.textSecondary,
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
    onSelect: (String) -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()

    Scaffold(
        containerColor = Color(0xFFEDEDED),
        topBar = {
            androidx.compose.material3.TopAppBar(
                title = {
                    Text(
                        "AI 员工${modInfos.size.takeIf { it > 0 }?.let { "($it)" }.orEmpty()}",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = Color.Black,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "返回")
                    }
                },
                colors = androidx.compose.material3.TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.White,
                ),
            )
        },
    ) { padding ->
        if (modInfos.isEmpty()) {
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
                        tint = Color(0xFFCCCCCC),
                    )
                    Spacer(Modifier.height(12.dp))
                    Text("暂无 AI 员工", fontSize = 15.sp, color = MobileTokens.textTertiary)
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                items(modInfos) { mod ->
                    Surface(
                        color = Color.White,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(mod.name) },
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // 彩色头像（首字）
                            val avatarColors = listOf(
                                Color(0xFF4A90D9), Color(0xFFE74C3C), Color(0xFF2ECC71),
                                Color(0xFFF39C12), Color(0xFF9B59B6), Color(0xFF1ABC9C),
                                Color(0xFFE67E22), Color(0xFF3498DB),
                            )
                            val avatarColor = avatarColors[kotlin.math.abs(mod.name.hashCode()) % avatarColors.size]
                            Box(
                                Modifier
                                    .size(48.dp)
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(avatarColor),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    mod.name.firstOrNull()?.toString() ?: "A",
                                    fontSize = 20.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = Color.White,
                                )
                            }
                            Spacer(Modifier.width(12.dp))

                            // 名称 + 描述
                            Column(Modifier.weight(1f)) {
                                Text(
                                    mod.name,
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = Color(0xFF1A1A1A),
                                    maxLines = 1,
                                )
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    mod.description.takeIf { it.isNotBlank() }
                                        ?: "智能助手 · ${mod.author.takeIf { it.isNotBlank() } ?: "XCAGI"}",
                                    fontSize = 13.sp,
                                    color = Color(0xFF999999),
                                    maxLines = 1,
                                )
                            }

                            // 右箭头
                            Icon(
                                Icons.Default.ChevronRight,
                                contentDescription = null,
                                tint = Color(0xFFCCCCCC),
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                    HorizontalDivider(thickness = 0.5.dp, color = Color(0xFFE5E5E5), modifier = Modifier.padding(start = 72.dp))
                }
            }
        }
    }
}
