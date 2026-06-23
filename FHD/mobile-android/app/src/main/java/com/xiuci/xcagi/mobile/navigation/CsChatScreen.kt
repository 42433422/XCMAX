package com.xiuci.xcagi.mobile.navigation

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
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBarAvatarAction
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageActionMenu
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageAvatarLayout
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CsChatScreen(
    vm: AppViewModel,
    onBack: () -> Unit = {},
    onOpenProfile: () -> Unit = {},
) {
    val messages by vm.csMessages.collectAsState()
    val streaming by vm.csStreaming.collectAsState()
    val csInfo by vm.csInfo.collectAsState()
    var input by remember { mutableStateOf("") }
    var showVoiceSheet by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current

    // 录音权限请求
    val recordPermissionLauncher =
            androidx.activity.compose.rememberLauncherForActivityResult(
                    androidx.activity.result.contract.ActivityResultContracts.RequestPermission()
            ) { granted ->
                if (granted) showVoiceSheet = true
                else vm.snack("需要麦克风权限才能使用语音输入")
            }

    fun startVoiceInput() {
        val hasPermission =
                androidx.core.content.ContextCompat.checkSelfPermission(
                        context,
                        android.Manifest.permission.RECORD_AUDIO,
                ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (hasPermission) showVoiceSheet = true
        else recordPermissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
    }

    LaunchedEffect(Unit) {
        launch { vm.loadCsInfo() }
        launch { vm.loadCsMessages() }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    // 语音输入 BottomSheet
    if (showVoiceSheet) {
        com.xiuci.xcagi.mobile.core.speech.VoiceInputSheet(
                onResult = { text ->
                    input = if (input.isBlank()) text else "$input $text"
                },
                onDismiss = { showVoiceSheet = false },
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.surface,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            "专属客服",
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        csInfo?.let { info ->
                            if (info.online) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Box(
                                        Modifier
                                            .size(Spacing.sm)
                                            .background(XcagiTheme.extra.weChatOnline, CircleShape),
                                    )
                                    Spacer(Modifier.width(Spacing.xs))
                                    Text(
                                        info.name.ifBlank { "客服在线" },
                                        style = MaterialTheme.typography.labelSmall,
                                        color = XcagiTheme.extra.weChatOnline,
                                    )
                                }
                            } else {
                                Text(
                                    info.name.ifBlank { "客服离线" },
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                        )
                    }
                },
                actions = {
                    WeTopBarAvatarAction(
                        fallback = AppAvatarFallback.CUSTOMER_SERVICE,
                        onClick = onOpenProfile,
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                windowInsets = WindowInsets(0.dp),
            )
        },
        bottomBar = {
            WeChatStyleInputBarForCs(
                value = input,
                onValueChange = { input = it },
                onSend = {
                    val text = input.trim()
                    if (text.isNotBlank() && !streaming) {
                        scope.launch { vm.sendCsMessage(text) }
                        input = ""
                    }
                },
                onStop = { vm.stopCsStream() },
                streaming = streaming,
                onVoice = { startVoiceInput() },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .background(MaterialTheme.colorScheme.background),
        ) {
            // 空状态
            if (messages.isEmpty()) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .padding(vertical = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(
                            Icons.Default.SupportAgent,
                            contentDescription = null,
                            modifier = Modifier.size(48.dp),
                            tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                        )
                        Spacer(Modifier.height(Spacing.md))
                        Text(
                            "向专属客服提问",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        Text(
                            "客服上线后会尽快回复您",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                        )
                    }
                }
            } else {
                LazyColumn(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = Spacing.md, vertical = Spacing.sm),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(messages) { msg ->
                        CsMessageBubble(
                            msg = msg,
                            isStreaming = streaming &&
                                messages.indexOf(msg) == messages.lastIndex &&
                                msg.sender == "cs",
                            onReply = { input = "引用「" + msg.body.take(60) + "」\n" + input },
                            onDelete = { vm.deleteCsMessage(msg) },
                        )
                    }
                }
            }
        }
    }
}

