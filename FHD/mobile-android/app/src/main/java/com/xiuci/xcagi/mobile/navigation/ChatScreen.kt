package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.ChatSuggestion
import com.xiuci.xcagi.mobile.ui.components.ConnectionStatusChip
import com.xiuci.xcagi.mobile.ui.components.mobile.ChatToolRow
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeChatInputBar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption

private val chatModes = listOf(
    WeModeOption("fast", "快速", Icons.Default.Bolt, "适合日常对话，即时响应"),
    WeModeOption("expert", "专家", Icons.Default.AutoAwesome, "深度分析，适合复杂业务问题"),
    WeModeOption("vision", "识图", Icons.Default.PhotoCamera, "图片识别请在工作台或 PC 端使用"),
)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: AppViewModel,
    onOpenWorkbench: () -> Unit,
    onOpenMod: (String) -> Unit,
    onOpenOcr: () -> Unit = {},
) {
    val messages by vm.chatMessages.collectAsState()
    val streaming by vm.streaming.collectAsState()
    val connectionChip by vm.chatConnectionChip.collectAsState()
    val isCloud by vm.isCloudMode.collectAsState()
    val suggestions by vm.chatSuggestions.collectAsState()
    val syncStale by vm.syncStaleHint.collectAsState()
    val canUseNativeChat by vm.canUseNativeChat.collectAsState()
    val chatAction by vm.chatAction.collectAsState()
    var input by remember { mutableStateOf("") }
    var chatMode by remember { mutableStateOf("fast") }
    var deepThinking by remember { mutableStateOf(false) }
    var smartSearch by remember { mutableStateOf(false) }
    var showMoreSheet by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    LaunchedEffect(chatMode) {
        deepThinking = chatMode == "expert"
    }

    LaunchedEffect(Unit) {
        vm.loadChatCache()
        if (suggestions.isEmpty()) vm.loadHomeHub()
    }

    LaunchedEffect(messages.size, streaming) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    fun submitMessage() {
        val text = input.trim()
        if (text.isBlank() && !streaming) return
        if (streaming) {
            vm.stopChat()
            return
        }
        when (chatMode) {
            "vision" -> {
                onOpenOcr()
                return
            }
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

    if (showMoreSheet) {
        ModalBottomSheet(
            onDismissRequest = { showMoreSheet = false },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.padding(bottom = 24.dp)) {
                Text(
                    "更多能力",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 8.dp),
                )
                WeCellGroup {
                    WeCell(
                        title = "深度思考",
                        subtitle = if (deepThinking) "已开启" else "关闭",
                        showArrow = false,
                        trailing = {
                            androidx.compose.material3.Switch(
                                checked = deepThinking,
                                onCheckedChange = {
                                    deepThinking = it
                                    if (it) chatMode = "expert"
                                },
                            )
                        },
                        onClick = {
                            deepThinking = !deepThinking
                            if (deepThinking) chatMode = "expert"
                        },
                    )
                    WeCell(
                        title = "工作台",
                        subtitle = "打开 MODstore 网页版",
                        showArrow = true,
                        onClick = {
                            showMoreSheet = false
                            onOpenWorkbench()
                        },
                    )
                    WeCell(
                        title = "OCR 拍照识别",
                        showArrow = true,
                        showDivider = false,
                        onClick = {
                            showMoreSheet = false
                            onOpenOcr()
                        },
                    )
                }
                Spacer(Modifier.height(8.dp))
                WeCellGroup {
                    WeCell(
                        title = "语音输入",
                        subtitle = "即将上线",
                        showArrow = false,
                        showDivider = false,
                        onClick = { vm.snack("语音输入即将上线") },
                    )
                }
            }
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            Column {
                TopAppBar(
                    title = { Text("对话") },
                    actions = {
                        ConnectionStatusChip(
                            label = connectionChip,
                            isCloud = isCloud,
                            modifier = Modifier.padding(end = 4.dp),
                        )
                        IconButton(onClick = { vm.clearChat() }) {
                            Icon(Icons.Default.AddComment, contentDescription = "新对话")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                    ),
                )
                HorizontalDivider(
                    thickness = 0.5.dp,
                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                )
            }
        },
        bottomBar = {
            Column {
                ChatToolRow(
                    modeOptions = chatModes,
                    selectedModeId = chatMode,
                    onModeSelect = { chatMode = it },
                    smartSearch = smartSearch,
                    onSmartSearchChange = { smartSearch = it },
                    onMore = { showMoreSheet = true },
                )
                WeChatInputBar(
                    value = input,
                    onValueChange = { input = it },
                    placeholder = if (chatMode == "vision") "识图模式：点击发送进入 OCR" else "发消息，或输入你的问题…",
                    onSend = { submitMessage() },
                    onStop = { vm.stopChat() },
                    streaming = streaming,
                    onVoice = { vm.snack("语音输入即将上线") },
                )
            }
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (!canUseNativeChat) {
                Text(
                    "云端账号请在工作台使用 AI；连接电脑并登录电脑端账号后可使用本页原生对话。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 4.dp),
                )
            }
            if (syncStale) {
                Text(
                    "数据可能不是最新，请在「我的」执行立即同步。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 4.dp),
                )
            }
            chatAction?.let { action ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    when (action.type) {
                        "workbench" -> Button(onClick = {
                            vm.clearChatAction()
                            onOpenWorkbench()
                        }) { Text("打开工作台") }
                        "mod" -> Button(onClick = {
                            vm.clearChatAction()
                            onOpenMod(action.targetId)
                        }) { Text("打开 ${action.label}") }
                    }
                }
            }

            if (messages.isEmpty()) {
                ChatEmptyState(
                    chatMode = chatMode,
                    suggestions = suggestions,
                    streaming = streaming,
                    onSuggestionClick = { prompt ->
                        input = prompt
                        vm.sendChat(prompt)
                    },
                )
            } else {
                LazyColumn(
                    Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 8.dp),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(messages) { (role, text) ->
                        ChatBubble(role = role, text = text)
                    }
                    if (streaming) {
                        item {
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Start,
                            ) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(20.dp),
                                    strokeWidth = 2.dp,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChatEmptyState(
    chatMode: String,
    suggestions: List<ChatSuggestion>,
    streaming: Boolean,
    onSuggestionClick: (String) -> Unit,
) {
    val modeLabel = chatModes.firstOrNull { it.id == chatMode }?.label ?: "快速"
    val modeHint = chatModes.firstOrNull { it.id == chatMode }?.hint.orEmpty()
    val displaySuggestions = suggestions.take(3)

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = MobileTokens.horizontalPagePadding),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            painter = painterResource(R.mipmap.ic_launcher_foreground),
            contentDescription = null,
            modifier = Modifier.size(56.dp),
            tint = Color.Unspecified,
        )
        Spacer(Modifier.height(MobileTokens.sectionSpacing))
        Text(
            "你好，我是 XCAGI",
            style = MaterialTheme.typography.headlineSmall,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "使用${modeLabel}模式，直接输入问题开始对话",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        if (modeHint.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(
                modeHint,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        if (displaySuggestions.isNotEmpty()) {
            Spacer(Modifier.height(24.dp))
            Text(
                "试试这些问题",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
            )
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                maxItemsInEachRow = 1,
            ) {
                displaySuggestions.forEach { s ->
                    FilterChip(
                        selected = false,
                        onClick = { if (!streaming) onSuggestionClick(s.prompt) },
                        label = {
                            Text(
                                s.label,
                                modifier = Modifier.fillMaxWidth(),
                                maxLines = 2,
                            )
                        },
                        modifier = Modifier.fillMaxWidth(0.92f),
                    )
                }
            }
        }
    }
}

@Composable
private fun ChatBubble(role: String, text: String) {
    val isUser = role == "user"
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            modifier = Modifier.widthIn(max = 320.dp),
            shape = RoundedCornerShape(
                topStart = 12.dp,
                topEnd = 12.dp,
                bottomStart = if (isUser) 12.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 12.dp,
            ),
            color = if (isUser) {
                MobileTokens.accent()
            } else {
                MaterialTheme.colorScheme.surface
            },
            shadowElevation = if (isUser) 0.dp else 1.dp,
        ) {
            Text(
                text,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isUser) Color.White else MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            )
        }
    }
}
