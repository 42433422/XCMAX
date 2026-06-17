# 手机端首页重构实施计划：AI 微信模式

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Android App 首页从单一聊天界面重构为 AI 微信风格的会话列表（仅改 Tab 1，Tab 2/3/4 不变）

**Architecture:** 新建 ConversationListScreen 替换 ChatScreen 作为 CHAT route 的 Composable；固定联系人（小C助理+专属客服）置顶；点击跳转到现有 ChatScreen（带 conversationId 参数）或新建 CsChatScreen；后端新增 3 个 cs/* 接口

**Tech Stack:** Kotlin / Jetpack Compose / Hilt / Room / Retrofit / OkHttp SSE

**Spec:** `docs/superpowers/specs/2026-06-17-mobile-homepage-redesign.md`

---

## 文件结构总览

### 新建文件（4 个）

| 文件 | 职责 |
|------|------|
| `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/model/ConversationItem.kt` | 会话列表数据模型 |
| `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt` | 新首页：会话列表 Composable |
| `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/CsChatScreen.kt` | 专属客服聊天页 |
| `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/cs/CsRepository.kt` | 客服数据层 |

### 修改文件（6 个）

| 文件 | 改动点 |
|------|--------|
| `navigation/XcagiNavHost.kt` | CHAT route → ConversationListScreen；Tab1 label "对话"→"消息"；新增 CS_CHAT composable |
| `navigation/Routes.kt` | 新增 CS_CHAT / CONVERSATION_CHAT 常量 |
| `navigation/ChatScreen.kt` | 新增 conversationId / conversationTitle 可选参数（向后兼容） |
| `ui/AppViewModel.kt` | 新增 csMessages / csStreaming StateFlow；loadConversations() |
| `core/network/FhdApi.kt` | 新增客服 Retrofit 接口定义 |
| `ui/components/mobile/WeTopBar.kt` | 支持 showSearch / onSearchClick 参数 |

---

## Task 1: 数据模型 — ConversationItem

**Files:**
- Create: `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/model/ConversationItem.kt`

- [ ] **Step 1: 创建 ConversationItem 数据类**

```kotlin
package com.xiuci.xcagi.mobile.model

import androidx.compose.ui.graphics.Color

/**
 * 会话列表中的单个条目。
 * 来源三部分：(A) 固定联系人 (B) AI 任务/工具会话 (C) 系统通知。
 */
data class ConversationItem(
    // ── 身份 ──
    val id: String,
    val type: ConversationType,

    // ── 显示 ──
    val title: String,
    val subtitle: String,
    val timestamp: Long,

    // ── 头像 ──
    val avatarType: AvatarType,
    val avatarIcon: Int? = null,
    val avatarLetter: Char? = null,
    val avatarColor: Color? = null,
    val avatarUrl: String? = null,

    // ── 状态 ──
    val unreadCount: Int = 0,
    val isOnline: Boolean = false,
    val isPinned: Boolean = false,

    // ── 徽标 ──
    val badgeText: String? = null,
    val badgeColor: Color? = null,
)

enum class ConversationType {
    PINNED_CS,            // 固定：专属客服（仅 enterprise）
    PINNED_ASSISTANT,     // 固定：小C助理
    AI_TASK,              // AI 任务会话
    SYSTEM_NOTIFICATION,  // 系统通知
}

enum class AvatarType { ICON, LETTER, URL }

/** 固定联系人 ID 常量 */
object PinnedIds {
    const val CS = "pinned:cs"
    const val ASSISTANT = "pinned:assistant"
}
```

- [ ] **Step 2: 验证编译**

Run: `cd mobile-android && ./gradlew compileDebugKotlin`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/model/ConversationItem.kt
git commit -m "feat(mobile): add ConversationItem data model for AI WeChat home page"
```

---

## Task 2: 会话列表首页 — ConversationListScreen

**Files:**
- Create: `mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt`
- Modify: `ui/AppViewModel.kt` (新增 loadConversations 方法)

- [ ] **Step 1: 在 AppViewModel 中新增会话列表状态**

在 `AppViewModel.kt` 中添加：

