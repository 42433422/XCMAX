import 'package:flutter/material.dart';

import 'design_tokens.generated.dart';

class AppTheme {
  static const brand = DesignTokens.semanticLightPrimary;
  static const brandContainer = DesignTokens.colorsBrandPrimaryContainer;
  static const brandGradientEnd = DesignTokens.colorsBrandGradientEnd;
  static const danger = DesignTokens.colorsStatusDanger;
  static const success = DesignTokens.colorsStatusSuccess;
  static const warning = DesignTokens.colorsStatusWarning;
  static const weChatOnline = DesignTokens.colorsStatusSuccess;
  static const momentAccent = DesignTokens.colorsMomentAccentLight;
  static const momentChipBg = DesignTokens.colorsMomentChipBgLight;
  static const replyBoxBg = DesignTokens.colorsMomentReplyBgLight;
  static const page = DesignTokens.semanticLightPage;
  static const surface = DesignTokens.semanticLightSurface;
  static const surfaceHigh = DesignTokens.semanticLightSurfaceHigh;
  static const divider = DesignTokens.semanticLightBorder;
  static const textPrimary = DesignTokens.semanticLightTextPrimary;
  static const textSecondary = DesignTokens.semanticLightTextSecondary;
  static const textStrongSecondary = DesignTokens.colorsNeutralLightN600;
  static const textTertiary = DesignTokens.colorsNeutralLightN500;

  static Duration motionDuration(BuildContext context,
          {int milliseconds = DesignTokens.motionStandardMs}) =>
      MediaQuery.disableAnimationsOf(context) ||
              MediaQuery.accessibleNavigationOf(context)
          ? const Duration(milliseconds: DesignTokens.motionReducedMs)
          : Duration(milliseconds: milliseconds);

