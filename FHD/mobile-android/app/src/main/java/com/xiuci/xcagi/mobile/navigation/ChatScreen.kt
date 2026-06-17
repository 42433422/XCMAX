package com.xiuci.xcagi.mobile.navigation

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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import com.xiuci.xcagi.mobile.ui.components.ConnectionStatusChip
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeChatInputBar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeCapsule
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption

private val chatModes = listOf(
    WeModeOption("fast", "快速模式", Icons.Default.Bolt, "适合日常对话，即时响应"),
    WeModeOption("expert", "专家模式", Icons.Default.AutoAwesome, "深度分析，适合复杂业务问题"),
    WeModeOption("vision", "识图模式", Icons.Default.PhotoCamera, "图片识别请在工作台或 PC 端使用"),
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
    val listState = rememberLazyListState()

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

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            Column {
                TopAppBar(
                    title = { Text("对话") },
                    navigationIcon = {
                        IconButton(onClick = { /* 历史会话占位 */ }) {
                            Icon(Icons.Default.Menu, contentDescription = "菜单")
                        }
                    },
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
            WeChatInputBar(
                value = input,
                onValueChange = { input = it },
                placeholder = if (chatMode == "vision") "识图模式：点击发送进入 OCR" else "发消息或按住说话",
                deepThinking = deepThinking,
                onDeepThinkingChange = { deepThinking = it },
                smartSearch = smartSearch,
                onSmartSearchChange = { smartSearch = it },
                onSend = { submitMessage() },
                onStop = { vm.stopChat() },
                streaming = streaming,
                onAttach = { onOpenWorkbench() },
                onVoice = { vm.snack("语音输入即将上线") },
            )
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
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            if (syncStale) {
                Text(
                    "数据可能不是最新，请在「我的」执行立即同步。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            chatAction?.let { action ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp),
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
                Column(
                    Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Icon(
                        painter = painterResource(R.mipmap.ic_launcher),
                        contentDescription = null,
                        modifier = Modifier.size(56.dp),
                        tint = Color.Unspecified,
                    )
                    Spacer(Modifier.height(16.dp))
                    Text(
                        "使用${chatModes.firstOrNull { it.id == chatMode }?.label ?: "快速模式"}开始对话",
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center,
                    )
                    Spacer(Modifier.height(20.dp))
                    WeModeCapsule(
                        options = chatModes,
                        selectedId = chatMode,
                        onSelect = { chatMode = it },
                    )
                    Spacer(Modifier.height(12.dp))
                    Text(
                        chatModes.firstOrNull { it.id == chatMode }?.hint.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                    if (suggestions.isNotEmpty()) {
                        Spacer(Modifier.height(20.dp))
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            suggestions.forEach { s ->
                                FilterChip(
                                    selected = false,
                                    onClick = {
                                        input = s.prompt
                                        vm.sendChat(s.prompt)
                                    },
                                    label = { Text(s.label) },
                                )
                            }
                        }
                    }
                }
            } else {
                LazyColumn(
                    Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(messages) { (role, text) ->
                        ChatBubble(role = role, text = text)
                    }
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
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp,
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