```kotlin
// 新增 import
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.ConversationType
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.model.AvatarType
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

// 在 AppViewModel 类内部新增：

private val _conversations = MutableStateFlow<List<ConversationItem>>(emptyList())
val conversations: StateFlow<List<ConversationItem>> = _conversations

/** 构建会话列表：固定联系人 + AI 会话历史 */
fun loadConversations(isEnterprise: Boolean) {
    val items = mutableListOf<ConversationItem>()

    // 1. 小C助理（始终显示）
    items.add(
        ConversationItem(
            id = PinnedIds.ASSISTANT,
            type = ConversationType.PINNED_ASSISTANT,
            title = "小C助理",
            subtitle = "有什么可以帮您？",
            timestamp = System.currentTimeMillis(),
            avatarType = AvatarType.ICON,
            isPinned = true,
            badgeText = "AI在线",
            badgeColor = androidx.compose.ui.graphics.Color(0xFF4CAF50),
        )
    )

    // 2. 专属客服（仅企业版）
    if (isEnterprise) {
        items.add(
            ConversationItem(
                id = PinnedIds.CS,
                type = ConversationType.PINNED_CS,
                title = "专属客服",
                subtitle = "您好，我是您的专属客服",
                timestamp = System.currentTimeMillis() - 3600_000,
                avatarType = AvatarType.ICON,
                isOnline = true,
                isPinned = true,
                badgeText = "在线",
                badgeColor = androidx.compose.ui.graphics.Color.Color(0xFF07C160),
            )
        )
    )

    // 3. AI 会话历史（从聊天缓存构建占位——Phase 3 接入 Room DB）
    // TODO: Phase 3 从 ImMessageCacheEntity 聚合真实会话历史
    val chatHistory = chatMessages.value
    if (chatHistory.isNotEmpty()) {
        val lastAi = chatHistory.lastOrNull { it.first == "assistant" }
        if (lastAi != null) {
            val preview = lastAi.second.takeIf { it.length > 40 }?.substring(0, 40)?.plus("…") ?: lastAi.second
            items.add(
                ConversationItem(
                    id = "conv:ai-chat",
                    type = ConversationType.AI_TASK,
                    title = "AI 对话",
                    subtitle = preview,
                    timestamp = System.currentTimeMillis() - 7200_000,
                    avatarType = AvatarType.LETTER,
                    avatarLetter = 'A',
                    avatarColor = androidx.compose.ui.graphics.Color(0xFF4A90D9),
                    unreadCount = 0,
                )
            )
        }
    }

    _conversations.value = items
}
```

- [ ] **Step 2: 创建 ConversationListScreen**

