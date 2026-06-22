package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * XCAGI 字体系统 — 对标飞书/钉钉字号阶梯
 *
 * 中文显示优化：
 * - 显式 FontFamily.SansSerif（Android 系统会按字符走 fallback：英文 Roboto，中文系统 CJK）
 * - letterSpacing 微开张（中文方块字略松散视觉更稳）
 * - LineHeightStyle 上下居中 + 不修剪（中文字符基线/上下行距更均衡）
 *
 * 字号阶梯：
 * - displayLarge   28sp Bold    — 大标题（页面主标题）
 * - headlineLarge  24sp Bold    — 标题
 * - headlineMedium 20sp SemiBold — 区块标题
 * - titleLarge     18sp SemiBold — 导航栏标题
 * - titleMedium    17sp Medium  — 列表项主标题
 * - titleSmall     15sp Medium  — 小标题
 * - bodyLarge      16sp Regular — 正文（重要）
 * - bodyMedium     15sp Regular — 正文（默认）
 * - bodySmall      14sp Regular — 辅助文本
 * - labelLarge     14sp Medium  — 按钮
 * - labelMedium    13sp Medium  — 标签/徽标
 * - labelSmall     11sp Medium  — 时间戳/角标
 *
 * 后续如接入 HarmonyOS Sans / 思源黑体，仅替换 [XcagiFontFamily] 即可全局生效。
 */
val XcagiFontFamily: FontFamily = FontFamily.SansSerif

/** 中文字符微开张 — 0.02em 在小字号上不显眼，在大标题上让方块字更"呼吸" */
private val CJKLetterSpacing = 0.02.em

/** 中文垂直居中 — 避免英文/中文混排时基线漂浮 */
private val CJKLineHeightStyle = LineHeightStyle(
    alignment = LineHeightStyle.Alignment.Center,
    trim = LineHeightStyle.Trim.None,
)

private fun cjkStyle(
    fontSize: androidx.compose.ui.unit.TextUnit,
    fontWeight: FontWeight,
    lineHeight: androidx.compose.ui.unit.TextUnit,
    letterSpacing: androidx.compose.ui.unit.TextUnit = CJKLetterSpacing,
): TextStyle = TextStyle(
    fontFamily = XcagiFontFamily,
    fontSize = fontSize,
    fontWeight = fontWeight,
    lineHeight = lineHeight,
    letterSpacing = letterSpacing,
    lineHeightStyle = CJKLineHeightStyle,
)

val XcagiTypography = Typography(
    displayLarge = cjkStyle(28.sp, FontWeight.Bold, 36.sp),
    displayMedium = cjkStyle(24.sp, FontWeight.Bold, 32.sp),
    displaySmall = cjkStyle(20.sp, FontWeight.SemiBold, 28.sp),

    headlineLarge = cjkStyle(24.sp, FontWeight.Bold, 32.sp),
    headlineMedium = cjkStyle(20.sp, FontWeight.SemiBold, 28.sp),
    headlineSmall = cjkStyle(18.sp, FontWeight.SemiBold, 26.sp),

    titleLarge = cjkStyle(18.sp, FontWeight.SemiBold, 24.sp),
    titleMedium = cjkStyle(17.sp, FontWeight.Medium, 22.sp),
    titleSmall = cjkStyle(15.sp, FontWeight.Medium, 20.sp),

    bodyLarge = cjkStyle(16.sp, FontWeight.Normal, 22.sp),
    bodyMedium = cjkStyle(15.sp, FontWeight.Normal, 21.sp),
    bodySmall = cjkStyle(14.sp, FontWeight.Normal, 19.sp),

    // 按钮/标签字符更紧凑，letterSpacing 减半
    labelLarge = cjkStyle(14.sp, FontWeight.Medium, 18.sp, letterSpacing = 0.01.em),
    labelMedium = cjkStyle(13.sp, FontWeight.Medium, 17.sp, letterSpacing = 0.01.em),
    labelSmall = cjkStyle(11.sp, FontWeight.Medium, 14.sp, letterSpacing = 0.sp),
)
