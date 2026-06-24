package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CallMerge
import androidx.compose.material.icons.filled.Difference
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.ChatSuggestion
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.rememberHaptics
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBarAvatarAction
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import com.xiuci.xcagi.mobile.core.speech.VoiceInputSheet
import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat

// ── IM 风格色值 ──
// 全部走主题：用户气泡/发送键/光标用 XcagiTheme.extra，背景/文字/边框用 MaterialTheme.colorScheme，
// 明暗双主题对比度由主题令牌保证（见 Theme.kt 的 chatUserBubble / chatUserBubbleText / weChatOnline）。

/** 聊天背景色（深色模式下用深蓝灰，浅色用微信灰） */
@Composable
private fun imChatBg() = MaterialTheme.colorScheme.background

/** 顶栏/输入栏背景 */
@Composable
private fun imBarBg() = MaterialTheme.colorScheme.surface

/** 分隔线 */
@Composable
private fun imDivider() = MaterialTheme.colorScheme.outlineVariant

/** 输入框边框 */
@Composable
private fun imInputBorder() = MaterialTheme.colorScheme.outline

/** 主文字色 */
@Composable
private fun imTextPrimary() = MaterialTheme.colorScheme.onSurface

/** 次要文字色 */
@Composable
private fun imTextSecondary() = MaterialTheme.colorScheme.onSurfaceVariant

/** 时间戳色 */
@Composable
private fun imTimestamp() = MaterialTheme.colorScheme.onSurfaceVariant

private data class EmployeeConversationRef(
    val modId: String,
    val employeeId: String,
)

private fun parseEmployeeConversationRef(conversationId: String?): EmployeeConversationRef? {
    val raw = conversationId?.trim().orEmpty()
    if (!raw.startsWith("employee:")) return null
    val parts = raw.split(":")
    if (parts.size != 3) return null
    return EmployeeConversationRef(modId = parts[1], employeeId = parts[2])
}

internal fun isCodexConversation(conversationId: String?): Boolean =
    conversationId?.trim() == PinnedIds.CODEX

internal fun isClaudeConversation(conversationId: String?): Boolean =
    conversationId?.trim() == PinnedIds.CLAUDE

