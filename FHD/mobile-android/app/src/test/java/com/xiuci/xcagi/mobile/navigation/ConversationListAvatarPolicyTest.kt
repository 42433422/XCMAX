package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.ConversationType
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversationListAvatarPolicyTest {
    @Test
    fun `all pinned super employees use branded avatar path`() {
        assertTrue(usesPinnedConversationAvatar(ConversationType.PINNED_CODEX))
        assertTrue(usesPinnedConversationAvatar(ConversationType.PINNED_CURSOR))
        assertTrue(usesPinnedConversationAvatar(ConversationType.PINNED_CLAUDE))
        assertTrue(usesPinnedConversationAvatar(ConversationType.PINNED_TRAE))
    }

    @Test
    fun `regular ai task uses employee avatar path`() {
        assertFalse(usesPinnedConversationAvatar(ConversationType.AI_TASK))
        assertFalse(usesPinnedConversationAvatar(ConversationType.SYSTEM_NOTIFICATION))
    }
}
