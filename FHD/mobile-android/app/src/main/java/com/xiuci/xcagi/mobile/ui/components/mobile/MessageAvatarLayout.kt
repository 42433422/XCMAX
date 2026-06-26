package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 消息页头像布局 SSOT。
 *
 * 会话列表、聊天气泡、客服会话和员工选择列表都从这里取头像尺寸、圆角、
 * 左右间距和分割线缩进，避免页面内散落 40.dp / 52.dp / 84.dp 这类硬编码。
 */
object MessageAvatarLayout {
    const val HeaderAvatarSizeDp = 44
    const val HeaderAvatarCornerRadiusDp = 10
    const val TopBarAvatarSizeDp = 32

    const val ConversationAvatarSizeDp = 52
    const val ConversationAvatarCornerRadiusDp = 8
    const val ConversationRowHorizontalPaddingDp = 16
    const val ConversationRowVerticalPaddingDp = 11
    const val ConversationAvatarTextGapDp = 12
    const val ConversationDividerExtraInsetDp = 4
    const val ConversationDividerStartDp =
        ConversationRowHorizontalPaddingDp +
            ConversationAvatarSizeDp +
            ConversationAvatarTextGapDp +
            ConversationDividerExtraInsetDp

    const val UnreadBadgeOffsetXDp = 5
    const val UnreadBadgeOffsetYDp = -5
    const val UnreadBadgeSizeDp = 21
    const val UnreadBadgeLargeSizeDp = 25
    const val OnlineIndicatorSizeDp = 14
    const val OnlineIndicatorOffsetYDp = 2
    const val OnlineIndicatorPaddingDp = 2.5f

    const val BubbleAvatarSizeDp = 40
    const val BubbleAvatarCornerRadiusDp = 8
    const val BubbleAvatarGapDp = 8
    const val BubbleTopPaddingWithAvatarDp = 12
    const val BubbleTopPaddingWithoutAvatarDp = 4
    const val BubbleAvatarReservedWidthDp = BubbleAvatarSizeDp + BubbleAvatarGapDp
    const val EmptyStateAvatarSizeDp = 72
    const val EmptyStateAvatarCornerRadiusDp = 20

    const val EmployeePickerAvatarSizeDp = 44
    const val EmployeePickerAvatarCornerRadiusDp = 4
    const val EmployeePickerRowHorizontalPaddingDp = 12
    const val EmployeePickerRowVerticalPaddingDp = 10
    const val EmployeePickerAvatarTextGapDp = 12
    const val EmployeePickerDividerStartDp =
        EmployeePickerRowHorizontalPaddingDp +
            EmployeePickerAvatarSizeDp +
            EmployeePickerAvatarTextGapDp

    const val CustomerServiceBubbleAvatarSizeDp = 36
    const val CustomerServiceBubbleIconSizeDp = 24
    const val CustomerServiceBubbleAvatarGapDp = 8

    val headerAvatarSize: Dp = HeaderAvatarSizeDp.dp
    val topBarAvatarSize: Dp = TopBarAvatarSizeDp.dp
    val conversationAvatarSize: Dp = ConversationAvatarSizeDp.dp
    val conversationRowHorizontalPadding: Dp = ConversationRowHorizontalPaddingDp.dp
    val conversationRowVerticalPadding: Dp = ConversationRowVerticalPaddingDp.dp
    val conversationAvatarTextGap: Dp = ConversationAvatarTextGapDp.dp
    val conversationDividerStart: Dp = ConversationDividerStartDp.dp
    val unreadBadgeOffsetX: Dp = UnreadBadgeOffsetXDp.dp
    val unreadBadgeOffsetY: Dp = UnreadBadgeOffsetYDp.dp
    val unreadBadgeSize: Dp = UnreadBadgeSizeDp.dp
    val unreadBadgeLargeSize: Dp = UnreadBadgeLargeSizeDp.dp
    val onlineIndicatorSize: Dp = OnlineIndicatorSizeDp.dp
    val onlineIndicatorOffsetY: Dp = OnlineIndicatorOffsetYDp.dp
    val onlineIndicatorPadding: Dp = OnlineIndicatorPaddingDp.dp
    val bubbleAvatarSize: Dp = BubbleAvatarSizeDp.dp
    val bubbleAvatarGap: Dp = BubbleAvatarGapDp.dp
    val bubbleTopPaddingWithAvatar: Dp = BubbleTopPaddingWithAvatarDp.dp
    val bubbleTopPaddingWithoutAvatar: Dp = BubbleTopPaddingWithoutAvatarDp.dp
    val bubbleAvatarReservedWidth: Dp = BubbleAvatarReservedWidthDp.dp
    val emptyStateAvatarSize: Dp = EmptyStateAvatarSizeDp.dp
    val employeePickerAvatarSize: Dp = EmployeePickerAvatarSizeDp.dp
    val employeePickerRowHorizontalPadding: Dp = EmployeePickerRowHorizontalPaddingDp.dp
    val employeePickerRowVerticalPadding: Dp = EmployeePickerRowVerticalPaddingDp.dp
    val employeePickerAvatarTextGap: Dp = EmployeePickerAvatarTextGapDp.dp
    val employeePickerDividerStart: Dp = EmployeePickerDividerStartDp.dp
    val customerServiceBubbleAvatarSize: Dp = CustomerServiceBubbleAvatarSizeDp.dp
    val customerServiceBubbleIconSize: Dp = CustomerServiceBubbleIconSizeDp.dp
    val customerServiceBubbleAvatarGap: Dp = CustomerServiceBubbleAvatarGapDp.dp

    fun headerAvatarShape(): Shape = RoundedCornerShape(HeaderAvatarCornerRadiusDp.dp)
    fun conversationAvatarShape(): Shape = RoundedCornerShape(ConversationAvatarCornerRadiusDp.dp)
    fun bubbleAvatarShape(): Shape = RoundedCornerShape(BubbleAvatarCornerRadiusDp.dp)
    fun emptyStateAvatarShape(): Shape = RoundedCornerShape(EmptyStateAvatarCornerRadiusDp.dp)
    fun employeePickerAvatarShape(): Shape =
        RoundedCornerShape(EmployeePickerAvatarCornerRadiusDp.dp)
}
