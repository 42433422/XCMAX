package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.PersonSearch
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.db.ImMessageCacheEntity
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageActionMenu
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.launch

@Composable
fun ImMessengerScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var peerIdText by remember { mutableStateOf("") }
    var conversationId by remember { mutableStateOf<Int?>(null) }
    var draft by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val cid = conversationId
    val messages by if (cid != null) {
        vm.observeImMessages(cid).collectAsState(initial = emptyList())
    } else {
        remember { mutableStateOf(emptyList()) }
    }

    DisposableEffect(Unit) {
        vm.connectImWebSocket()
        onDispose { vm.disconnectImWebSocket() }
    }

    LaunchedEffect(cid) {
        val activeCid = cid ?: return@LaunchedEffect
        vm.seedImMessages(activeCid).onFailure { error = it.message }
    }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(title = "IM 消息", onBack = onBack, showRightSearch = false, showRightAdd = false)

        if (conversationId == null) {
            WeSectionCaption("新会话")
            WeCellGroup {
                WeCell(
                    title = "对方用户",
                    subtitle = "输入企业用户 ID 后发起直聊",
                    icon = Icons.Default.PersonSearch,
                    iconTint = XcagiTheme.extra.brandBlue,
                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                    showArrow = false,
                    showDivider = false,
                )
                WeField(
                    value = peerIdText,
                    onValueChange = { peerIdText = it.filter(Char::isDigit).take(10) },
                    placeholder = "用户 ID",
                    singleLine = true,
                    modifier = Modifier.padding(horizontal = Spacing.lg),
                )
                Spacer(Modifier.height(Spacing.sm))
                WeBlockButton(
                    text = "打开会话",
                    enabled = peerIdText.isNotBlank(),
                    onClick = {
                        val peer = peerIdText.toIntOrNull() ?: return@WeBlockButton
                        scope.launch {
                            vm.imOpenDirect(peer)
                                .onSuccess { body ->
                                    @Suppress("UNCHECKED_CAST")
                                    val conv = body["conversation"] as? Map<String, Any?>
                                    conversationId = (conv?.get("id") as? Number)?.toInt()
                                    error = null
                                }
                                .onFailure { error = it.message }
                        }
                    },
                )
                Spacer(Modifier.height(Spacing.md))
            }
            ImErrorText(error)
        } else {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier.size(34.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Default.ChatBubbleOutline, contentDescription = null, tint = XcagiTheme.extra.brandBlue)
                }
                Spacer(Modifier.width(Spacing.sm))
                Column(Modifier.weight(1f)) {
                    Text("会话 #${conversationId}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text("WebSocket 已连接，消息实时同步", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                }
            }

            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = Spacing.lg),
                verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                if (messages.isEmpty()) {
                    item { EmptyConversationHint() }
                }
                items(messages, key = { it.message_id }) { message ->
                    ImMessageBubble(
                        message = message,
                        onReply = { draft = "引用「" + message.body.take(60) + "」\n" + draft },
                        onDelete = {
                            conversationId?.let { vm.deleteImMessage(it, message.message_id) }
                        },
                    )
                }
            }

            ImErrorText(error)

            Row(
                Modifier
                    .fillMaxWidth()
                    .imePadding()
                    .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                WeField(
                    value = draft,
                    onValueChange = { draft = it.take(1000) },
                    placeholder = "输入消息",
                    modifier = Modifier.weight(1f),
                    singleLine = false,
                )
                Spacer(Modifier.width(Spacing.sm))
                IconButton(
                    onClick = {
                        val activeCid = conversationId ?: return@IconButton
                        val text = draft.trim()
                        if (text.isEmpty()) return@IconButton
                        scope.launch {
                            vm.imSendMessage(activeCid, text)
                                .onSuccess {
                                    draft = ""
                                    error = null
                                }
                                .onFailure { error = it.message }
                        }
                    },
                    enabled = draft.isNotBlank(),
                ) {
                    Icon(Icons.Default.Send, contentDescription = "发送", tint = XcagiTheme.extra.brandBlue)
                }
            }
        }
    }
}

@Composable
private fun EmptyConversationHint() {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 64.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(52.dp).clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.ChatBubbleOutline, contentDescription = null, tint = MaterialTheme.colorScheme.outline)
        }
        Spacer(Modifier.height(Spacing.sm))
        Text("暂无消息", style = MaterialTheme.typography.titleMedium)
        Text("发出第一条消息后会显示在这里", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
    }
}

@Composable
private fun ImMessageBubble(
    message: ImMessageCacheEntity,
    onReply: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
) {
    val mine = message.sender_user_id <= 0
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        MessageActionMenu(text = message.body, onReply = onReply, onDelete = onDelete) { longPress ->
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = if (mine) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.surfaceVariant,
                modifier = Modifier
                    .fillMaxWidth(0.78f)
                    .then(longPress),
            ) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
                    Text(
                        "用户 ${message.sender_user_id}",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (mine) MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.72f) else MaterialTheme.colorScheme.outline,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        message.body,
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun ImErrorText(error: String?) {
    if (error.isNullOrBlank()) return
    Text(
        error,
        color = MaterialTheme.colorScheme.error,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.xs),
    )
}
