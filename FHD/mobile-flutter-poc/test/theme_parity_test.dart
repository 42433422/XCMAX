import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import 'package:xcagi_flutter_poc/src/theme/message_avatar_layout.dart';

void main() {
  final androidTheme = _AndroidThemeSource.read();

  test('brand and functional color constants mirror Android Theme.kt', () {
    expect(AppTheme.brand, androidTheme.color('BrandBlue'));
    expect(AppTheme.brandContainer, androidTheme.color('BrandBlueContainer'));
    expect(
      AppTheme.brandGradientEnd,
      androidTheme.color('BrandBlueGradientEnd'),
    );
    expect(AppTheme.danger, androidTheme.color('FuncDanger'));
    expect(AppTheme.success, androidTheme.color('FuncGreen'));
    expect(AppTheme.warning, androidTheme.color('FuncWarning'));
    expect(AppTheme.weChatOnline, androidTheme.color('WeChatOnline'));
    expect(AppTheme.momentAccent, androidTheme.color('MomentAccentLight'));
    expect(AppTheme.momentChipBg, androidTheme.color('MomentChipBgLight'));
    expect(AppTheme.replyBoxBg, androidTheme.color('ReplyBoxBgLight'));
    expect(AppTheme.page, androidTheme.color('N50'));
    expect(AppTheme.surface, androidTheme.color('N00'));
    expect(AppTheme.surfaceHigh, androidTheme.color('N100'));
    expect(AppTheme.divider, androidTheme.color('N200'));
    expect(AppTheme.textPrimary, androidTheme.color('N800'));
    expect(AppTheme.textSecondary, androidTheme.color('N500'));
    expect(AppTheme.textStrongSecondary, androidTheme.color('N600'));
    expect(AppTheme.textTertiary, androidTheme.color('N400'));
  });

  test('extra theme colors mirror Android LightExtraColors', () {
    final android = androidTheme.extraColors('LightExtraColors');
    const flutter = XcagiThemeColors.light;

    expect(flutter.brand, android['brandBlue']);
    expect(flutter.brandContainer, android['brandBlueContainer']);
    expect(flutter.brandGradientEnd, android['brandBlueGradientEnd']);
    expect(flutter.weChatGreen, android['weChatGreen']);
    expect(flutter.weChatOnline, android['weChatOnline']);
    expect(flutter.weChatInputBg, android['weChatInputBg']);
    expect(flutter.weChatDivider, android['weChatDivider']);
    expect(flutter.chatUserBubble, android['chatUserBubble']);
    expect(flutter.chatUserBubbleText, android['chatUserBubbleText']);
    expect(flutter.momentAccent, android['momentAccent']);
    expect(flutter.momentChipBg, android['momentChipBg']);
    expect(flutter.replyBoxBg, android['replyBoxBg']);
    expect(flutter.success, android['success']);
    expect(flutter.warning, android['warning']);
    expect(flutter.danger, android['danger']);
    expect(flutter.page, android['n50']);
    expect(flutter.surface, android['n00']);
    expect(flutter.surfaceHigh, android['n100']);
    expect(flutter.divider, android['n200']);
    expect(flutter.textPrimary, android['n800']);
    expect(flutter.textSecondary, android['n500']);
    expect(flutter.textStrongSecondary, android['n600']);
    expect(flutter.textTertiary, android['n400']);
  });

  test('extra theme colors mirror Android DarkExtraColors', () {
    final android = androidTheme.extraColors('DarkExtraColors');
    const flutter = XcagiThemeColors.dark;

    expect(flutter.brand, android['brandBlue']);
    expect(flutter.brandContainer, android['brandBlueContainer']);
    expect(flutter.brandGradientEnd, android['brandBlueGradientEnd']);
    expect(flutter.weChatGreen, android['weChatGreen']);
    expect(flutter.weChatOnline, android['weChatOnline']);
    expect(flutter.weChatInputBg, android['weChatInputBg']);
    expect(flutter.weChatDivider, android['weChatDivider']);
    expect(flutter.chatUserBubble, android['chatUserBubble']);
    expect(flutter.chatUserBubbleText, android['chatUserBubbleText']);
    expect(flutter.momentAccent, android['momentAccent']);
    expect(flutter.momentChipBg, android['momentChipBg']);
    expect(flutter.replyBoxBg, android['replyBoxBg']);
    expect(flutter.success, android['success']);
    expect(flutter.warning, android['warning']);
    expect(flutter.danger, android['danger']);
    expect(flutter.page, android['n00']);
    expect(flutter.surface, android['n50']);
    expect(flutter.surfaceHigh, android['n100']);
    expect(flutter.divider, android['n200']);
    expect(flutter.textPrimary, androidTheme.color('DarkTextPrimary'));
    expect(flutter.textSecondary, android['n400']);
    expect(flutter.textStrongSecondary, android['n600']);
    expect(flutter.textTertiary, android['n300']);
  });

  test('Material light color scheme mirrors Android LightColors', () {
    final android = androidTheme.colorScheme('LightColors');
    final flutter = AppTheme.light().colorScheme;

    _expectColorScheme(flutter, android);
    expect(AppTheme.light().scaffoldBackgroundColor, android['background']);
  });

  test('Material dark color scheme mirrors Android DarkColors', () {
    final android = androidTheme.colorScheme('DarkColors');
    final flutter = AppTheme.dark().colorScheme;

    _expectColorScheme(flutter, android);
    expect(AppTheme.dark().scaffoldBackgroundColor, android['background']);
  });

  test('Flutter typography mirrors Android XcagiTypography', () {
    final android = _androidTypography();

    _expectTextTheme(AppTheme.light().textTheme, android);
    _expectTextTheme(AppTheme.dark().textTheme, android);
  });

  test('Flutter shape, elevation and spacing tokens mirror Android Shape.kt',
      () {
    final android = _androidShapeTokens();

    expect(XcagiShapeTokens.extraSmall, android['shape.extraSmall']);
    expect(XcagiShapeTokens.small, android['shape.small']);
    expect(XcagiShapeTokens.medium, android['shape.medium']);
    expect(XcagiShapeTokens.large, android['shape.large']);
    expect(XcagiShapeTokens.extraLarge, android['shape.extraLarge']);

    expect(XcagiElevation.none, android['elevation.none']);
    expect(XcagiElevation.level1, android['elevation.level1']);
    expect(XcagiElevation.level2, android['elevation.level2']);
    expect(XcagiElevation.level3, android['elevation.level3']);

    expect(XcagiSpacing.xs, android['spacing.xs']);
    expect(XcagiSpacing.sm, android['spacing.sm']);
    expect(XcagiSpacing.md, android['spacing.md']);
    expect(XcagiSpacing.lg, android['spacing.lg']);
    expect(XcagiSpacing.xl, android['spacing.xl']);
    expect(XcagiSpacing.xxl, android['spacing.xxl']);
    expect(XcagiSpacing.xxxl, android['spacing.xxxl']);
  });

  test('message avatar layout mirrors Android MessageAvatarLayout.kt', () {
    final android = _androidMessageAvatarLayoutTokens();

    expect(
      {
        'HeaderAvatarSizeDp': MessageAvatarLayout.headerAvatarSize,
        'HeaderAvatarCornerRadiusDp':
            MessageAvatarLayout.headerAvatarCornerRadius,
        'TopBarAvatarSizeDp': MessageAvatarLayout.topBarAvatarSize,
        'ConversationAvatarSizeDp': MessageAvatarLayout.conversationAvatarSize,
        'ConversationAvatarCornerRadiusDp':
            MessageAvatarLayout.conversationAvatarCornerRadius,
        'ConversationRowHorizontalPaddingDp':
            MessageAvatarLayout.conversationRowHorizontalPadding,
        'ConversationRowVerticalPaddingDp':
            MessageAvatarLayout.conversationRowVerticalPadding,
        'ConversationAvatarTextGapDp':
            MessageAvatarLayout.conversationAvatarTextGap,
        'ConversationDividerExtraInsetDp':
            MessageAvatarLayout.conversationDividerExtraInset,
        'ConversationDividerStartDp':
            MessageAvatarLayout.conversationDividerStart,
        'UnreadBadgeOffsetXDp': MessageAvatarLayout.unreadBadgeOffsetX,
        'UnreadBadgeOffsetYDp': MessageAvatarLayout.unreadBadgeOffsetY,
        'UnreadBadgeSizeDp': MessageAvatarLayout.unreadBadgeSize,
        'UnreadBadgeLargeSizeDp': MessageAvatarLayout.unreadBadgeLargeSize,
        'OnlineIndicatorSizeDp': MessageAvatarLayout.onlineIndicatorSize,
        'OnlineIndicatorOffsetYDp': MessageAvatarLayout.onlineIndicatorOffsetY,
        'OnlineIndicatorPaddingDp': MessageAvatarLayout.onlineIndicatorPadding,
        'BubbleAvatarSizeDp': MessageAvatarLayout.bubbleAvatarSize,
        'BubbleAvatarCornerRadiusDp':
            MessageAvatarLayout.bubbleAvatarCornerRadius,
        'BubbleAvatarGapDp': MessageAvatarLayout.bubbleAvatarGap,
        'BubbleTopPaddingWithAvatarDp':
            MessageAvatarLayout.bubbleTopPaddingWithAvatar,
        'BubbleTopPaddingWithoutAvatarDp':
            MessageAvatarLayout.bubbleTopPaddingWithoutAvatar,
        'BubbleAvatarReservedWidthDp':
            MessageAvatarLayout.bubbleAvatarReservedWidth,
        'EmptyStateAvatarSizeDp': MessageAvatarLayout.emptyStateAvatarSize,
        'EmptyStateAvatarCornerRadiusDp':
            MessageAvatarLayout.emptyStateAvatarCornerRadius,
        'EmployeePickerAvatarSizeDp':
            MessageAvatarLayout.employeePickerAvatarSize,
        'EmployeePickerAvatarCornerRadiusDp':
            MessageAvatarLayout.employeePickerAvatarCornerRadius,
        'EmployeePickerRowHorizontalPaddingDp':
            MessageAvatarLayout.employeePickerRowHorizontalPadding,
        'EmployeePickerRowVerticalPaddingDp':
            MessageAvatarLayout.employeePickerRowVerticalPadding,
        'EmployeePickerAvatarTextGapDp':
            MessageAvatarLayout.employeePickerAvatarTextGap,
        'EmployeePickerDividerStartDp':
            MessageAvatarLayout.employeePickerDividerStart,
        'CustomerServiceBubbleAvatarSizeDp':
            MessageAvatarLayout.customerServiceBubbleAvatarSize,
        'CustomerServiceBubbleIconSizeDp':
            MessageAvatarLayout.customerServiceBubbleIconSize,
        'CustomerServiceBubbleAvatarGapDp':
            MessageAvatarLayout.customerServiceBubbleAvatarGap,
      },
      android,
      reason:
          'Flutter message avatar layout must mirror Android MessageAvatarLayout.kt.',
    );
  });
}

