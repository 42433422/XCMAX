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
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.model.AiCircleComment
import com.xiuci.xcagi.mobile.core.model.AiCirclePost
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
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
    val avatarUrl: String? = null,
) {
    val key: String = "$modId:$employeeId"
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
                    avatarUrl = employee.market_avatar?.takeIf { it.isNotBlank() }
                        ?: mod.avatar_url?.takeIf { it.isNotBlank() },
                )
            }
        }
    }.distinctBy { it.key } // 防止后端返回重复 employee 导致 key 冲突

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

/**
 * AI 圈预览标签的分类配色（按 key 哈希取色）。
 * 这是一组刻意的「分类装饰色板」，非语义色，故不纳入主题令牌；明暗主题下均为实底色块，可读性一致。
 */
internal fun aiEmployeeAvatarColor(key: String): Color {
    val colors = listOf(
        Color(0xFF3370FF),
        Color(0xFF00B578),
        Color(0xFF8B5CF6),
        Color(0xFF00ACC1),
        Color(0xFFED7B2F),
        Color(0xFF494E56),
    )
    return colors[Math.floorMod(key.hashCode(), colors.size)]
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
    val avatarSource by vm.userAvatarSource.collectAsState()
    val posts by vm.aiCirclePosts.collectAsState()
    val loading by vm.aiCircleLoading.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }

    LaunchedEffect(Unit) {
        vm.refreshModInfos()
        vm.loadAiCirclePosts()
    }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        WeTopBar(title = "AI交流圈", onBack = onBack)

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 24.dp),
        ) {
            item {
                AiCircleHeader(
                    employees = employees,
                    displayName = displayName.ifBlank { "当前账号" },
                    avatarUri = avatarSource,
                )
            }
            if (posts.isEmpty()) {
                item {
                    Box(
                        Modifier.fillMaxWidth().padding(top = 56.dp, bottom = 24.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            if (loading) "正在加载动态…" else "暂无动态，AI 员工的工作汇报会出现在这里",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            } else {
                itemsIndexed(
                    items = posts,
                    key = { _, post -> post.id },
                ) { _, post ->
                    AiCirclePostCard(
                        post = post,
                        onLike = { vm.toggleAiCircleLike(post.id) },
                        onComment = { text -> vm.addAiCircleComment(post.id, text) },
                        onOpenHome = {
                            val eid = post.employee_id?.trim().orEmpty()
                            if (eid.isNotBlank()) {
                                employees.firstOrNull { it.employeeId == eid }
                                    ?.let { onOpenEmployee(it.modId, it.employeeId) }
                            }
                        },
                    )
                }
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
                // 交流圈封面：刻意的深岩灰「封面照」底色（承载白字），明暗主题一致，故保留为常量
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
                    imageSource = avatarUri,
                    modifier = Modifier.border(2.dp, Color.White, MaterialTheme.shapes.extraSmall),
                    size = 50.dp,
                    shape = MaterialTheme.shapes.extraSmall,
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

@Composable
private fun AiCirclePostCard(
    post: AiCirclePost,
    onLike: () -> Unit,
    onComment: (String) -> Unit,
    onOpenHome: () -> Unit,
) {
    val showCommentInput = remember(post.id) { mutableStateOf(false) }
    val draft = remember(post.id) { mutableStateOf("") }
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Column {
            Row(Modifier.padding(start = 16.dp, end = 14.dp, top = 12.dp, bottom = 4.dp)) {
                AppAvatar(
                    imageSource = post.author_avatar,
                    fallback = AppAvatarFallback.AI_EMPLOYEE,
                    size = 42.dp,
                    shape = CircleShape,
                    contentDescription = post.author_name,
                )
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        post.author_name.ifBlank { "AI员工" },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = XcagiTheme.extra.momentAccent,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (post.body.isNotBlank()) {
                        Text(
                            post.body,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                    Row(
                        modifier = Modifier.padding(top = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            formatCircleTime(post.created_at),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                        CircleActionButton(
                            icon = if (post.liked_by_me) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            label = if (post.like_count > 0) "赞 ${post.like_count}" else "赞",
                            tint = if (post.liked_by_me) Color(0xFFE5484D) else XcagiTheme.extra.momentAccent,
                            onClick = onLike,
                        )
                        Spacer(Modifier.width(12.dp))
                        CircleActionButton(
                            icon = Icons.Default.ChatBubbleOutline,
                            label = "评论",
                            tint = XcagiTheme.extra.momentAccent,
                            onClick = { showCommentInput.value = !showCommentInput.value },
                        )
                        if (!post.employee_id.isNullOrBlank()) {
                            Spacer(Modifier.width(12.dp))
                            CircleActionButton(
                                icon = Icons.Default.Person,
                                label = "主页",
                                tint = XcagiTheme.extra.momentAccent,
                                onClick = onOpenHome,
                            )
                        }
                    }
                    if (post.comments.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        CircleComments(post.comments)
                    }
                    if (showCommentInput.value) {
                        Spacer(Modifier.height(6.dp))
                        CircleCommentInput(
                            value = draft.value,
                            onValueChange = { draft.value = it },
                            onSend = {
                                val t = draft.value.trim()
                                if (t.isNotEmpty()) {
                                    onComment(t)
                                    draft.value = ""
                                    showCommentInput.value = false
                                }
                            },
                        )
                    }
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
private fun CircleActionButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    tint: Color,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .clip(MaterialTheme.shapes.small)
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = label,
            tint = tint,
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = tint,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun CircleComments(comments: List<AiCircleComment>) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.extraSmall,
        color = XcagiTheme.extra.replyBoxBg,
    ) {
        Column(Modifier.padding(horizontal = 9.dp, vertical = 6.dp)) {
            comments.forEach { comment ->
                Text(
                    "${comment.author_name.ifBlank { "用户" }}：${comment.body}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 1.dp),
                )
            }
        }
    }
}

@Composable
private fun CircleCommentInput(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("写评论…", style = MaterialTheme.typography.bodySmall) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
        )
        TextButton(onClick = onSend, enabled = value.isNotBlank()) {
            Text("发送")
        }
    }
}

// 后端返回 ISO 时间(如 2026-06-24T07:53:32…)，取「日期 时:分」轻量展示，避免解析时区出错。
private fun formatCircleTime(iso: String): String {
    if (iso.isBlank()) return ""
    val cleaned = iso.replace('T', ' ')
    return if (cleaned.length >= 16) cleaned.substring(0, 16) else cleaned
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

            item {
                Spacer(Modifier.height(8.dp))
                AiProfileActionRow(
                    text = "进入 AI 交流圈",
                    icon = Icons.Default.Forum,
                    onClick = onOpenCircle,
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
        Column(Modifier.padding(horizontal = 20.dp, vertical = 14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Forum,
                    contentDescription = null,
                    tint = XcagiTheme.extra.momentAccent,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        "AI交流圈",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        "进入交流圈 · 查看 ${employee.name} 的动态与能力更新",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                Icon(
                    Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f),
                    modifier = Modifier.size(20.dp),
                )
            }
            val abilities = employee.abilityLabels().take(3)
            if (abilities.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Row(
                    Modifier.padding(start = 30.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    abilities.forEach { label ->
                        AiCirclePreviewTile(label = label, color = aiEmployeeAvatarColor("${employee.key}:$label"))
                    }
                }
            }
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
    AppAvatar(
        imageSource = employee.avatarUrl,
        fallback = AppAvatarFallback.AI_EMPLOYEE,
        size = size,
        shape = CircleShape,
        contentDescription = employee.name,
    )
}

@Composable
private fun AiAbilityChip(label: String) {
    Surface(
        shape = MaterialTheme.shapes.large,
        color = XcagiTheme.extra.momentChipBg,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = XcagiTheme.extra.momentAccent,
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
