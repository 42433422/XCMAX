package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R

/**
 * 中文主字体 — HarmonyOS Sans SC（OFL 协议）
 *
 * 字体文件需放入 app/src/main/res/font/，文件名固定：
 *   harmony_sc_regular.ttf  / harmony_sc_medium.ttf
 *   harmony_sc_semibold.ttf / harmony_sc_bold.ttf
 * 建议先用 pyftsubset 子集化至通用规范汉字一级表(~3500字) + ASCII + 标点，
 * 每字重 ≤400KB，合计 ≤1.6MB。
 */
val XcagiFontFamily: FontFamily = FontFamily(
    Font(R.font.harmony_sc_regular, FontWeight.Normal),
    Font(R.font.harmony_sc_medium, FontWeight.Medium),
    Font(R.font.harmony_sc_semibold, FontWeight.SemiBold),
    Font(R.font.harmony_sc_bold, FontWeight.Bold),
)

/**
 * XCAGI 字体系统 — 对标飞书/钉钉字号阶梯
 *
 * 字号阶梯（中文优化）：
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
 */
val XcagiTypography = Typography(
    displayLarge = TextStyle(fontFamily = XcagiFontFamily, fontSize = 28.sp, fontWeight = FontWeight.Bold, lineHeight = 36.sp),
    displayMedium = TextStyle(fontFamily = XcagiFontFamily, fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp),
    displaySmall = TextStyle(fontFamily = XcagiFontFamily, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, lineHeight = 28.sp),

    headlineLarge = TextStyle(fontFamily = XcagiFontFamily, fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp),
    headlineMedium = TextStyle(fontFamily = XcagiFontFamily, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, lineHeight = 28.sp),
    headlineSmall = TextStyle(fontFamily = XcagiFontFamily, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, lineHeight = 26.sp),

    titleLarge = TextStyle(fontFamily = XcagiFontFamily, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, lineHeight = 24.sp),
    titleMedium = TextStyle(fontFamily = XcagiFontFamily, fontSize = 17.sp, fontWeight = FontWeight.Medium, lineHeight = 22.sp),
    titleSmall = TextStyle(fontFamily = XcagiFontFamily, fontSize = 15.sp, fontWeight = FontWeight.Medium, lineHeight = 20.sp),

    bodyLarge = TextStyle(fontFamily = XcagiFontFamily, fontSize = 16.sp, fontWeight = FontWeight.Normal, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = XcagiFontFamily, fontSize = 15.sp, fontWeight = FontWeight.Normal, lineHeight = 21.sp),
    bodySmall = TextStyle(fontFamily = XcagiFontFamily, fontSize = 14.sp, fontWeight = FontWeight.Normal, lineHeight = 19.sp),

    labelLarge = TextStyle(fontFamily = XcagiFontFamily, fontSize = 14.sp, fontWeight = FontWeight.Medium, lineHeight = 18.sp),
    labelMedium = TextStyle(fontFamily = XcagiFontFamily, fontSize = 13.sp, fontWeight = FontWeight.Medium, lineHeight = 17.sp),
    labelSmall = TextStyle(fontFamily = XcagiFontFamily, fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 14.sp),
)