void _expectColorScheme(ColorScheme flutter, Map<String, Color> android) {
  expect(flutter.primary, android['primary']);
  expect(flutter.onPrimary, android['onPrimary']);
  expect(flutter.primaryContainer, android['primaryContainer']);
  expect(flutter.onPrimaryContainer, android['onPrimaryContainer']);
  expect(flutter.secondary, android['secondary']);
  expect(flutter.onSecondary, android['onSecondary']);
  expect(flutter.secondaryContainer, android['secondaryContainer']);
  expect(flutter.onSecondaryContainer, android['onSecondaryContainer']);
  expect(flutter.tertiary, android['tertiary']);
  expect(flutter.surface, android['surface']);
  expect(flutter.onSurface, android['onSurface']);
  expect(flutter.surfaceContainerHighest, android['surfaceVariant']);
  expect(flutter.onSurfaceVariant, android['onSurfaceVariant']);
  expect(flutter.outline, android['outline']);
  expect(flutter.outlineVariant, android['outlineVariant']);
  expect(flutter.error, android['error']);
  expect(flutter.onError, android['onError']);
  expect(flutter.errorContainer, android['errorContainer']);
  expect(flutter.onErrorContainer, android['onErrorContainer']);
  expect(flutter.surfaceTint, android['surfaceTint']);
}

