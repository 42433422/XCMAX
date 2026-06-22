package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.PinnedIds
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatAvatarPolicyTest {
    @Test
    fun `codex pinned conversation uses codex avatar policy`() {
        assertTrue(isCodexConversation(PinnedIds.CODEX))
        assertTrue(isCodexConversation("  ${PinnedIds.CODEX}  "))
        assertEquals(
            AppAvatarFallback.CODEX,
            chatAvatarFallback(PinnedIds.CODEX, hasEmployeeProfile = false),
        )
    }

    @Test
    fun `other conversations do not use codex avatar policy`() {
        assertFalse(isCodexConversation(null))
        assertFalse(isCodexConversation("assistant"))
        assertFalse(isCodexConversation("employee:mod:codex"))
        assertEquals(
            AppAvatarFallback.ASSISTANT,
            chatAvatarFallback("assistant", hasEmployeeProfile = false),
        )
        assertEquals(
            AppAvatarFallback.AI_EMPLOYEE,
            chatAvatarFallback("employee:mod:worker", hasEmployeeProfile = true),
        )
    }
}
