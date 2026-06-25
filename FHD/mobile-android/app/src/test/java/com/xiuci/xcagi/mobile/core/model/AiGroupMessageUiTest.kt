package com.xiuci.xcagi.mobile.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AiGroupMessageUiTest {
    @Test
    fun discussionAndRoutingKinds() {
        assertEquals("讨论", AiGroupMessageUi.resolve("discussion", null, null).badge)
        assertEquals(AiGroupBubbleTone.ROUTING, AiGroupMessageUi.resolve("routing_decision", null, null).bubbleTone)
    }

    @Test
    fun falseAcceptanceNeedsReview() {
        val ui = AiGroupMessageUi.resolve("work_acceptance", "needs_review", null)
        assertEquals("待复核", ui.badge)
        assertTrue(ui.needsReview)
    }

    @Test
    fun sendingLabelReflectsMode() {
        assertTrue(AiGroupMessageUi.sendingLabel(false).contains("讨论"))
        assertTrue(AiGroupMessageUi.sendingLabel(true).contains("执行"))
    }
}