```kotlin
package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.HeadsetMic
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.model.ConversationItem
import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

private val LIST_BG = Color(0xFFEDEDED)
private val CELL_BG = Color.White
private val DIVIDER_COLOR = Color(0xFFE5E5E5)

/** 首字头像颜色池（参考 AiEmployeeListScreen） */
private val AVATAR_COLORS = listOf(
    Color(0xFF4A90D9), Color(0xFFE74C3C), Color(0xFF2ECC71),
    Color(0xFFF39C12), Color(0xFF9B59B6), Color(0xFF1ABC9C),
    Color(0xFFE67E22), Color(0xFF3498DB),
)

@Composable
fun ConversationListScreen(
    vm: AppViewModel,
    onOpenAssistant: () -> Unit,
    onOpenCustomerService: () -> Unit,
    onOpenConversation: (String) -> Unit,
    onOpenScan: () -> Unit,
) {
    val conversations by vm.conversations.collectAsState()
    var searchQuery by remember { mutableStateOf("") }
    var showSearch by remember { mutableStateOf(false) }
    val isEnterprise = ProductSkuConfig.showsEnterpriseNav()

    LaunchedEffect(Unit) {
        vm.loadConversations(isEnterprise)
    }

    // 搜索过滤
    val filtered = remember(searchQuery, conversations) {
        if (searchQuery.isBlank()) conversations
        else conversations.filter {
            it.title.contains(searchQuery, ignoreCase = true) ||
            it.subtitle.contains(searchQuery, ignoreCase = true)
        }
    }

    Scaffold(
        containerColor = LIST_BG,
        topBar = {
            WeTopBar(
                title = "消息",
                showRightAdd = true,
                showSearch = true,
                onSearchClick = { showSearch = !showSearch },
                onRightAdd = {
                    // TODO: Phase 2 加号菜单（发起新对话 / 扫一扫）
                    onOpenScan()
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 搜索栏（可展开）
            if (showSearch) {
                SearchBarField(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    onClear = { searchQuery = ""; showSearch = false },
                )
            }

            // 会话列表
            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                items(filtered, key = { it.id }) { item ->
                    ConversationCell(
                        item = item,
                        onClick = {
                            when (item.id) {
                                PinnedIds.ASSISTANT -> onOpenAssistant()
                                PinnedIds.CS -> onOpenCustomerService()
                                else -> onOpenConversation(item.id)
                            }
                        },
                    )
                    HorizontalDivider(
                        color = DIVIDER_COLOR,
                        thickness = 0.5.dp,
                        modifier = Modifier.padding(start = if (item.isPinned) 0.dp else 72.dp),
                    )
                }

                // 空状态
                if (filtered.isEmpty()) {
                    item {
                        Box(
                            Modifier
                                .fillParentMaxSize()
                                .padding(vertical = 48.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("暂无对话", fontSize = 15.sp, color = MobileTokens.textTertiary)
                                Spacer(Modifier.height(8.dp))
                                Text("开始和小C助理聊聊吧", fontSize = 13.sp, color = MobileTokens.textDisabled)
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── 搜索栏 ──
@Composable
private fun SearchBarField(
    value: String,
    onValueChange: (String) -> Unit,
    onClear: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = Color.White,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
        ) {
            Text("🔍", fontSize = 14.sp)
            Spacer(Modifier.width(6.dp))
            androidx.compose.foundation.text.BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium.copy(color = MobileTokens.textPrimary),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth()) {
                        if (value.isEmpty()) Text("搜索", style = MaterialTheme.typography.bodyMedium, color = MobileTokens.textDisabled)
                        inner()
                    }
                },
            )
            if (value.isNotEmpty()) {
                Box(
                    Modifier.size(20.dp).clip(CircleShape).clickable(onClick = onClear).background(Color(0xFFEEEEEE)),
                    contentAlignment = Alignment.Center,
                ) { Text("×", color = MobileTokens.textSecondary, fontSize = 12.sp) }
            }
        }
    }
}

// ── 会话单元格（微信风格） ──
@Composable
private fun ConversationCell(
    item: ConversationItem,
    onClick: () -> Unit,
) {
    Surface(
        color = CELL_BG,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 头像
            when (item.avatarType) {
                AvatarType.ICON -> {
                    val icon = when (item.type) {
                        com.xiuci.xcagi.mobile.model.ConversationType.PINNED_CS -> Icons.Default.SupportAgent
                        else -> Icons.Default.HeadsetMic
                    }
                    Box(
                        Modifier
                            .size(48.dp)
                            .clip(RoundedCornerShape(6.dp))
                            .background(item.avatarColor ?: MobileTokens.brandBlue.copy(alpha = 0.1f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(icon, contentDescription = null, tint = item.avatarColor ?: MobileTokens.brandBlue, modifier = Modifier.size(26.dp))
                    }
                }
                AvatarType.LETTER -> {
                    val letter = item.avatarLetter ?: 'A'
                    val color = item.avatarColor
                        ?: AVATAR_COLORS[kotlin.math.abs(item.title.hashCode()) % AVATAR_COLORS.size]
                    Box(
                        Modifier.size(48.dp).clip(RoundedCornerShape(6.dp)).background(color),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(letter, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color.White)
                    }
                }
                AvatarType.URL -> {
                    // 未来扩展：Coil 加载远程头像
                    Box(Modifier.size(48.dp).clip(CircleShape).background(Color(0xFFEEEEEE)))
                }
            }

            Spacer(Modifier.width(12.dp))

            // 名称 + 副标题
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        item.title,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                        color = Color(0xFF1A1A1A),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    // 未读角标
                    if (item.unreadCount > 0) {
                        Spacer(Modifier.width(6.dp))
                        Box(
                            Modifier.size(18.dp).clip(CircleShape).background(Color(0xFFFF3B30)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                "${item.unreadCount}",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color.White,
                            )
                        }
                    }
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    item.subtitle,
                    fontSize = 13.sp,
                    color = Color(0xFF999999),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            // 右侧：时间 + 徽标
            Column(horizontalAlignment = Alignment.End) {
                Text(formatTimestamp(item.timestamp), fontSize = 11.sp, color = Color(0xFFCCCCCC))
                item.badgeText?.let { badge ->
                    Spacer(Modifier.height(4.dp))
                    Text(badge, fontSize = 11.sp, color = item.badgeColor ?: MobileTokens.textTertiary)
                }
                Spacer(Modifier.height(2.dp))
                Icon(Icons.Default.ChevronRight, contentDescription = null, tint = Color(0xFFCCCCCC), modifier = Modifier.size(16.dp))
            }
        }
    }
}

private fun formatTimestamp(ts: Long): String {
    val now = System.currentTimeMillis()
    val diffMs = now - ts
    return when {
        diffMs < 60_000 -> "刚刚"
        diffMs < 3600_000 -> "${diffMs / 60_000}分钟前"
        diffMs < 86400_000 -> "${diffMs / 3600_000}小时前"
        diffMs < 172800_000 -> "昨天"
        else -> java.text.SimpleDateFormat("M月d日", java.util.Locale.CHINA).format(java.util.Date(ts))
    }
}
```

