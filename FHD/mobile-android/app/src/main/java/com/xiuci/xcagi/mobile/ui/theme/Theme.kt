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

private val DarkExtraColors = XcagiExtraColors(
    brandBlue = BrandBlueLight,
    brandBlueContainer = Color(0xFF1A3A80),
    weChatGreen = Color(0xFF6FAA4A),
    weChatOnline = FuncGreenLight,
    weChatInputBg = N700,
    weChatDivider = N600,
    success = FuncGreenLight,
    warning = FuncWarning,
    danger = FuncDanger,
    n00 = N900, n50 = N800, n100 = N700, n200 = N600, n300 = N500,
    n400 = N400, n500 = N300, n600 = N200, n700 = N100, n800 = N50, n900 = N00,
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
    background = N900,
    onBackground = N100,
    surface = N800,
    onSurface = N100,
    surfaceVariant = N700,
    onSurfaceVariant = N400,
    outline = N400,
    outlineVariant = N700,
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
