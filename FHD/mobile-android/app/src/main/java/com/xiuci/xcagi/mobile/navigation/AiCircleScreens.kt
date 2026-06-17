package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
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
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileEmptyState
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

internal data class AiEmployeeProfile(
    val modId: String,
    val modName: String,
    val modDescription: String,
    val modVersion: String,
    val modAuthor: String,
    val industryName: String,
    val employeeId: String,
    val name: String,
    val title: String,
    val summary: String,
    val apiBasePath: String,
    val phoneChannel: String,
    val workflowPlaceholder: Boolean,
) {
    val key: String = "$modId:$employeeId"
    val avatarText: String = name.firstOrNull()?.toString() ?: "AI"
}

internal fun List<ModInfo>.aiEmployeeProfiles(): List<AiEmployeeProfile> =
    flatMap { mod ->
        mod.workflow_employees.mapNotNull { employee ->
            val employeeId = employee.id.trim()
            val name = employee.displayName()
            if (employeeId.isBlank() || name.isBlank()) {
                null
            } else {
                AiEmployeeProfile(
                    modId = mod.id,
                    modName = mod.name.ifBlank { mod.id },
                    modDescription = mod.description,
                    modVersion = mod.version,
                    modAuthor = mod.author,
                    industryName = mod.industry?.name.orEmpty(),
                    employeeId = employeeId,
                    name = name,
                    title = employee.panel_title.ifBlank { name },
                    summary = employee.panel_summary.ifBlank {
                        mod.description.ifBlank { "由企业端安装的 ${mod.name.ifBlank { mod.id }} 同步到手机端。" }
                    },
                    apiBasePath = employee.api_base_path,
                    phoneChannel = employee.phone_channel,
                    workflowPlaceholder = employee.workflow_placeholder,
                )
            }
        }
    }

private fun WorkflowEmployeeInfo.displayName(): String =
    label.ifBlank { panel_title }.ifBlank { id }

internal fun List<AiEmployeeProfile>.findEmployee(modId: String, employeeId: String): AiEmployeeProfile? =
    firstOrNull { it.modId == modId && it.employeeId == employeeId }

private fun AiEmployeeProfile.abilityLabels(): List<String> {
    val labels = mutableListOf<String>()
    if (phoneChannel.isNotBlank()) labels += "移动端沟通"
    if (apiBasePath.isNotBlank()) labels += "企业 API"
    if (industryName.isNotBlank()) labels += industryName
    if (modVersion.isNotBlank()) labels += "v$modVersion"
    if (workflowPlaceholder) labels += "待企业端完善"
    if (labels.isEmpty()) labels += "企业端配置能力"
    return labels.take(4)
}

@Composable
internal fun aiEmployeeAvatarColor(key: String): Color {
    val colors = listOf(
        XcagiTheme.extra.brandBlue,
        XcagiTheme.extra.success,
        XcagiTheme.extra.warning,
        MaterialTheme.colorScheme.secondary,
        MaterialTheme.colorScheme.tertiary,
    )
    return colors[kotlin.math.abs(key.hashCode()) % colors.size]
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun AiCircleScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onOpenEmployee: (String, String) -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }

    LaunchedEffect(Unit) { vm.refreshModInfos() }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        WeTopBar(title = "AI交流圈", onBack = onBack)

        if (employees.isEmpty()) {
            MobileEmptyState(
                message = "暂无 AI 员工动态",
                onRetry = { vm.refreshModInfos(showError = true) },
            )
            return@Column
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                AiCircleHeader(count = employees.size)
            }
            items(
                items = employees,
                key = { it.key },
            ) { employee ->
                AiMomentCard(
                    employee = employee,
                    onClick = { onOpenEmployee(employee.modId, employee.employeeId) },
                )
            }
        }
    }
}

