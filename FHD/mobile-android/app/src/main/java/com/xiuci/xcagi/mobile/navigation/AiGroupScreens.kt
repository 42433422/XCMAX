package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.PersonRemove
import androidx.compose.material3.AlertDialog
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.core.model.AiGroupDto
import com.xiuci.xcagi.mobile.core.model.AiGroupMessageDto
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.rememberHaptics
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

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

    LaunchedEffect(Unit) { vm.loadAiGroups() }

    if (showCreate) {
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("创建群聊") },
            text = {
                OutlinedTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    singleLine = true,
                    placeholder = { Text("群名称") },
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
                Surface(
                    color = MaterialTheme.colorScheme.surface,
                    modifier = Modifier.fillMaxWidth().clickable { onOpenGroup(group) },
                ) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = Spacing.md, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        GroupAvatar()
                        Spacer(Modifier.width(Spacing.md))
                        Column(Modifier.weight(1f)) {
                            Text(
                                group.name,
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = FontWeight.Medium,
                                color = MaterialTheme.colorScheme.onSurface,
                                maxLines = 1,
                            )
                            Spacer(Modifier.height(2.dp))
                            Text(
                                group.last_message_preview.ifBlank {
                                    if (group.member_count == 0) "还没有成员，进群把 AI 拉进来"
                                    else "${group.member_count} 个 AI 成员"
                                },
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                        }
                        if (group.member_count > 0) {
                            Text(
                                "${group.member_count}人",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                if (idx < groups.lastIndex) {
                    HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant, modifier = Modifier.padding(start = 68.dp))
                }
            }
        }
    }
}

@Composable
private fun GroupAvatar() {
    Box(
        modifier = Modifier.size(48.dp).clip(RoundedCornerShape(10.dp))
            .background(XcagiTheme.extra.brandBlue.copy(alpha = 0.12f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Default.Group, contentDescription = null, tint = XcagiTheme.extra.brandBlue, modifier = Modifier.size(26.dp))
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
    val userAvatar by vm.userAvatarSource.collectAsState()
    val modInfos by vm.modInfos.collectAsState()
    val allEmployees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    var input by remember { mutableStateOf("") }
    var showMembers by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val haptics = rememberHaptics()
    val g = group

    LaunchedEffect(messages.size, sending) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }
    LaunchedEffect(Unit) { vm.refreshModInfos() }

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
                    Column {
                        Text(g?.name ?: "群聊", fontWeight = FontWeight.Medium, fontSize = 17.sp, maxLines = 1)
                        if ((g?.member_count ?: 0) > 0) {
                            Text("${g?.member_count} 个 AI 成员", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
                onSend = {
                    if (g != null && input.isNotBlank()) {
                        haptics.confirm()
                        vm.sendGroupMessage(g.id, input.trim())
                        input = ""
                    }
                },
            )
        },
    ) { padding ->
        if (messages.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(horizontal = 40.dp)) {
                    Text(
                        if ((g?.member_count ?: 0) == 0) "点右上角把 AI 员工拉进群，然后开聊" else "群里安静得很，发条消息试试",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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
    Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(8.dp))
        Text("AI 成员正在回复…", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun GroupInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    sending: Boolean,
    onSend: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
        Column {
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp).padding(bottom = Spacing.md),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.background,
                    modifier = Modifier.weight(1f).height(40.dp),
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
                                    Text("发群消息（@成员 可单独点名）", style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                inner()
                            }
                        },
                    )
                }
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = if (value.isBlank() || sending) MaterialTheme.colorScheme.surfaceVariant else XcagiTheme.extra.weChatOnline,
                    modifier = Modifier.size(40.dp).clickable(enabled = value.isNotBlank() && !sending, onClick = onSend),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            Icons.AutoMirrored.Filled.Send,
                            contentDescription = "发送",
                            tint = if (value.isBlank() || sending) MaterialTheme.colorScheme.onSurfaceVariant else Color.White,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
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