  static XcagiThemeColors colors(BuildContext context) {
    final extension = Theme.of(context).extension<XcagiThemeColors>();
    if (extension != null) return extension;
    return Theme.of(context).brightness == Brightness.dark
        ? XcagiThemeColors.dark
        : XcagiThemeColors.light;
  }

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: brand,
      brightness: Brightness.light,
    ).copyWith(
      primary: brand,
      onPrimary: surface,
      primaryContainer: brandContainer,
      onPrimaryContainer: DesignTokens.mobileColorsLightOnBrandContainer,
      secondary: success,
      onSecondary: DesignTokens.colorsNeutralLightN900,
      secondaryContainer: DesignTokens.colorsStatusSuccessContainer,
      onSecondaryContainer: DesignTokens.mobileColorsLightOnSuccessContainer,
      tertiary: brand,
      surfaceTint: brand,
      surface: surface,
      onSurface: textPrimary,
      surfaceContainerHighest: surfaceHigh,
      onSurfaceVariant: textSecondary,
      outline: textSecondary,
      outlineVariant: divider,
      error: danger,
      onError: DesignTokens.colorsNeutralLightN900,
      errorContainer: DesignTokens.mobileColorsLightErrorContainer,
      onErrorContainer: DesignTokens.mobileColorsLightOnErrorContainer,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: scheme,
      focusColor: brand.withValues(alpha: DesignTokens.focusRingAlpha),
      extensions: const [XcagiThemeColors.light],
      scaffoldBackgroundColor: page,
      appBarTheme: const AppBarTheme(
        backgroundColor: surface,
        foregroundColor: textPrimary,
        elevation: DesignTokens.elevationNone,
        centerTitle: false,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: brandContainer,
        height: DesignTokens.mobileGeometryNavigationHeight,
        iconTheme: WidgetStateProperty.resolveWith(
          (states) => IconThemeData(
            size: DesignTokens.mobileGeometryNavigationIcon,
            color:
                states.contains(WidgetState.selected) ? brand : textSecondary,
          ),
        ),
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: DesignTokens.mobileGeometryNavigationLabel,
            fontWeight: states.contains(WidgetState.selected)
                ? DesignTokens.typographyDisplayLargeWeight
                : DesignTokens.typographyLabelLargeWeight,
            color:
                states.contains(WidgetState.selected) ? brand : textSecondary,
          ),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: divider,
        thickness: DesignTokens.mobileGeometryDividerThickness,
        space: 0,
      ),
      cardTheme: _cardTheme(surface),
      dialogTheme: _dialogTheme(surface),
      bottomSheetTheme: _bottomSheetTheme(surface, divider),
      popupMenuTheme: _popupMenuTheme(surface),
      sliderTheme: _sliderTheme(brand, divider),
      filledButtonTheme: _filledButtonTheme(),
      inputDecorationTheme: _inputDecorationTheme,
      textTheme: _typography(textPrimary),
    );
  }

  static ThemeData dark() {
    const darkBg = DesignTokens.mobileColorsDarkPage;
    const darkSurface = DesignTokens.mobileColorsDarkSurface;
    const darkSurfaceVariant = DesignTokens.mobileColorsDarkSurfaceHigh;
    const darkBorder = DesignTokens.mobileColorsDarkDivider;
    const darkTextPrimary = DesignTokens.mobileColorsDarkTextPrimary;
    const darkTextSecondary = DesignTokens.mobileColorsDarkTextSecondary;
    const darkBrand = DesignTokens.colorsBrandPrimaryLight;

    final scheme = ColorScheme.fromSeed(
      seedColor: darkBrand,
      brightness: Brightness.dark,
    ).copyWith(
      primary: darkBrand,
      onPrimary: DesignTokens.colorsNeutralLightN900,
      primaryContainer: DesignTokens.mobileColorsDarkBrandContainer,
      onPrimaryContainer: DesignTokens.mobileColorsDarkOnBrandContainer,
      secondary: success,
      onSecondary: DesignTokens.colorsNeutralLightN900,
      secondaryContainer: DesignTokens.mobileColorsDarkSuccessContainer,
      onSecondaryContainer: DesignTokens.colorsStatusSuccessLight,
      tertiary: darkBrand,
      surfaceTint: darkBrand,
      surface: darkSurface,
      onSurface: darkTextPrimary,
      surfaceContainerHighest: darkSurfaceVariant,
      onSurfaceVariant: darkTextSecondary,
      outline: darkBorder,
      outlineVariant: darkSurfaceVariant,
      error: danger,
      onError: DesignTokens.colorsNeutralLightN900,
      errorContainer: DesignTokens.mobileColorsDarkErrorContainer,
      onErrorContainer: DesignTokens.mobileColorsDarkOnErrorContainer,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      focusColor: darkBrand.withValues(alpha: DesignTokens.focusRingAlpha),
      extensions: const [XcagiThemeColors.dark],
      scaffoldBackgroundColor: darkBg,
      appBarTheme: const AppBarTheme(
        backgroundColor: darkSurface,
        foregroundColor: darkTextPrimary,
        elevation: DesignTokens.elevationNone,
        centerTitle: false,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: darkSurface,
        indicatorColor: darkSurfaceVariant,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: DesignTokens.mobileGeometryNavigationLabel,
            fontWeight: states.contains(WidgetState.selected)
                ? DesignTokens.typographyDisplayLargeWeight
                : DesignTokens.typographyLabelLargeWeight,
            color: states.contains(WidgetState.selected)
                ? darkBrand
                : darkTextSecondary,
          ),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: darkBorder,
        thickness: DesignTokens.mobileGeometryDividerThickness,
        space: 0,
      ),
      cardTheme: _cardTheme(darkSurface),
      dialogTheme: _dialogTheme(darkSurface),
      bottomSheetTheme: _bottomSheetTheme(darkSurface, darkBorder),
      popupMenuTheme: _popupMenuTheme(darkSurface),
      sliderTheme: _sliderTheme(darkBrand, darkBorder),
      filledButtonTheme: _filledButtonTheme(),
      inputDecorationTheme: _inputDecorationTheme,
      textTheme: _typography(darkTextPrimary),
    );
  }

  // Use native Material overlays and their built-in focus, modal barrier, layer
  // and keyboard behavior. Geometry and motion values come from DesignTokens.
  static DialogThemeData _dialogTheme(Color color) => DialogThemeData(
        backgroundColor: color,
        surfaceTintColor: Colors.transparent,
        elevation: DesignTokens.elevationLevel2,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radiusLarge),
        ),
      );

  static BottomSheetThemeData _bottomSheetTheme(Color color, Color divider) =>
      BottomSheetThemeData(
        backgroundColor: color,
        modalBackgroundColor: color,
        surfaceTintColor: Colors.transparent,
        elevation: DesignTokens.elevationLevel2,
        modalElevation: DesignTokens.elevationLevel3,
        showDragHandle: true,
        dragHandleColor: divider,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(
            top: Radius.circular(DesignTokens.radiusLarge),
          ),
        ),
      );

  static PopupMenuThemeData _popupMenuTheme(Color color) =>
      PopupMenuThemeData(
        color: color,
        surfaceTintColor: Colors.transparent,
        elevation: DesignTokens.elevationLevel2,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
        ),
      );

  static SliderThemeData _sliderTheme(Color primary, Color divider) =>
      SliderThemeData(
        trackHeight: DesignTokens.spacingXs,
        activeTrackColor: primary,
        inactiveTrackColor: divider,
        thumbColor: primary,
      );

  // Native Material components keep the same geometry in both themes.
  static CardThemeData _cardTheme(Color color) => CardThemeData(
        color: color,
        elevation: DesignTokens.componentsCardElevation,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.componentsCardRadius),
        ),
      );

  static FilledButtonThemeData _filledButtonTheme() => FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, DesignTokens.mobileGeometryButtonMinHeight),
          elevation: DesignTokens.elevationNone,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(DesignTokens.mobileGeometryButtonRadius),
          ),
          textStyle: const TextStyle(
            fontSize: DesignTokens.componentsButtonLabelSize,
            fontWeight: DesignTokens.componentsButtonWeight,
          ),
        ),
      );

  static const _inputDecorationTheme = InputDecorationTheme(
    border: InputBorder.none,
    filled: false,
    contentPadding: EdgeInsets.symmetric(
      horizontal: DesignTokens.mobileGeometryInputPaddingX,
      vertical: DesignTokens.componentsInputPaddingY,
    ),
  );

  static TextTheme _typography(Color color) {
    TextStyle style(double fontSize, FontWeight fontWeight, double lineHeight) {
      return TextStyle(
        fontSize: fontSize,
        fontWeight: fontWeight,
        color: color,
        height: lineHeight / fontSize,
        letterSpacing: 0,
      );
    }

    return TextTheme(
      displayLarge: style(DesignTokens.typographyDisplayLargeSize, DesignTokens.typographyDisplayLargeWeight, DesignTokens.typographyDisplayLargeLineHeight),
      displayMedium: style(DesignTokens.typographyDisplayMediumSize, DesignTokens.typographyDisplayMediumWeight, DesignTokens.typographyDisplayMediumLineHeight),
      displaySmall: style(DesignTokens.typographyDisplaySmallSize, DesignTokens.typographyDisplaySmallWeight, DesignTokens.typographyDisplaySmallLineHeight),
      headlineLarge: style(DesignTokens.typographyHeadlineLargeSize, DesignTokens.typographyHeadlineLargeWeight, DesignTokens.typographyHeadlineLargeLineHeight),
      headlineMedium: style(DesignTokens.typographyHeadlineMediumSize, DesignTokens.typographyHeadlineMediumWeight, DesignTokens.typographyHeadlineMediumLineHeight),
      headlineSmall: style(DesignTokens.typographyHeadlineSmallSize, DesignTokens.typographyHeadlineSmallWeight, DesignTokens.typographyHeadlineSmallLineHeight),
      titleLarge: style(DesignTokens.typographyTitleLargeSize, DesignTokens.typographyTitleLargeWeight, DesignTokens.typographyTitleLargeLineHeight),
      titleMedium: style(DesignTokens.typographyTitleMediumSize, DesignTokens.typographyTitleMediumWeight, DesignTokens.typographyTitleMediumLineHeight),
      titleSmall: style(DesignTokens.typographyTitleSmallSize, DesignTokens.typographyTitleSmallWeight, DesignTokens.typographyTitleSmallLineHeight),
      bodyLarge: style(DesignTokens.typographyBodyLargeSize, DesignTokens.typographyBodyLargeWeight, DesignTokens.typographyBodyLargeLineHeight),
      bodyMedium: style(DesignTokens.typographyBodyMediumSize, DesignTokens.typographyBodyMediumWeight, DesignTokens.typographyBodyMediumLineHeight),
      bodySmall: style(DesignTokens.typographyBodySmallSize, DesignTokens.typographyBodySmallWeight, DesignTokens.typographyBodySmallLineHeight),
      labelLarge: style(DesignTokens.typographyLabelLargeSize, DesignTokens.typographyLabelLargeWeight, DesignTokens.typographyLabelLargeLineHeight),
      labelMedium: style(DesignTokens.typographyLabelMediumSize, DesignTokens.typographyLabelMediumWeight, DesignTokens.typographyLabelMediumLineHeight),
      labelSmall: style(DesignTokens.typographyLabelSmallSize, DesignTokens.typographyLabelSmallWeight, DesignTokens.typographyLabelSmallLineHeight),
    );
  }
}