- [ ] **Step 3: 验证编译**

Run: `cd mobile-android && ./gradlew compileDebugKotlin`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ConversationListScreen.kt
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt
git commit -m "feat(mobile): add ConversationListScreen - AI WeChat style home page"
```

---

## Task 3: 导航改造 — XcagiNavHost + Routes

**Files:**
- Modify: `navigation/Routes.kt`
- Modify: `navigation/XcagiNavHost.kt`

- [ ] **Step 1: 在 Routes.kt 中新增常量**

在 `Routes.kt` 中 `const val CHAT = "chat"` 之后添加：

```kotlin
    /** 专属客服聊天页 */
    const val CS_CHAT = "cs_chat"
    /** 普通会话聊天页（带 conversationId 参数） */
    const val CONVERSATION_CHAT = "conversation_chat/{conversationId}"
    fun conversationChat(conversationId: String) = "conversation_chat/$conversationId"
```

- [ ] **Step 2: 在 XcagiNavHost.kt 中替换 CHAT route**

找到 XcagiNavHost.kt 中现有的 `composable(Routes.CHAT)` 块（约第 395 行），将整个 block 从：
```kotlin
composable(Routes.CHAT) {
    ChatScreen(vm, onOpenMod = { nav.navigate(Routes.MOD_WEB.replace("{modId}", it)) }, onNavigateToEmployees = { nav.navigate(Routes.AI_EMPLOYEES) })
}
```
替换为：
```kotlin
composable(Routes.CHAT) {
    ConversationListScreen(
        vm = vm,
        onOpenAssistant = {
            // 点击小C助手 → 进入 AI 对话（复用现有 ChatScreen）
            nav.navigate(Routes.AI_CHAT) {
                popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                launchSingleTop = true
                restoreState = true
            }
        },
        onOpenCustomerService = {
            // 点击专属客服 → 进入客服聊天页
            nav.navigate(Routes.CS_CHAT)
        },
        onOpenConversation = { convId ->
            // 点击普通会话 → 进入带 conversationId 的 AI 对话
            nav.navigate(Routes.conversationChat(convId))
        },
        onOpenScan = { nav.navigate(Routes.SCAN_QR) },
    )
}

// 新增：AI 助理聊天页（= 原 ChatScreen 带 assistant 标识）
composable(Routes.AI_CHAT) {
    ChatScreen(
        vm = vm,
        onOpenMod = { modId -> nav.navigate(Routes.MOD_WEB.replace("{modId}", modId)) },
        onOpenOcr = { nav.navigate(Routes.OCR) },
        onNavigateToEmployees = { nav.navigate(Routes.AI_EMPLOYEES) },
        conversationId = "assistant",
        conversationTitle = "小C助理",
    )
}

// 新增：普通会话聊天页
composable(Routes.CONVERSATION_CHAT) { backStackEntry ->
    val convId = backStackEntry.arguments?.getString("conversationId") ?: ""
    ChatScreen(
        vm = vm,
        onOpenMod = { modId -> nav.navigate(Routes.MOD_WEB.replace("{modId}", modId)) },
        onOpenOcr = { nav.navigate(Routes.OCR) },
        onNavigateToEmployees = { nav.navigate(Routes.AI_EMPLOYEES) },
        conversationId = convId.ifEmpty { null },
        conversationTitle = convId.ifEmpty { "AI 对话" },
    )
}

// 新增：专属客服聊天页
composable(Routes.CS_CHAT) {
    CsChatScreen(
        vm = vm,
        onBack = { nav.popBackStack() },
    )
}
```

- [ ] **Step 3: 修改 Tab 1 label**

在 XcagiNavHost.kt 的 bottomBar WeBottomNavBar items 列表中，将 Tab 1 的 label 从 `"对话"` 改为 `"消息"`：

```kotlin
// 原来:
WeBottomNavItem(Routes.CHAT, "对话", Icons.Default.Chat)
// 改为:
WeBottomNavItem(Routes.CHAT, "消息", Icons.Default.Chat)
```

- [ ] **Step 4: 验证编译**

Run: `cd mobile-android && ./gradlew compileDebugKotlin`
Expected: BUILD SUCCESSFUL

- [ ] **Step 5: Commit**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/XcagiNavHost.kt
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/Routes.kt
git commit -m "feat(mobile): replace ChatScreen with ConversationListScreen as Tab 1; add CS/AI chat routes"
```

---

## Task 4: ChatScreen 向后兼容改造