void _expectTextTheme(
  TextTheme flutter,
  Map<String, _AndroidTextStyleSpec> android,
) {
  final styles = {
    'displayLarge': flutter.displayLarge,
    'displayMedium': flutter.displayMedium,
    'displaySmall': flutter.displaySmall,
    'headlineLarge': flutter.headlineLarge,
    'headlineMedium': flutter.headlineMedium,
    'headlineSmall': flutter.headlineSmall,
    'titleLarge': flutter.titleLarge,
    'titleMedium': flutter.titleMedium,
    'titleSmall': flutter.titleSmall,
    'bodyLarge': flutter.bodyLarge,
    'bodyMedium': flutter.bodyMedium,
    'bodySmall': flutter.bodySmall,
    'labelLarge': flutter.labelLarge,
    'labelMedium': flutter.labelMedium,
    'labelSmall': flutter.labelSmall,
  };

  expect(styles.keys.toSet(), android.keys.toSet());
  for (final entry in android.entries) {
    final flutterStyle = styles[entry.key]!;
    final androidStyle = entry.value;
    expect(flutterStyle.fontSize, androidStyle.fontSize);
    expect(flutterStyle.fontWeight, androidStyle.fontWeight);
    expect(
      flutterStyle.height! * flutterStyle.fontSize!,
      closeTo(androidStyle.lineHeight, 0.0001),
    );
    expect(flutterStyle.letterSpacing, 0);
  }
}

