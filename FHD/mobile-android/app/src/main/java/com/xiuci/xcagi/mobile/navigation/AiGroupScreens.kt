package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.CallMerge
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PersonRemove
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.outlined.PushPin
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import android.app.Activity
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.core.model.AiGroupDto
import com.xiuci.xcagi.mobile.core.model.AiGroupMemberDraft
import com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto
import com.xiuci.xcagi.mobile.core.model.GitBranchDto
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.MessageAvatarLayout
import com.xiuci.xcagi.mobile.ui.components.mobile.WeField
import com.xiuci.xcagi.mobile.ui.components.mobile.rememberHaptics
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import com.xiuci.xcagi.mobile.core.model.AiGroupMemberDto
import kotlin.math.ceil

// ══════════════════════════════════════════
//  AI 群聊列表（默认 6 部门群 + 自定义群）
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiGroupListScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onOpenGroup: (AiGroupDto) -> Unit,
) {
    val groups by vm.aiGroups.collectAsState()
    var showCreate by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var longPressGroup by remember { mutableStateOf<AiGroupDto?>(null) }
    val haptics = rememberHaptics()

    LaunchedEffect(Unit) { vm.loadAiGroups() }

    if (showCreate) {
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("创建群聊") },
            text = {
                WeField(
                    value = newName,
                    onValueChange = { newName = it },
                    placeholder = "群名称",
                    singleLine = true,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    if (newName.isNotBlank()) { vm.createAiGroup(newName.trim()); newName = ""; showCreate = false }
                }) { Text("创建") }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("取消") } },
        )
    }

    longPressGroup?.let { g ->
        AiGroupActionSheet(
            title = g.name.ifBlank { "群聊操作" },
            onDismiss = { longPressGroup = null },
            actions = listOf(
                AiGroupAction("标为未读") { vm.markGroupUnread(g.id); longPressGroup = null; haptics.tap() },
                AiGroupAction(if (g.is_pinned) "取消置顶" else "置顶聊天") { vm.toggleGroupPin(g.id); longPressGroup = null; haptics.tap() },
                AiGroupAction(if (g.is_followed) "不再关注" else "恢复关注") { vm.toggleGroupFollowed(g.id); longPressGroup = null; haptics.tap() },
                AiGroupAction(if (g.is_hidden) "显示该聊天" else "不显示该聊天") { vm.toggleGroupHidden(g.id); longPressGroup = null; haptics.tap() },
                AiGroupAction("删除该聊天", danger = true) { vm.deleteGroup(g.id); longPressGroup = null; haptics.tap() },
            ),
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("群聊", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showCreate = true }) {
                        Icon(Icons.Default.Add, contentDescription = "创建群聊")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                windowInsets = WindowInsets(0.dp),
            )
        },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding),
            state = rememberLazyListState(),
        ) {
            itemsIndexed(groups, key = { _, g -> g.id }) { idx, group ->
                GroupConversationRow(
                    group = group,
                    onClick = { onOpenGroup(group) },
                    onLongClick = { haptics.confirm(); longPressGroup = group },
                )
                if (idx < groups.lastIndex) {
                    HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(start = 80.dp))
                }
            }
        }
    }
}

