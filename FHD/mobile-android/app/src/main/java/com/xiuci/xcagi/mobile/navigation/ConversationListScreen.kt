package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Contacts
import androidx.compose.material.icons.filled.Public
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
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
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.ConversationType
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.LocalProfileAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageAvatarLayout
import com.xiuci.xcagi.mobile.ui.components.mobile.rememberHaptics
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

// ═══════════════════════════════════════════
// 首页 — 会话列表（微信风格）
// ═══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
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
        onStartGroupChat: () -> Unit = {},
        onOpenGroups: () -> Unit = {},
        onOpenGroup: (com.xiuci.xcagi.mobile.core.model.AiGroupDto) -> Unit = {},
) {
    val conversations by vm.conversations.collectAsState()
    val aiGroups by vm.aiGroups.collectAsState()
    val displayName by vm.displayName.collectAsState()
    val avatarSource by vm.userAvatarSource.collectAsState()
    val accountKindLabel by vm.accountKindLabel.collectAsState()
    val refreshing by vm.conversationsRefreshing.collectAsState()
    // 使用 rememberSaveable 保持 UI 状态：切 tab / 旋转屏幕后搜索词和筛选不丢失
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var selectedFilter by rememberSaveable { mutableStateOf(ConversationFilter.ALL) }
    // 群聊长按菜单
    var longPressGroup by remember { mutableStateOf<com.xiuci.xcagi.mobile.core.model.AiGroupDto?>(null) }
    // 会话长按菜单
    var longPressItem by remember { mutableStateOf<ConversationItem?>(null) }
    val haptics = rememberHaptics()
    // 保持列表滚动位置：切 tab 回来后不回到顶部
    val listState = rememberLazyListState()
    // 企业态判定与 ViewModel 对齐：admin/admin_portal 账号在 personal flavor 上也需加载 AI 群聊
    val isEnterprise by vm.isEnterpriseEffective.collectAsState()
    val hasEcosystemEmployees = conversations.any { it.type == ConversationType.AI_TASK }
    val employeeCount = conversations.count { it.type == ConversationType.AI_TASK }
    val unreadTotal = conversations.sumOf { it.unreadCount }

    // 首次进入：拉取一次（受 TTL 控制，5 分钟内不重复请求）
    LaunchedEffect(isEnterprise, accountKindLabel) { vm.loadConversations(isEnterprise) }

    // AI 群聊（学微信：6 个部门群直接出现在消息页）。仅企业/管理端有群。
    LaunchedEffect(isEnterprise) { if (isEnterprise) vm.loadAiGroups() }
    val filteredGroups =
            remember(searchQuery, aiGroups) {
                if (searchQuery.isBlank()) aiGroups
                else aiGroups.filter { it.name.contains(searchQuery, ignoreCase = true) }
            }

    // 长按群聊时的操作菜单（微信/钉钉式底部动作面板）
    longPressGroup?.let { g ->
        ConversationActionSheet(
                title = g.name.ifBlank { "群聊操作" },
                onDismiss = { longPressGroup = null },
                actions = listOf(
                        ConversationAction("标为未读") { vm.markGroupUnread(g.id); longPressGroup = null; haptics.tap() },
                        ConversationAction(if (g.is_pinned) "取消置顶" else "置顶聊天") { vm.toggleGroupPin(g.id); longPressGroup = null; haptics.tap() },
                        ConversationAction(if (g.is_followed) "不再关注" else "恢复关注") { vm.toggleGroupFollowed(g.id); longPressGroup = null; haptics.tap() },
                        ConversationAction(if (g.is_hidden) "显示该聊天" else "不显示该聊天") { vm.toggleGroupHidden(g.id); longPressGroup = null; haptics.tap() },
                        ConversationAction("删除该聊天", danger = true) { vm.deleteGroup(g.id); longPressGroup = null; haptics.tap() },
                ),
        )
    }

    // 长按会话时的操作菜单（微信/钉钉式底部动作面板）
    longPressItem?.let { item ->
        ConversationActionSheet(
                title = item.title.ifBlank { "会话操作" },
                onDismiss = { longPressItem = null },
                actions = listOf(
                        ConversationAction(if (item.unreadCount > 0) "标为已读" else "标为未读") { vm.toggleConversationUnread(item.id); longPressItem = null; haptics.tap() },
                        ConversationAction(if (item.isPinned) "取消置顶" else "置顶聊天") { vm.toggleConversationPin(item.id); longPressItem = null; haptics.tap() },
                        ConversationAction(if (item.isFollowed) "不再关注" else "恢复关注") { vm.toggleConversationFollowed(item.id); longPressItem = null; haptics.tap() },
                        ConversationAction(if (item.isHidden) "显示该聊天" else "不显示该聊天") { vm.toggleConversationHidden(item.id); longPressItem = null; haptics.tap() },
                        ConversationAction("删除该聊天", danger = true) { vm.deleteConversation(item.id); longPressItem = null; haptics.tap() },
                ),
        )
    }

    // ON_RESUME 静默刷新：从其他页面返回时，若缓存过期则后台刷新（不显示 loading）
    // force=false → TTL 内不刷新；静默刷新不触发 refreshing 状态，用户无感知
    LifecycleResumeEffect(Unit) {
        vm.loadConversations(isEnterprise, force = false)
        // 群也在恢复时重拉：抓住 token 新鲜的时机（admin 接口令牌过期时会 401 静默失败）。
        if (isEnterprise) vm.loadAiGroups()
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
                        onStartGroupChat = onStartGroupChat,
                        onOpenGroups = onOpenGroups,
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
                    // AI 群聊（6 个部门群，学微信直接出现在消息页）
                    items(filteredGroups, key = { "group:${it.id}" }) { group ->
                        Column(Modifier.animateItemPlacement()) {
                            GroupConversationRow(
                                group = group,
                                onClick = { onOpenGroup(group) },
                                onLongClick = { haptics.confirm(); longPressGroup = group },
                            )
                            HorizontalDivider(
                                    color = MaterialTheme.colorScheme.outlineVariant,
                                    thickness = 0.5.dp,
                                    modifier = Modifier.padding(start = MessageAvatarLayout.conversationDividerStart),
                            )
                        }
                    }
                    items(filtered, key = { it.id }) { item ->
                        Column(Modifier.animateItemPlacement()) {
                            ConversationCell(
                                    item = item,
                                    onClick = {
                                        when (item.id) {
                                            PinnedIds.ASSISTANT -> onOpenAssistant()
                                            PinnedIds.CS -> onOpenCustomerService()
                                            PinnedIds.CODEX -> onOpenConversation(PinnedIds.CODEX)
                                            PinnedIds.CURSOR -> onOpenConversation(PinnedIds.CURSOR)
                                            PinnedIds.CLAUDE -> onOpenConversation(PinnedIds.CLAUDE)
                                            PinnedIds.TRAE -> onOpenConversation(PinnedIds.TRAE)
                                            else -> onOpenConversation(item.id)
                                        }
                                    },
                                    onLongClick = { haptics.confirm(); longPressItem = item },
                            )
                            HorizontalDivider(
                                    color = MaterialTheme.colorScheme.outlineVariant,
                                    thickness = 0.5.dp,
                                    modifier = Modifier.padding(start = MessageAvatarLayout.conversationDividerStart),
                            )
                        }
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

// ═══════════════════════════════════════════
// 长按操作面板（微信/钉钉式底部 ModalBottomSheet）
// ═══════════════════════════════════════════
private data class ConversationAction(
        val label: String,
        val danger: Boolean = false,
        val onClick: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ConversationActionSheet(
        title: String,
        onDismiss: () -> Unit,
        actions: List<ConversationAction>,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    // 点动作时先播放收起动画再执行，质感更顺滑；动画失败也兜底执行。
    fun runThenClose(action: () -> Unit) {
        scope.launch { sheetState.hide() }.invokeOnCompletion { action() }
    }
    ModalBottomSheet(
            onDismissRequest = onDismiss,
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(Modifier.fillMaxWidth().padding(bottom = Spacing.lg)) {
            if (title.isNotBlank()) {
                Box(
                        Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                        contentAlignment = Alignment.Center,
                ) {
                    Text(
                            title,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                    )
                }
                HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            }
            actions.forEachIndexed { index, action ->
                Box(
                        Modifier.fillMaxWidth()
                                .height(52.dp)
                                .clickable { runThenClose(action.onClick) },
                        contentAlignment = Alignment.Center,
                ) {
                    Text(
                            action.label,
                            style = MaterialTheme.typography.bodyLarge,
                            color = if (action.danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                    )
                }
                if (index < actions.lastIndex) {
                    HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
                }
            }
        }
    }
}

@Composable
private fun MessageHomeHeader(
        displayName: String,
        avatarUri: String,
        subtitle: String,
        searchQuery: String,
        onSearchChange: (String) -> Unit,
        onClearSearch: () -> Unit,
        onStartGroupChat: () -> Unit,
        onOpenGroups: () -> Unit,
        onOpenEmployees: () -> Unit,
        onOpenContacts: () -> Unit,
        onOpenDiscover: () -> Unit,
        onOpenScan: () -> Unit,
) {
    Surface(
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = Elevation.none,
    ) {
        // 学微信：只留 身份行(含右上「+」菜单) + 搜索,去掉快捷操作行与筛选条,更干净。
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
                HeaderPlusMenu(
                        onStartGroupChat = onStartGroupChat,
                        onOpenGroups = onOpenGroups,
                        onOpenEmployees = onOpenEmployees,
                        onOpenContacts = onOpenContacts,
                        onOpenDiscover = onOpenDiscover,
                        onOpenScan = onOpenScan,
                )
            }

            Spacer(Modifier.height(Spacing.md))

            SearchBarField(
                    value = searchQuery,
                    onValueChange = onSearchChange,
                    onClear = onClearSearch,
                    modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

/** 右上「+」菜单（微信式）：发起群聊 / 我的群聊 / 扫一扫 / AI员工 / 通讯录 / 交流圈。 */
@Composable
private fun HeaderPlusMenu(
        onStartGroupChat: () -> Unit,
        onOpenGroups: () -> Unit,
        onOpenEmployees: () -> Unit,
        onOpenContacts: () -> Unit,
        onOpenDiscover: () -> Unit,
        onOpenScan: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { expanded = true }) {
            Icon(Icons.Default.Add, contentDescription = "更多", tint = MaterialTheme.colorScheme.onSurface)
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            shape = RoundedCornerShape(14.dp),
            containerColor = MaterialTheme.colorScheme.surface,
            tonalElevation = 0.dp,
            shadowElevation = 12.dp,
            modifier = Modifier.width(188.dp),
        ) {
            PlusMenuRow(Icons.Default.Groups, "发起群聊") { expanded = false; onStartGroupChat() }
            PlusMenuRow(Icons.Default.QrCodeScanner, "扫一扫") { expanded = false; onOpenScan() }
            PlusMenuRow(Icons.Default.SmartToy, "AI 员工") { expanded = false; onOpenEmployees() }
            PlusMenuRow(Icons.Default.Contacts, "通讯录") { expanded = false; onOpenContacts() }
            PlusMenuRow(Icons.Default.Public, "交流圈") { expanded = false; onOpenDiscover() }
        }
    }
}

@Composable
private fun PlusMenuRow(icon: ImageVector, label: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = XcagiTheme.extra.brandBlue,
            modifier = Modifier.size(20.dp),
        )
        Spacer(Modifier.width(14.dp))
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun BrandIdentityAvatar(avatarUri: String) {
    LocalProfileAvatar(
            imageSource = avatarUri,
            size = MessageAvatarLayout.headerAvatarSize,
            shape = MessageAvatarLayout.headerAvatarShape(),
    )
}

@Composable
internal fun SearchBarField(
        value: String,
        onValueChange: (String) -> Unit,
        onClear: () -> Unit,
        modifier: Modifier = Modifier,
        placeholder: String = "查找会话或伙伴",
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
                                        placeholder,
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
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ConversationCell(
        item: ConversationItem,
        onClick: () -> Unit,
        onLongClick: (() -> Unit)? = null,
) {
    val hasUnread = item.unreadCount > 0
    val timestampText = formatTimestamp(item.timestamp)
    val visibleBadge = item.badgeText?.takeUnless { it == timestampText }
    val dimmed = item.isHidden || !item.isFollowed

    Surface(
            color = if (item.isPinned) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
            modifier = Modifier.fillMaxWidth().then(
                    if (onLongClick != null) Modifier.combinedClickable(onClick = onClick, onLongClick = onLongClick)
                    else Modifier.clickable(onClick = onClick)
            ),
    ) {
        Row(
                Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = MessageAvatarLayout.conversationRowHorizontalPadding,
                        vertical = MessageAvatarLayout.conversationRowVerticalPadding,
                    ),
                verticalAlignment = Alignment.CenterVertically,
        ) {
            // ── 头像 ──
            Box {
                when (item.type) {
                    ConversationType.PINNED_ASSISTANT,
                    ConversationType.PINNED_CS,
                    ConversationType.PINNED_CODEX,
                    ConversationType.PINNED_CURSOR,
                    ConversationType.PINNED_CLAUDE,
                    ConversationType.PINNED_TRAE -> PinnedAvatar(type = item.type)
                    else -> AppAvatar(
                        imageSource = item.avatarUrl,
                        fallback = AppAvatarFallback.AI_EMPLOYEE,
                        size = MessageAvatarLayout.conversationAvatarSize,
                        shape = MessageAvatarLayout.conversationAvatarShape(),
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
                                            .offset(
                                                x = MessageAvatarLayout.unreadBadgeOffsetX,
                                                y = MessageAvatarLayout.unreadBadgeOffsetY,
                                            )
                                            .zIndex(10f)
                                            .size(
                                                if (item.unreadCount > 99) {
                                                    MessageAvatarLayout.unreadBadgeLargeSize
                                                } else {
                                                    MessageAvatarLayout.unreadBadgeSize
                                                },
                                            ),
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
                                    .offset(x = 0.dp, y = MessageAvatarLayout.onlineIndicatorOffsetY)
                                    .zIndex(10f)
                                    .size(MessageAvatarLayout.onlineIndicatorSize)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.surface)
                                    .padding(MessageAvatarLayout.onlineIndicatorPadding)
                                    .background(XcagiTheme.extra.weChatOnline, CircleShape),
                    )
                }
            }

            Spacer(Modifier.width(MessageAvatarLayout.conversationAvatarTextGap))

            // ── 文字区域 ──
            Column(Modifier.weight(1f).height(IntrinsicSize.Min)) {
                // 第一行：名称 | 时间
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                            text = item.title,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = if (hasUnread) FontWeight.Bold else FontWeight.SemiBold,
                            color = if (item.isHidden) MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f) else if (!item.isFollowed) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
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
        ConversationType.PINNED_CURSOR -> CursorAvatar()
        ConversationType.PINNED_CLAUDE -> ClaudeAvatar()
        ConversationType.PINNED_TRAE -> TraeAvatar()
        else -> AssistantAvatar()
    }
}

/** 小C助理固定图片头像 */
@Composable
private fun AssistantAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.ASSISTANT,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "小C助理",
    )
}

/** 专属客服固定图片头像 */
@Composable
private fun CsAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CUSTOMER_SERVICE,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "专属客服",
    )
}

/** 超级员工-Codex 头像 */
@Composable
private fun CodexAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CODEX,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "超级员工-Codex",
    )
}

/** 超级员工-Cursor 头像 */
@Composable
private fun CursorAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CURSOR,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "超级员工-Cursor",
    )
}

/** 超级员工-Claude 头像 */
@Composable
private fun ClaudeAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.CLAUDE,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "超级员工-Claude",
    )
}

/** 超级员工-Trae 头像 */
@Composable
private fun TraeAvatar() {
    AppAvatar(
        fallback = AppAvatarFallback.TRAE,
        size = MessageAvatarLayout.conversationAvatarSize,
        shape = MessageAvatarLayout.conversationAvatarShape(),
        contentDescription = "超级员工-Trae",
    )
}

// ═══════════════════════════════════════════
// 时间格式化
// ═══════════════════════════════════════════
internal fun formatTimestamp(ts: Long): String {
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
