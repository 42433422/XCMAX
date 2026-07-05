import 'package:flutter/material.dart';

class AppTheme {
  static const brand = Color(0xFF6366F1);
  static const brandContainer = Color(0xFFEAEBFE);
  static const brandGradientEnd = Color(0xFF7C3AED);
  static const danger = Color(0xFFEF4444);
  static const success = Color(0xFF10B981);
  static const warning = Color(0xFFF59E0B);
  static const weChatOnline = Color(0xFF10B981);
  static const momentAccent = Color(0xFF5145CD);
  static const momentChipBg = Color(0xFFECEDFE);
  static const replyBoxBg = Color(0xFFF4F5F7);
  static const page = Color(0xFFF5F6F7);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceHigh = Color(0xFFE8E9EB);
  static const divider = Color(0xFFDEE0E3);
  static const textPrimary = Color(0xFF1F2329);
  static const textSecondary = Color(0xFF646A73);
  static const textStrongSecondary = Color(0xFF494E56);
  static const textTertiary = Color(0xFF8F959E);

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
      onPrimaryContainer: const Color(0xFF312E81),
      secondary: success,
      onSecondary: surface,
      secondaryContainer: const Color(0xFFE7FAF3),
      onSecondaryContainer: const Color(0xFF064E3B),
      tertiary: brand,
      surfaceTint: brand,
      surface: surface,
      onSurface: textPrimary,
      surfaceContainerHighest: surfaceHigh,
      onSurfaceVariant: textSecondary,
      outline: textSecondary,
      outlineVariant: divider,
      error: danger,
      onError: surface,
      errorContainer: const Color(0xFFFFECEC),
      onErrorContainer: const Color(0xFF6B1A1A),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: scheme,
      extensions: const [XcagiThemeColors.light],
      scaffoldBackgroundColor: page,
      appBarTheme: const AppBarTheme(
        backgroundColor: surface,
        foregroundColor: textPrimary,
        elevation: 0,
        centerTitle: false,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        indicatorColor: page,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: 11,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color:
                states.contains(WidgetState.selected) ? brand : textSecondary,
          ),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: divider,
        thickness: 0.6,
        space: 0,
      ),
      textTheme: _typography(textPrimary),
    );
  }

  static ThemeData dark() {
    const darkBg = Color(0xFF1A1A1A);
    const darkSurface = Color(0xFF242424);
    const darkSurfaceVariant = Color(0xFF2E2E2E);
    const darkBorder = Color(0xFF383838);
    const darkTextPrimary = Color(0xFFE5E5E5);
    const darkTextSecondary = Color(0xFF888888);
    const darkBrand = Color(0xFF818CF8);

    final scheme = ColorScheme.fromSeed(
      seedColor: darkBrand,
      brightness: Brightness.dark,
    ).copyWith(
      primary: darkBrand,
      onPrimary: Colors.white,
      primaryContainer: const Color(0xFF1A3A80),
      onPrimaryContainer: const Color(0xFFB8CCFF),
      secondary: success,
      onSecondary: Colors.white,
      secondaryContainer: const Color(0xFF005B3F),
      onSecondaryContainer: const Color(0xFF34D399),
      tertiary: darkBrand,
      surfaceTint: darkBrand,
      surface: darkSurface,
      onSurface: darkTextPrimary,
      surfaceContainerHighest: darkSurfaceVariant,
      onSurfaceVariant: darkTextSecondary,
      outline: darkBorder,
      outlineVariant: darkSurfaceVariant,
      error: danger,
      onError: Colors.white,
      errorContainer: const Color(0xFF5C1A1A),
      onErrorContainer: const Color(0xFFFFB3B3),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      extensions: const [XcagiThemeColors.dark],
      scaffoldBackgroundColor: darkBg,
      appBarTheme: const AppBarTheme(
        backgroundColor: darkSurface,
        foregroundColor: darkTextPrimary,
        elevation: 0,
        centerTitle: false,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: darkSurface,
        indicatorColor: darkSurfaceVariant,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: 11,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color: states.contains(WidgetState.selected)
                ? darkBrand
                : darkTextSecondary,
          ),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: darkBorder,
        thickness: 0.6,
        space: 0,
      ),
      textTheme: _typography(darkTextPrimary),
    );
  }

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
      displayLarge: style(28, FontWeight.w700, 36),
      displayMedium: style(24, FontWeight.w700, 32),
      displaySmall: style(20, FontWeight.w600, 28),
      headlineLarge: style(24, FontWeight.w700, 32),
      headlineMedium: style(20, FontWeight.w600, 28),
      headlineSmall: style(18, FontWeight.w600, 26),
      titleLarge: style(18, FontWeight.w600, 24),
      titleMedium: style(17, FontWeight.w500, 22),
      titleSmall: style(15, FontWeight.w500, 20),
      bodyLarge: style(16, FontWeight.w400, 22),
      bodyMedium: style(15, FontWeight.w400, 21),
      bodySmall: style(14, FontWeight.w400, 19),
      labelLarge: style(14, FontWeight.w500, 18),
      labelMedium: style(13, FontWeight.w500, 17),
      labelSmall: style(11, FontWeight.w500, 14),
    );
  }
}

