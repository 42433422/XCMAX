package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.SupportAgent
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.model.AdminCsInboxItemDto
import com.xiuci.xcagi.mobile.model.AdminCsMessageItemDto
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageAvatarLayout
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 管理端客服收件箱(运营者):列出企业客户的专属客服会话,点进去看历史并以「企业专属客服」回复。
 * 客户消息和回复都走真实 IM 通道(与桌面端同源 enterprise-cs)。样式对齐 CsChatScreen。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdminCsConsoleScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val inbox by vm.adminCsInbox.collectAsState()
    var selected by remember { mutableStateOf<AdminCsInboxItemDto?>(null) }

    LaunchedEffect(selected) {
        if (selected == null) {
            while (true) {
                vm.loadAdminCsInbox()
                delay(8_000)
            }
        }
    }

    if (selected == null) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            topBar = {
                TopAppBar(
                    title = {
                        Text(
                            "客户客服",
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                    ),
                    windowInsets = WindowInsets(0.dp),
                )
            },
        ) { padding ->
            if (inbox.isEmpty()) {
                Box(
                    Modifier.fillMaxSize().padding(padding),
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
                            "暂无客户咨询",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.height(Spacing.xs))
                        Text(
                            "客户在「专属客服」发起咨询后会出现在这里",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                        )
                    }
                }
            } else {
                LazyColumn(Modifier.fillMaxSize().padding(padding)) {
                    items(inbox, key = { it.conversationId }) { conv ->
                        AdminCsInboxRow(conv) { selected = conv }
                    }
                }
            }
        }
    } else {
        AdminCsConversation(
            vm = vm,
            conversation = selected!!,
            onBack = {
                vm.clearAdminCsMessages()
                selected = null
            },
        )
    }
}

@Composable
private fun AdminCsInboxRow(conv: AdminCsInboxItemDto, onClick: () -> Unit) {
    val dividerColor = XcagiTheme.extra.weChatDivider
    Row(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .clickable(onClick = onClick)
            .drawBehind {
                drawLine(
                    dividerColor,
                    Offset(80.dp.toPx(), size.height),
                    Offset(size.width, size.height),
                    strokeWidth = 0.5.dp.toPx(),
                )
            }
            .padding(horizontal = Spacing.md, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 头像:客户名首字
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(XcagiTheme.extra.brandBlue),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                conv.customerName.take(1).uppercase(),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onPrimary,
            )
        }
        Spacer(Modifier.width(Spacing.md))
        Column(Modifier.weight(1f)) {
            Text(
                conv.customerName,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (conv.lastMessageAt.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(
                    conv.lastMessageAt.replace("T", " ").take(19),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
        if (conv.unreadCount > 0) {
            Box(
                modifier = Modifier
                    .size(20.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.error),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    conv.unreadCount.toString(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AdminCsConversation(
    vm: AppViewModel,
    conversation: AdminCsInboxItemDto,
    onBack: () -> Unit,
) {
    val messages by vm.adminCsMessages.collectAsState()
    var input by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    LaunchedEffect(conversation.conversationId) {
        while (true) {
            vm.loadAdminCsMessages(conversation.conversationId)
            delay(5_000)
        }
    }
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.surface,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        conversation.customerName,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回收件箱")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
                windowInsets = WindowInsets(0.dp),
            )
        },
        bottomBar = {
            AdminCsInputBar(
                value = input,
                onValueChange = { input = it },
                enabled = !sending,
                onSend = {
                    val text = input.trim()
                    if (text.isNotBlank() && !sending) {
                        sending = true
                        input = ""
                        scope.launch {
                            vm.replyAdminCs(conversation.conversationId, text)
                            sending = false
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .background(MaterialTheme.colorScheme.background),
        ) {
            if (messages.isEmpty()) {
                Box(
                    Modifier.fillMaxSize().padding(vertical = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "暂无消息",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.outline,
                    )
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
                    items(messages, key = { it.messageId }) { m ->
                        AdminCsBubble(m)
                    }
                }
            }
        }
    }
}

// ── 消息气泡:客户(对方,左)/ 运营者以企业专属客服(我方,右)──
@Composable
private fun AdminCsBubble(msg: AdminCsMessageItemDto) {
    val mine = !msg.fromCustomer
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        if (!mine) {
            Box(
                modifier = Modifier
                    .size(MessageAvatarLayout.customerServiceBubbleAvatarSize)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.outlineVariant),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    msg.senderName.take(1).uppercase().ifBlank { "客" },
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            }
            Spacer(Modifier.size(MessageAvatarLayout.customerServiceBubbleAvatarGap))
        }
        Box(
            modifier = Modifier
                .widthIn(max = 260.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 8.dp,
                        topEnd = 8.dp,
                        bottomStart = if (mine) 8.dp else 2.dp,
                        bottomEnd = if (mine) 2.dp else 8.dp,
                    ),
                )
                .background(if (mine) XcagiTheme.extra.weChatGreen else MaterialTheme.colorScheme.surface),
        ) {
            Text(
                msg.body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(horizontal = Spacing.md, vertical = 9.dp),
            )
        }
        if (mine) {
            Spacer(Modifier.size(MessageAvatarLayout.customerServiceBubbleAvatarGap))
            Box(
                modifier = Modifier
                    .size(MessageAvatarLayout.customerServiceBubbleAvatarSize)
                    .clip(CircleShape)
                    .background(XcagiTheme.extra.brandBlue),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "客服",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            }
        }
    }
}

// ── 输入栏(对齐 CsChatScreen 微信风)──
@Composable
private fun AdminCsInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean,
    onSend: () -> Unit,
) {
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
            Surface(
                shape = MaterialTheme.shapes.extraSmall,
                color = inputBgColor,
                border = BorderStroke(0.5.dp, dividerColor),
                modifier = Modifier.weight(1f),
            ) {
                BasicTextField(
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
                                Text(
                                    "以企业专属客服身份回复…",
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
                    .clickable(enabled = enabled && value.isNotBlank()) { onSend() },
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Send,
                        contentDescription = "发送",
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }
    }
}
