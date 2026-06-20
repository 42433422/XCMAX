package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * XCAGI 品牌色系 v4 — 单一真相源（SSOT）
 *
 * 对标飞书/钉钉/企业微信的克制专业风格。
 * 所有颜色必须通过 [MaterialTheme.colorScheme] 或 [LocalXcagiColors] 引用，
 * 禁止页面内硬编码 Color(0xFF...)。
 */

// ── 品牌色 ──
private val BrandBlue = Color(0xFF3370FF)
private val BrandBlueLight = Color(0xFF5B8FFF)
private val BrandBlueDark = Color(0xFF1A50CC)
private val BrandBlueContainer = Color(0xFFE8F0FF)

// ── 功能色 ──
private val FuncGreen = Color(0xFF00B578)
private val FuncGreenLight = Color(0xFF33C793)
private val FuncGreenContainer = Color(0xFFE6F9F1)
private val FuncDanger = Color(0xFFF54A45)
private val FuncWarning = Color(0xFFED7B2F)

// ── 微信色（聊天专用）──
private val WeChatGreen = Color(0xFF95EC69)
private val WeChatOnline = Color(0xFF07C160)

// ── 中性色（飞书同系）──
private val N00 = Color(0xFFFFFFFF)
private val N50 = Color(0xFFF5F6F7)
private val N100 = Color(0xFFE8E9EB)
private val N200 = Color(0xFFDEE0E3)
private val N300 = Color(0xFFC9CDD4)
private val N400 = Color(0xFF8F959E)
private val N500 = Color(0xFF646A73)
private val N600 = Color(0xFF494E56)
private val N700 = Color(0xFF33363D)
private val N800 = Color(0xFF1F2329)
private val N900 = Color(0xFF141619)

/**
 * 扩展颜色 — 品牌专用色，不在 Material3 colorScheme 中
 * 通过 LocalXcagiColors 访问
 */
data class XcagiExtraColors(
    val brandBlue: Color,
    val brandBlueContainer: Color,
    val weChatGreen: Color,
    val weChatOnline: Color,
    val weChatInputBg: Color,
    val weChatDivider: Color,
    val success: Color,
    val warning: Color,
    val danger: Color,
    // 中性色
    val n00: Color,
    val n50: Color,
    val n100: Color,
    val n200: Color,
    val n300: Color,
    val n400: Color,
    val n500: Color,
    val n600: Color,
    val n700: Color,
    val n800: Color,
    val n900: Color,
)

val LocalXcagiColors = staticCompositionLocalOf {
    XcagiExtraColors(
        brandBlue = BrandBlue,
        brandBlueContainer = BrandBlueContainer,
        weChatGreen = WeChatGreen,
        weChatOnline = WeChatOnline,
        weChatInputBg = N50,
        weChatDivider = N200,
        success = FuncGreen,
        warning = FuncWarning,
        danger = FuncDanger,
        n00 = N00, n50 = N50, n100 = N100, n200 = N200, n300 = N300,
        n400 = N400, n500 = N500, n600 = N600, n700 = N700, n800 = N800, n900 = N900,
    )
}

private val LightExtraColors = XcagiExtraColors(
    brandBlue = BrandBlue,
    brandBlueContainer = BrandBlueContainer,
    weChatGreen = WeChatGreen,
    weChatOnline = WeChatOnline,
    weChatInputBg = N50,
    weChatDivider = N200,
    success = FuncGreen,
    warning = FuncWarning,
    danger = FuncDanger,
    n00 = N00, n50 = N50, n100 = N100, n200 = N200, n300 = N300,
    n400 = N400, n500 = N500, n600 = N600, n700 = N700, n800 = N800, n900 = N900,
)

// ── 深色主题专用色（中性深灰，参考微信深色模式）──
private val DarkBg = Color(0xFF1A1A1A)          // 主背景：中性深灰黑
private val DarkSurface = Color(0xFF242424)      // 卡片表面：深灰
private val DarkSurfaceVariant = Color(0xFF2E2E2E) // 次级表面
private val DarkBorder = Color(0xFF383838)       // 边框/分割线
private val DarkTextPrimary = Color(0xFFE5E5E5)  // 主文字：浅灰白
private val DarkTextSecondary = Color(0xFF888888) // 次文字
private val DarkTextTertiary = Color(0xFF5C5C5C)  // 三级文字/占位

private val DarkExtraColors = XcagiExtraColors(
    brandBlue = BrandBlueLight,
    brandBlueContainer = Color(0xFF1A3A80),
    weChatGreen = Color(0xFF6FAA4A),
    weChatOnline = FuncGreenLight,
    weChatInputBg = DarkSurfaceVariant,
    weChatDivider = DarkBorder,
    success = FuncGreenLight,
    warning = FuncWarning,
    danger = FuncDanger,
    n00 = DarkBg, n50 = DarkSurface, n100 = DarkSurfaceVariant, n200 = DarkBorder, n300 = DarkTextTertiary,
    n400 = DarkTextSecondary, n500 = DarkTextSecondary, n600 = DarkTextTertiary, n700 = DarkBorder, n800 = DarkSurface, n900 = DarkBg,
)

private val DarkColors = darkColorScheme(
    primary = BrandBlueLight,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF1A3A80),
    onPrimaryContainer = Color(0xFFB8CCFF),
    secondary = FuncGreen,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFF005B3F),
    onSecondaryContainer = FuncGreenLight,
    tertiary = BrandBlueLight,
    background = DarkBg,
    onBackground = DarkTextPrimary,
    surface = DarkSurface,
    onSurface = DarkTextPrimary,
    surfaceVariant = DarkSurfaceVariant,
    onSurfaceVariant = DarkTextSecondary,
    outline = DarkBorder,
    outlineVariant = DarkSurfaceVariant,
    error = FuncDanger,
    onError = Color.White,
    errorContainer = Color(0xFF5C1A1A),
    onErrorContainer = Color(0xFFFFB3B3),
    surfaceTint = BrandBlueLight,
)

private val LightColors = lightColorScheme(
    primary = BrandBlue,
    onPrimary = Color.White,
    primaryContainer = BrandBlueContainer,
    onPrimaryContainer = Color(0xFF0A1F6B),
    secondary = FuncGreen,
    onSecondary = Color.White,
    secondaryContainer = FuncGreenContainer,
    onSecondaryContainer = Color(0xFF004D35),
    tertiary = BrandBlue,
    background = N50,
    onBackground = N800,
    surface = N00,
    onSurface = N800,
    surfaceVariant = N100,
    onSurfaceVariant = N500,
    outline = N500,
    outlineVariant = N200,
    error = FuncDanger,
    onError = Color.White,
    errorContainer = Color(0xFFFFECEC),
    onErrorContainer = Color(0xFF6B1A1A),
    surfaceTint = BrandBlue,
)

@Composable
fun XcagiTheme(
    themeMode: String = "system",
    content: @Composable () -> Unit,
) {
    val dark = when (themeMode) {
        "light" -> false
        "dark" -> true
        else -> isSystemInDarkTheme()
    }
    val extraColors = if (dark) DarkExtraColors else LightExtraColors

    androidx.compose.runtime.CompositionLocalProvider(LocalXcagiColors provides extraColors) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = XcagiTypography,
            shapes = XcagiShapes,
            content = content,
        )
    }
}

/** 便捷访问扩展 */
object XcagiTheme {
    val extra: XcagiExtraColors
        @Composable get() = LocalXcagiColors.current
}