internal fun chatAvatarFallback(
    conversationId: String?,
    hasEmployeeProfile: Boolean,
): AppAvatarFallback =
    when {
        isCodexConversation(conversationId) -> AppAvatarFallback.CODEX
        isClaudeConversation(conversationId) -> AppAvatarFallback.CLAUDE
        hasEmployeeProfile -> AppAvatarFallback.AI_EMPLOYEE
        else -> AppAvatarFallback.ASSISTANT
    }

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: AppViewModel,
    conversationId: String? = null,
    conversationTitle: String = "小C助理",
    onBack: (() -> Unit)? = null,
    onOpenMod: (String) -> Unit = {},
    onOpenOcr: () -> Unit = {},
    onOpenProfile: (() -> Unit)? = null,
    onOpenEmployeeProfile: (String, String) -> Unit = { _, _ -> },
) {
    val messages by vm.chatMessages.collectAsState()
    val streaming by vm.streaming.collectAsState()
    val syncStale by vm.syncStaleHint.collectAsState()
    val chatAction by vm.chatAction.collectAsState()
    val suggestions by vm.chatSuggestions.collectAsState()
    val userAvatarSource by vm.userAvatarSource.collectAsState()
    var input by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val sheetState = androidx.compose.material3.rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var showMoreSheet by remember { mutableStateOf(false) }
    var showVoiceSheet by remember { mutableStateOf(false) }
    val context = LocalContext.current

    // 录音权限请求（仅 app 内识别器兜底路径用）
    val recordPermissionLauncher =
            rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestPermission()
            ) { granted ->
                if (granted) showVoiceSheet = true
                else vm.snack("需要麦克风权限才能使用语音输入")
            }

    // 系统语音输入(ACTION_RECOGNIZE_SPEECH)：由系统语音引擎(如小米/讯飞)弹 UI 并回写转写。
    // 这是「用手机自带语音」最兼容的方式——很多国产 ROM 没注册默认 RecognitionService，
    // 程序化 SpeechRecognizer 用不了，但这个 Activity 意图能用。
    val speechIntentLauncher =
            rememberLauncherForActivityResult(
                    ActivityResultContracts.StartActivityForResult()
            ) { result ->
                if (result.resultCode == android.app.Activity.RESULT_OK) {
                    val text = result.data
                            ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                            ?.firstOrNull()
                            .orEmpty()
                    if (text.isNotBlank()) {
                        input = if (input.isBlank()) text else "$input $text"
                    }
                }
            }

    fun startVoiceInput() {
        val intent =
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(
                            RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                            RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                    )
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                    putExtra(RecognizerIntent.EXTRA_PROMPT, "请说话…")
                }
        try {
            speechIntentLauncher.launch(intent)
        } catch (_: ActivityNotFoundException) {
            // 无系统语音 UI → 回退到 app 内识别器(需录音权限)。
            if (SpeechRecognizer.isRecognitionAvailable(context)) {
                val hasPermission =
                        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                                PackageManager.PERMISSION_GRANTED
                if (hasPermission) showVoiceSheet = true
                else recordPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            } else {
                vm.snack("当前设备未提供语音输入")
            }
        }
    }
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    val employeeRef = remember(conversationId) { parseEmployeeConversationRef(conversationId) }
    val codexConversation = remember(conversationId) { isCodexConversation(conversationId) }
    val claudeConversation = remember(conversationId) { isClaudeConversation(conversationId) }
    val employeeProfile =
        remember(employeeRef, employees) {
            employeeRef?.let { ref -> employees.findEmployee(ref.modId, ref.employeeId) }
        }
    val resolvedTitle =
        when {
            employeeProfile != null -> employeeProfile.name
            codexConversation -> "超级员工-Codex"
            claudeConversation -> "超级员工-Claude"
            else -> conversationTitle
        }
    val aiAvatarFallback = chatAvatarFallback(conversationId, employeeProfile != null)

    // 解析"当前未处置的开发任务分支"，用于底部功能键（合并/diff/丢弃）。
    // 单遍扫描所有助手消息：push/diff 都带 super-employee/ 分支名→记为候选；
    // 遇到"✅已合并/已丢弃分支"→该分支已处置，清空（看完 diff 不会误清，因为 diff 仍带分支名）。
    val gitBranch =
        remember(messages, streaming) {
            if (streaming) {
                null
            } else {
                var candidate: String? = null
                val re = Regex("(super-employee/[\\w./-]+)")
                for ((role, text) in messages) {
                    if (role != "assistant") continue
                    re.find(text)?.let { candidate = it.groupValues[1] }
                    if (text.contains("✅ 已合并") || text.contains("已丢弃分支")) candidate = null
                }
                candidate
            }
        }

    LaunchedEffect(conversationId) {
        vm.loadChatCache(conversationId)
        if (suggestions.isEmpty()) vm.loadHomeHub()
    }

    LaunchedEffect(employeeRef?.modId, employeeRef?.employeeId) {
        if (employeeRef != null) vm.refreshModInfos()
    }

    LaunchedEffect(messages.size, streaming) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    fun submitMessage() {
        val text = input.trim()
        if (text.isBlank() && !streaming) return
        if (streaming) { vm.stopChat(); return }
        vm.sendChat(text, conversationId)
        input = ""
    }

    // 语音输入 BottomSheet
    if (showVoiceSheet) {
        VoiceInputSheet(
                onResult = { text ->
                    input = if (input.isBlank()) text else "$input $text"
                },
                onDismiss = { showVoiceSheet = false },
        )
    }

    // 更多 BottomSheet
    if (showMoreSheet) {
        androidx.compose.material3.ModalBottomSheet(
            onDismissRequest = { showMoreSheet = false },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.padding(bottom = Spacing.xxl)) {
                Text(
                    "更多",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                )
                HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
                WeCellGroup {
                    WeCell(
                        title = "新建对话",
                        subtitle = "清空当前对话，开始新的一轮",
                        iconTint = XcagiTheme.extra.brandBlue,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        showDivider = true,
                        onClick = { showMoreSheet = false; vm.clearChat(); input = "" },
                    )
                    WeCell(
                        title = "OCR 拍照识别",
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = { showMoreSheet = false; onOpenOcr() },
                    )
                }
            }
        }
    }

    Scaffold(
        containerColor = imChatBg(),
        topBar = {
            ImTopBar(
                title = resolvedTitle,
                onBack = onBack,
                onVideoCall = { vm.snack("视频通话功能即将上线") },
                onMore = {
                    val ref = employeeRef
                    if (ref != null) {
                        onOpenEmployeeProfile(ref.modId, ref.employeeId)
                    } else if (onOpenProfile != null) {
                        onOpenProfile.invoke()
                    } else {
                        showMoreSheet = true
                    }
                },
            )
        },
        bottomBar = {
            ImInputBar(
                value = input,
                onValueChange = { input = it },
                onSend = { submitMessage() },
                onStop = { vm.stopChat() },
                streaming = streaming,
                onVoice = { startVoiceInput() },
                onMore = { showMoreSheet = true },
                gitBranch = gitBranch,
                showDevTools = claudeConversation || codexConversation,
                onGitMerge = { gitBranch?.let { vm.gitMerge(it, conversationId) } },
                onGitDiff = { gitBranch?.let { vm.gitDiff(it, conversationId) } },
                onGitDiscard = { gitBranch?.let { vm.gitDiscard(it, conversationId) } },
                onGitHint = {
                    vm.snack("还没有可操作的分支——在这里发一个开发任务（如\"修复…\"），跑完就能合并/查看/丢弃")
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // 同步提示条
            if (syncStale) {
                Surface(
                    color = XcagiTheme.extra.warning.copy(alpha = 0.08f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "数据同步中...",
                        style = MaterialTheme.typography.bodySmall,
                        color = XcagiTheme.extra.warning,
                        modifier = Modifier.padding(horizontal = Spacing.lg, vertical = 6.dp),
                    )
                }
            }

            // 快捷操作条
            chatAction?.let { action ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = Spacing.md, vertical = Spacing.xs),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    when (action.type) {
                        "mod" -> Button(
                            onClick = { vm.clearChatAction(); onOpenMod(action.targetId) },
                            shape = MaterialTheme.shapes.small,
                            colors = ButtonDefaults.buttonColors(containerColor = XcagiTheme.extra.brandBlue),
                        ) { Text("打开 ${action.label}", style = MaterialTheme.typography.labelMedium) }
                    }
                }
            }

            if (messages.isNotEmpty()) {
                LazyColumn(
                    Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = 14.dp, vertical = 4.dp),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(0.dp),
                ) {
                    itemsIndexed(messages) { index, pair ->
                        val (role, text) = pair
                        val isLastAssistant =
                            index == messages.indexOfLast { it.first == "assistant" }
                        ImBubble(
                            role = role,
                            text = text,
                            isStreaming = streaming && isLastAssistant && role == "assistant",
                            showAvatar = isUserOrFirstInGroup(messages, index, role),
                            aiAvatarUrl = employeeProfile?.avatarUrl,
                            aiAvatarFallback = aiAvatarFallback,
                            userAvatarUrl = userAvatarSource,
                        )
                    }
                }
            } else {
                // 空状态保持纯空白，仿微信（不放建议气泡等功能按键）。
                Spacer(Modifier.weight(1f).fillMaxWidth())
            }
        }
    }
}

