package com.xiuci.xcagi.mobile.ui.components.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class MessageAvatarLayoutTest {
    @Test
    fun conversationDividerInsetIsDerivedFromAvatarPosition() {
        assertEquals(
            MessageAvatarLayout.ConversationRowHorizontalPaddingDp +
                MessageAvatarLayout.ConversationAvatarSizeDp +
                MessageAvatarLayout.ConversationAvatarTextGapDp +
                MessageAvatarLayout.ConversationDividerExtraInsetDp,
            MessageAvatarLayout.ConversationDividerStartDp,
        )
    }

    @Test
    fun hiddenBubbleAvatarKeepsTheSameHorizontalSlot() {
        assertEquals(
            MessageAvatarLayout.BubbleAvatarSizeDp + MessageAvatarLayout.BubbleAvatarGapDp,
            MessageAvatarLayout.BubbleAvatarReservedWidthDp,
        )
    }

    @Test
    fun employeePickerDividerInsetFollowsAvatarAndTextGap() {
        assertEquals(
            MessageAvatarLayout.EmployeePickerRowHorizontalPaddingDp +
                MessageAvatarLayout.EmployeePickerAvatarSizeDp +
                MessageAvatarLayout.EmployeePickerAvatarTextGapDp,
            MessageAvatarLayout.EmployeePickerDividerStartDp,
        )
    }

    @Test
    fun messageAvatarSizesRemainCentralized() {
        assertEquals(52, MessageAvatarLayout.ConversationAvatarSizeDp)
        assertEquals(40, MessageAvatarLayout.BubbleAvatarSizeDp)
        assertEquals(36, MessageAvatarLayout.CustomerServiceBubbleAvatarSizeDp)
        assertEquals(32, MessageAvatarLayout.TopBarAvatarSizeDp)
        assertEquals(72, MessageAvatarLayout.EmptyStateAvatarSizeDp)
    }
}