// ── 客服消息气泡 ──
@Composable
private fun CsMessageBubble(
    msg: com.xiuci.xcagi.mobile.model.CsMessageItemDto,
    isStreaming: Boolean = false,
    onReply: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
) {
    val isUser = msg.sender == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        if (!isUser) {
            Box(
                modifier = Modifier
                    .size(MessageAvatarLayout.customerServiceBubbleAvatarSize)
                    .clip(CircleShape)
                    .background(XcagiTheme.extra.brandBlue),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(MessageAvatarLayout.customerServiceBubbleIconSize),
                    tint = MaterialTheme.colorScheme.onPrimary,
                )
            }
            Spacer(Modifier.size(MessageAvatarLayout.customerServiceBubbleAvatarGap))
        }
        MessageActionMenu(text = msg.body, onReply = onReply, onDelete = onDelete) { longPress ->
        Box(
            modifier = Modifier
                .widthIn(max = 260.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 8.dp,
                        topEnd = 8.dp,
                        bottomStart = if (isUser) 8.dp else 2.dp,
                        bottomEnd = if (isUser) 2.dp else 8.dp,
                    ),
                )
                .background(if (isUser) XcagiTheme.extra.weChatGreen else MaterialTheme.colorScheme.surface)
                .then(longPress),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = Spacing.md, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    msg.body,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (isUser) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface,
                )
                if (isStreaming) {
                    val infiniteTransition = rememberInfiniteTransition(label = "cs_cursor")
                    val cursorAlpha by infiniteTransition.animateFloat(
                        initialValue = 0f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(tween(530), RepeatMode.Reverse),
                    )
                    Text(
                        "\u258C",  // ▌
                        style = MaterialTheme.typography.bodyMedium,
                        color = XcagiTheme.extra.brandBlue.copy(alpha = cursorAlpha),
                    )
                }
            }
        }
        }
        if (isUser) {
            Spacer(Modifier.size(MessageAvatarLayout.customerServiceBubbleAvatarGap))
            Box(
                modifier = Modifier
                    .size(MessageAvatarLayout.customerServiceBubbleAvatarSize)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.outlineVariant),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "我",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            }
        }
    }
}

// ── 客服输入栏 ──
@Composable
private fun WeChatStyleInputBarForCs(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    onVoice: () -> Unit = {},
) {
    // 提前提取颜色变量，drawBehind 内不能调用 @Composable
    val dividerColor = XcagiTheme.extra.weChatDivider
    val inputBgColor = XcagiTheme.extra.weChatInputBg
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .drawBehind {
                drawLine(
                    dividerColor,
                    Offset(0f, 0f),
                    Offset(size.width, 0f),
                    strokeWidth = 0.5.dp.toPx(),
                )
            },
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.sm, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // 语音按钮
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .clickable { onVoice() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.Mic,
                    contentDescription = "语音",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(22.dp),
                )
            }
            Surface(
                shape = MaterialTheme.shapes.extraSmall,
                color = inputBgColor,
                border = androidx.compose.foundation.BorderStroke(0.5.dp, dividerColor),
                modifier = Modifier.weight(1f),
            ) {
                androidx.compose.foundation.text.BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = Spacing.sm),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
                    decorationBox = { inner ->
                        Box(
                            Modifier.fillMaxWidth(),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            if (value.isEmpty()) {
                                Text(
                                    "输入消息...",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                                )
                            }
                            inner()
                        }
                    },
                )
            }
            Surface(
                shape = CircleShape,
                color = XcagiTheme.extra.brandBlue,
                modifier = Modifier
                    .size(36.dp)
                    .clickable { if (streaming) onStop() else onSend() },
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = if (streaming) Icons.Default.Close else Icons.AutoMirrored.Filled.Send,
                        contentDescription = if (streaming) "停止" else "发送",
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }
    }
}