/** 判断是否显示头像：用户消息始终显示；对方消息仅每组第一条显示 */
private fun isUserOrFirstInGroup(messages: List<Pair<String, String>>, index: Int, role: String): Boolean {
    val isUser = role == "user"
    if (isUser) return true // 用户消息每条都显示头像
    if (index == 0) return true
    return messages[index - 1].first != role // 角色切换时显示
}

// ══════════════════════════════════════════
//  IM 风格顶部栏（仿飞书/微信）
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ImTopBar(
    title: String,
    onBack: (() -> Unit)?,
    onVideoCall: () -> Unit,
    onMore: () -> Unit,
) {
    Surface(
        color = imBarBg(),
        shadowElevation = 0.dp,
    ) {
        Column {
            Row(
                Modifier
                    .fillMaxWidth()
                    .height(48.dp)
                    .padding(horizontal = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 返回（更精致的箭头）
                IconButton(
                    onClick = { onBack?.invoke() },
                    modifier = Modifier.size(44.dp),
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = imTextPrimary(),
                        modifier = Modifier.size(24.dp),
                    )
                }
                // 标题（左对齐，更现代）
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium.copy(
                        fontSize = 17.sp,
                        letterSpacing = 0.5.sp,
                    ),
                    fontWeight = FontWeight.Medium,
                    color = imTextPrimary(),
                    modifier = Modifier.weight(1f).padding(start = 4.dp),
                )
                // 视频通话
                IconButton(
                    onClick = onVideoCall,
                    modifier = Modifier.size(44.dp),
                ) {
                    Icon(
                        Icons.Default.Videocam,
                        contentDescription = "视频",
                        tint = imTextPrimary(),
                        modifier = Modifier.size(22.dp),
                    )
                }
                // 更多
                IconButton(
                    onClick = onMore,
                    modifier = Modifier.size(44.dp),
                ) {
                    Icon(
                        Icons.Default.MoreHoriz,
                        contentDescription = "更多",
                        tint = imTextPrimary(),
                        modifier = Modifier.size(22.dp),
                    )
                }
            }
            // 精致底部分隔线（0.5dp）
            HorizontalDivider(thickness = 0.5.dp, color = imDivider())
        }
    }
}

