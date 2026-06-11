package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * XCAGI 企业级设计令牌 v3
 *
 * 设计理念：对标飞书/钉钉/企业微信的克制、专业、高信息密度。
 * - 主色：靛蓝 #3370FF（飞书同系蓝）
 * - 辅色：翡翠 #00B578（企业微信同系绿）
 * - 无渐变，纯色块 + 微阴影 + 留白
 * - 图标用品牌色实心圆底（类似钉钉宫格图标风格）
 */
object MobileTokens {
    // ── 间距（大厂级留白） ──
    val pageHorizontal = 16.dp
    val horizontalPagePadding = 16.dp
    val sectionGap = 12.dp
    val itemSpacing = 12.dp
    val cardInnerPadding = 16.dp
    val authHorizontalMargin = 24.dp

    // ── 圆角 ──
    val cornerCard = RoundedCornerShape(12.dp)
    val cornerCardSmall = RoundedCornerShape(8.dp)
    val cornerAuthCard = RoundedCornerShape(12.dp)
    val cornerAuthButton = RoundedCornerShape(8.dp)
    val cornerChip = RoundedCornerShape(6.dp)
    val cornerInputBar = RoundedCornerShape(20.dp)
    val cornerIconBox = RoundedCornerShape(8.dp)

    // ── 品牌色 ──
    val brandBlue = Color(0xFF3370FF)
    val brandBlueLight = Color(0xFFE8F0FF)
    val brandGreen = Color(0xFF00B578)
    val brandGreenLight = Color(0xFFE6F9F1)
    val weChatGreen = Color(0xFF95EC69)
    val warningBg = Color(0xFFFFF8E1)
    val warningFg = Color(0xFFF57F17)

    // ── 语义色 ──
    val successGreen = Color(0xFF00B578)
    val warningOrange = Color(0xFFED7B2F)
    val dangerRed = Color(0xFFF54A45)
    val infoBlue = Color(0xFF3370FF)

    // ── 图标背景色（浅色底+深色图标，钉钉风格） ──
    val iconBgBlue = Color(0xFFE8F0FF)
    val iconBgGreen = Color(0xFFE6F9F1)
    val iconBgOrange = Color(0xFFFFF3E0)
    val iconBgRed = Color(0xFFFFECEC)
    val iconBgPurple = Color(0xFFF3E8FF)
    val iconBgCyan = Color(0xFFE0F7FA)

    // ── 图标前景色 ──
    val iconFgBlue = Color(0xFF3370FF)
    val iconFgGreen = Color(0xFF00B578)
    val iconFgOrange = Color(0xFFED7B2F)
    val iconFgRed = Color(0xFFF54A45)
    val iconFgPurple = Color(0xFF8B5CF6)
    val iconFgCyan = Color(0xFF00ACC1)

    // ── 中性色 ──
    val textPrimary = Color(0xFF1F2329)
    val textSecondary = Color(0xFF646A73)
    val textTertiary = Color(0xFF8F959E)
    val textDisabled = Color(0xFFB0B5BD)
    val divider = Color(0xFFDEE0E3)
    val surfaceBg = Color(0xFFF5F6F7)
    val surfaceWhite = Color(0xFFFFFFFF)

    // ── Auth 专用 ──
    val authTextPrimary = Color(0xFF1F2329)
    val authTextMuted = Color(0xFF8F959E)
    val authPlaceholder = Color(0xFFB0B5BD)
    val authDivider = Color(0xFFDEE0E3)
    val authPageBg = Color(0xFFF5F6F7)

    // ── 阴影层级 ──
    val elevationNone = 0.dp
    val elevationSubtle = 0.5.dp
    val elevationCard = 1.dp
    val elevationRaised = 2.dp

    @Composable
    fun accent(): Color = MaterialTheme.colorScheme.primary

    @Composable
    fun pending(): Color = MaterialTheme.colorScheme.onSurfaceVariant

    @Composable
    fun success(): Color = successGreen

    @Composable
    fun danger(): Color = MaterialTheme.colorScheme.error

    @Composable
    fun warning(): Color = warningOrange

    @Composable
    fun chipSelectedBg(): Color = MaterialTheme.colorScheme.primaryContainer

    @Composable
    fun chipUnselectedBg(): Color = MaterialTheme.colorScheme.surfaceVariant
}
