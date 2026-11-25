import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import 'package:xcagi_flutter_poc/src/theme/design_tokens.generated.dart';
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

  test('typography, motion and dark overrides use the shared contract', () {
    final body = (tokens['typography'] as Map)['body_medium'] as Map;
    final mobile = (tokens['platform_overrides'] as Map)['mobile'] as Map;
    final dark = mobile['colors'] as Map;
    expect(AppTheme.light().textTheme.bodyMedium!.fontSize, body['size']);
    expect(AppTheme.light().textTheme.bodyMedium!.height, body['line_height'] / body['size']);
    expect(AppTheme.dark().scaffoldBackgroundColor.toARGB32(), _argb(dark['dark_page'] as String));
    expect(XcagiThemeColors.dark.surface.toARGB32(), _argb(dark['dark_surface'] as String));
    expect(DesignTokens.motionStandardMs, (tokens['motion'] as Map)['standard_ms']);
    expect(DesignTokens.motionReducedMs, 0);
    expect(AppTheme.light().focusColor.a, closeTo(DesignTokens.focusRingAlpha, 0.01));
    expect(AppTheme.dark().focusColor.a, closeTo(DesignTokens.focusRingAlpha, 0.01));
  });

  test('Material component geometry is identical in light and dark themes', () {
    for (final theme in [AppTheme.light(), AppTheme.dark()]) {
      final style = theme.filledButtonTheme.style!;
      expect(style.minimumSize!.resolve(<WidgetState>{})!.height,
          DesignTokens.mobileGeometryButtonMinHeight);
      final shape = style.shape!.resolve(<WidgetState>{}) as RoundedRectangleBorder;
      expect(shape.borderRadius,
          BorderRadius.circular(DesignTokens.mobileGeometryButtonRadius));
      expect(style.textStyle!.resolve(<WidgetState>{})!.fontSize,
          DesignTokens.componentsButtonLabelSize);
      expect(style.textStyle!.resolve(<WidgetState>{})!.fontWeight,
          DesignTokens.componentsButtonWeight);
      expect(theme.cardTheme.elevation, DesignTokens.componentsCardElevation);
      expect((theme.cardTheme.shape! as RoundedRectangleBorder).borderRadius,
          BorderRadius.circular(DesignTokens.componentsCardRadius));
      expect(theme.inputDecorationTheme.contentPadding, const EdgeInsets.symmetric(
        horizontal: DesignTokens.mobileGeometryInputPaddingX,
        vertical: DesignTokens.componentsInputPaddingY,
      ));
    }
    expect(AppTheme.light().cardTheme.color, XcagiThemeColors.light.surface);
    expect(AppTheme.dark().cardTheme.color, XcagiThemeColors.dark.surface);
  });

  test('Material overlays and slider share tokens in both themes', () {
    for (final theme in [AppTheme.light(), AppTheme.dark()]) {
      final surface = theme.colorScheme.surface;
      final border = theme.brightness == Brightness.light
          ? AppTheme.divider
          : DesignTokens.mobileColorsDarkDivider;
      expect(theme.dialogTheme.backgroundColor, surface);
      expect(theme.dialogTheme.elevation, DesignTokens.elevationLevel2);
      expect((theme.dialogTheme.shape! as RoundedRectangleBorder).borderRadius,
          BorderRadius.circular(DesignTokens.radiusLarge));
      expect(theme.bottomSheetTheme.modalBackgroundColor, surface);
      expect(theme.bottomSheetTheme.showDragHandle, isTrue);
      expect(theme.bottomSheetTheme.dragHandleColor, border);
      expect(theme.bottomSheetTheme.modalElevation, DesignTokens.elevationLevel3);
      expect((theme.bottomSheetTheme.shape! as RoundedRectangleBorder).borderRadius,
          const BorderRadius.vertical(top: Radius.circular(DesignTokens.radiusLarge)));
      expect(theme.popupMenuTheme.color, surface);
      expect(theme.popupMenuTheme.elevation, DesignTokens.elevationLevel2);
      expect(theme.sliderTheme.trackHeight, DesignTokens.spacingXs);
      expect(theme.sliderTheme.inactiveTrackColor, border);
      expect(theme.sliderTheme.activeTrackColor, theme.colorScheme.primary);
    }
  });

  testWidgets('system reduced motion disables optional micro-interactions', (tester) async {
    Duration? duration;
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: Builder(builder: (context) {
        duration = AppTheme.motionDuration(context);
        return const SizedBox();
      }),
    ));
    expect(duration, const Duration(milliseconds: DesignTokens.motionReducedMs));
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(accessibleNavigation: true),
      child: Builder(builder: (context) {
        duration = AppTheme.motionDuration(context);
        return const SizedBox();
      }),
    ));
    expect(duration, const Duration(milliseconds: DesignTokens.motionReducedMs));
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(),
      child: Builder(builder: (context) {
        duration = AppTheme.motionDuration(context);
        return const SizedBox();
      }),
    ));
    expect(duration, const Duration(milliseconds: DesignTokens.motionStandardMs));
  });

  test('message avatar layout keeps stable Flutter geometry', () {
    expect(MessageAvatarLayout.conversationAvatarSize, 52.0);
    expect(MessageAvatarLayout.bubbleAvatarSize, 40.0);
    expect(MessageAvatarLayout.employeePickerAvatarSize, 44.0);
  });
}