// ══════════════════════════════════════════
//  IM 风格消息气泡（仿微信：左白右绿+圆角头像+弹性动画）
// ══════════════════════════════════════════
@OptIn(androidx.compose.animation.ExperimentalAnimationApi::class)
@Composable
private fun ImBubble(
    role: String,
    text: String,
    isStreaming: Boolean = false,
    showAvatar: Boolean = true,
    aiAvatarUrl: String? = null,
    aiAvatarFallback: AppAvatarFallback = AppAvatarFallback.ASSISTANT,
    userAvatarUrl: String? = null,
) {
    val isUser = role == "user"
    Row(
        Modifier
            .fillMaxWidth()
            .animateContentSize(
                animationSpec = spring(
                    dampingRatio = Spring.DampingRatioMediumBouncy,
                    stiffness = Spring.StiffnessLow,
                ),
            )
            .padding(
                top = if (showAvatar) 12.dp else 4.dp,
                bottom = 4.dp,
            ),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        // 对方头像
        if (!isUser) {
            if (showAvatar) {
                AppAvatar(
                    imageSource = aiAvatarUrl,
                    fallback = aiAvatarFallback,
                    size = 40.dp,
                    shape = RoundedCornerShape(8.dp),
                )
                Spacer(Modifier.width(8.dp))
            } else {
                Spacer(Modifier.width(48.dp))
            }
        }

        // 气泡（微信同款圆角 + 精致阴影）
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
                text = buildString { append(text); if (isStreaming) append("\u200B▌") },
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.sp,
                    lineHeight = 21.sp,
                ),
                color = if (isUser) XcagiTheme.extra.chatUserBubbleText else imTextPrimary(),
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            )
        }

        // 用户头像
        if (isUser) {
            if (showAvatar) {
                Spacer(Modifier.width(8.dp))
                AppAvatar(
                    imageSource = userAvatarUrl,
                    fallback = AppAvatarFallback.USER,
                    size = 40.dp,
                    shape = RoundedCornerShape(8.dp),
                )
            } else {
                Spacer(Modifier.width(48.dp))
            }
        }
    }
}

