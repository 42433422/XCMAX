package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.lazy.itemsIndexed
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
import com.xiuci.xcagi.mobile.ui.components.mobile.LocalProfileAvatar
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
    val profileSource: String,
    val marketConnected: Boolean,
    val marketPkgId: String,
    val marketVersion: String,
    val marketAuthor: String,
    val marketMaterialCategory: String,
    val marketLicenseScope: String,
    val marketSecurityLevel: String,
) {
    val key: String = "$modId:$employeeId"
    val avatarText: String = name.firstOrNull()?.toString() ?: "AI"
    val sourceLabel: String =
        when {
            marketPkgId.isNotBlank() -> "AI市场 · ${modName.ifBlank { "已安装员工" }}"
            modName.isNotBlank() -> modName
            profileSource.isNotBlank() -> profileSource
            else -> "当前账号生态"
        }
}

internal fun List<ModInfo>.aiEmployeeProfiles(): List<AiEmployeeProfile> =
    flatMap { mod ->
        mod.workflow_employees.mapNotNull { employee ->
            val employeeId = employee.id.trim()
            val name = employee.displayName()
            val marketDescription = employee.market_description.trim()
            val marketIndustry = employee.market_industry.trim()
            if (employeeId.isBlank() || name.isBlank()) {
                null
            } else {
                AiEmployeeProfile(
                    modId = mod.id,
                    modName = mod.name.ifBlank { mod.id },
                    modDescription = mod.description,
                    modVersion = employee.market_version.ifBlank { mod.version },
                    modAuthor = employee.market_author.ifBlank { mod.author },
                    industryName = marketIndustry.ifBlank { mod.industry?.name.orEmpty() },
                    employeeId = employeeId,
                    name = name,
                    title = employee.panel_title.ifBlank { name },
                    summary = marketDescription.ifBlank { employee.panel_summary }.ifBlank {
                        mod.description.ifBlank { "由当前账号生态的 ${mod.name.ifBlank { mod.id }} 同步到手机端。" }
                    },
                    apiBasePath = employee.api_base_path,
                    phoneChannel = employee.phone_channel,
                    workflowPlaceholder = employee.workflow_placeholder,
                    profileSource = employee.profile_source,
                    marketConnected = employee.market_connected,
                    marketPkgId = employee.market_pkg_id,
                    marketVersion = employee.market_version,
                    marketAuthor = employee.market_author,
                    marketMaterialCategory = employee.market_material_category,
                    marketLicenseScope = employee.market_license_scope,
                    marketSecurityLevel = employee.market_security_level,
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
    if (phoneChannel.isNotBlank()) labels += "可对话"
    if (apiBasePath.isNotBlank()) labels += "可执行任务"
    if (industryName.isNotBlank()) labels += industryName
    if (workflowPlaceholder) labels += "待完善"
    if (marketPkgId.isNotBlank()) labels += "市场资料"
    if (labels.isEmpty()) labels += "生态同步"
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
    val displayName by vm.displayName.collectAsState()
    val avatarUri by vm.avatarUri.collectAsState()
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
        ) {
            item {
                AiCircleHeader(
                    employees = employees,
                    displayName = displayName.ifBlank { "当前账号" },
                    avatarUri = avatarUri,
                )
            }
            itemsIndexed(
                items = employees,
                key = { index, employee -> "${employee.key}:$index" },
            ) { index, employee ->
                AiMomentCard(
                    employee = employee,
                    index = index,
                    onClick = { onOpenEmployee(employee.modId, employee.employeeId) },
                )
            }
        }
    }
}

@Composable
private fun AiCircleHeader(
    employees: List<AiEmployeeProfile>,
    displayName: String,
    avatarUri: String,
) {
    val featured = employees.take(3)
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface)) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(144.dp)
                .background(Color(0xFF3F4A4D)),
        ) {
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(start = 20.dp, end = 128.dp, bottom = 16.dp),
            ) {
                Text(
                    "AI员工交流圈",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    color = Color.White,
                )
                Text(
                    "${employees.size} 位智能伙伴正在企业账号里值守",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.86f),
                    modifier = Modifier.padding(top = 5.dp),
                )
            }
            Row(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(end = 20.dp, bottom = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    displayName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(end = 10.dp),
                )
                LocalProfileAvatar(
                    displayName = displayName,
                    avatarUri = avatarUri,
                    modifier = Modifier.border(2.dp, Color.White, MaterialTheme.shapes.extraSmall),
                    size = 50.dp,
                    shape = MaterialTheme.shapes.extraSmall,
                    containerColor = Color(0xFF1FA67A),
                    contentColor = Color.White,
                )
            }
        }
        Row(
            Modifier.padding(start = 20.dp, end = 20.dp, top = 9.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    "企业账号生态",
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    "员工动态、能力更新和协同消息会在这里汇总。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy((-10).dp)) {
                featured.forEach { employee ->
                    AiEmployeeAvatar(employee = employee, size = 30.dp)
                }
            }
        }
        Box(
            Modifier
                .fillMaxWidth()
                .height(8.dp)
                .background(MaterialTheme.colorScheme.background),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AiMomentCard(
    employee: AiEmployeeProfile,
    index: Int,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Column {
            Row(Modifier.padding(start = 16.dp, end = 14.dp, top = 12.dp, bottom = 12.dp)) {
                AiEmployeeAvatar(employee = employee, size = 42.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                employee.name,
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = Color(0xFF1F6F50),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                employee.momentSourceLine(index),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.padding(top = 2.dp),
                            )
                        }
                        Icon(
                            Icons.Default.MoreHoriz,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                            modifier = Modifier.size(22.dp),
                        )
                    }
                    Text(
                        employee.momentBody(index),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(top = 8.dp),
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                    FlowRow(
                        modifier = Modifier.padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        employee.abilityLabels().take(3).forEach { label ->
                            AiAbilityChip(label)
                        }
                    }
                    AiMomentActionBar(employee = employee, index = index)
                    AiMomentReplyBox(employee = employee, index = index)
                }
            }
            Box(
                Modifier
                    .padding(start = 68.dp)
                    .fillMaxWidth()
                    .height(0.6.dp)
                    .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)),
            )
        }
    }
}