class XcagiShapeTokens {
  const XcagiShapeTokens._();

  static const extraSmall = DesignTokens.radiusExtraSmall;
  static const small = DesignTokens.radiusSmall;
  static const medium = DesignTokens.radiusMedium;
  static const large = DesignTokens.radiusLarge;
  static const extraLarge = DesignTokens.radiusExtraLarge;
}

class XcagiElevation {
  const XcagiElevation._();

  static const none = DesignTokens.elevationNone;
  static const level1 = DesignTokens.elevationLevel1;
  static const level2 = DesignTokens.elevationLevel2;
  static const level3 = DesignTokens.elevationLevel3;
}

class XcagiSpacing {
  const XcagiSpacing._();

  static const xs = DesignTokens.spacingXs;
  static const sm = DesignTokens.spacingSm;
  static const md = DesignTokens.spacingMd;
  static const lg = DesignTokens.spacingLg;
  static const xl = DesignTokens.spacingXl;
  static const xxl = DesignTokens.spacingXxl;
  static const xxxl = DesignTokens.spacingXxxl;
}

class XcagiThemeColors extends ThemeExtension<XcagiThemeColors> {
  const XcagiThemeColors({
    required this.brand,
    required this.brandContainer,
    required this.brandGradientEnd,
    required this.danger,
    required this.success,
    required this.warning,
    required this.weChatGreen,
    required this.weChatOnline,
    required this.weChatInputBg,
    required this.weChatDivider,
    required this.chatUserBubble,
    required this.chatUserBubbleText,
    required this.momentAccent,
    required this.momentChipBg,
    required this.replyBoxBg,
    required this.page,
    required this.surface,
    required this.surfaceHigh,
    required this.divider,
    required this.textPrimary,
    required this.textSecondary,
    required this.textStrongSecondary,
    required this.textTertiary,
  });