Map<String, _AndroidTextStyleSpec> _androidTypography() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Type.kt',
  ).readAsStringSync();
  final styles = <String, _AndroidTextStyleSpec>{};
  for (final match in RegExp(
    r'(\w+)\s*=\s*TextStyle\(fontSize\s*=\s*(\d+)\.sp,\s*fontWeight\s*=\s*FontWeight\.(\w+),\s*lineHeight\s*=\s*(\d+)\.sp\)',
  ).allMatches(source)) {
    styles[match.group(1)!] = _AndroidTextStyleSpec(
      fontSize: double.parse(match.group(2)!),
      fontWeight: _fontWeight(match.group(3)!),
      lineHeight: double.parse(match.group(4)!),
    );
  }
  return styles;
}

FontWeight _fontWeight(String androidWeight) {
  return switch (androidWeight) {
    'Bold' => FontWeight.w700,
    'SemiBold' => FontWeight.w600,
    'Medium' => FontWeight.w500,
    'Normal' => FontWeight.w400,
    _ => throw StateError('Unsupported Android FontWeight: $androidWeight'),
  };
}

class _AndroidTextStyleSpec {
  const _AndroidTextStyleSpec({
    required this.fontSize,
    required this.fontWeight,
    required this.lineHeight,
  });

  final double fontSize;
  final FontWeight fontWeight;
  final double lineHeight;
}

