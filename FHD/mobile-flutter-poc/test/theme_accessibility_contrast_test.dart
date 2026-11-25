import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

double _contrast(Color foreground, Color background) {
  final a = foreground.computeLuminance();
  final b = background.computeLuminance();
  return (a > b ? a + 0.05 : b + 0.05) /
      (a > b ? b + 0.05 : a + 0.05);
}

void main() {
  test('Material action roles meet WCAG 2.2 AA text contrast', () {
    for (final theme in [AppTheme.light(), AppTheme.dark()]) {
      final scheme = theme.colorScheme;
      for (final pair in <(Color, Color, String)>[
        (scheme.onPrimary, scheme.primary, 'primary'),
        (scheme.onSecondary, scheme.secondary, 'secondary'),
        (scheme.onError, scheme.error, 'error'),
        (scheme.onSurface, scheme.surface, 'surface'),
      ]) {
        expect(_contrast(pair.$1, pair.$2), greaterThanOrEqualTo(4.5),
            reason: '${theme.brightness}: ${pair.$3}');
      }
    }
  });

  test('chat bubble and tertiary text roles meet 4.5:1', () {
    for (final palette in [XcagiThemeColors.light, XcagiThemeColors.dark]) {
      expect(_contrast(palette.chatUserBubbleText, palette.chatUserBubble),
          greaterThanOrEqualTo(4.5));
      expect(_contrast(palette.textTertiary, palette.surfaceHigh),
          greaterThanOrEqualTo(4.5));
    }
  });
}
