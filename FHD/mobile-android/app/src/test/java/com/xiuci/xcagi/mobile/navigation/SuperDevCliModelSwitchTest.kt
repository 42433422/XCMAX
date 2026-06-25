package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.PinnedIds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SuperDevCliModelSwitchTest {
    @Test
    fun superDevCliPinnedIdsCoverAllCliTools() {
        val cliIds = setOf(PinnedIds.CODEX, PinnedIds.CURSOR, PinnedIds.CLAUDE)
        assertEquals(3, cliIds.size)
        assertTrue(isCodexConversation(PinnedIds.CODEX))
        assertTrue(isCursorConversation(PinnedIds.CURSOR))
        assertTrue(isClaudeConversation(PinnedIds.CLAUDE))
    }
}