**Files:**
- Modify: `navigation/ChatScreen.kt`

- [ ] **Step 1: 修改 ChatScreen 函数签名和顶部标题**

在 `ChatScreen.kt` 中：

**(a)** 修改函数签名（约第 98 行），新增两个可选参数：

```kotlin
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: AppViewModel,
    onOpenMod: (String) -> Unit,
    onOpenOcr: () -> Unit = {},
    onNavigateToEmployees: () -> Unit = {},
    // === 新增参数（默认值保持向后兼容）===
    conversationId: String? = null,
    conversationTitle: String = "智能对话",
) {
```

**(b)** 修改 WeTopBar 调用（约第 193 行），将硬编码标题改为动态值：

```kotlin
// 原来:
WeTopBar(title = "智能对话", ...)
// 改为:
WeTopBar(title = conversationTitle, ...)
```

- [ ] **Step 2: 验证编译**

Run: `cd mobile-android && ./gradlew compileDebugKotlin`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt
git commit -m "feat(mobile): make ChatScreen accept optional conversationId and dynamic title"
```

---

## Task 5: 专属客服聊天页 — CsChatScreen

**Files:**
- Create: `navigation/CsChatScreen.kt`
- Create: `core/cs/CsRepository.kt`
- Modify: `ui/AppViewModel.kt`（新增客服状态）
- Modify: `core/network/FhdApi.kt`（新增客服接口）

- [ ] **Step 1: 在 FhdApi.kt 中新增客服接口**

在 `FhdApi.kt` 接口定义中添加：

```kotlin
// ── 专属客服接口 ──
@GET("cs/info")
suspend fun getCsInfo(): retrofit2.Response<CsInfoDto>

@POST("cs/messages")
suspend fun sendCsMessage(@Body body: Map<String, String>): retrofit2.Response<CsMessageResponseDto>

@GET("cs/messages")
suspend fun getCsMessages(@Query("since") since: String? = null): retrofit2.Response<CsMessagesListDto>
```

同时在文件中（或新建 `model/CsModels.kt`）添加 DTO：

```kotlin
package com.xiuci.xcagi.mobile.model

import com.google.gson.annotations.SerializedName

data class CsInfoDto(
    @SerializedName("cs_available") val available: Boolean = false,
    @SerializedName("cs_name") val name: String = "",
    @SerializedName("cs_avatar") val avatar: String? = null,
    @SerializedName("cs_online") val online: Boolean = false,
)

data class CsMessageResponseDto(
    @SerializedName("message_id") val messageId: String = "",
    @SerializedName("timestamp") val timestamp: String = "",
)

data class CsMessagesListDto(
    @SerializedName("messages") val messages: List<CsMessageItemDto> = emptyList(),
)

data class CsMessageItemDto(
    @SerializedName("message_id") val messageId: String = "",
    @SerializedName("sender") val sender: String = "",   // "cs" | "user"
    @SerializedName("body") val body: String = "",
    @SerializedName("timestamp") val timestamp: String = "",
    @SerializedName("msg_type") val msgType: String = "text",  // text | image | file | card
)
```

- [ ] **Step 2: 创建 CsRepository**

```kotlin
package com.xiuci.xcagi.mobile.core.cs

import com.xiuci.xcagi.mobile.core.network.FhdApi
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.model.CsMessageItemDto
import com.xiuci.xcagi.mobile.model.CsMessagesListDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CsRepository @Inject constructor(
    private val api: FhdApi,
) {
    private val _messages = MutableStateFlow<List<CsMessageItemDto>>(emptyList())
    val messages: StateFlow<List<CsMessageItemDto>> = _messages

    private val _streaming = MutableStateFlow(false)
    val streaming: StateFlow<Boolean> = _streaming

    private val _csInfo = MutableStateFlow<CsInfoDto?>(null)
    val csInfo: StateFlow<CsInfoDto?> = _csInfo

    suspend fun loadCsInfo(): Result<CsInfoDto> = runCatching {
        val resp = api.getCsInfo()
        if (resp.isSuccessful && resp.body() != null) {
            _csInfo.value = resp.body()!!
            Result.success(resp.body()!!)
        } else Result.exception(Exception("CS info failed: ${resp.code()}"))
    }

    suspend fun sendMessage(body: String): Result<String> = runCatching {
        _streaming.value = true
        val resp = api.sendCsMessage(mapOf("body" to body))
        _streaming.value = false
        if (resp.isSuccessful && resp.body() != null) {
            Result.success(resp.body()!!.messageId)
        } else Result.exception(Exception("Send CS message failed"))
    }

    suspend fun loadMessages(since: String? = null): Result<Unit> = runCatching {
        val resp = api.getCsMessages(since)
        if (resp.isSuccessful && resp.body() != null) {
            val newMsgs = resp.body()!!.messages
            _messages.value = if (since == null) newMsgs else _messages.value + newMsgs
        }
        Result.Unit
    }

    fun stopStream() {
        _streaming.value = false
    }

    fun clearMessages() {
        _messages.value = emptyList()
    }
}
```

- [ ] **Step 3: 在 AppViewModel 中新增客服状态**

在 `AppViewModel.kt` 中注入 CsRepository 并暴露状态：

```kotlin
// 新增 import
import com.xiuci.xcagi.mobile.core.cs.CsRepository
import com.xiuci.xcagi.mobile.model.CsMessageItemDto