Map<String, double> _androidShapeTokens() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Shape.kt',
  ).readAsStringSync();
  final tokens = <String, double>{};

  final shapeBlock = RegExp(
    r'XcagiShapes\s*=\s*Shapes\((.*?)\n\)',
    dotAll: true,
  ).firstMatch(source)?.group(1);
  if (shapeBlock == null) throw StateError('Missing Android XcagiShapes');
  for (final match in RegExp(
    r'(\w+)\s*=\s*RoundedCornerShape\((\d+(?:\.\d+)?)\.dp\)',
  ).allMatches(shapeBlock)) {
    tokens['shape.${match.group(1)!}'] = double.parse(match.group(2)!);
  }

  for (final section in const ['Elevation', 'Spacing']) {
    final block = RegExp(
      r'object\s+' + section + r'\s*\{(.*?)\n\}',
      dotAll: true,
    ).firstMatch(source)?.group(1);
    if (block == null) throw StateError('Missing Android $section');
    for (final match in RegExp(
      r'val\s+(\w+)\s*=\s*(\d+(?:\.\d+)?)\.dp',
    ).allMatches(block)) {
      tokens['${section.toLowerCase()}.${match.group(1)!}'] =
          double.parse(match.group(2)!);
    }
  }
  return tokens;
}

Map<String, double> _androidMessageAvatarLayoutTokens() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/components/mobile/MessageAvatarLayout.kt',
  ).readAsStringSync();
  final tokens = <String, double>{};
  for (final match in RegExp(
    r'const val\s+(\w+)\s*=\s*([\s\S]*?)(?=\n\s*(?:const val|val)\s+\w+|\n\s*\})',
  ).allMatches(source)) {
    tokens[match.group(1)!] = _evaluateAndroidDpConst(
      match.group(2)!,
      tokens,
    );
  }
  return tokens;
}

double _evaluateAndroidDpConst(String expression, Map<String, double> tokens) {
  final normalized = expression
      .replaceAll(RegExp(r'//.*'), '')
      .replaceAll(RegExp(r'\s+'), '')
      .replaceAll('f', '');
  return normalized.split('+').fold(0, (total, part) {
    if (part.isEmpty) return total;
    return total + (tokens[part] ?? double.parse(part));
  });
}

class _AndroidThemeSource {
  const _AndroidThemeSource(this.source, this.constants);

  final String source;
  final Map<String, Color> constants;

  static _AndroidThemeSource read() {
    final source = File(
      '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/theme/Theme.kt',
    ).readAsStringSync();
    final constants = <String, Color>{};
    for (final match in RegExp(
      r'private val\s+(\w+)\s*=\s*Color\(0x([0-9A-Fa-f]{8})\)',
    ).allMatches(source)) {
      constants[match.group(1)!] = Color(
        int.parse(match.group(2)!, radix: 16),
      );
    }
    return _AndroidThemeSource(source, constants);
  }

  Color color(String name) {
    final color = constants[name];
    if (color == null) {
      throw StateError('Missing Android Theme.kt color constant: $name');
    }
    return color;
  }

  Map<String, Color> extraColors(String name) {
    return _parseAssignments(name);
  }

  Map<String, Color> colorScheme(String name) {
    return _parseAssignments(name);
  }

  Map<String, Color> _parseAssignments(String declarationName) {
    final block = RegExp(
      r'(?:private\s+)?val\s+' + declarationName + r'\s*=\s*\w+\((.*?)\n\)',
      dotAll: true,
    ).firstMatch(source)?.group(1);
    if (block == null) {
      throw StateError(
          'Missing Android Theme.kt declaration: $declarationName');
    }

    final assignments = <String, Color>{};
    for (final match in RegExp(
      r'(\w+)\s*=\s*(Color\.White|Color\(0x[0-9A-Fa-f]{8}\)|\w+)',
    ).allMatches(block)) {
      assignments[match.group(1)!] = _resolveColor(match.group(2)!);
    }
    return assignments;
  }

  Color _resolveColor(String expression) {
    if (expression == 'Color.White') return Colors.white;
    final inline = RegExp(r'Color\(0x([0-9A-Fa-f]{8})\)').firstMatch(
      expression,
    );
    if (inline != null) return Color(int.parse(inline.group(1)!, radix: 16));
    return color(expression);
  }
}