@Composable
private fun AiCircleHeader(count: Int) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 20.dp, vertical = 18.dp),
    ) {
        Text(
            "企业 AI 动态",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            "$count 位智能伙伴来自企业端已安装生态",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AiMomentCard(
    employee: AiEmployeeProfile,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp)
            .clip(MaterialTheme.shapes.medium)
            .clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
    ) {
        Row(Modifier.padding(14.dp)) {
            AiEmployeeAvatar(employee = employee, size = 46.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        employee.name,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        "刚刚同步",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    employee.modName,
                    style = MaterialTheme.typography.labelMedium,
                    color = XcagiTheme.extra.brandBlue,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Text(
                    employee.summary,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(top = 8.dp),
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                FlowRow(
                    modifier = Modifier.padding(top = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    employee.abilityLabels().forEach { label ->
                        AiAbilityChip(label)
                    }
                }
                Text(
                    "查看主页",
                    style = MaterialTheme.typography.labelLarge,
                    color = XcagiTheme.extra.brandBlue,
                    modifier = Modifier.padding(top = 12.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun AiEmployeeProfileScreen(
    vm: AppViewModel,
    modId: String,
    employeeId: String,
    onBack: () -> Unit,
    onOpenCircle: () -> Unit,
    onOpenChat: (String) -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    val employee = employees.findEmployee(modId, employeeId)

    LaunchedEffect(Unit) { vm.refreshModInfos() }

    Scaffold(
        topBar = { AiProfileTopBar(onBack = onBack) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        if (employee == null) {
            Box(Modifier.fillMaxSize().padding(padding)) {
                MobileEmptyState(
                    message = "未找到该 AI 员工",
                    onRetry = { vm.refreshModInfos(showError = true) },
                )
            }
            return@Scaffold
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(bottom = 28.dp),
        ) {
            item { AiEmployeeContactHeader(employee) }

            item {
                Spacer(Modifier.height(10.dp))
                AiProfilePlainCell(
                    title = "AI资料",
                    subtitle = employee.summary,
                    showArrow = true,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                AiProfileCirclePreview(
                    employee = employee,
                    onClick = onOpenCircle,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                AiProfilePlainCell(
                    title = "基础功能",
                    subtitle = employee.abilityLabels().joinToString("、"),
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(10.dp))
                AiProfilePlainCell(
                    title = "来源",
                    subtitle = employee.modName,
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(12.dp))
                AiProfileActionRow(
                    text = "发消息",
                    icon = Icons.AutoMirrored.Filled.Chat,
                    onClick = { onOpenChat("employee:${employee.modId}:${employee.employeeId}") },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AiProfileTopBar(onBack: () -> Unit) {
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
    )
}

@Composable
private fun AiEmployeeContactHeader(employee: AiEmployeeProfile) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(start = 28.dp, end = 24.dp, top = 34.dp, bottom = 34.dp),
            verticalAlignment = Alignment.Top,
        ) {
            AiEmployeeAvatar(employee = employee, size = 76.dp)
            Spacer(Modifier.width(18.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    employee.name,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    "昵称：${employee.title}",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 10.dp),
                )
                Text(
                    "AI号：${employee.employeeId}",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    "来源：${employee.modName}",
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
private fun AiProfilePlainCell(
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
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
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
private fun AiProfileCirclePreview(
    employee: AiEmployeeProfile,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "AI交流圈",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(96.dp),
            )
            Row(
                Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                employee.abilityLabels().take(3).forEach { label ->
                    AiCirclePreviewTile(label = label, color = aiEmployeeAvatarColor("${employee.key}:$label"))
                }
            }
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f),
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

@Composable
private fun AiCirclePreviewTile(label: String, color: Color) {
    Box(
        modifier = Modifier
            .size(54.dp)
            .clip(MaterialTheme.shapes.extraSmall)
            .background(color.copy(alpha = 0.16f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label.take(2),
            style = MaterialTheme.typography.labelSmall,
            color = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun AiProfileActionRow(
    text: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(vertical = 20.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(24.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                text,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun AiEmployeeAvatar(employee: AiEmployeeProfile, size: androidx.compose.ui.unit.Dp) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(aiEmployeeAvatarColor(employee.key)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            employee.avatarText,
            style = MaterialTheme.typography.titleLarge,
            color = Color.White,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun AiAbilityChip(label: String) {
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.primaryContainer,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = XcagiTheme.extra.brandBlue,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
        )
    }
}

@Composable
private fun AiMiniBadge(label: String) {
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

private fun abilitySubtitle(employee: AiEmployeeProfile, label: String): String =
    when (label) {
        "移动端沟通" -> "可通过手机端会话触达该员工"
        "企业 API" -> "由企业端接口 ${employee.apiBasePath} 提供能力"
        "企业端配置能力" -> "随企业端安装配置同步"
        "待企业端完善" -> "该员工配置仍在企业端补齐中"
        else -> "来源于 ${employee.modName}"
    }