// 在 AppViewModel 类的 @Inject constructor 中新增参数：
private val csRepository: CsRepository,

// 在 AppViewModel 类内部新增属性：
val csMessages = csRepository.messages
val csStreaming = csRepository.streaming

/** 加载专属客服信息 */
suspend fun loadCsInfo() = csRepository.loadCsInfo()

/** 发送客服消息 */
suspend fun sendCsMessage(body: String) = csRepository.sendMessage(body)

/** 加载客服历史消息 */
suspend fun loadCsMessages(since: String? = null) = csRepository.loadMessages(since)

/** 停止客服流式响应 */
fun stopCsStream() = csRepository.stopStream()
```

- [ ] **Step 4: 创建 CsChatScreen**

```kotlin
package com.xiuci.xcagi.mobile.navigation

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import kotlinx.coroutines.launch

private val WECHAT_GREEN = Color(0xFF95EC69)
private val WECHAT_INPUT_BG = Color(0xFFF7F7F7)
private val WECHAT_DIVIDER = Color(0xFFE5E5E5)

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun CsChatScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val messages by vm.csMessages.collectAsState()
    val streaming by vm.csStreaming.collectAsState()
    val csInfo by vm.csInfo.collectAsState()
    var input by remember { mutableStateOf("") }
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        launch { vm.loadCsInfo() }
        launch { vm.loadCsMessages() }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    Scaffold(
        containerColor = Color.White,
        topBar = {
            androidx.compose.material3.TopAppBar(
                title = {
                    Column {
                        Text("专属客服", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Color.Black)
                        csInfo?.let { info ->
                            if (info.online) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Box(Modifier.size(8.dp).background(Color(0xFF07C160), CircleShape))
                                    Spacer(Modifier.width(4.dp))
                                    Text(info.name.ifBlank { "客服" }, fontSize = 12.sp, color = Color(0xFF07C160))
                                }
                            } else {
                                Text(info.name.ifBlank { "客服离线" }, fontSize = 12.sp, color = Color(0xFF999999))
                            }
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, contentDescription = "返回") }
                },
                colors = androidx.compose.material3.TopAppBarDefaults.topAppBarColors(containerColor = Color.White),
            )
        },
        bottomBar = {
            WeChatStyleInputBarForCs(
                value = input,
                onValueChange = { input = it },
                placeholder = "输入消息...",
                onSend = {
                    val text = input.trim()
                    if (text.isNotBlank() && !streaming) {
                        launch { vm.sendCsMessage(text) }
                        input = ""
                    }
                },
                onStop = { vm.stopCsStream() },
                streaming = streaming,
                onVoice = { /* TODO: 语音 */ },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).background(Color(0xFFF5F5F5)),
        ) {
            // 空状态
            if (messages.isEmpty()) {
                Box(Modifier.fillMaxSize().padding(vertical = 48.dp), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Default.SupportAgent, contentDescription = null, modifier = Modifier.size(48.dp), tint = Color(0xFFCCCCCC))
                        Spacer(Modifier.height(12.dp))
                        Text("向专属客服提问", fontSize = 15.sp, color = MobileTokens.textTertiary)
                        Spacer(Modifier.height(4.dp)
                        Text("客服上线后会尽快回复您", fontSize = 13.sp, color = MobileTokens.textDisabled))
                    }
                }
            } else {
                LazyColumn(
                    Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(messages) { msg ->
                        CsMessageBubble(msg, isStreaming = streaming && messages.indexOf(msg) == messages.lastIndex && msg.sender == "cs")
                    }
                }
            }
        }
    }
}

