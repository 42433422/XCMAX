package com.xiuci.xcagi.mobile.core.repository

import com.xiuci.xcagi.mobile.model.PinnedIds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SuperEmployeeRoutingPolicyTest {
    @Test
    fun onlySuperEmployeesCanEnterCliRelay() {
        assertFalse(SuperEmployeeRoutingPolicy.isSuperEmployeeConversation(PinnedIds.ASSISTANT))
        assertNull(SuperEmployeeRoutingPolicy.relayKindForConversation(PinnedIds.ASSISTANT))
        assertNull(SuperEmployeeRoutingPolicy.relayKindForConversation("employee:mod:worker"))

        assertTrue(SuperEmployeeRoutingPolicy.isSuperEmployeeConversation(PinnedIds.CODEX))
        assertTrue(SuperEmployeeRoutingPolicy.isSuperEmployeeConversation(PinnedIds.CURSOR))
        assertTrue(SuperEmployeeRoutingPolicy.isSuperEmployeeConversation(PinnedIds.CLAUDE))
    }

    @Test
    fun superEmployeesMapToTheirOwnCliRelayKind() {
        assertEquals("codex.invoke", SuperEmployeeRoutingPolicy.relayKindForConversation(PinnedIds.CODEX))
        assertEquals("cursor.invoke", SuperEmployeeRoutingPolicy.relayKindForConversation(PinnedIds.CURSOR))
        assertEquals("claude.invoke", SuperEmployeeRoutingPolicy.relayKindForConversation(PinnedIds.CLAUDE))
    }
}
