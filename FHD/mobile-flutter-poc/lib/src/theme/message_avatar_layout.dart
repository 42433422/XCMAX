import 'package:flutter/material.dart';

class MessageAvatarLayout {
  static const headerAvatarSize = 44.0;
  static const headerAvatarCornerRadius = 10.0;
  static const topBarAvatarSize = 32.0;

  static const conversationAvatarSize = 52.0;
  static const conversationAvatarCornerRadius = 8.0;
  static const conversationRowHorizontalPadding = 16.0;
  static const conversationRowVerticalPadding = 11.0;
  static const conversationAvatarTextGap = 12.0;
  static const conversationDividerExtraInset = 4.0;
  static const conversationDividerStart = conversationRowHorizontalPadding +
      conversationAvatarSize +
      conversationAvatarTextGap +
      conversationDividerExtraInset;

  static const unreadBadgeOffsetX = 5.0;
  static const unreadBadgeOffsetY = -5.0;
  static const unreadBadgeSize = 21.0;
  static const unreadBadgeLargeSize = 25.0;
  static const onlineIndicatorSize = 14.0;
  static const onlineIndicatorOffsetY = 2.0;
  static const onlineIndicatorPadding = 2.5;

  static const bubbleAvatarSize = 40.0;
  static const bubbleAvatarCornerRadius = 8.0;
  static const bubbleAvatarGap = 8.0;
  static const bubbleTopPaddingWithAvatar = 12.0;
  static const bubbleTopPaddingWithoutAvatar = 4.0;
  static const bubbleAvatarReservedWidth = bubbleAvatarSize + bubbleAvatarGap;
  static const emptyStateAvatarSize = 72.0;
  static const emptyStateAvatarCornerRadius = 20.0;

  static const employeePickerAvatarSize = 44.0;
  static const employeePickerAvatarCornerRadius = 4.0;
  static const employeePickerRowHorizontalPadding = 12.0;
  static const employeePickerRowVerticalPadding = 10.0;
  static const employeePickerAvatarTextGap = 12.0;
  static const employeePickerDividerStart = employeePickerRowHorizontalPadding +
      employeePickerAvatarSize +
      employeePickerAvatarTextGap;

  static const customerServiceBubbleAvatarSize = 36.0;
  static const customerServiceBubbleIconSize = 24.0;
  static const customerServiceBubbleAvatarGap = 8.0;

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
