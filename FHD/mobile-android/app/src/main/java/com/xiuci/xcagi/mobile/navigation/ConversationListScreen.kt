package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.ConversationType
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.LocalProfileAvatar
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

// ═══════════════════════════════════════════
// 首页 — 会话列表（微信风格）
// ═══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationListScreen(
        vm: AppViewModel,
        onOpenAssistant: () -> Unit,
        onOpenCustomerService: () -> Unit,
        onOpenConversation: (String) -> Unit,
        onOpenScan: () -> Unit,
        onOpenEmployees: () -> Unit,
        onOpenContacts: () -> Unit,
        onOpenDiscover: () -> Unit,
) {
    val conversations by vm.conversations.collectAsState()
    val displayName by vm.displayName.collectAsState()
    val avatarSource by vm.userAvatarSource.collectAsState()
    val accountKindLabel by vm.accountKindLabel.collectAsState()
    val refreshing by vm.conversationsRefreshing.collectAsState()
    // 使用 rememberSaveable 保持 UI 状态：切 tab / 旋转屏幕后搜索词和筛选不丢失
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var selectedFilter by rememberSaveable { mutableStateOf(ConversationFilter.ALL) }
    // 保持列表滚动位置：切 tab 回来后不回到顶部
    val listState = rememberLazyListState()
    val isEnterprise = ProductSkuConfig.showsEnterpriseNav
    val hasEcosystemEmployees = conversations.any { it.type == ConversationType.AI_TASK }
    val employeeCount = conversations.count { it.type == ConversationType.AI_TASK }
    val unreadTotal = conversations.sumOf { it.unreadCount }

    // 首次进入：拉取一次（受 TTL 控制，5 分钟内不重复请求）
    LaunchedEffect(isEnterprise, accountKindLabel) { vm.loadConversations(isEnterprise) }

    // ON_RESUME 静默刷新：从其他页面返回时，若缓存过期则后台刷新（不显示 loading）
    // force=false → TTL 内不刷新；静默刷新不触发 refreshing 状态，用户无感知
    LifecycleResumeEffect(Unit) {
        vm.loadConversations(isEnterprise, force = false)
        onPauseOrDispose { }
    }

    val filtered =
            remember(searchQuery, selectedFilter, conversations) {
                conversations
                        .filter { item ->
                            when (selectedFilter) {
                                ConversationFilter.ALL -> true
                                ConversationFilter.PINNED -> item.isPinned
                                ConversationFilter.UNREAD -> item.unreadCount > 0
                            }
                        }
                        .filter { item ->
                            searchQuery.isBlank() ||
                                    item.title.contains(searchQuery, ignoreCase = true) ||
                                            item.subtitle.contains(searchQuery, ignoreCase = true)
                        }
            }

    Scaffold(
            containerColor = MaterialTheme.colorScheme.surface,
            topBar = {
                MessageHomeHeader(
                        displayName =
                                displayName.ifBlank {
                                    if (isEnterprise) "XCAGI 企业版" else "XCAGI 个人版"
                                },
                        avatarUri = avatarSource,
                        subtitle =
                                buildString {
                                    append(accountKindLabel.ifBlank { "未登录" })
                                    if (employeeCount > 0) append(" · ${employeeCount}位AI员工")
                                },
                        searchQuery = searchQuery,
                        onSearchChange = { searchQuery = it },
                        onClearSearch = { searchQuery = "" },
                        selectedFilter = selectedFilter,
                        unreadTotal = unreadTotal,
                        onFilterChange = { selectedFilter = it },
                        onOpenEmployees = onOpenEmployees,
                        onOpenContacts = onOpenContacts,
                        onOpenDiscover = onOpenDiscover,
                        onOpenScan = onOpenScan,
                )
            },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 下拉刷新：用户主动下拉时强制刷新（force=true），保留旧数据不闪烁
            PullToRefreshBox(
                    isRefreshing = refreshing,
                    onRefresh = { vm.loadConversations(isEnterprise, force = true) },
                    modifier = Modifier.weight(1f).fillMaxWidth(),
            ) {
                LazyColumn(
                        state = listState,
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.spacedBy(0.dp),
                ) {
                    items(filtered, key = { it.id }) { item ->
                        ConversationCell(
                                item = item,
                                onClick = {
                                    when (item.id) {
                                        PinnedIds.ASSISTANT -> onOpenAssistant()
                                        PinnedIds.CS -> onOpenCustomerService()
                                        PinnedIds.CODEX -> onOpenConversation(PinnedIds.CODEX)
                                        PinnedIds.CLAUDE -> onOpenConversation(PinnedIds.CLAUDE)
                                        else -> onOpenConversation(item.id)
                                    }
                                }
                        )
                        HorizontalDivider(
                                color = MaterialTheme.colorScheme.outlineVariant,
                                thickness = 0.5.dp,
                                modifier = Modifier.padding(start = 84.dp),
                        )
                    }

                    if (!hasEcosystemEmployees && searchQuery.isBlank() && selectedFilter == ConversationFilter.ALL) {
                        item { EcosystemSyncHint(onRefresh = { vm.loadConversations(isEnterprise, force = true) }) }
                    }

                    if (filtered.isEmpty()) {
                        item {
                            Box(
                                    Modifier.fillParentMaxSize().padding(vertical = 80.dp),
                                    contentAlignment = Alignment.Center,
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    if (refreshing) {
                                        CircularProgressIndicator(
                                                modifier = Modifier.size(28.dp),
                                                strokeWidth = 2.dp,
                                                color = MaterialTheme.colorScheme.primary,
                                        )
                                        Spacer(Modifier.height(Spacing.sm))
                                    }
                                    Text(
                                            if (refreshing) "正在同步会话…" else "暂无会话",
                                            style = MaterialTheme.typography.bodyLarge,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    if (!refreshing) {
                                        Spacer(Modifier.height(Spacing.sm))
                                        Text(
                                                "下拉刷新或和小C助理聊聊吧",
                                                style = MaterialTheme.typography.bodyMedium,
                                                color = MaterialTheme.colorScheme.outline,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private enum class ConversationFilter {
    ALL,
    PINNED,
    UNREAD,
}

@Composable
private fun MessageHomeHeader(
        displayName: String,
        avatarUri: String,
        subtitle: String,
        searchQuery: String,
        onSearchChange: (String) -> Unit,
        onClearSearch: () -> Unit,
        selectedFilter: ConversationFilter,
        unreadTotal: Int,
        onFilterChange: (ConversationFilter) -> Unit,
        onOpenEmployees: () -> Unit,
        onOpenContacts: () -> Unit,
        onOpenDiscover: () -> Unit,
        onOpenScan: () -> Unit,
) {
    Surface(
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = Elevation.none,
    ) {
        Column(
                Modifier.fillMaxWidth()
                        .padding(start = Spacing.lg, end = Spacing.lg, top = 8.dp, bottom = 10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                BrandIdentityAvatar(avatarUri)
                Spacer(Modifier.width(Spacing.md))
                Column(Modifier.weight(1f)) {
                    Text(
                            displayName,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                            subtitle,
                            style = MaterialTheme.typography.labelMedium,
                            color = XcagiTheme.extra.n500,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                    )
                }
            }

            Spacer(Modifier.height(Spacing.md))

            SearchBarField(
                    value = searchQuery,
                    onValueChange = onSearchChange,
                    onClear = onClearSearch,
                    modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(Spacing.md))

            QuickActionRow(
                    onOpenEmployees = onOpenEmployees,
                    onOpenContacts = onOpenContacts,
                    onOpenDiscover = onOpenDiscover,
                    onOpenScan = onOpenScan,
            )

            Spacer(Modifier.height(Spacing.md))

            ConversationFilterBar(
                    selected = selectedFilter,
                    unreadTotal = unreadTotal,
                    onSelect = onFilterChange,
            )
        }
    }
}

@Composable
private fun BrandIdentityAvatar(avatarUri: String) {
    LocalProfileAvatar(
            imageSource = avatarUri,
            size = 44.dp,
            shape = RoundedCornerShape(10.dp),
    )
}

@Composable
internal fun SearchBarField(
        value: String,
        onValueChange: (String) -> Unit,
        onClear: () -> Unit,
        modifier: Modifier = Modifier,
) {
    Surface(
            shape = RoundedCornerShape(20.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            border = BorderStroke(0.5.dp, XcagiTheme.extra.n200),
            shadowElevation = Elevation.none,
            modifier = modifier.height(38.dp),
    ) {
        Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(horizontal = 14.dp),
        ) {
            Icon(
                    Icons.Default.Search,
                    contentDescription = null,
                    tint = XcagiTheme.extra.n400,
                    modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(Spacing.sm))
            BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    textStyle =
                            MaterialTheme.typography.bodyMedium.copy(
                                    color = MaterialTheme.colorScheme.onSurface,
                            ),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                            if (value.isEmpty()) {
                                Text(
                                        "查找会话或伙伴",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = XcagiTheme.extra.n400,
                                )
                            }
                            inner()
                        }
                    },
            )
            if (value.isNotEmpty()) {
                Box(
                        Modifier.size(18.dp)
                                .clip(CircleShape)
                                .clickable(onClick = onClear)
                                .background(MaterialTheme.colorScheme.outlineVariant),
                        contentAlignment = Alignment.Center,
                ) {
                    Text(
                            "\u00D7",
                            color = MaterialTheme.colorScheme.surface,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                    )
                }
            }
        }
    }
}

@Composable
private fun QuickActionRow(
        onOpenEmployees: () -> Unit,
        onOpenContacts: () -> Unit,
        onOpenDiscover: () -> Unit,
        onOpenScan: () -> Unit,
) {
    Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        QuickAction(
                label = "AI员工",
                glyph = QuickGlyph.PARTNER,
                color = XcagiTheme.extra.brandBlue,
                onClick = onOpenEmployees,
                modifier = Modifier.weight(1f),
        )
        QuickAction(
                label = "通讯录",
                glyph = QuickGlyph.DIRECTORY,
                color = XcagiTheme.extra.success,
                onClick = onOpenContacts,
                modifier = Modifier.weight(1f),
        )
        QuickAction(
                label = "交流圈",
                glyph = QuickGlyph.COMPASS,
                color = XcagiTheme.extra.warning,
                onClick = onOpenDiscover,
                modifier = Modifier.weight(1f),
        )
        QuickAction(
                label = "扫码",
                glyph = QuickGlyph.SCAN,
                color = XcagiTheme.extra.n600,
                onClick = onOpenScan,
                modifier = Modifier.weight(1f),
        )
    }
}

private enum class QuickGlyph {
    PARTNER,
    DIRECTORY,
    COMPASS,
    SCAN,
    SYNC,
}

@Composable
private fun QuickAction(
        label: String,
        glyph: QuickGlyph,
        color: Color,
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
) {
    Surface(
            modifier = modifier.padding(horizontal = 2.dp),
            onClick = onClick,
            shape = RoundedCornerShape(8.dp),
            color = Color.Transparent,
    ) {
        Column(
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(contentAlignment = Alignment.TopEnd) {
                Box(
                        Modifier.size(34.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(color.copy(alpha = 0.11f)),
                        contentAlignment = Alignment.Center,
                ) {
                    QuickGlyphIcon(glyph = glyph, color = color, modifier = Modifier.size(21.dp))
                }
            }
            Spacer(Modifier.height(5.dp))
            Text(
                    label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
            )
        }
    }
}

@Composable
private fun QuickGlyphIcon(glyph: QuickGlyph, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val stroke = Stroke(width = size.minDimension * 0.10f, cap = StrokeCap.Round)
        val thin = Stroke(width = size.minDimension * 0.075f, cap = StrokeCap.Round)
        when (glyph) {
            QuickGlyph.PARTNER -> {
                drawRoundRect(
                        color = color,
                        topLeft = Offset(size.width * 0.18f, size.height * 0.22f),
                        size = Size(size.width * 0.64f, size.height * 0.54f),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(
                                size.width * 0.18f,
                                size.height * 0.18f,
                        ),
                        style = stroke,
                )
                drawCircle(color, radius = size.minDimension * 0.055f, center = Offset(size.width * 0.39f, size.height * 0.48f))
                drawCircle(color, radius = size.minDimension * 0.055f, center = Offset(size.width * 0.61f, size.height * 0.48f))
                drawLine(color, Offset(size.width * 0.50f, size.height * 0.12f), Offset(size.width * 0.50f, size.height * 0.22f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(color, Offset(size.width * 0.34f, size.height * 0.84f), Offset(size.width * 0.66f, size.height * 0.84f), strokeWidth = stroke.width, cap = StrokeCap.Round)
            }
            QuickGlyph.DIRECTORY -> {
                drawRoundRect(
                        color = color,
                        topLeft = Offset(size.width * 0.24f, size.height * 0.13f),
                        size = Size(size.width * 0.52f, size.height * 0.74f),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(size.width * 0.08f),
                        style = stroke,
                )
                drawLine(color, Offset(size.width * 0.76f, size.height * 0.30f), Offset(size.width * 0.85f, size.height * 0.30f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawLine(color, Offset(size.width * 0.76f, size.height * 0.52f), Offset(size.width * 0.85f, size.height * 0.52f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawCircle(color, radius = size.minDimension * 0.09f, center = Offset(size.width * 0.50f, size.height * 0.42f), style = thin)
                drawArc(color, startAngle = 205f, sweepAngle = 130f, useCenter = false, topLeft = Offset(size.width * 0.37f, size.height * 0.52f), size = Size(size.width * 0.26f, size.height * 0.20f), style = thin)
            }
            QuickGlyph.COMPASS -> {
                drawCircle(color, radius = size.minDimension * 0.36f, center = center, style = stroke)
                drawLine(color, Offset(size.width * 0.60f, size.height * 0.34f), Offset(size.width * 0.42f, size.height * 0.60f), strokeWidth = stroke.width, cap = StrokeCap.Round)
                drawCircle(color, radius = size.minDimension * 0.035f, center = center)
            }
            QuickGlyph.SCAN -> {
                val left = size.width * 0.18f
                val right = size.width * 0.82f
                val top = size.height * 0.18f
                val bottom = size.height * 0.82f
                val len = size.minDimension * 0.20f
                listOf(left to top, right to top, left to bottom, right to bottom).forEachIndexed { index, (x, y) ->
                    val hEnd = if (index % 2 == 0) x + len else x - len
                    val vEnd = if (index < 2) y + len else y - len
                    drawLine(color, Offset(x, y), Offset(hEnd, y), strokeWidth = stroke.width, cap = StrokeCap.Round)
                    drawLine(color, Offset(x, y), Offset(x, vEnd), strokeWidth = stroke.width, cap = StrokeCap.Round)
                }
                drawCircle(color, radius = size.minDimension * 0.04f, center = Offset(size.width * 0.42f, size.height * 0.44f))
                drawCircle(color, radius = size.minDimension * 0.04f, center = Offset(size.width * 0.58f, size.height * 0.44f))
                drawLine(color, Offset(size.width * 0.42f, size.height * 0.62f), Offset(size.width * 0.62f, size.height * 0.62f), strokeWidth = thin.width, cap = StrokeCap.Round)
            }
            QuickGlyph.SYNC -> {
                drawRoundRect(
                        color = color,
                        topLeft = Offset(size.width * 0.18f, size.height * 0.24f),
                        size = Size(size.width * 0.64f, size.height * 0.48f),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(size.width * 0.12f),
                        style = stroke,
                )
                drawLine(color, Offset(size.width * 0.34f, size.height * 0.48f), Offset(size.width * 0.66f, size.height * 0.48f), strokeWidth = thin.width, cap = StrokeCap.Round)
            }
        }
    }
}

@Composable
private fun ConversationFilterBar(
        selected: ConversationFilter,
        unreadTotal: Int,
        onSelect: (ConversationFilter) -> Unit,
) {
    val items =
            listOf(
                    ConversationFilter.ALL to "全量",
                    ConversationFilter.PINNED to "星标",
                    ConversationFilter.UNREAD to
                            if (unreadTotal > 0) "待读 ${if (unreadTotal > 99) "99+" else unreadTotal}" else "待读",
            )
    Surface(
            modifier = Modifier.fillMaxWidth().height(42.dp),
            shape = RoundedCornerShape(21.dp),
            color = XcagiTheme.extra.n50,
            shadowElevation = Elevation.none,
    ) {
        Row(Modifier.fillMaxSize().padding(4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            items.forEach { (filter, label) ->
                val isSelected = selected == filter
                Box(
                        Modifier.weight(1f)
                                .fillMaxSize()
                                .clip(RoundedCornerShape(17.dp))
                                .background(
                                        if (isSelected) MaterialTheme.colorScheme.surface
                                        else Color.Transparent
                                )
                                .clickable { onSelect(filter) },
                        contentAlignment = Alignment.Center,
                ) {
                    Text(
                            label,
                            style = MaterialTheme.typography.bodyMedium,
                            color =
                                    if (isSelected) MaterialTheme.colorScheme.onSurface
                                    else XcagiTheme.extra.n500,
                            fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Medium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun EcosystemSyncHint(onRefresh: () -> Unit) {
    Row(
            Modifier.fillMaxWidth()
                    .clickable(onClick = onRefresh)
                    .padding(horizontal = Spacing.lg, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
                Modifier.size(34.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(XcagiTheme.extra.n50),
                contentAlignment = Alignment.Center,
        ) {
            QuickGlyphIcon(
                    glyph = QuickGlyph.SYNC,
                    color = XcagiTheme.extra.n400,
                    modifier = Modifier.size(19.dp),
            )
        }
        Spacer(Modifier.width(Spacing.md))
        Column(Modifier.weight(1f)) {
            Text(
                    "账号生态待同步",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                    "点这里重新同步管理端员工。",
                    style = MaterialTheme.typography.bodySmall,
                    color = XcagiTheme.extra.n500,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

// ═══════════════════════════════════════════
// 会话单元格 — 核心组件
// ═══════════════════════════════════════════
@Composable
private fun ConversationCell(item: ConversationItem, onClick: () -> Unit) {
    val hasUnread = item.unreadCount > 0
    val timestampText = formatTimestamp(item.timestamp)
    val visibleBadge = item.badgeText?.takeUnless { it == timestampText }

    Surface(
            color = MaterialTheme.colorScheme.surface,
            modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Row(
                Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
        ) {
            // ── 头像 ──
            Box {
                when (item.type) {
                    ConversationType.PINNED_ASSISTANT,
                    ConversationType.PINNED_CS,
                    ConversationType.PINNED_CODEX,
                    ConversationType.PINNED_CLAUDE -> PinnedAvatar(type = item.type)
                    else -> AppAvatar(
                        imageSource = item.avatarUrl,
                        fallback = AppAvatarFallback.AI_EMPLOYEE,
                        size = 52.dp,
                        shape = MaterialTheme.shapes.small,
                        contentDescription = item.title,
                    )
                }

                // 待读角标：头像右上角红色圆点
                if (hasUnread) {
                    Surface(
                            shape = CircleShape,
                            color = XcagiTheme.extra.danger,
                            modifier =
                                    Modifier.align(Alignment.TopEnd)
                                            .offset(x = 5.dp, y = (-5).dp)
                                            .zIndex(10f)
                                            .size(if (item.unreadCount > 99) 25.dp else 21.dp),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(
                                    text =
                                            if (item.unreadCount > 99) "99+"
                                            else "${item.unreadCount}",
                                    color = Color.White,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                // 在线绿点（专属客服右下角）
                if (item.isOnline && item.type == ConversationType.PINNED_CS) {
                    Box(
                            Modifier.align(Alignment.BottomEnd)
                                    .offset(x = 0.dp, y = 2.dp)
                                    .zIndex(10f)
                                    .size(14.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.surface)
                                    .padding(2.5.dp)
                                    .background(XcagiTheme.extra.weChatOnline, CircleShape),
                    )
                }
            }

            Spacer(Modifier.width(Spacing.md))

            // ── 文字区域 ──
            Column(Modifier.weight(1f).height(IntrinsicSize.Min)) {
                // 第一行：名称 | 时间
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                            text = item.title,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = if (hasUnread) FontWeight.Bold else FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(Spacing.xs))
                    Text(
                            text = timestampText,
                            style = MaterialTheme.typography.labelMedium,
                            color =
                                    if (hasUnread) XcagiTheme.extra.n600
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                            fontWeight = if (hasUnread) FontWeight.Medium else FontWeight.Normal,
                    )
                }

                Spacer(Modifier.height(5.dp))

                // 第二行：副标题预览 + 徽标
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                            text = item.subtitle,
                            style = MaterialTheme.typography.bodyMedium,
                            color =
                                    if (hasUnread) MaterialTheme.colorScheme.onSurfaceVariant
                                    else XcagiTheme.extra.n600,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                            fontWeight = if (hasUnread) FontWeight.Medium else FontWeight.Normal,
                    )

                    visibleBadge?.let { badge ->
                        Spacer(Modifier.width(Spacing.sm))
                        StatusBadge(
                                text = badge,
                                color = item.badgeColor ?: XcagiTheme.extra.weChatOnline,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun StatusBadge(text: String, color: Color) {
    Surface(
            shape = RoundedCornerShape(10.dp),
            color = color.copy(alpha = 0.12f),
            border = BorderStroke(0.5.dp, color.copy(alpha = 0.3f)),
    ) {
        Text(
                text = text,
                style = MaterialTheme.typography.labelSmall.copy(
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium,
                ),
                color = color,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
        )
    }
}

// ═══════════════════════════════════════════
// 固定联系人头像 — 品牌设计
// ═══════════════════════════════════════════
@Composable
private fun PinnedAvatar(type: ConversationType) {
    when (type) {
        ConversationType.PINNED_ASSISTANT -> AssistantAvatar()
        ConversationType.PINNED_CS -> CsAvatar()
        ConversationType.PINNED_CODEX -> CodexAvatar()
        ConversationType.PINNED_CLAUDE -> ClaudeAvatar()
        else -> AssistantAvatar()
    }
}

/** 小C助理固定图片头像 */
@Composable
private fun AssistantAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.ASSISTANT,
        size = 52.dp,
        shape = MaterialTheme.shapes.small,
        contentDescription = "小C助理",
    )
}

/** 专属客服固定图片头像 */
@Composable
private fun CsAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CUSTOMER_SERVICE,
        size = 52.dp,
        shape = MaterialTheme.shapes.small,
        contentDescription = "专属客服",
    )
}

/** 超级员工-Codex 头像 */
@Composable
private fun CodexAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CODEX,
        size = 52.dp,
        shape = MaterialTheme.shapes.small,
        contentDescription = "超级员工-Codex",
    )
}

/** 超级员工-Claude 头像 */
@Composable
private fun ClaudeAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CLAUDE,
        size = 52.dp,
        shape = MaterialTheme.shapes.small,
        contentDescription = "超级员工-Claude",
    )
}

// ═══════════════════════════════════════════
// 时间格式化
// ═══════════════════════════════════════════
private fun formatTimestamp(ts: Long): String {
    if (ts <= 0L) return ""
    val now = System.currentTimeMillis()
    val diffMs = now - ts
    return when {
        diffMs < 60_000L -> "刚刚"
        diffMs < 3600_000L -> "${diffMs / 60_000}分钟前"
        diffMs < 86400_000L -> "${diffMs / 3_600_000}小时前"
        diffMs < 172800_000L -> "昨天"
        else -> {
            val calNow = java.util.Calendar.getInstance()
            val calMsg = java.util.Calendar.getInstance().apply { timeInMillis = ts }
            if (calNow.get(java.util.Calendar.YEAR) == calMsg.get(java.util.Calendar.YEAR))
                    java.text.SimpleDateFormat("M/d", java.util.Locale.CHINA)
                            .format(java.util.Date(ts))
            else
                    java.text.SimpleDateFormat("yy/M/d", java.util.Locale.CHINA)
                            .format(java.util.Date(ts))
        }
    }
}
