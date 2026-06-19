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
    PINNED_CODEX,         // 固定：超级员工-Codex
    AI_TASK,              // AI 任务会话
    SYSTEM_NOTIFICATION,  // 系统通知
}

enum class AvatarType { ICON, LETTER, URL }

/** 固定联系人 ID 常量 */
object PinnedIds {
    const val CS = "pinned:cs"
    const val ASSISTANT = "pinned:assistant"
    const val CODEX = "pinned:codex"
}
