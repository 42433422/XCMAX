import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import 'package:xcagi_flutter_poc/src/theme/message_avatar_layout.dart';

int _argb(String value) => int.parse('FF${value.substring(1)}', radix: 16);

void main() {
  final tokens =
      jsonDecode(File('../config/mobile_design_tokens.json').readAsStringSync())
          as Map<String, dynamic>;

  test('Flutter colors match the mobile token SSOT', () {
    final colors = tokens['colors'] as Map<String, dynamic>;
    final brand = colors['brand'] as Map<String, dynamic>;
    final status = colors['status'] as Map<String, dynamic>;

    expect(AppTheme.brand.toARGB32(), _argb(brand['primary'] as String));
    expect(
      AppTheme.brandContainer.toARGB32(),
      _argb(brand['primary_container'] as String),
    );
    expect(
      AppTheme.brandGradientEnd.toARGB32(),
      _argb(brand['gradient_end'] as String),
    );
    expect(AppTheme.success.toARGB32(), _argb(status['success'] as String));
    expect(AppTheme.warning.toARGB32(), _argb(status['warning'] as String));
    expect(AppTheme.danger.toARGB32(), _argb(status['danger'] as String));
  });

  test('Flutter spacing and radius match the mobile token SSOT', () {
    expect(tokens['spacing'], {
      'xs': XcagiSpacing.xs,
      'sm': XcagiSpacing.sm,
      'md': XcagiSpacing.md,
      'lg': XcagiSpacing.lg,
      'xl': XcagiSpacing.xl,
      'xxl': XcagiSpacing.xxl,
      'xxxl': XcagiSpacing.xxxl,
    });
    expect(tokens['radius'], {
      'extra_small': XcagiShapeTokens.extraSmall,
      'small': XcagiShapeTokens.small,
      'medium': XcagiShapeTokens.medium,
      'large': XcagiShapeTokens.large,
      'extra_large': XcagiShapeTokens.extraLarge,
    });
  });

  test('message avatar layout keeps stable Flutter geometry', () {
    expect(MessageAvatarLayout.conversationAvatarSize, 52.0);
    expect(MessageAvatarLayout.bubbleAvatarSize, 40.0);
    expect(MessageAvatarLayout.employeePickerAvatarSize, 44.0);
  });
}