class XcagiShapeTokens {
  const XcagiShapeTokens._();

  static const extraSmall = 4.0;
  static const small = 8.0;
  static const medium = 12.0;
  static const large = 16.0;
  static const extraLarge = 20.0;
}

class XcagiElevation {
  const XcagiElevation._();

  static const none = 0.0;
  static const level1 = 1.0;
  static const level2 = 3.0;
  static const level3 = 8.0;
}

class XcagiSpacing {
  const XcagiSpacing._();

  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 20.0;
  static const xxl = 24.0;
  static const xxxl = 32.0;
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
    weChatGreen: Color(0xFF95EC69),
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
    brand: Color(0xFF818CF8),
    brandContainer: Color(0xFF1A3A80),
    brandGradientEnd: Color(0xFF3F6FD8),
    danger: AppTheme.danger,
    success: Color(0xFF34D399),
    warning: AppTheme.warning,
    weChatGreen: Color(0xFF6FAA4A),
    weChatOnline: Color(0xFF34D399),
    weChatInputBg: Color(0xFF2E2E2E),
    weChatDivider: Color(0xFF383838),
    chatUserBubble: Color(0xFF4F46E5),
    chatUserBubbleText: Color(0xFFEEF0FF),
    momentAccent: Color(0xFFA5B0FF),
    momentChipBg: Color(0xFF2A2A3D),
    replyBoxBg: Color(0xFF26262E),
    page: Color(0xFF1A1A1A),
    surface: Color(0xFF242424),
    surfaceHigh: Color(0xFF2E2E2E),
    divider: Color(0xFF383838),
    textPrimary: Color(0xFFE5E5E5),
    textSecondary: Color(0xFF888888),
    textStrongSecondary: Color(0xFF5C5C5C),
    textTertiary: Color(0xFF5C5C5C),
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
      brandGradientEnd:
          Color.lerp(brandGradientEnd, other.brandGradientEnd, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      weChatGreen: Color.lerp(weChatGreen, other.weChatGreen, t)!,
      weChatOnline: Color.lerp(weChatOnline, other.weChatOnline, t)!,
      weChatInputBg: Color.lerp(weChatInputBg, other.weChatInputBg, t)!,
      weChatDivider: Color.lerp(weChatDivider, other.weChatDivider, t)!,
      chatUserBubble: Color.lerp(chatUserBubble, other.chatUserBubble, t)!,
      chatUserBubbleText:
          Color.lerp(chatUserBubbleText, other.chatUserBubbleText, t)!,
      momentAccent: Color.lerp(momentAccent, other.momentAccent, t)!,
      momentChipBg: Color.lerp(momentChipBg, other.momentChipBg, t)!,
      replyBoxBg: Color.lerp(replyBoxBg, other.replyBoxBg, t)!,
      page: Color.lerp(page, other.page, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceHigh: Color.lerp(surfaceHigh, other.surfaceHigh, t)!,
      divider: Color.lerp(divider, other.divider, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textStrongSecondary:
          Color.lerp(textStrongSecondary, other.textStrongSecondary, t)!,
      textTertiary: Color.lerp(textTertiary, other.textTertiary, t)!,
    );
  }
}