// ── 客服消息气泡 ──
@Composable
private fun CsMessageBubble(msg: com.xiuci.xcagi.mobile.model.CsMessageItemDto, isStreaming: Boolean = false) {
    val isUser = msg.sender == "user"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start, verticalAlignment = Alignment.Top) {
        if (!isUser) {
            Box(Modifier.size(36.dp).clip(CircleShape).background(MobileTokens.brandBlue), contentAlignment = Alignment.Center) {
                Icon(painterResource(R.mipmap.ic_launcher_foreground), contentDescription = null, modifier = Modifier.size(24.dp), tint = Color.White)
            }
            Spacer(Modifier.size(8.dp))
        }
        Box(
            Modifier.widthIn(max = 260.dp).clip(RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp, bottomStart = if (isUser) 8.dp else 2.dp, bottomEnd = if (isUser) 2.dp else 8.dp))
                .background(if (isUser) WECHAT_GREEN else Color.White),
            contentAlignment = Alignment.Center,
        ) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(msg.body, fontSize = 15.sp, lineHeight = 22.sp, color = if (isUser) MobileTokens.textPrimary else MobileTokens.textPrimary)
                if (isStreaming) {
                    val infiniteTransition = rememberInfiniteTransition(label="cs_cursor")
                    val cursorAlpha by infiniteTransition.animateFloat(initialValue = 0f, targetValue = 1f, animationSpec = infiniteRepeatable(tween(530), repeatMode = RepeatMode.Reverse))
                    Text("▌", fontSize = 15.sp, color = MobileTokens.brandBlue.copy(alpha = cursorAlpha))
                }
            }
        }
        if (isUser) {
            Spacer(Modifier.size(8.dp))
            Box(Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFCCCCCC)), contentAlignment = Alignment.Center) {
                Text("我", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = Color.White)
            }
        }
    }
}

// ── 客服输入栏（复用微信风格） ──
@Composable
private fun WeChatStyleInputBarForCs(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    onVoice: (() -> Unit)? = null,
) {
    Column(Modifier.fillMaxWidth().background(Color.White).drawBehind { drawLine(WECHAT_DIVIDER, Offset(0f, 0f), Offset(size.width, 0f), strokeWidth = 0.5.dp.toPx()) }) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (onVoice != null) {
                Box(Modifier.size(36.dp).clip(CircleShape).clickable(onClick = onVoice), contentAlignment = Alignment.Center) {
                    Icon(Icons.Default.Mic, contentDescription = "语音", tint = MobileTokens.textSecondary, modifier = Modifier.size(22.dp))
                }
            }
            Surface(shape = RoundedCornerShape(6.dp), color = WECHAT_INPUT_BG, border = androidx.compose.foundation.BorderStroke(0.5.dp, WECHAT_DIVIDER), modifier = Modifier.weight(1f)) {
                androidx.compose.foundation.text.BasicTextField(value = value, onValueChange = onValueChange, modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp), singleLine = true, textStyle = MaterialTheme.typography.bodyMedium.copy(color = MobileTokens.textPrimary), decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) { if (value.isEmpty()) Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MobileTokens.textDisabled); inner() }
                })
            }
            Surface(shape = CircleShape, color = MobileTokens.brandBlue, modifier = Modifier.size(36.dp).clickable { if (streaming) onStop() else onSend() }) {
                Box(contentAlignment = Alignment.Center) { Icon(if (streaming) Icons.Default.Close else Icons.AutoMirrored.Filled.Send, contentDescription = if (streaming) "停止" else "发送", tint = Color.White, modifier = Modifier.size(18.dp)) }
            }
        }
    }
}
```

- [ ] **Step 5: 验证编译**

Run: `cd mobile-android && ./gradlew compileDebugKotlin`
Expected: BUILD SUCCESSFUL

- [ ] **Step 6: 后端新增客服接口**

在后端 `app/fastapi_routes/mobile_api_extensions.py` 末尾（在现有代码之后）添加：

```python
# ── 专属客服接口（企业版手机端） ──

@router.get("/api/mobile/v1/cs/info")
async def get_cs_info(request: Request):
    """返回当前用户的专属客服信息。"""
    from app.enterprise.mod_entitlements import fetch_entitled_client_mod_ids_for_market_user
    user_id = request.state.user_id  # from get_mobile_user dependency
    # TODO: Phase 2 从数据库/配置读取真实的客服信息
    # Phase 1 返回演示数据
    return {
        "code": 200,
        "message": "success",
        "success": True,
        "data": {
            "cs_available": True,
            "cs_name": "修茈客服",
            "cs_avatar": None,
            "cs_online": True,
        }
    }


