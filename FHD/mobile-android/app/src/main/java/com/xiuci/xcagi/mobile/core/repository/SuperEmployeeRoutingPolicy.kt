package com.xiuci.xcagi.mobile.core.repository

import com.xiuci.xcagi.mobile.model.PinnedIds

internal object SuperEmployeeRoutingPolicy {
    fun isSuperEmployeeConversation(conversationId: String?): Boolean =
        relayKindForConversation(conversationId) != null

    fun relayKindForConversation(conversationId: String?): String? =
        when (conversationId?.trim()) {
            PinnedIds.CODEX -> "codex.invoke"
            PinnedIds.CURSOR -> "cursor.invoke"
            PinnedIds.CLAUDE -> "claude.invoke"
            PinnedIds.TRAE -> "trae.invoke"
            else -> null
        }

    /** conversationId 形如 `employee:modId:employeeId` 表示和企业生态里的员工 chat。 */
    fun isEmployeeConversation(conversationId: String?): Boolean =
        conversationId?.trim()?.startsWith("employee:") == true

    /** 解析 `employee:modId:employeeId` → (modId, employeeId)；非 employee 会话返回 null。 */
    fun parseEmployeeRef(conversationId: String?): Pair<String, String>? {
        val raw = conversationId?.trim() ?: return null
        if (!raw.startsWith("employee:")) return null
        val parts = raw.split(":")
        if (parts.size != 3) return null
        val modId = parts[1].trim()
        val employeeId = parts[2].trim()
        if (modId.isEmpty() || employeeId.isEmpty()) return null
        return modId to employeeId
    }

    fun toolLabelForRelayKind(kind: String): String =
        when {
            kind.startsWith("claude") -> "Claude"
            kind.startsWith("cursor") -> "Cursor"
            kind.startsWith("trae") -> "Trae"
            else -> "Codex"
        }
}
