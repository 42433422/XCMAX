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

    fun toolLabelForRelayKind(kind: String): String =
        when {
            kind.startsWith("claude") -> "Claude"
            kind.startsWith("cursor") -> "Cursor"
            kind.startsWith("trae") -> "Trae"
            else -> "Codex"
        }
}