  static const light = XcagiThemeColors(
    brand: AppTheme.brand,
    brandContainer: AppTheme.brandContainer,
    brandGradientEnd: AppTheme.brandGradientEnd,
    danger: AppTheme.danger,
    success: AppTheme.success,
    warning: AppTheme.warning,
    weChatGreen: DesignTokens.mobileColorsWechatGreenLight,
    weChatOnline: AppTheme.weChatOnline,
    weChatInputBg: AppTheme.page,
    weChatDivider: AppTheme.divider,
    chatUserBubble: AppTheme.brand,
    chatUserBubbleText: AppTheme.surface,
    momentAccent: AppTheme.momentAccent,
    momentChipBg: AppTheme.momentChipBg,
    replyBoxBg: AppTheme.replyBoxBg,
    page: AppTheme.page,
    surface: AppTheme.surface,
    surfaceHigh: AppTheme.surfaceHigh,
    divider: AppTheme.divider,
    textPrimary: AppTheme.textPrimary,
    textSecondary: AppTheme.textSecondary,
    textStrongSecondary: AppTheme.textStrongSecondary,
    textTertiary: AppTheme.textTertiary,
  );

  static const dark = XcagiThemeColors(
    brand: DesignTokens.colorsBrandPrimaryLight,
    brandContainer: DesignTokens.mobileColorsDarkBrandContainer,
    brandGradientEnd: DesignTokens.mobileColorsDarkBrandGradientEnd,
    danger: AppTheme.danger,
    success: DesignTokens.colorsStatusSuccessLight,
    warning: AppTheme.warning,
    weChatGreen: DesignTokens.mobileColorsWechatGreenDark,
    weChatOnline: DesignTokens.colorsStatusSuccessLight,
    weChatInputBg: DesignTokens.colorsNeutralDarkSurfaceVariant,
    weChatDivider: DesignTokens.colorsNeutralDarkBorder,
    chatUserBubble: DesignTokens.colorsBrandPrimaryDark,
    chatUserBubbleText: DesignTokens.colorsChatUserTextDark,
    momentAccent: DesignTokens.colorsMomentAccentDark,
    momentChipBg: DesignTokens.colorsMomentChipBgDark,
    replyBoxBg: DesignTokens.colorsMomentReplyBgDark,
    page: DesignTokens.mobileColorsDarkPage,
    surface: DesignTokens.mobileColorsDarkSurface,
    surfaceHigh: DesignTokens.mobileColorsDarkSurfaceHigh,
    divider: DesignTokens.mobileColorsDarkDivider,
    textPrimary: DesignTokens.mobileColorsDarkTextPrimary,
    textSecondary: DesignTokens.mobileColorsDarkTextSecondary,
    textStrongSecondary: DesignTokens.mobileColorsDarkTextStrongSecondary,
    textTertiary: DesignTokens.mobileColorsDarkTextTertiary,
  );

