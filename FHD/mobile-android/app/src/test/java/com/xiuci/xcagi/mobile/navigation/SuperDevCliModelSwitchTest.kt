package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.PinnedIds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SuperDevCliModelSwitchTest {
    @Test
    fun superDevCliPinnedIdsCoverAllCliTools() {
        val cliIds = setOf(PinnedIds.CODEX, PinnedIds.CURSOR, PinnedIds.CLAUDE, PinnedIds.TRAE)
        assertEquals(4, cliIds.size)
        assertTrue(isCodexConversation(PinnedIds.CODEX))
        assertTrue(isCursorConversation(PinnedIds.CURSOR))
        assertTrue(isClaudeConversation(PinnedIds.CLAUDE))
        assertTrue(isTraeConversation(PinnedIds.TRAE))
    }
}