// ══════════════════════════════════════════
//  IM 风格输入栏（仿微信：精致圆角+常驻发送+按压动画）
// ══════════════════════════════════════════
@Composable
private fun ImInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    modifier: Modifier = Modifier,
    onVoice: (() -> Unit)? = null,
    onMore: (() -> Unit)? = null,
    gitBranch: String? = null,
    showDevTools: Boolean = false,
    onGitMerge: () -> Unit = {},
    onGitDiff: () -> Unit = {},
    onGitDiscard: () -> Unit = {},
    onGitHint: () -> Unit = {},
) {
    val haptics = rememberHaptics()
    Surface(
        color = imBarBg(),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column {
            // 顶部分隔线
            HorizontalDivider(thickness = 0.5.dp, color = imDivider())
            // 开发工具条：超级员工聊天里常驻（钉钉式输入框上方一排）。
            // 有分支时点亮可合并/查看/丢弃；无分支置灰，点了提示先发开发任务。
            if (showDevTools) {
                GitActionBar(
                    branch = gitBranch,
                    onMerge = onGitMerge,
                    onDiff = onGitDiff,
                    onDiscard = onGitDiscard,
                    onEmptyHint = onGitHint,
                )
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                // 语音按钮（精致图标）
                if (onVoice != null) {
                    IconButton(onClick = onVoice, modifier = Modifier.size(38.dp)) {
                        Icon(
                            Icons.Default.Mic,
                            contentDescription = "语音",
                            tint = imTextPrimary(),
                            modifier = Modifier.size(22.dp),
                        )
                    }
                }

                // 输入框（微信风格：圆角矩形+浅灰背景）
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.surface,
                    modifier = Modifier.weight(1f).height(38.dp),
                ) {
                    androidx.compose.foundation.text.BasicTextField(
                        value = value,
                        onValueChange = onValueChange,
                        modifier = Modifier.padding(horizontal = 12.dp).fillMaxSize(),
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                            color = imTextPrimary(),
                            fontSize = 15.sp,
                        ),
                        cursorBrush = androidx.compose.ui.graphics.SolidColor(XcagiTheme.extra.weChatOnline),
                        decorationBox = { inner ->
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                                if (value.isEmpty()) {
                                    Text(
                                        "发消息",
                                        style = MaterialTheme.typography.bodyMedium.copy(fontSize = 15.sp),
                                        color = imTextSecondary(),
                                    )
                                }
                                inner()
                            }
                        },
                    )
                }

                // 发送/停止（常驻显示，微信风格圆角按钮+按压动画）
                var pressed by remember { mutableStateOf(false) }
                val scale by animateFloatAsState(
                    targetValue = if (pressed) 0.92f else 1f,
                    animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
                    label = "sendScale",
                )
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = if (streaming) MaterialTheme.colorScheme.errorContainer else XcagiTheme.extra.weChatOnline,
                    modifier = Modifier
                        .size(38.dp)
                        .scale(scale)
                        .pointerInput(streaming) {
                            detectTapGestures(
                                onPress = {
                                    pressed = true
                                    awaitRelease()
                                    pressed = false
                                },
                                onTap = {
                                    if (streaming) { haptics.tap(); onStop() }
                                    else { haptics.confirm(); onSend() }
                                },
                            )
                        },
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            if (streaming) Icons.Default.Stop else Icons.AutoMirrored.Filled.Send,
                            contentDescription = if (streaming) "停止" else "发送",
                            tint = if (streaming) MaterialTheme.colorScheme.error else Color.White,
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
            }
        }
    }
}

// ══════════════════════════════════════════
//  情境功能键条（开发任务分支：合并/diff/丢弃）
//  仿钉钉/微信：输入框上方一排快捷键，跟着场景出现、用完即走
// ══════════════════════════════════════════
@Composable
private fun GitActionBar(
    branch: String?,
    onMerge: () -> Unit,
    onDiff: () -> Unit,
    onDiscard: () -> Unit,
    onEmptyHint: () -> Unit,
) {
    val haptics = rememberHaptics()
    val active = branch != null
    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.CallMerge,
                contentDescription = "待处理分支",
                tint = imTextSecondary(),
                modifier = Modifier.size(13.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(
                if (active) "开发任务分支 · ${branch?.substringAfterLast('/').orEmpty()}"
                else "开发工具 · 发任务后可合并 / 查看 / 丢弃分支",
                style = MaterialTheme.typography.labelSmall,
                color = imTextSecondary(),
                maxLines = 1,
            )
        }
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GitChip("查看 diff", Icons.Default.Difference, imTextPrimary(), dimmed = !active) {
                haptics.tap(); if (active) onDiff() else onEmptyHint()
            }
            GitChip(
                "合并到主干",
                Icons.Default.CallMerge,
                XcagiTheme.extra.weChatOnline,
                filled = active,
                dimmed = !active,
            ) {
                if (active) {
                    haptics.confirm(); onMerge()
                } else {
                    haptics.tap(); onEmptyHint()
                }
            }
            GitChip(
                "丢弃",
                Icons.Default.DeleteOutline,
                MaterialTheme.colorScheme.error,
                dimmed = !active,
            ) {
                haptics.tap(); if (active) onDiscard() else onEmptyHint()
            }
        }
    }
}

