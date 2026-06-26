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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PersonRemove
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.outlined.PushPin
import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.speech.SpeechRecognizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
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
import kotlinx.coroutines.delay
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
import com.xiuci.xcagi.mobile.core.speech.VoiceInputSheet
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
                                    fallback = aiGroupMemberFallback(shown[idx].employee_id),
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
    onOpenOcr: () -> Unit = {},
) {
    val group by vm.currentGroup.collectAsState()
    val messages by vm.groupMessages.collectAsState()
    val sending by vm.groupSending.collectAsState()
    val userAvatar by vm.userAvatarSource.collectAsState()
    val modInfos by vm.modInfos.collectAsState()
    val allEmployees = remember(modInfos) { modInfos.aiGroupMemberCatalog() }
    val g = group
    var input by remember { mutableStateOf("") }
    var showMembers by remember { mutableStateOf(false) }
    var showGroupTools by remember { mutableStateOf(false) }
    var dispatchMode by remember { mutableStateOf(false) }
    var showBranchSheet by remember { mutableStateOf(false) }
    var selectedBranch by remember(g?.id) { mutableStateOf("") }
    var showVoiceSheet by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val haptics = rememberHaptics()
    val context = LocalContext.current
    val branchCandidates = remember(messages, selectedBranch) {
        aiGroupBranchCandidates(messages, selectedBranch)
    }

    val voicePermissionLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) showVoiceSheet = true
            else vm.snack("需要麦克风权限才能使用语音输入", true)
        }

    if (showVoiceSheet) {
        VoiceInputSheet(
            onResult = { text ->
                input = if (input.isBlank()) text else "$input $text"
            },
            onDismiss = { showVoiceSheet = false },
        )
    }

    if (showBranchSheet) {
        AiGroupBranchSheet(
            group = g,
            selectedBranch = selectedBranch,
            candidates = branchCandidates,
            onSelect = { branch ->
                selectedBranch = normalizeAiGroupBranch(branch)
                showBranchSheet = false
                if (selectedBranch.isNotBlank()) {
                    vm.snack("已选择分支：${selectedBranch.substringAfterLast('/')}")
                }
            },
            onCreate = {
                selectedBranch = newAiGroupBranchName(g)
                showBranchSheet = false
                vm.snack("已准备新分支：${selectedBranch.substringAfterLast('/')}")
            },
            onClear = {
                selectedBranch = ""
                showBranchSheet = false
                vm.snack("已切回自动隔离分支")
            },
            onDismiss = { showBranchSheet = false },
        )
    }

    fun startGroupVoice() {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            vm.snack("当前设备未提供语音输入", true)
            return
        }
        val granted =
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        if (granted) {
            showVoiceSheet = true
        } else {
            voicePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    fun copyGroupMessage(text: String) {
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("群聊消息", text))
        vm.snack("已复制")
    }

    LaunchedEffect(messages.size, sending) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }
    LaunchedEffect(g?.id) {
        val groupId = g?.id ?: return@LaunchedEffect
        vm.loadAiGroupMessages(groupId)
        while (true) {
            delay(2_500)
            vm.loadAiGroupMessages(groupId, showError = false).join()
        }
    }
    LaunchedEffect(Unit) { vm.refreshModInfos() }

    val groupToolActions =
        buildList {
            add(
                if (dispatchMode) {
                    XcagiComposerToolAction("普通消息", "下一条不生成工作单", Icons.Default.Close) {
                        dispatchMode = false
                        showGroupTools = false
                    }
                } else {
                    XcagiComposerToolAction("派工模式", "下一条生成工作单", Icons.Default.AutoAwesome) {
                        dispatchMode = true
                        showGroupTools = false
                    }
                },
            )
            add(
                XcagiComposerToolAction("工作分支", "选择或新建干净分支", Icons.Default.AccountTree) {
                    showGroupTools = false
                    showBranchSheet = true
                },
            )
            add(
                XcagiComposerToolAction("群成员", "添加或移除 AI 员工", Icons.Default.GroupAdd) {
                    showGroupTools = false
                    showMembers = true
                },
            )
            add(
                XcagiComposerToolAction("语音输入", "打开系统语音识别", Icons.Default.Mic) {
                    showGroupTools = false
                    startGroupVoice()
                },
            )
            add(
                XcagiComposerToolAction("OCR 识别", "拍照或选图识别", Icons.Default.PhotoCamera) {
                    showGroupTools = false
                    onOpenOcr()
                },
            )
            add(
                XcagiComposerToolAction("同步工作台", "刷新移动端缓存", Icons.Default.Refresh) {
                    showGroupTools = false
                    vm.runSyncNow()
                },
            )
            add(
                XcagiComposerToolAction("刷新消息", "拉取群聊最新记录", Icons.Default.Refresh) {
                    showGroupTools = false
                    g?.id?.let { vm.loadAiGroupMessages(it) } ?: vm.snack("群聊还在加载", true)
                },
            )
            add(
                XcagiComposerToolAction("收起工具", "回到输入状态", Icons.Default.Close) {
                    showGroupTools = false
                },
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
                onValueChange = {
                    input = it
                    if (it.isNotBlank()) showGroupTools = false
                },
                sending = sending,
                dispatchMode = dispatchMode,
                onDispatchModeChange = { dispatchMode = it },
                branchContext = selectedBranch,
                onBranchClick = { showBranchSheet = true },
                showToolPanel = showGroupTools && !sending && input.isBlank(),
                toolActions = groupToolActions,
                onVoice = {
                    showGroupTools = false
                    startGroupVoice()
                },
                onMore = { showGroupTools = !showGroupTools },
                onSend = {
                    if (g != null && input.isNotBlank()) {
                        haptics.confirm()
                        vm.sendGroupMessage(
                            g.id,
                            input.trim(),
                            dispatch = dispatchMode,
                            branchContext = if (dispatchMode) selectedBranch else "",
                        )
                        input = ""
                        dispatchMode = false
                        showGroupTools = false
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
                                if ((g?.member_count ?: 0) == 0) "点右上角把 AI 员工拉进群，然后开聊" else "默认小C接待；@成员点对点，@所有人广播",
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
                    GroupBubble(
                        message = m,
                        userAvatarUrl = userAvatar,
                        onCopy = {
                            haptics.tap()
                            copyGroupMessage(m.body)
                        },
                        onDelete = if (m.role == "user" && !m.id.startsWith("local-")) {
                            {
                                haptics.confirm()
                                g?.id?.let { vm.deleteGroupMessage(it, m.id) }
                            }
                        } else {
                            null
                        },
                    )
                }
                if (sending) {
                    item { GroupTypingRow() }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun GroupBubble(
    message: AiGroupMessageDto,
    userAvatarUrl: String?,
    onCopy: () -> Unit,
    onDelete: (() -> Unit)?,
) {
    val isUser = message.role == "user"
    val isWork = !isUser && isAiGroupWorkMessage(message.kind)
    var showActions by remember { mutableStateOf(false) }
    val longPressModifier = Modifier.combinedClickable(
        onClick = {},
        onLongClick = { showActions = true },
    )
    if (showActions) {
        AiGroupActionSheet(
            title = if (isUser) "我的消息" else message.sender_name.ifBlank { "消息操作" },
            onDismiss = { showActions = false },
            actions = buildList {
                add(AiGroupAction("复制") {
                    showActions = false
                    onCopy()
                })
                if (onDelete != null) {
                    add(AiGroupAction("删除", danger = true) {
                        showActions = false
                        onDelete()
                    })
                }
            },
        )
    }
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        if (!isUser) {
            AppAvatar(
                imageSource = message.sender_avatar.ifBlank { null },
                fallback = aiGroupMemberFallback(message.sender_id),
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
            if (isWork) {
                AiGroupWorkCard(message, longPressModifier)
            } else {
                Surface(
                    modifier = Modifier.widthIn(max = 260.dp).then(longPressModifier),
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
private fun AiGroupWorkCard(message: AiGroupMessageDto, modifier: Modifier = Modifier) {
    val lines = remember(message.kind, message.body) {
        aiGroupWorkCardLines(message.kind, message.body)
    }
    val accent = aiGroupWorkAccent(message.kind, message.status)
    val label = aiGroupWorkKindLabel(message.kind)
    val status = aiGroupWorkStatusLabel(message.kind, message.status)
    Surface(
        modifier = modifier.widthIn(max = 292.dp),
        shape = RoundedCornerShape(topStart = 4.dp, topEnd = 12.dp, bottomStart = 12.dp, bottomEnd = 12.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
        tonalElevation = 0.5.dp,
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = RoundedCornerShape(7.dp),
                    color = accent.copy(alpha = 0.13f),
                ) {
                    Icon(
                        imageVector = when (message.kind) {
                            "work_order", "routing_decision" -> Icons.Default.GroupAdd
                            "work_acceptance" -> Icons.Default.AutoAwesome
                            else -> Icons.Default.Refresh
                        },
                        contentDescription = null,
                        tint = accent,
                        modifier = Modifier.padding(5.dp).size(15.dp),
                    )
                }
                Spacer(Modifier.width(8.dp))
                Text(
                    label,
                    style = MaterialTheme.typography.labelLarge.copy(fontSize = 14.sp),
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
                AiGroupStatusPill(status, accent)
            }
            if (lines.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    lines.forEach { line ->
                        Text(
                            line,
                            style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 19.sp),
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AiGroupStatusPill(label: String, color: Color) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = color.copy(alpha = 0.12f),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall.copy(fontSize = 11.sp),
            color = color,
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
            maxLines = 1,
        )
    }
}

private fun isAiGroupWorkMessage(kind: String): Boolean =
    kind in setOf("discussion", "routing_decision", "work_order", "work_report", "work_progress", "relay_work_report", "work_acceptance")

private fun aiGroupWorkKindLabel(kind: String): String =
    when (kind) {
        "discussion" -> "任务讨论"
        "routing_decision" -> "小C分工"
        "work_order" -> "工作派单"
        "work_report" -> "接单进度"
        "work_progress" -> "进度回访"
        "relay_work_report" -> "员工回报"
        "work_acceptance" -> "小C验收"
        else -> "工作消息"
    }

private fun aiGroupWorkStatusLabel(kind: String, status: String): String {
    val normalized = status.trim().lowercase()
    return when {
        kind == "work_acceptance" && normalized == "completed" -> "可验收"
        kind == "discussion" && normalized == "completed" -> "已讨论"
        normalized in setOf("queued", "assigned", "accepted") -> "已接单"
        normalized in setOf("running", "in_progress") -> "执行中"
        normalized in setOf("completed", "done") -> "完成"
        normalized in setOf("failed", "blocked") -> "需处理"
        normalized.isNotBlank() -> status
        else -> "记录"
    }
}

@Composable
private fun aiGroupWorkAccent(kind: String, status: String): Color {
    val normalized = status.trim().lowercase()
    return when {
        normalized in setOf("failed", "blocked") -> MaterialTheme.colorScheme.error
        kind == "work_acceptance" -> XcagiTheme.extra.weChatOnline
        kind == "work_order" || kind == "routing_decision" -> XcagiTheme.extra.brandBlue
        else -> MaterialTheme.colorScheme.primary
    }
}

private fun aiGroupWorkCardLines(kind: String, body: String): List<String> {
    val raw = body.lines().map { it.trim() }.filter { it.isNotBlank() }
    val cleaned =
        raw.mapNotNull { line ->
            val text = line
                .removePrefix("【小C分工】")
                .removePrefix("【小C派单】")
                .removePrefix("【小C验收】")
                .removePrefix("【任务讨论】")
                .replace("执行汇报】", "】")
                .trim()
                .trimStart('：', ':')
                .trim()
            when {
                text.isBlank() -> null
                text == "成员：" || text == "成员回报：" || text == "分工：" -> text
                kind == "work_acceptance" && text.startsWith("任务：") -> null
                text.startsWith("流程：") -> null
                text.startsWith("你不用翻执行端") -> null
                text.startsWith("下一步：我完成后") -> null
                text.startsWith("下一步：等其他负责人") -> null
                else -> compactAiGroupWorkLine(kind, text)
            }
        }
    val limit =
        when (kind) {
            "work_acceptance" -> 6
            "work_order" -> 8
            else -> 5
        }
    return cleaned.take(limit)
}

private fun compactAiGroupWorkLine(kind: String, line: String): String {
    val maxChars =
        when {
            kind == "work_acceptance" && line.startsWith("- ") -> 42
            kind == "work_acceptance" -> 54
            line.startsWith("结果：") -> 74
            else -> 86
        }
    return if (line.length <= maxChars) line else line.take(maxChars).trimEnd() + "…"
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

private val AiGroupBranchLineRegex = Regex("(?:工作分支|分支)[：:]\\s*([A-Za-z0-9._/-]{2,180})")

private fun normalizeAiGroupBranch(raw: String): String {
    var branch = raw.trim()
    if (branch.startsWith("origin/")) branch = branch.removePrefix("origin/")
    branch = branch
        .replace(Regex("\\s+"), "-")
        .replace(Regex("[^A-Za-z0-9._/-]+"), "-")
        .replace(Regex("/+"), "/")
        .trim('/', '.')
    while (branch.contains("..")) branch = branch.replace("..", ".")
    return if (branch == "HEAD") "" else branch.take(180)
}

private fun newAiGroupBranchName(group: AiGroupDto?): String {
    val rawName = group?.name.orEmpty().lowercase()
    val slug = normalizeAiGroupBranch(rawName).ifBlank { "group" }.substringAfterLast('/').take(32)
    val suffix = System.currentTimeMillis().toString().takeLast(8)
    return "mobile-group/$slug-$suffix"
}

private fun aiGroupBranchCandidates(
    messages: List<AiGroupMessageDto>,
    selectedBranch: String,
): List<String> {
    val seen = linkedSetOf<String>()
    normalizeAiGroupBranch(selectedBranch).takeIf { it.isNotBlank() }?.let { seen.add(it) }
    messages.asReversed().forEach { message ->
        AiGroupBranchLineRegex.findAll(message.body).forEach { match ->
            normalizeAiGroupBranch(match.groupValues.getOrNull(1).orEmpty())
                .takeIf { it.isNotBlank() }
                ?.let { seen.add(it) }
        }
    }
    return seen.take(8)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AiGroupBranchSheet(
    group: AiGroupDto?,
    selectedBranch: String,
    candidates: List<String>,
    onSelect: (String) -> Unit,
    onCreate: () -> Unit,
    onClear: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var manualBranch by remember(selectedBranch) { mutableStateOf(selectedBranch) }
    val normalizedManual = normalizeAiGroupBranch(manualBranch)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.sm).padding(bottom = Spacing.xxl)) {
            Text(
                "工作分支",
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.xs))
            Text(
                if (selectedBranch.isBlank()) {
                    "当前使用自动隔离分支；派工时每个任务会自动创建干净工作分支。"
                } else {
                    "当前派工会进入 $selectedBranch。"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(Spacing.md))
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = XcagiTheme.extra.brandBlue.copy(alpha = 0.1f),
                modifier = Modifier.fillMaxWidth().clickable(onClick = onCreate),
            ) {
                Row(
                    Modifier.padding(horizontal = 12.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.AccountTree, contentDescription = null, tint = XcagiTheme.extra.brandBlue, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text("新建干净分支", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
                        Text(newAiGroupBranchName(group), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    }
                }
            }
            if (candidates.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.lg))
                Text("最近分支", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(Spacing.xs))
                candidates.forEach { branch ->
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = if (branch == selectedBranch) XcagiTheme.extra.weChatOnline.copy(alpha = 0.1f) else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.42f),
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { onSelect(branch) },
                    ) {
                        Row(
                            Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(Icons.Default.AccountTree, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(branch, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
            Spacer(Modifier.height(Spacing.lg))
            WeField(
                value = manualBranch,
                onValueChange = { manualBranch = it },
                placeholder = "输入已有分支或新分支名",
                singleLine = true,
            )
            Row(
                Modifier.fillMaxWidth().padding(top = Spacing.sm),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onClear) { Text("自动") }
                TextButton(
                    enabled = normalizedManual.isNotBlank(),
                    onClick = { onSelect(normalizedManual) },
                ) { Text("选择") }
            }
        }
    }
}

@Composable
private fun GroupInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    sending: Boolean,
    dispatchMode: Boolean,
    onDispatchModeChange: (Boolean) -> Unit,
    branchContext: String,
    onBranchClick: () -> Unit,
    showToolPanel: Boolean,
    toolActions: List<XcagiComposerToolAction>,
    onVoice: () -> Unit,
    onMore: () -> Unit,
    onSend: () -> Unit,
) {
    val canSend = value.isNotBlank() && !sending
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
        Column {
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            if (dispatchMode) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = Spacing.lg, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = XcagiTheme.extra.brandBlue.copy(alpha = 0.12f),
                        modifier = Modifier.clickable { onDispatchModeChange(false) },
                    ) {
                        Row(
                            Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Default.AutoAwesome,
                                contentDescription = null,
                                tint = XcagiTheme.extra.brandBlue,
                                modifier = Modifier.size(14.dp),
                            )
                            Spacer(Modifier.width(4.dp))
                            Text(
                                "派工",
                                style = MaterialTheme.typography.labelMedium,
                                color = XcagiTheme.extra.brandBlue,
                            )
                        }
                    }
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.56f),
                        modifier = Modifier.widthIn(max = 148.dp).clickable(onClick = onBranchClick),
                    ) {
                        Row(
                            Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Default.AccountTree,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(14.dp),
                            )
                            Spacer(Modifier.width(4.dp))
                            Text(
                                if (branchContext.isBlank()) "自动分支" else branchContext.substringAfterLast('/'),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            )
                        }
                    }
                    Text(
                        "下一条发送为工作单",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp).padding(bottom = Spacing.md),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                IconButton(onClick = onVoice, modifier = Modifier.size(38.dp)) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = "语音",
                        tint = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.size(22.dp),
                    )
                }
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.background,
                    modifier = Modifier.weight(1f).height(38.dp),
                ) {
                    BasicTextField(
                        value = value,
                        onValueChange = onValueChange,
                        modifier = Modifier.padding(horizontal = 12.dp).fillMaxSize(),
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface, fontSize = 15.sp),
                        cursorBrush = SolidColor(XcagiTheme.extra.weChatOnline),
                        decorationBox = { inner ->
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                                if (value.isEmpty()) {
                                    Text(
                                        if (dispatchMode) "输入派工任务" else "发群消息（@成员 可单独点名）",
                                        style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp),
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                                    )
                                }
                                inner()
                            }
                        },
                    )
                }
                if (canSend || sending) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color =
                            if (sending) MaterialTheme.colorScheme.surfaceVariant
                            else if (dispatchMode) XcagiTheme.extra.warning
                            else XcagiTheme.extra.brandBlue,
                        modifier = Modifier
                            .height(38.dp)
                            .clickable(enabled = canSend, onClick = onSend),
                    ) {
                        Box(
                            Modifier.fillMaxSize().padding(horizontal = 17.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                when {
                                    sending -> "发送中"
                                    dispatchMode -> "派工"
                                    else -> "发送"
                                },
                                style = MaterialTheme.typography.labelLarge.copy(
                                    fontWeight = FontWeight.Medium,
                                    fontSize = 15.sp,
                                ),
                                color =
                                    if (sending) MaterialTheme.colorScheme.onSurfaceVariant
                                    else Color.White,
                            )
                        }
                    }
                } else {
                    XcagiComposerMoreButton(
                        expanded = showToolPanel,
                        onClick = onMore,
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
            if (showToolPanel) {
                XcagiComposerToolPanel(actions = toolActions)
            }
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
    var query by remember { mutableStateOf("") }
    val memberIds = remember(group) { group.members.map { it.employee_id }.toSet() }
    val addable = remember(allEmployees, memberIds, query) {
        allEmployees.filter { it.employeeId !in memberIds && it.matchesGroupMemberQuery(query) }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState, containerColor = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxWidth().padding(bottom = Spacing.xxl)) {
            Text("群成员（${group.member_count}）", style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium), modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm))

            group.members.forEach { m ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    AppAvatar(imageSource = m.avatar.ifBlank { null }, fallback = aiGroupMemberFallback(m.employee_id), size = 38.dp, shape = RoundedCornerShape(8.dp))
                    Spacer(Modifier.width(Spacing.md))
                    Text(m.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f))
                    if (isRequiredAiGroupMember(m.employee_id)) {
                        Text(
                            "固定",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        IconButton(onClick = { onRemove(m.employee_id) }) {
                            Icon(Icons.Default.PersonRemove, contentDescription = "移除", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(20.dp))
                        }
                    }
                }
            }

            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(vertical = 6.dp))
            Text("添加 AI 成员", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm))
            SearchBarField(
                value = query,
                onValueChange = { query = it },
                onClear = { query = "" },
                placeholder = "搜索员工、超级员工或小C",
                modifier = Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = Spacing.xs),
            )

            if (addable.isEmpty()) {
                Text(
                    if (allEmployees.isEmpty()) "暂无可用 AI 员工，先在「AI员工」里同步" else if (query.isBlank()) "已把所有 AI 员工都拉进群了" else "没有匹配的成员",
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
                            AppAvatar(imageSource = emp.avatarUrl, fallback = aiGroupMemberFallback(emp.employeeId), size = 38.dp, shape = RoundedCornerShape(8.dp))
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
@Composable
private fun GroupCreateNameField(
    value: String,
    onValueChange: (String) -> Unit,
    autoName: String,
    selectedCount: Int,
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.5.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.fillMaxWidth().padding(horizontal = Spacing.lg, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "群名称",
                    style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Medium),
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    "$selectedCount 人",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(8.dp))
            Surface(
                shape = RoundedCornerShape(8.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
                modifier = Modifier.fillMaxWidth().height(42.dp),
            ) {
                BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                        fontSize = 15.sp,
                    ),
                    cursorBrush = SolidColor(XcagiTheme.extra.brandBlue),
                    modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                            if (value.isBlank()) {
                                Text(
                                    autoName.ifBlank { "留空后自动使用成员名称" },
                                    style = MaterialTheme.typography.bodyMedium.copy(fontSize = 15.sp),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                                )
                            }
                            inner()
                        }
                    },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiGroupCreateScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onCreated: () -> Unit,
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiGroupMemberCatalog() }
    val selectedKeys = remember { mutableStateListOf(XIAOC_GROUP_PROFILE.key) }
    var name by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var creating by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { vm.refreshModInfos() }
    LaunchedEffect(employees) {
        if (XIAOC_GROUP_PROFILE.key !in selectedKeys) selectedKeys.add(XIAOC_GROUP_PROFILE.key)
    }
    val picked = remember(selectedKeys.toList(), employees) { employees.filter { it.key in selectedKeys } }
    val visibleEmployees = remember(employees, query) {
        employees.filter { it.matchesGroupMemberQuery(query) }
    }
    val autoName = remember(picked) { suggestedAiGroupName(picked) }

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
                        enabled = picked.isNotEmpty() && !creating,
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
                    ) { Text(if (picked.isEmpty()) "完成" else "完成(${picked.size})") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                windowInsets = WindowInsets(0.dp),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            GroupCreateNameField(
                value = name,
                onValueChange = { name = it },
                autoName = autoName,
                selectedCount = picked.size,
            )
            SearchBarField(
                value = query,
                onValueChange = { query = it },
                onClear = { query = "" },
                placeholder = "搜索员工、超级员工或小C",
                modifier = Modifier.fillMaxWidth().padding(horizontal = Spacing.md, vertical = Spacing.xs),
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
                    itemsIndexed(visibleEmployees, key = { _, e -> e.key }) { _, e ->
                        val checked = e.key in selectedKeys
                        val locked = isRequiredAiGroupMember(e.employeeId)
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable(enabled = !locked) { if (checked) selectedKeys.remove(e.key) else selectedKeys.add(e.key) }
                                .padding(horizontal = Spacing.md, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = checked,
                                onCheckedChange = {
                                    if (!locked) {
                                        if (checked) selectedKeys.remove(e.key) else selectedKeys.add(e.key)
                                    }
                                },
                                enabled = !locked,
                            )
                            Spacer(Modifier.width(Spacing.sm))
                            AppAvatar(imageSource = e.avatarUrl, fallback = aiGroupMemberFallback(e.employeeId), size = 40.dp, shape = RoundedCornerShape(8.dp))
                            Spacer(Modifier.width(Spacing.md))
                            Column(Modifier.weight(1f)) {
                                Text(e.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1)
                                Text(e.summary, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                            }
                            if (locked) {
                                Text(
                                    "固定",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(start = 84.dp))
                    }
                }
            }
        }
    }
}

private fun suggestedAiGroupName(picked: List<AiEmployeeProfile>): String {
    val ids = picked.map { it.employeeId.trim() }.toSet()
    val superDevIds = setOf(
        XIAOC_ASSISTANT_EMPLOYEE_ID,
        CODEX_SUPER_EMPLOYEE_ID,
        CURSOR_SUPER_EMPLOYEE_ID,
        CLAUDE_SUPER_EMPLOYEE_ID,
        TRAE_SUPER_EMPLOYEE_ID,
    )
    if (superDevIds.all { it in ids }) return "超级开发部"
    return picked.joinToString("、") { it.name }.take(40)
}
