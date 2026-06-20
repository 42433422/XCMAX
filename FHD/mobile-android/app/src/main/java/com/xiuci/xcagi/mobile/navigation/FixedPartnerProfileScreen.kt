package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.MoreHoriz
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

internal object FixedPartnerKinds {
    const val ASSISTANT = "assistant"
    const val CUSTOMER_SERVICE = "cs"
}

private data class FixedPartnerProfileSpec(
    val name: String,
    val alias: String,
    val accountId: String,
    val summary: String,
    val source: String,
    val abilityLabels: List<String>,
    val circleLabels: List<String>,
    val avatarFallback: AppAvatarFallback,
    val avatarColor: Color,
)

@Composable
fun FixedPartnerProfileScreen(
    vm: AppViewModel,
    partnerKind: String,
    onBack: () -> Unit,
    onOpenChat: () -> Unit,
) {
    val csInfo by vm.csInfo.collectAsState()
    val assistantAvatarColor = XcagiTheme.extra.brandBlue
    val customerServiceAvatarColor = XcagiTheme.extra.weChatOnline

    LaunchedEffect(partnerKind) {
        if (partnerKind == FixedPartnerKinds.CUSTOMER_SERVICE) {
            vm.loadCsInfo()
        }
    }

    val spec =
        remember(
            partnerKind,
            csInfo,
            assistantAvatarColor,
            customerServiceAvatarColor,
        ) {
            fixedPartnerProfileSpec(
                partnerKind = partnerKind,
                csInfo = csInfo,
                assistantAvatarColor = assistantAvatarColor,
                customerServiceAvatarColor = customerServiceAvatarColor,
            )
        }
    if (spec == null) {
        return
    }

    Scaffold(
        topBar = { FixedPartnerProfileTopBar(onBack = onBack) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(bottom = 28.dp),
        ) {
            item { FixedPartnerHeader(spec) }

            item {
                Spacer(Modifier.height(10.dp))
                FixedPartnerPlainCell(
                    title = "伙伴资料",
                    subtitle = spec.summary,
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                FixedPartnerCirclePreview(
                    labels = spec.circleLabels,
                    accentColor = spec.avatarColor,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                FixedPartnerPlainCell(
                    title = "基础功能",
                    subtitle = spec.abilityLabels.joinToString("、"),
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                FixedPartnerPlainCell(
                    title = "来源",
                    subtitle = spec.source,
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(12.dp))
                FixedPartnerActionRow(
                    text = "发消息",
                    icon = Icons.AutoMirrored.Filled.Chat,
                    onClick = onOpenChat,
                )
            }
        }
    }
}

private fun fixedPartnerProfileSpec(
    partnerKind: String,
    csInfo: CsInfoDto?,
    assistantAvatarColor: Color,
    customerServiceAvatarColor: Color,
): FixedPartnerProfileSpec? =
    when (partnerKind) {
        FixedPartnerKinds.ASSISTANT ->
            FixedPartnerProfileSpec(
                name = "小C助理",
                alias = "企业智能助手",
                accountId = "XCAGI-AI-C",
                summary = "负责智能对话、快速分析、识图入口和企业协同问答。",
                source = "XCAGI 企业版内置伙伴",
                abilityLabels = listOf("智能对话", "快速模式", "深度分析", "拍照识图"),
                circleLabels = listOf("对话", "分析", "识图"),
                avatarFallback = AppAvatarFallback.ASSISTANT,
                avatarColor = assistantAvatarColor,
            )
        FixedPartnerKinds.CUSTOMER_SERVICE ->
            FixedPartnerProfileSpec(
                name = csInfo?.name?.ifBlank { "专属客服" } ?: "专属客服",
                alias = "企业服务顾问",
                accountId = "XCAGI-CS",
                summary = "用于企业服务接待、问题反馈、订单跟进与人工协同支持。",
                source = "企业服务通道",
                abilityLabels = listOf("服务咨询", "进度跟进", "问题反馈", "人工协同"),
                circleLabels = listOf("服务", "协同", "反馈"),
                avatarFallback = AppAvatarFallback.CUSTOMER_SERVICE,
                avatarColor = customerServiceAvatarColor,
            )
        else -> null
    }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FixedPartnerProfileTopBar(onBack: () -> Unit) {
    TopAppBar(
        title = {},
        navigationIcon = {
            IconButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "返回",
                    tint = MaterialTheme.colorScheme.onSurface,
                )
            }
        },
        actions = {
            IconButton(onClick = {}) {
                Icon(
                    Icons.Default.MoreHoriz,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurface,
                )
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        windowInsets = WindowInsets(0.dp),
    )
}

@Composable
private fun FixedPartnerHeader(spec: FixedPartnerProfileSpec) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(start = 28.dp, end = 24.dp, top = 34.dp, bottom = 34.dp),
            verticalAlignment = Alignment.Top,
        ) {
            AppAvatar(
                fallback = spec.avatarFallback,
                size = 76.dp,
                shape = MaterialTheme.shapes.small,
                contentDescription = spec.name,
            )
            Spacer(Modifier.width(18.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    spec.name,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    "昵称：${spec.alias}",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 10.dp),
                )
                Text(
                    "AI号：${spec.accountId}",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Text(
                    "来源：${spec.source}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun FixedPartnerPlainCell(
    title: String,
    subtitle: String,
    showArrow: Boolean,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
            if (showArrow) {
                Icon(
                    Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f),
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun FixedPartnerCirclePreview(
    labels: List<String>,
    accentColor: Color,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "介绍预览",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(96.dp),
            )
            Row(
                Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                labels.take(3).forEach { label ->
                    Box(
                        modifier = Modifier
                            .size(54.dp)
                            .clip(MaterialTheme.shapes.extraSmall)
                            .background(accentColor.copy(alpha = 0.14f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            label.take(2),
                            style = MaterialTheme.typography.labelSmall,
                            color = accentColor,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FixedPartnerActionRow(
    text: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(22.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                text = text,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}