@Composable
private fun GitChip(
    label: String,
    icon: ImageVector,
    tint: Color,
    filled: Boolean = false,
    dimmed: Boolean = false,
    onClick: () -> Unit,
) {
    val effTint = if (dimmed) tint.copy(alpha = 0.45f) else tint
    Surface(
        shape = RoundedCornerShape(8.dp),
        color =
            if (filled) tint.copy(alpha = 0.12f)
            else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = if (dimmed) 0.3f else 0.5f),
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Row(
            Modifier.padding(horizontal = 11.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icon, contentDescription = null, tint = effTint, modifier = Modifier.size(15.dp))
            Spacer(Modifier.width(4.dp))
            Text(label, style = MaterialTheme.typography.labelMedium, color = effTint)
        }
    }
}

// ══════════════════════════════════════════
//  空状态：AI 头像 + 问候 + 建议气泡
// ══════════════════════════════════════════
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChatEmptyState(
    title: String,
    aiAvatarUrl: String?,
    aiAvatarFallback: AppAvatarFallback,
    suggestions: List<ChatSuggestion>,
    onSuggestionClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptics = rememberHaptics()
    Box(modifier, contentAlignment = Alignment.TopCenter) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(top = 56.dp, start = Spacing.xl, end = Spacing.xl),
        ) {
            AppAvatar(
                imageSource = aiAvatarUrl,
                fallback = aiAvatarFallback,
                size = 72.dp,
                shape = RoundedCornerShape(20.dp),
            )
            Spacer(Modifier.height(Spacing.md))
            Text(
                "你好，我是 $title",
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                color = imTextPrimary(),
            )
            Spacer(Modifier.height(Spacing.xs))
            Text(
                "有什么我可以帮你的？",
                style = MaterialTheme.typography.bodyMedium,
                color = imTextSecondary(),
            )
            if (suggestions.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.lg))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm, Alignment.CenterHorizontally),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                ) {
                    suggestions.forEach { s ->
                        ChatSuggestionChip(
                            label = s.label,
                            onClick = { haptics.tap(); onSuggestionClick(s.prompt) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ChatSuggestionChip(label: String, onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = XcagiTheme.extra.momentChipBg,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = XcagiTheme.extra.momentAccent,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

// ══════════════════════════════════════════
//  AI 员工列表页（IM 列表风格，不变）
// ══════════════════════════════════════════
@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun AiEmployeeListScreen(
    vm: AppViewModel,
    onBack: (() -> Unit)? = null,
    onSelect: (String, String) -> Unit,
    onScan: () -> Unit = {},
) {
    val modInfos by vm.modInfos.collectAsState()
    val employees = remember(modInfos) { modInfos.aiEmployeeProfiles() }
    var searchQuery by remember { mutableStateOf("") }
    val filteredEmployees = remember(employees, searchQuery) {
        if (searchQuery.isBlank()) employees
        else employees.filter {
            it.name.contains(searchQuery, ignoreCase = true) ||
                it.modName.contains(searchQuery, ignoreCase = true) ||
                it.employeeId.contains(searchQuery, ignoreCase = true)
        }
    }

    LaunchedEffect(Unit) { vm.refreshModInfos() }

    Scaffold(
        containerColor = imChatBg(),
        topBar = {
            androidx.compose.material3.TopAppBar(
                title = {
                    Text(
                        "AI员工${filteredEmployees.size.takeIf { it > 0 }?.let { "($it)" }.orEmpty()}",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = imTextPrimary(),
                    )
                },
                navigationIcon = {
                    if (onBack != null) {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                        }
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refreshModInfos(showError = true) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新AI员工")
                    }
                    IconButton(onClick = onScan) {
                        Icon(Icons.Default.QrCodeScanner, contentDescription = "扫码绑定")
                    }
                },
                colors = androidx.compose.material3.TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
                windowInsets = WindowInsets(0.dp),
            )
        },
    ) { padding ->
        if (employees.isEmpty()) {
            Box(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(vertical = 48.dp),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(
                        modifier = Modifier
                            .size(64.dp)
                            .clip(RoundedCornerShape(18.dp))
                            .background(XcagiTheme.extra.brandBlue.copy(alpha = 0.10f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Default.AutoAwesome,
                            contentDescription = null,
                            modifier = Modifier.size(34.dp),
                            tint = XcagiTheme.extra.brandBlue,
                        )
                    }
                    Spacer(Modifier.height(Spacing.md))
                    Text(
                        "暂无 AI 员工",
                        style = MaterialTheme.typography.bodyMedium,
                        color = imTextPrimary(),
                    )
                    Spacer(Modifier.height(Spacing.xs))
                    Text(
                        "扫码绑定企业端或登录管理端后，员工会自动同步到这里。",
                        style = MaterialTheme.typography.bodySmall,
                        color = imTextSecondary(),
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 32.dp),
                    )
                    Spacer(Modifier.height(Spacing.lg))
                    Button(
                        onClick = onScan,
                        colors = ButtonDefaults.buttonColors(containerColor = XcagiTheme.extra.brandBlue),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Icon(
                            Icons.Default.QrCodeScanner,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("扫码绑定")
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                // 搜索框（复用会话列表页同款样式）
                item {
                    SearchBarField(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        onClear = { searchQuery = "" },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = Spacing.md, vertical = 8.dp),
                    )
                }
                // 搜索无结果提示
                if (filteredEmployees.isEmpty() && searchQuery.isNotEmpty()) {
                    item {
                        Box(
                            Modifier.fillMaxWidth().padding(vertical = 32.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                "未找到匹配的 AI 员工",
                                style = MaterialTheme.typography.bodyMedium,
                                color = imTextSecondary(),
                            )
                        }
                    }
                }
                itemsIndexed(
                    items = filteredEmployees,
                    key = { index, employee -> "${employee.key}:$index" },
                ) { _, employee ->
                    Surface(
                        color = MaterialTheme.colorScheme.surface,
                        modifier = Modifier
                            .fillMaxWidth()
                            .animateItemPlacement()
                            .clickable { onSelect(employee.modId, employee.employeeId) },
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(horizontal = Spacing.md, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            AppAvatar(
                                imageSource = employee.avatarUrl,
                                fallback = AppAvatarFallback.AI_EMPLOYEE,
                                size = 44.dp,
                                shape = MaterialTheme.shapes.extraSmall,
                                contentDescription = employee.name,
                            )
                            Spacer(Modifier.width(Spacing.md))

                            Column(Modifier.weight(1f)) {
                                Text(
                                    employee.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.Medium,
                                    color = imTextPrimary(),
                                    maxLines = 1,
                                )
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    employee.summary,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = imTextSecondary(),
                                    maxLines = 1,
                                )
                                Spacer(Modifier.height(2.dp))
                                Text(
                                    employee.contactLine(),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = XcagiTheme.extra.brandBlue,
                                    maxLines = 1,
                                )
                            }

                            Icon(
                                Icons.Default.ChevronRight,
                                contentDescription = null,
                                tint = imTextSecondary(),
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                    HorizontalDivider(thickness = 0.5.dp, color = imDivider(), modifier = Modifier.padding(start = 68.dp))
                }
            }
        }
    }
}

private fun AiEmployeeProfile.contactLine(): String =
    listOf(
        phoneChannel.contactChannelLabel(),
        employeeId.takeIf { it.isNotBlank() }?.let { "AI号 $it" }.orEmpty(),
        apiBasePath.takeIf { it.isNotBlank() }?.let { "入口 $it" }.orEmpty(),
    ).filter { it.isNotBlank() }.joinToString(" · ")

private fun String.contactChannelLabel(): String =
    when (trim()) {
        "admin-duty" -> "管理端工作台"
        "mobile", "mobile-chat" -> "手机端会话"
        "" -> ""
        else -> trim()
    }
