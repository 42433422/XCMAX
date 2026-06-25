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

// ── 品牌色 v5 —— 取自桌面端工作台色系（indigo #818cf8 / violet / emerald），
//    刻意区别于微信绿+飞书蓝，避免"抄袭"观感，与桌面端保持同一品牌身份。 ──
private val BrandBlue = Color(0xFF6366F1)          // 桌面 accent-indigo：浅色主色
private val BrandBlueLight = Color(0xFF818CF8)     // 桌面 --color-primary：深色主色/亮一档
private val BrandBlueDark = Color(0xFF4F46E5)      // indigo-600
private val BrandBlueContainer = Color(0xFFEAEBFE) // 浅靛紫容器

// ── 功能色（桌面 accent-green / status 系）──
private val FuncGreen = Color(0xFF10B981)          // emerald-500
private val FuncGreenLight = Color(0xFF34D399)     // 桌面 --color-accent-green
private val FuncGreenContainer = Color(0xFFE7FAF3)
private val FuncDanger = Color(0xFFEF4444)         // 桌面 danger
private val FuncWarning = Color(0xFFF59E0B)        // 桌面 warning

// ── 活跃/在线点缀（用桌面翡翠绿，不用微信绿）──
private val WeChatGreen = Color(0xFF95EC69)        // legacy 兼容（基本不用）
private val WeChatOnline = Color(0xFF10B981)       // emerald 在线/活跃

// ── 品牌渐变端色（钱包卡：indigo→violet，对齐桌面 --wb-gradient-accent #7c3aed→#4f46e5）──
private val BrandBlueGradientEnd = Color(0xFF7C3AED) // violet-600

// ── 聊天气泡（用户侧 = 品牌靛紫气泡 + 白字，从根上区别于微信绿气泡）──
private val ChatUserBubbleLight = Color(0xFF6366F1)
private val ChatUserBubbleDark = Color(0xFF4F46E5)
private val ChatBubbleTextLight = Color(0xFFFFFFFF)
private val ChatBubbleTextDark = Color(0xFFEEF0FF)

// ── AI 交流圈（朋友圈风，靛紫强调）──
private val MomentAccentLight = Color(0xFF5145CD)
private val MomentAccentDark = Color(0xFFA5B0FF)
private val MomentChipBgLight = Color(0xFFECEDFE)
private val MomentChipBgDark = Color(0xFF2A2A3D)
private val ReplyBoxBgLight = Color(0xFFF4F5F7)
private val ReplyBoxBgDark = Color(0xFF26262E)

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
    val brandBlueGradientEnd: Color,
    val weChatGreen: Color,
    val weChatOnline: Color,
    val weChatInputBg: Color,
    val weChatDivider: Color,
    // 聊天气泡（用户侧绿气泡 + 其上文字，明暗各一套以保证对比度）
    val chatUserBubble: Color,
    val chatUserBubbleText: Color,
    // AI 交流圈（朋友圈风）：强调绿、能力标签底、回复框底
    val momentAccent: Color,
    val momentChipBg: Color,
    val replyBoxBg: Color,
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
        brandBlueGradientEnd = BrandBlueGradientEnd,
        weChatGreen = WeChatGreen,
        weChatOnline = WeChatOnline,
        weChatInputBg = N50,
        weChatDivider = N200,
        chatUserBubble = ChatUserBubbleLight,
        chatUserBubbleText = ChatBubbleTextLight,
        momentAccent = MomentAccentLight,
        momentChipBg = MomentChipBgLight,
        replyBoxBg = ReplyBoxBgLight,
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
    brandBlueGradientEnd = BrandBlueGradientEnd,
    weChatGreen = WeChatGreen,
    weChatOnline = WeChatOnline,
    weChatInputBg = N50,
    weChatDivider = N200,
    chatUserBubble = ChatUserBubbleLight,
    chatUserBubbleText = ChatBubbleTextLight,
    momentAccent = MomentAccentLight,
    momentChipBg = MomentChipBgLight,
    replyBoxBg = ReplyBoxBgLight,
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
    brandBlueGradientEnd = Color(0xFF3F6FD8),
    weChatGreen = Color(0xFF6FAA4A),
    weChatOnline = FuncGreenLight,
    weChatInputBg = DarkSurfaceVariant,
    weChatDivider = DarkBorder,
    chatUserBubble = ChatUserBubbleDark,
    chatUserBubbleText = ChatBubbleTextDark,
    momentAccent = MomentAccentDark,
    momentChipBg = MomentChipBgDark,
    replyBoxBg = ReplyBoxBgDark,
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
    onPrimaryContainer = Color(0xFF312E81),
    secondary = FuncGreen,
    onSecondary = Color.White,
    secondaryContainer = FuncGreenContainer,
    onSecondaryContainer = Color(0xFF064E3B),
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
