package com.xiuci.xcagi.mobile.navigation

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Campaign
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.db.NotificationCacheEntity
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 通知类型 */
enum class NotificationType(val icon: ImageVector, val label: String) {
    SYSTEM(Icons.Default.Info, "系统通知"),
    ANNOUNCEMENT(Icons.Default.Campaign, "企业公告"),
    UPDATE(Icons.Default.Build, "版本更新"),
    ALERT(Icons.Default.Warning, "紧急提醒"),
    SUCCESS(Icons.Default.CheckCircle, "任务完成"),
}

/** 通知项数据 */
data class NotificationItem(
        val id: String,
        val type: NotificationType,
        val title: String,
        val content: String,
        val timestamp: Long,
        val read: Boolean = false,
)

/** 服务端 channel（见 NotificationChannels.kt）→ 通知页分类图标/配色。未知 channel 兜底为系统通知。 */
internal fun channelToNotificationType(channel: String): NotificationType =
        when (channel) {
            "xcagi_approval" -> NotificationType.ALERT
            "xcagi_sync" -> NotificationType.SYSTEM
            "xcagi_chat" -> NotificationType.ANNOUNCEMENT
            "xcagi_system" -> NotificationType.SYSTEM
            else -> NotificationType.SYSTEM
        }

internal fun NotificationCacheEntity.toNotificationItem(): NotificationItem =
        NotificationItem(
                id = id.toString(),
                type = channelToNotificationType(channel),
                title = title.ifBlank { "通知" },
                content = body,
                timestamp = createdAt,
                read = read,
        )

/** 通知类型对应的主题色 */
@Composable
private fun NotificationType.tint(): Color =
        when (this) {
            NotificationType.SYSTEM -> MaterialTheme.colorScheme.primary
            NotificationType.ANNOUNCEMENT -> XcagiTheme.extra.brandBlue
            NotificationType.UPDATE -> XcagiTheme.extra.weChatGreen
            NotificationType.ALERT -> MaterialTheme.colorScheme.error
            NotificationType.SUCCESS -> XcagiTheme.extra.success
        }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotificationListScreen(
        vm: AppViewModel,
        onBack: () -> Unit,
) {
    // 来自服务端一次性推送 + 本机 Room 历史（notification_cache），不再是硬编码样例数据。
    // 服务端 /notifications/pending 消费即删（delivered=true 后不再返回），所以历史全靠本机持久化，
    // 见 XcagiRepository.fetchPendingNotifications() 落库、PushPollWorker 后台轮询同步写入。
    val history by vm.notificationHistory.collectAsState()
    val notifications = remember(history) { history.map { it.toNotificationItem() } }
    var refreshing by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        vm.refreshNotifications()
        refreshing = false
    }

    val dateFormatter = remember { SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()) }

    Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            topBar = {
                WeTopBar(
                        title = "通知与公告",
                        showRightSearch = false,
                )
            },
    ) { padding ->
        if (notifications.isEmpty()) {
            Box(
                    Modifier.fillMaxSize().padding(padding),
                    contentAlignment = Alignment.Center,
            ) {
                if (refreshing) {
                    CircularProgressIndicator(modifier = Modifier.size(28.dp), strokeWidth = 2.dp)
                } else {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                                "暂无通知",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(Spacing.sm))
                        Text(
                                "有系统公告、审批提醒时会在这里出现",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
            }
        } else {
            LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                items(notifications, key = { it.id }) { item ->
                    NotificationCell(
                            item = item,
                            isRead = item.read,
                            dateText = dateFormatter.format(Date(item.timestamp)),
                            onClick = { vm.markNotificationRead(item.id.toLongOrNull() ?: return@NotificationCell) },
                    )
                }
            }
        }
    }
}

@Composable
private fun NotificationCell(
        item: NotificationItem,
        isRead: Boolean,
        dateText: String,
        onClick: () -> Unit,
) {
    val bg =
            if (!isRead) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
            else MaterialTheme.colorScheme.surface
    Row(
            modifier = Modifier
                    .fillMaxWidth()
                    .background(bg)
                    .clickable(onClick = onClick)
                    .padding(horizontal = Spacing.lg, vertical = Spacing.md),
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 图标
        Box(
                modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(item.type.tint().copy(alpha = 0.12f)),
                contentAlignment = Alignment.Center,
        ) {
            Icon(
                    item.type.icon,
                    contentDescription = item.type.label,
                    tint = item.type.tint(),
                    modifier = Modifier.size(22.dp),
            )
        }

        // 内容
        Column(modifier = Modifier.weight(1f)) {
            Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                        item.title,
                        style = MaterialTheme.typography.titleSmall.copy(
                                fontWeight = if (!isRead) FontWeight.Bold else FontWeight.Medium,
                        ),
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                )
                if (!isRead) {
                    Box(
                            modifier = Modifier
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.error),
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(
                    item.content,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                    dateText,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