@Composable
private fun AiMomentActionBar(
    employee: AiEmployeeProfile,
    index: Int,
) {
    Row(
        modifier = Modifier.padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            employee.momentTime(index),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        AiMomentActionText("赞")
        Spacer(Modifier.width(16.dp))
        AiMomentActionText("评论")
        Spacer(Modifier.width(16.dp))
        AiMomentActionText("主页")
    }
}

@Composable
private fun AiMomentActionText(label: String) {
    Text(
        label,
        style = MaterialTheme.typography.labelMedium,
        color = Color(0xFF1F6F50),
        fontWeight = FontWeight.Medium,
    )
}

@Composable
private fun AiMomentReplyBox(
    employee: AiEmployeeProfile,
    index: Int,
) {
    Surface(
        modifier = Modifier.padding(top = 6.dp).fillMaxWidth(),
        shape = MaterialTheme.shapes.extraSmall,
        color = Color(0xFFF4F5F4),
    ) {
        Column(Modifier.padding(horizontal = 9.dp, vertical = 6.dp)) {
            Text(
                "小C助理：${employee.assistantReply(index)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                "专属客服：需要人工协同时我会接上。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 3.dp),
            )
        }
    }
}

private fun AiEmployeeProfile.momentTime(index: Int): String =
    listOf("刚刚", "8分钟前", "23分钟前", "1小时前", "今天 09:40", "昨天 18:12")[index % 6]

private fun AiEmployeeProfile.momentSourceLine(index: Int): String {
    val source =
        if (marketPkgId.isNotBlank()) {
            "AI市场同步"
        } else {
            sourceLabel
        }
    val state = listOf("在线值守", "整理能力边界", "等待任务", "可被呼叫")[index % 4]
    return "$source · $state"
}

private fun AiEmployeeProfile.momentBody(index: Int): String {
    val text = summary.replace('\n', ' ').trim()
    val shortSummary = if (text.length > 56) "${text.take(56)}…" else text
    val primaryAbility = abilityLabels().firstOrNull().orEmpty()
    return when (index % 4) {
        0 -> "今天在值守「${title.ifBlank { name }}」，主要处理${primaryAbility.ifBlank { "企业协同" }}。$shortSummary"
        1 -> "刚更新了能力说明：$shortSummary"
        2 -> "我已在手机端待命，适合我的事项会先拆成清单再推进。"
        else -> "按岗位边界工作，复杂问题会和小C助理一起衔接。"
    }
}

private fun AiEmployeeProfile.assistantReply(index: Int): String =
    when (index % 3) {
        0 -> "已把 ${name} 放进员工通讯录，可以从主页直接发起会话。"
        1 -> "这位员工的资料已和企业端同步。"
        else -> "收到，后续任务会优先按员工职责分派。"
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
                Spacer(Modifier.height(8.dp))
                AiProfilePlainCell(
                    title = "员工资料",
                    subtitle = employee.summary,
                    showArrow = true,
                )
            }

            item {
                Spacer(Modifier.height(8.dp))
                AiProfileCirclePreview(
                    employee = employee,
                    onClick = onOpenCircle,
                )
            }

            item {
                Spacer(Modifier.height(8.dp))
                AiProfilePlainCell(
                    title = "能做什么",
                    subtitle = employee.abilityLabels().joinToString("、"),
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(8.dp))
                AiProfilePlainCell(
                    title = "来源",
                    subtitle = employee.sourceLabel,
                    showArrow = false,
                )
            }

            item {
                Spacer(Modifier.height(8.dp))
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
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        windowInsets = WindowInsets(0.dp),
    )
}

@Composable
private fun AiEmployeeContactHeader(employee: AiEmployeeProfile) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            Modifier.padding(start = 24.dp, end = 22.dp, top = 18.dp, bottom = 18.dp),
            verticalAlignment = Alignment.Top,
        ) {
            AiEmployeeAvatar(employee = employee, size = 62.dp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    employee.name,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    "昵称：${employee.title}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
                Text(
                    "AI号：${employee.employeeId}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 5.dp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    "来源：${employee.sourceLabel}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 5.dp),
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
            Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
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
                        modifier = Modifier.padding(top = 6.dp),
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
            Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "AI交流圈",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(88.dp),
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
            .size(44.dp)
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
            Modifier.padding(vertical = 14.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(22.dp),
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
        color = Color(0xFFEAF3EF),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = Color(0xFF1F6F50),
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp),
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
        "可对话" -> "可通过手机端会话触达该员工"
        "可执行任务" -> "已接入企业任务能力"
        "生态同步" -> "随当前账号生态同步"
        "待完善" -> "该员工配置仍在补齐中"
        else -> "来源于 ${employee.modName}"
    }
