import 'package:flutter/material.dart';

import 'design_tokens.generated.dart';

class MessageAvatarLayout {
  static const headerAvatarSize = DesignTokens.mobileAvatarLayoutHeaderAvatarSize;
  static const headerAvatarCornerRadius = DesignTokens.mobileAvatarLayoutHeaderAvatarCornerRadius;
  static const topBarAvatarSize = DesignTokens.mobileAvatarLayoutTopBarAvatarSize;

  static const conversationAvatarSize = DesignTokens.mobileAvatarLayoutConversationAvatarSize;
  static const conversationAvatarCornerRadius = DesignTokens.mobileAvatarLayoutConversationAvatarCornerRadius;
  static const conversationRowHorizontalPadding = DesignTokens.mobileAvatarLayoutConversationRowHorizontalPadding;
  static const conversationRowVerticalPadding = DesignTokens.mobileAvatarLayoutConversationRowVerticalPadding;
  static const conversationAvatarTextGap = DesignTokens.mobileAvatarLayoutConversationAvatarTextGap;
  static const conversationDividerExtraInset = DesignTokens.mobileAvatarLayoutConversationDividerExtraInset;
  static const conversationDividerStart = conversationRowHorizontalPadding +
      conversationAvatarSize +
      conversationAvatarTextGap +
      conversationDividerExtraInset;

  static const unreadBadgeOffsetX = DesignTokens.mobileAvatarLayoutUnreadBadgeOffsetX;
  static const unreadBadgeOffsetY = DesignTokens.mobileAvatarLayoutUnreadBadgeOffsetY;
  static const unreadBadgeSize = DesignTokens.mobileAvatarLayoutUnreadBadgeSize;
  static const unreadBadgeLargeSize = DesignTokens.mobileAvatarLayoutUnreadBadgeLargeSize;
  static const onlineIndicatorSize = DesignTokens.mobileAvatarLayoutOnlineIndicatorSize;
  static const onlineIndicatorOffsetY = DesignTokens.mobileAvatarLayoutOnlineIndicatorOffsetY;
  static const onlineIndicatorPadding = DesignTokens.mobileAvatarLayoutOnlineIndicatorPadding;

  static const bubbleAvatarSize = DesignTokens.mobileAvatarLayoutBubbleAvatarSize;
  static const bubbleAvatarCornerRadius = DesignTokens.mobileAvatarLayoutBubbleAvatarCornerRadius;
  static const bubbleAvatarGap = DesignTokens.mobileAvatarLayoutBubbleAvatarGap;
  static const bubbleTopPaddingWithAvatar = DesignTokens.mobileAvatarLayoutBubbleTopPaddingWithAvatar;
  static const bubbleTopPaddingWithoutAvatar = DesignTokens.mobileAvatarLayoutBubbleTopPaddingWithoutAvatar;
  static const bubbleAvatarReservedWidth = bubbleAvatarSize + bubbleAvatarGap;
  static const emptyStateAvatarSize = DesignTokens.mobileAvatarLayoutEmptyStateAvatarSize;
  static const emptyStateAvatarCornerRadius = DesignTokens.mobileAvatarLayoutEmptyStateAvatarCornerRadius;

  static const employeePickerAvatarSize = DesignTokens.mobileAvatarLayoutEmployeePickerAvatarSize;
  static const employeePickerAvatarCornerRadius = DesignTokens.mobileAvatarLayoutEmployeePickerAvatarCornerRadius;
  static const employeePickerRowHorizontalPadding = DesignTokens.mobileAvatarLayoutEmployeePickerRowHorizontalPadding;
  static const employeePickerRowVerticalPadding = DesignTokens.mobileAvatarLayoutEmployeePickerRowVerticalPadding;
  static const employeePickerAvatarTextGap = DesignTokens.mobileAvatarLayoutEmployeePickerAvatarTextGap;
  static const employeePickerDividerStart = employeePickerRowHorizontalPadding +
      employeePickerAvatarSize +
      employeePickerAvatarTextGap;

  static const customerServiceBubbleAvatarSize = DesignTokens.mobileAvatarLayoutCustomerServiceBubbleAvatarSize;
  static const customerServiceBubbleIconSize = DesignTokens.mobileAvatarLayoutCustomerServiceBubbleIconSize;
  static const customerServiceBubbleAvatarGap = DesignTokens.mobileAvatarLayoutCustomerServiceBubbleAvatarGap;

  static BorderRadius get headerAvatarRadius =>
      BorderRadius.circular(headerAvatarCornerRadius);

  static BorderRadius get conversationAvatarRadius =>
      BorderRadius.circular(conversationAvatarCornerRadius);

  static BorderRadius get bubbleAvatarRadius =>
      BorderRadius.circular(bubbleAvatarCornerRadius);

  static BorderRadius get emptyStateAvatarRadius =>
      BorderRadius.circular(emptyStateAvatarCornerRadius);

  static BorderRadius get employeePickerAvatarRadius =>
      BorderRadius.circular(employeePickerAvatarCornerRadius);
}