  final Color brand;
  final Color brandContainer;
  final Color brandGradientEnd;
  final Color danger;
  final Color success;
  final Color warning;
  final Color weChatGreen;
  final Color weChatOnline;
  final Color weChatInputBg;
  final Color weChatDivider;
  final Color chatUserBubble;
  final Color chatUserBubbleText;
  final Color momentAccent;
  final Color momentChipBg;
  final Color replyBoxBg;
  final Color page;
  final Color surface;
  final Color surfaceHigh;
  final Color divider;
  final Color textPrimary;
  final Color textSecondary;
  final Color textStrongSecondary;
  final Color textTertiary;

  @override
  XcagiThemeColors copyWith({
    Color? brand,
    Color? brandContainer,
    Color? brandGradientEnd,
    Color? danger,
    Color? success,
    Color? warning,
    Color? weChatGreen,
    Color? weChatOnline,
    Color? weChatInputBg,
    Color? weChatDivider,
    Color? chatUserBubble,
    Color? chatUserBubbleText,
    Color? momentAccent,
    Color? momentChipBg,
    Color? replyBoxBg,
    Color? page,
    Color? surface,
    Color? surfaceHigh,
    Color? divider,
    Color? textPrimary,
    Color? textSecondary,
    Color? textStrongSecondary,
    Color? textTertiary,
  }) {
    return XcagiThemeColors(
      brand: brand ?? this.brand,
      brandContainer: brandContainer ?? this.brandContainer,
      brandGradientEnd: brandGradientEnd ?? this.brandGradientEnd,
      danger: danger ?? this.danger,
      success: success ?? this.success,
      warning: warning ?? this.warning,
      weChatGreen: weChatGreen ?? this.weChatGreen,
      weChatOnline: weChatOnline ?? this.weChatOnline,
      weChatInputBg: weChatInputBg ?? this.weChatInputBg,
      weChatDivider: weChatDivider ?? this.weChatDivider,
      chatUserBubble: chatUserBubble ?? this.chatUserBubble,
      chatUserBubbleText: chatUserBubbleText ?? this.chatUserBubbleText,
      momentAccent: momentAccent ?? this.momentAccent,
      momentChipBg: momentChipBg ?? this.momentChipBg,
      replyBoxBg: replyBoxBg ?? this.replyBoxBg,
      page: page ?? this.page,
      surface: surface ?? this.surface,
      surfaceHigh: surfaceHigh ?? this.surfaceHigh,
      divider: divider ?? this.divider,
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textStrongSecondary: textStrongSecondary ?? this.textStrongSecondary,
      textTertiary: textTertiary ?? this.textTertiary,
    );
  }

  @override
  XcagiThemeColors lerp(ThemeExtension<XcagiThemeColors>? other, double t) {
    if (other is! XcagiThemeColors) return this;
    return XcagiThemeColors(
      brand: Color.lerp(brand, other.brand, t)!,
      brandContainer: Color.lerp(brandContainer, other.brandContainer, t)!,
      brandGradientEnd: Color.lerp(
        brandGradientEnd,
        other.brandGradientEnd,
        t,
      )!,
      danger: Color.lerp(danger, other.danger, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      weChatGreen: Color.lerp(weChatGreen, other.weChatGreen, t)!,
      weChatOnline: Color.lerp(weChatOnline, other.weChatOnline, t)!,
      weChatInputBg: Color.lerp(weChatInputBg, other.weChatInputBg, t)!,
      weChatDivider: Color.lerp(weChatDivider, other.weChatDivider, t)!,
      chatUserBubble: Color.lerp(chatUserBubble, other.chatUserBubble, t)!,
      chatUserBubbleText: Color.lerp(
        chatUserBubbleText,
        other.chatUserBubbleText,
        t,
      )!,
      momentAccent: Color.lerp(momentAccent, other.momentAccent, t)!,
      momentChipBg: Color.lerp(momentChipBg, other.momentChipBg, t)!,
      replyBoxBg: Color.lerp(replyBoxBg, other.replyBoxBg, t)!,
      page: Color.lerp(page, other.page, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceHigh: Color.lerp(surfaceHigh, other.surfaceHigh, t)!,
      divider: Color.lerp(divider, other.divider, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textStrongSecondary: Color.lerp(
        textStrongSecondary,
        other.textStrongSecondary,
        t,
      )!,
      textTertiary: Color.lerp(textTertiary, other.textTertiary, t)!,
    );
  }
}
