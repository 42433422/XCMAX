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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
        onBack: () -> Unit,
) {
    // 本地通知数据（后续可接入后端 API）
    val notifications =
            remember {
                val now = System.currentTimeMillis()
                val day = 24 * 60 * 60 * 1000L
                listOf(
                        NotificationItem(
                                id = "1",
                                type = NotificationType.ANNOUNCEMENT,
                                title = "欢迎使用 XCAGI 企业版",
                                content = "您的企业 AI 助手已就绪。可以随时和小C助理对话，或前往 AI员工 页面查看企业智能伙伴。",
                                timestamp = now - 2 * 3600 * 1000,
                        ),
                        NotificationItem(
                                id = "2",
                                type = NotificationType.SYSTEM,
                                title = "数据同步完成",
                                content = "您的会话和 AI 员工列表已同步至最新状态。",
                                timestamp = now - 5 * 3600 * 1000,
                                read = true,
                        ),
                        NotificationItem(
                                id = "3",
                                type = NotificationType.UPDATE,
                                title = "新功能：语音输入",
                                content = "聊天页和客服页现已支持语音输入，点击麦克风按钮即可将语音转为文字。",
                                timestamp = now - day,
                        ),
                        NotificationItem(
                                id = "4",
                                type = NotificationType.SUCCESS,
                                title = "账号配对成功",
                                content = "您的移动端已成功配对企业端，可以开始使用全部功能。",
                                timestamp = now - 2 * day,
                                read = true,
                        ),
                        NotificationItem(
                                id = "5",
                                type = NotificationType.ALERT,
                                title = "请及时更新应用",
                                content = "检测到新版本可用，建议尽快更新以获得最新功能和安全修复。",
                                timestamp = now - 3 * day,
                                read = true,
                        ),
                )
            }

    var readIds by remember { mutableStateOf(setOf<String>()) }
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
                Text(
                        "暂无通知",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                items(notifications, key = { it.id }) { item ->
                    val isRead = item.read || item.id in readIds
                    NotificationCell(
                            item = item,
                            isRead = isRead,
                            dateText = dateFormatter.format(Date(item.timestamp)),
                            onClick = { readIds = readIds + item.id },
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