// ══════════════════════════════════════════
//  长按群聊操作面板（微信/钉钉式底部 ModalBottomSheet）
// ══════════════════════════════════════════
private data class AiGroupAction(
    val label: String,
    val danger: Boolean = false,
    val onClick: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AiGroupActionSheet(
    title: String,
    onDismiss: () -> Unit,
    actions: List<AiGroupAction>,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    // 点动作时先播放收起动画再执行，质感更顺滑；动画完成后兜底执行。
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
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
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

/** 微信式九宫格群头像：把成员头像拼成网格（最多 9 个），空群显示占位图标。 */
@Composable
internal fun GroupGridAvatar(members: List<AiGroupMemberDto>, size: androidx.compose.ui.unit.Dp) {
    val shown = members.take(9)
    val n = shown.size
    Box(
        modifier = Modifier
            .size(size)
            .clip(MessageAvatarLayout.conversationAvatarShape())
            .background(XcagiTheme.extra.n200),
        contentAlignment = Alignment.Center,
    ) {
        if (n == 0) {
            Icon(
                Icons.Default.Group,
                contentDescription = null,
                tint = XcagiTheme.extra.n400,
                modifier = Modifier.size(size * 0.52f),
            )
        } else {
            val cols = if (n == 1) 1 else if (n <= 4) 2 else 3
            val rows = ceil(n / cols.toFloat()).toInt()
            val gap = 1.5.dp
            val cell = (size - gap * (cols + 1)) / cols
            Column(
                Modifier.padding(gap),
                verticalArrangement = Arrangement.spacedBy(gap),
            ) {
                for (r in 0 until rows) {
                    Row(horizontalArrangement = Arrangement.spacedBy(gap)) {
                        for (c in 0 until cols) {
                            val idx = r * cols + c
                            if (idx < n) {
                                AppAvatar(
                                    imageSource = shown[idx].avatar.ifBlank { null },
                                    fallback = AppAvatarFallback.AI_EMPLOYEE,
                                    size = cell,
                                    shape = RoundedCornerShape(3.dp),
                                )
                            } else {
                                Spacer(Modifier.size(cell))
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 群聊在「消息页」/群列表里的一行（九宫格头像 + 名字 + 预览）。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun GroupConversationRow(
    group: AiGroupDto,
    onClick: () -> Unit,
    onLongClick: (() -> Unit)? = null,
) {
    val dimmed = group.is_hidden || !group.is_followed
    Surface(
        color = if (group.is_pinned) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
        modifier = Modifier.fillMaxWidth().then(
            if (onLongClick != null)
                Modifier.combinedClickable(onClick = onClick, onLongClick = onLongClick)
            else
                Modifier.clickable(onClick = onClick)
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
            GroupGridAvatar(group.members, MessageAvatarLayout.conversationAvatarSize)
            Spacer(Modifier.width(MessageAvatarLayout.conversationAvatarTextGap))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (group.is_pinned) {
                        Icon(
                            imageVector = Icons.Outlined.PushPin,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(Modifier.width(4.dp))
                    }
                    Text(
                        group.name,
                        style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp),
                        fontWeight = FontWeight.Medium,
                        color = if (group.is_hidden) MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f) else if (!group.is_followed) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (group.member_count > 0) {
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "(${group.member_count})",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    group.last_message_preview.ifBlank {
                        if (group.member_count == 0) "还没有成员，进群把 AI 拉进来"
                        else "${group.member_count} 个 AI 成员在群里"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                if (group.unread_count > 0) {
                    Text(
                        text = if (group.unread_count > 99) "99+" else group.unread_count.toString(),
                        modifier = Modifier
                            .background(MaterialTheme.colorScheme.error, RoundedCornerShape(10.dp))
                            .padding(horizontal = 6.dp, vertical = 1.dp),
                        color = androidx.compose.ui.graphics.Color.White,
                        style = MaterialTheme.typography.labelSmall,
                        fontSize = 10.sp,
                    )
                } else {
                    Text(
                        // 原来直接显示原始 ISO 串（2026-06-21T20:38:06.646771+00:00）——一眼"劣质"。
                        // 解析为毫秒后走友好格式：刚刚/X分钟前/X小时前/昨天/M-d。
                        formatTimestamp(
                            com.xiuci.xcagi.mobile.core.im.ImRepository
                                .parseTimestampMs(group.last_message_at) ?: 0L
                        ),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                    )
                }
                if (!group.is_followed && group.unread_count == 0) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "不再关注",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                        fontSize = 10.sp,
                    )
                }
            }
        }
    }
}

// ══════════════════════════════════════════
//  AI 群聊会话（微信群风格：每条显示发送者名+头像）
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiGroupChatScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val group by vm.currentGroup.collectAsState()
    val messages by vm.groupMessages.collectAsState()
    val sending by vm.groupSending.collectAsState()
    val branches by vm.gitBranches.collectAsState()
    val userAvatar by vm.userAvatarSource.collectAsState()
    val modInfos by vm.modInfos.collectAsState()
    val allEmployees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    var input by remember { mutableStateOf("") }
    var showMembers by remember { mutableStateOf(false) }
    var showBranchPicker by remember { mutableStateOf(false) }
    var selectedBranch by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val haptics = rememberHaptics()
    val g = group

    // 系统语音输入（与主聊天一致：小米等系统语音引擎弹 UI 回写）。
    val speechLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                val text = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
                if (text.isNotBlank()) input = if (input.isBlank()) text else "$input $text"
            }
        }
    fun startGroupVoice() {
        runCatching {
            speechLauncher.launch(
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                    putExtra(RecognizerIntent.EXTRA_PROMPT, "请说话…")
                },
            )
        }
    }

    LaunchedEffect(messages.size, sending) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }
    LaunchedEffect(Unit) {
        vm.refreshModInfos()
        vm.loadGitBranches()
    }

    if (showBranchPicker) {
        BranchPickerSheet(
            branches = branches,
            selectedBranch = selectedBranch,
            onDismiss = { showBranchPicker = false },
            onSelect = { selectedBranch = it },
            onRefresh = { vm.loadGitBranches() },
        )
    }

    if (showMembers && g != null) {
        GroupMembersSheet(
            group = g,
            allEmployees = allEmployees,
            onDismiss = { showMembers = false },
            onAdd = { emp ->
                vm.addGroupMember(g.id, emp.employeeId, emp.modId, emp.name, emp.avatarUrl.orEmpty(), emp.summary)
            },
            onRemove = { employeeId -> vm.removeGroupMember(g.id, employeeId) },
        )
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        GroupGridAvatar(g?.members.orEmpty(), 36.dp)
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(
                                g?.name ?: "群聊",
                                fontWeight = FontWeight.Medium,
                                fontSize = 17.sp,
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            )
                            if ((g?.member_count ?: 0) > 0) {
                                Text(
                                    "${g?.member_count} 个 AI 成员",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showMembers = true }) {
                        Icon(Icons.Default.GroupAdd, contentDescription = "群成员")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                windowInsets = WindowInsets(0.dp),
            )
        },
        bottomBar = {
            GroupInputBar(
                value = input,
                onValueChange = { input = it },
                sending = sending,
                selectedBranch = selectedBranch,
                onBranchClick = { showBranchPicker = true },
                onVoice = { startGroupVoice() },
                onSend = {
                    if (g != null && input.isNotBlank()) {
                        haptics.confirm()
                        vm.sendGroupMessage(
                            groupId = g.id,
                            text = input.trim(),
                            branchContext = selectedBranch.orEmpty(),
                        )
                        input = ""
                    }
                },
            )
        },
    ) { padding ->
        if (messages.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier.padding(horizontal = 40.dp).padding(bottom = 40.dp),
                ) {
                    GroupGridAvatar(g?.members.orEmpty(), 64.dp)
                    Spacer(Modifier.height(Spacing.md))
                    Text(
                        if ((g?.member_count ?: 0) == 0) "群里还没有 AI 成员" else "群里安静得很",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Spacer(Modifier.height(Spacing.xs))
                    Text(
                        if ((g?.member_count ?: 0) == 0) "点右上角把 AI 员工拉进群，然后开聊" else "发条消息，群成员会各自回复你",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(padding).padding(horizontal = 14.dp, vertical = 6.dp),
                state = listState,
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                itemsIndexed(messages, key = { _, m -> m.id }) { _, m ->
                    GroupBubble(message = m, userAvatarUrl = userAvatar)
                }
                if (sending) {
                    item { GroupTypingRow() }
                }
            }
        }
    }
}

@Composable
private fun GroupBubble(message: AiGroupMessageDto, userAvatarUrl: String?) {
    val isUser = message.role == "user"
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        if (!isUser) {
            AppAvatar(
                imageSource = message.sender_avatar.ifBlank { null },
                fallback = AppAvatarFallback.AI_EMPLOYEE,
                size = 40.dp,
                shape = RoundedCornerShape(8.dp),
            )
            Spacer(Modifier.width(8.dp))
        }
        Column(horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
            if (!isUser) {
                Text(
                    message.sender_name,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 4.dp, bottom = 2.dp),
                )
            }
            Surface(
                modifier = Modifier.widthIn(max = 260.dp),
                shape = RoundedCornerShape(
                    topStart = if (isUser) 12.dp else 4.dp,
                    topEnd = if (isUser) 4.dp else 12.dp,
                    bottomStart = 12.dp,
                    bottomEnd = 12.dp,
                ),
                color = if (isUser) XcagiTheme.extra.chatUserBubble else MaterialTheme.colorScheme.surface,
                shadowElevation = 1.dp,
                tonalElevation = 0.5.dp,
            ) {
                Text(
                    message.body,
                    style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 21.sp),
                    color = if (isUser) XcagiTheme.extra.chatUserBubbleText else MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }
        }
        if (isUser) {
            Spacer(Modifier.width(8.dp))
            AppAvatar(
                imageSource = userAvatarUrl,
                fallback = AppAvatarFallback.USER,
                size = 40.dp,
                shape = RoundedCornerShape(8.dp),
            )
        }
    }
}

@Composable
private fun GroupTypingRow() {
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)).background(XcagiTheme.extra.n200),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Group, contentDescription = null, tint = XcagiTheme.extra.n400, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.width(8.dp))
        Surface(
            shape = RoundedCornerShape(topStart = 4.dp, topEnd = 12.dp, bottomStart = 12.dp, bottomEnd = 12.dp),
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = 1.dp,
            tonalElevation = 0.5.dp,
        ) {
            Row(
                Modifier.padding(horizontal = 12.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                CircularProgressIndicator(modifier = Modifier.size(13.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
                Text(
                    "AI 成员正在回复…",
                    style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun GroupInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    sending: Boolean,
    selectedBranch: String?,
    onBranchClick: () -> Unit,
    onVoice: () -> Unit,
    onSend: () -> Unit,
) {
    val canSend = value.isNotBlank() && !sending
    val branchLabel = selectedBranch?.takeIf { it.isNotBlank() }?.substringAfterLast('/') ?: "自动新建"
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
        Column {
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    shape = RoundedCornerShape(16.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.clickable(onClick = onBranchClick),
                ) {
                    Row(
                        Modifier.padding(horizontal = 12.dp, vertical = 7.dp).widthIn(max = 260.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.CallMerge,
                            contentDescription = "工作分支",
                            tint = XcagiTheme.extra.brandBlue,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "工作分支 · $branchLabel",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        )
                    }
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp).padding(bottom = Spacing.md),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).clickable(onClick = onVoice),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = "语音",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(22.dp),
                    )
                }
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.background,
                    modifier = Modifier.weight(1f).height(40.dp),
                ) {
                    BasicTextField(
                        value = value,
                        onValueChange = onValueChange,
                        modifier = Modifier.padding(horizontal = 16.dp).fillMaxSize(),
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface, fontSize = 15.sp),
                        cursorBrush = SolidColor(XcagiTheme.extra.weChatOnline),
                        decorationBox = { inner ->
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                                if (value.isEmpty()) {
                                    Text("发群消息（@成员 可单独点名）", style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                inner()
                            }
                        },
                    )
                }
                Box(
                    Modifier.size(40.dp).clip(CircleShape)
                        .background(if (canSend) XcagiTheme.extra.weChatOnline else MaterialTheme.colorScheme.surfaceVariant)
                        .clickable(enabled = canSend, onClick = onSend),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.Send,
                        contentDescription = "发送",
                        tint = if (canSend) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(19.dp),
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BranchPickerSheet(
    branches: List<GitBranchDto>,
    selectedBranch: String?,
    onDismiss: () -> Unit,
    onSelect: (String?) -> Unit,
    onRefresh: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState, containerColor = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxWidth().padding(bottom = Spacing.xxl)) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "工作分支",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = onRefresh) {
                    Icon(Icons.Default.Refresh, contentDescription = "刷新分支", modifier = Modifier.size(20.dp))
                }
            }
            BranchPickerRow(
                title = "自动新建任务分支",
                subtitle = "普通派工默认隔离，跑完后再合并",
                active = selectedBranch.isNullOrBlank(),
                onClick = {
                    onSelect(null)
                    onDismiss()
                },
            )
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            if (branches.isEmpty()) {
                Text(
                    "暂无可选分支，点右上角刷新",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.md),
                )
            } else {
                LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                    itemsIndexed(branches, key = { _, branch -> branch.name }) { _, branch ->
                        val subtitle = when {
                            branch.current -> "当前分支"
                            branch.remote -> "远端分支"
                            else -> "本地分支"
                        }
                        BranchPickerRow(
                            title = branch.name,
                            subtitle = subtitle,
                            active = selectedBranch == branch.name,
                            onClick = {
                                onSelect(branch.name)
                                onDismiss()
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun BranchPickerRow(
    title: String,
    subtitle: String,
    active: Boolean,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = Spacing.lg, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            modifier = Modifier.size(38.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    Icons.AutoMirrored.Filled.CallMerge,
                    contentDescription = null,
                    tint = if (active) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(19.dp),
                )
            }
        }
        Spacer(Modifier.width(Spacing.md))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
        if (active) {
            Icon(
                Icons.Default.Check,
                contentDescription = "已选择",
                tint = XcagiTheme.extra.brandBlue,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

// ══════════════════════════════════════════
//  群成员管理（查看 / 移除 / 添加 AI）
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GroupMembersSheet(
    group: AiGroupDto,
    allEmployees: List<AiEmployeeProfile>,
    onDismiss: () -> Unit,
    onAdd: (AiEmployeeProfile) -> Unit,
    onRemove: (String) -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val memberIds = remember(group) { group.members.map { it.employee_id }.toSet() }
    val addable = remember(allEmployees, memberIds) { allEmployees.filter { it.employeeId !in memberIds } }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState, containerColor = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxWidth().padding(bottom = Spacing.xxl)) {
            Text("群成员（${group.member_count}）", style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium), modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm))

            group.members.forEach { m ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    AppAvatar(imageSource = m.avatar.ifBlank { null }, fallback = AppAvatarFallback.AI_EMPLOYEE, size = 38.dp, shape = RoundedCornerShape(8.dp))
                    Spacer(Modifier.width(Spacing.md))
                    Text(m.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f))
                    IconButton(onClick = { onRemove(m.employee_id) }) {
                        Icon(Icons.Default.PersonRemove, contentDescription = "移除", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(20.dp))
                    }
                }
            }

            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(vertical = 6.dp))
            Text("添加 AI 成员", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm))

            if (addable.isEmpty()) {
                Text(
                    if (allEmployees.isEmpty()) "暂无可用 AI 员工，先在「AI员工」里同步" else "已把所有 AI 员工都拉进群了",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                )
            } else {
                LazyColumn(Modifier.fillMaxWidth().height(260.dp)) {
                    itemsIndexed(addable, key = { _, e -> e.key }) { _, emp ->
                        Row(
                            Modifier.fillMaxWidth().clickable { onAdd(emp) }.padding(horizontal = Spacing.lg, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            AppAvatar(imageSource = emp.avatarUrl, fallback = AppAvatarFallback.AI_EMPLOYEE, size = 38.dp, shape = RoundedCornerShape(8.dp))
                            Spacer(Modifier.width(Spacing.md))
                            Column(Modifier.weight(1f)) {
                                Text(emp.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
                                Text(emp.summary, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                            }
                            Icon(Icons.Default.Add, contentDescription = "添加", tint = XcagiTheme.extra.brandBlue, modifier = Modifier.size(22.dp))
                        }
                    }
                }
            }
        }
    }
}

// ══════════════════════════════════════════
//  微信式发起群聊：多选 AI 员工 → 一次建群
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiGroupCreateScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onCreated: () -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    val selectedKeys = remember { mutableStateListOf<String>() }
    var name by remember { mutableStateOf("") }
    var creating by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { vm.refreshModInfos() }
    val picked = remember(selectedKeys.toList(), employees) { employees.filter { it.key in selectedKeys } }
    val autoName = remember(picked) { picked.joinToString("、") { it.name }.take(40) }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("发起群聊", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(
                        enabled = selectedKeys.isNotEmpty() && !creating,
                        onClick = {
                            creating = true
                            val drafts = picked.map {
                                AiGroupMemberDraft(it.employeeId, it.modId, it.name, it.avatarUrl.orEmpty(), it.summary)
                            }
                            val finalName = name.ifBlank { autoName }.ifBlank { "新建群聊" }
                            vm.createGroupWithMembers(finalName, drafts) { g ->
                                creating = false
                                if (g != null) onCreated()
                            }
                        },
                    ) { Text(if (selectedKeys.isEmpty()) "完成" else "完成(${selectedKeys.size})") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                windowInsets = WindowInsets(0.dp),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                placeholder = { Text(autoName.ifBlank { "群名称（可留空，自动命名）" }, maxLines = 1) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = Spacing.md, vertical = Spacing.sm),
            )
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            if (employees.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "暂无可选 AI 员工，先在「AI员工」里同步",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    itemsIndexed(employees, key = { _, e -> e.key }) { _, e ->
                        val checked = e.key in selectedKeys
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable { if (checked) selectedKeys.remove(e.key) else selectedKeys.add(e.key) }
                                .padding(horizontal = Spacing.md, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = checked,
                                onCheckedChange = { if (checked) selectedKeys.remove(e.key) else selectedKeys.add(e.key) },
                            )
                            Spacer(Modifier.width(Spacing.sm))
                            AppAvatar(imageSource = e.avatarUrl, fallback = AppAvatarFallback.AI_EMPLOYEE, size = 40.dp, shape = RoundedCornerShape(8.dp))
                            Spacer(Modifier.width(Spacing.md))
                            Column(Modifier.weight(1f)) {
                                Text(e.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
                                Text(e.summary, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                            }
                        }
                        HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(start = 84.dp))
                    }
                }
            }
        }
    }
}
