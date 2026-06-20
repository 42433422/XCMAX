package com.xiuci.xcagi.mobile.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class ConversationTimestampPolicyTest {
    @Test
    fun `uses persisted last message timestamp`() {
        val cachedAt = 1_750_000_000_123L

        assertEquals(
            cachedAt,
            cachedConversationTimestamp("employee:mod:worker", mapOf("employee:mod:worker" to cachedAt)),
        )
    }

    @Test
    fun `conversation without a real message has no fake current timestamp`() {
        assertEquals(0L, cachedConversationTimestamp("employee:mod:new", emptyMap()))
        assertEquals(0L, cachedConversationTimestamp("employee:mod:new", mapOf("employee:mod:new" to 0L)))
    }

    @Test
    fun `preview returns persisted latest message preview`() {
        val preview = "我: 帮我写个周报"

        assertEquals(
            preview,
            cachedConversationPreview("pinned:assistant", mapOf("pinned:assistant" to preview)),
        )
    }

    @Test
    fun `preview falls back to empty when conversation has no preview`() {
        assertEquals("", cachedConversationPreview("pinned:assistant", emptyMap()))
        assertEquals("", cachedConversationPreview("pinned:assistant", mapOf("pinned:assistant" to "")))
        assertEquals("", cachedConversationPreview("pinned:assistant", mapOf("pinned:assistant" to "   ")))
    }

    @Test
    fun `preview is scoped by conversation id`() {
        val previews = mapOf(
            "pinned:assistant" to "有什么可以帮您？",
            "employee:mod:worker" to "我: 打开 Mod",
        )

        assertEquals("有什么可以帮您？", cachedConversationPreview("pinned:assistant", previews))
        assertEquals("我: 打开 Mod", cachedConversationPreview("employee:mod:worker", previews))
        assertEquals("", cachedConversationPreview("pinned:cs", previews))
    }
}