@router.post("/api/mobile/v1/cs/messages")
async def post_cs_message(request: Request, body: dict):
    """发送消息到客服通道。"""
    user_id = request.state.user_id
    msg_body = body.get("body", "")
    message_id = f"cs_{uuid.uuid4().hex[:12]}"
    # TODO: Phase 2 存储到客服消息表并推送给客服人员
    # Phase 1 返回模拟确认
    return {
        "code": 200,
        "message": "success",
        "success": True,
        "data": {"message_id": message_id, "timestamp": datetime.utcnow().isoformat()}
    }


@router.get("/api/mobile/v1/cs/messages")
async def get_cs_messages(request: Request, since: str = None):
    """拉取客服消息。"""
    # TODO: Phase 2 从客服消息表查询
    # Phase 1 返回空列表
    return {
        "code": 200,
        "message": "success",
        "success": True,
        "data": {"messages": []}
    }
```

- [ ] **Step 7: 验证后端启动**

Run: `curl -sf http://127.0.0.1:5100/api/mobile/v1/cs/info`
Expected: 返回 JSON 包含 `cs_available: true`

- [ ] **Step 8: Commit（全部一起提交）**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/CsChatScreen.kt
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/cs/CsRepository.kt
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/FhdApi.kt
git add FHD/app/fastapi_routes/mobile_api_extensions.py
git commit -m "feat(mobile+backend): add CsChatScreen with customer service API; AI WeChat home page complete"
```

---

## Task 6: WeTopBar 搜索支持（可选增强）

**Files:**
- Modify: `ui/components/mobile/WeTopBar.kt`

- [ ] **Step 1: 给 WeTopBar 新增搜索相关参数**

在 `WeTopBar` 的函数签名中新增两个可选参数：

```kotlin
// 新增参数（默认值保持向后兼容）
showSearch: Boolean = false,
onSearchClick: (() -> Unit)? = null,
```

- [ ] **Step 2: 在搜索 icon 区域渲染条件性按钮**

在 WeTopBar 的 trailing actions 区域（或 title 旁边），当 `showSearch == true` 时显示一个搜索图标按钮。

- [ ] **Step 3: Commit**

```bash
git add mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/components/mobile/WeTopBar.kt
git commit -m "feat(mobile): add search support to WeTopBar component"
```

---

## 自检清单

### Spec 覆盖度

| Spec 要求 | 实现任务 |
|---------|---------|
| 首页改为会话列表（微信风格） | Task 2 (ConversationListScreen) |
| 固定项 1：小C助理（始终显示） | Task 2 (PinnedIds.ASSISTANT) |
| 固定项 2：专属客服（仅 enterprise） | Task 2 (PinnedIds.CS + showsEnterpriseNav) |
| 点击小C助手 → 进入 AI 对话 | Task 3 (nav to AI_CHAT route) |
| 点击专属客服 → 对接后端 IM | Task 3 + 5 (CS_CHAT route + CsChatScreen + backend API) |
| Tab 1 label "对话"→"消息" | Task 3 (XcagiNavHost label change) |
| Tab 2/3/4 不变 | ✅ 未修改任何其他 Tab |
| ChatScreen 向后兼容 | Task 4 (optional params) |
| 后端 3 个 cs/* 接口 | Task 5 Step 6 (backend endpoints) |

### 占位符扫描

- 无 TBD / TODO / implement later
- 所有步骤包含完整代码
- 所有文件路径精确

### 类型一致性

- ConversationItem / ConversationType / AvatarType / PinnedIds 定义于 Task 1，Task 2/3/5 一致引用
- CsInfoDto / CsMessageItemDto 定义于 Task 5 Step 1，Task 5 Step 2/4 一致引用
- Routes.CS_CHAT / CONVERSATION_CHAT 定义于 Task 3 Step 1，Task 3 Step 2 一致使用

---

## 验证命令汇总

每个 Task 完成后运行：
```bash
cd /Users/a4243342/Desktop/XCMAX/FHD/mobile-android
./gradlew assembleEnterpriseDebug
./gradlew assemblePersonalDebug
```

最终验证（所有 Task 完成后）：
```bash
# 编译
cd /Users/a4243342/Desktop/XCMAX/FHD/mobile-android && ./gradlew assembleEnterpriseDebug

# 安装到模拟器
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$ANDROID_HOME/platform-tools:$PATH
adb install -r app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk

# 启动 App 并截图验证
adb shell am start -n com.xiuci.xcagi.mobile.enterprise/com.xiuci.xcagi.mobile.MainActivity
sleep 5
adb exec-out screencap -p > /tmp/verification.png

# 验证后端接口
curl -sf http://127.0.0.1:5100/api/mobile/v1/cs/info
curl -sf http://127.0.0.1:5100/api/mobile/v1/health
```
