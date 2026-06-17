package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * XCAGI 企业级设计令牌 v3（已废弃）
 *
 * 此 object 已被 [com.xiuci.xcagi.mobile.ui.theme.XcagiTheme] + MaterialTheme 体系取代。
 * 请改用：
 * - 颜色：`MaterialTheme.colorScheme.*` 或 `XcagiTheme.extra.*`
 * - 字号：`MaterialTheme.typography.*`
 * - 圆角：`MaterialTheme.shapes.*`
 * - 间距：[com.xiuci.xcagi.mobile.ui.theme.Spacing]
 * - 阴影：[com.xiuci.xcagi.mobile.ui.theme.Elevation]
 *
 * 文件保留仅为兼容历史反射引用，禁止新增使用。
 */
@Deprecated(
    "Use MaterialTheme.colorScheme / XcagiTheme.extra / MaterialTheme.typography / MaterialTheme.shapes instead",
    level = DeprecationLevel.WARNING,
)
object MobileTokens {
    // ── 间距（大厂级留白） ──
    @Deprecated("Use Spacing.lg", level = DeprecationLevel.WARNING)
    val pageHorizontal = 16.dp

    @Deprecated("Use Spacing.lg", level = DeprecationLevel.WARNING)
    val horizontalPagePadding = 16.dp

    @Deprecated("Use Spacing.md", level = DeprecationLevel.WARNING)
    val sectionGap = 12.dp

    @Deprecated("Use Spacing.md", level = DeprecationLevel.WARNING)
    val itemSpacing = 12.dp

    @Deprecated("Use Spacing.lg", level = DeprecationLevel.WARNING)
    val cardInnerPadding = 16.dp

    @Deprecated("Use Spacing.xl", level = DeprecationLevel.WARNING)
    val authHorizontalMargin = 24.dp

    // ── 圆角 ──
    @Deprecated("Use MaterialTheme.shapes.medium", level = DeprecationLevel.WARNING)
    val cornerCard = RoundedCornerShape(12.dp)

    @Deprecated("Use MaterialTheme.shapes.small", level = DeprecationLevel.WARNING)
    val cornerCardSmall = RoundedCornerShape(8.dp)

    @Deprecated("Use MaterialTheme.shapes.medium", level = DeprecationLevel.WARNING)
    val cornerAuthCard = RoundedCornerShape(12.dp)

    @Deprecated("Use MaterialTheme.shapes.small", level = DeprecationLevel.WARNING)
    val cornerAuthButton = RoundedCornerShape(8.dp)

    @Deprecated("Use MaterialTheme.shapes.extraSmall", level = DeprecationLevel.WARNING)
    val cornerChip = RoundedCornerShape(6.dp)

    @Deprecated("Use MaterialTheme.shapes.extraLarge", level = DeprecationLevel.WARNING)
    val cornerInputBar = RoundedCornerShape(20.dp)

    @Deprecated("Use MaterialTheme.shapes.small", level = DeprecationLevel.WARNING)
    val cornerIconBox = RoundedCornerShape(8.dp)

    // ── 品牌色 ──
    @Deprecated("Use XcagiTheme.extra.brandBlue", level = DeprecationLevel.WARNING)
    val brandBlue = Color(0xFF3370FF)

    @Deprecated("Use MaterialTheme.colorScheme.primaryContainer", level = DeprecationLevel.WARNING)
    val brandBlueLight = Color(0xFFE8F0FF)

    @Deprecated("Use MaterialTheme.colorScheme.secondary", level = DeprecationLevel.WARNING)
    val brandGreen = Color(0xFF00B578)

    @Deprecated("Use MaterialTheme.colorScheme.secondaryContainer", level = DeprecationLevel.WARNING)
    val brandGreenLight = Color(0xFFE6F9F1)

    @Deprecated("Use XcagiTheme.extra.weChatGreen", level = DeprecationLevel.WARNING)
    val weChatGreen = Color(0xFF95EC69)

    @Deprecated("Use XcagiTheme.extra.warning with container", level = DeprecationLevel.WARNING)
    val warningBg = Color(0xFFFFF8E1)

    @Deprecated("Use XcagiTheme.extra.warning", level = DeprecationLevel.WARNING)
    val warningFg = Color(0xFFF57F17)

    // ── 语义色 ──
    @Deprecated("Use XcagiTheme.extra.success", level = DeprecationLevel.WARNING)
    val successGreen = Color(0xFF00B578)

    @Deprecated("Use XcagiTheme.extra.warning", level = DeprecationLevel.WARNING)
    val warningOrange = Color(0xFFED7B2F)

    @Deprecated("Use XcagiTheme.extra.danger", level = DeprecationLevel.WARNING)
    val dangerRed = Color(0xFFF54A45)

    @Deprecated("Use XcagiTheme.extra.brandBlue", level = DeprecationLevel.WARNING)
    val infoBlue = Color(0xFF3370FF)

    // ── 图标背景色（浅色底+深色图标，钉钉风格） ──
    @Deprecated("Use MaterialTheme.colorScheme.primaryContainer", level = DeprecationLevel.WARNING)
    val iconBgBlue = Color(0xFFE8F0FF)

    @Deprecated("Use MaterialTheme.colorScheme.secondaryContainer", level = DeprecationLevel.WARNING)
    val iconBgGreen = Color(0xFFE6F9F1)

    @Deprecated("Use MaterialTheme.colorScheme.secondaryContainer", level = DeprecationLevel.WARNING)
    val iconBgOrange = Color(0xFFFFF3E0)

    @Deprecated("Use MaterialTheme.colorScheme.errorContainer", level = DeprecationLevel.WARNING)
    val iconBgRed = Color(0xFFFFECEC)

    @Deprecated("Use MaterialTheme.colorScheme.tertiaryContainer", level = DeprecationLevel.WARNING)
    val iconBgPurple = Color(0xFFF3E8FF)

    @Deprecated("Use MaterialTheme.colorScheme.primaryContainer", level = DeprecationLevel.WARNING)
    val iconBgCyan = Color(0xFFE0F7FA)

    // ── 图标前景色 ──
    @Deprecated("Use XcagiTheme.extra.brandBlue", level = DeprecationLevel.WARNING)
    val iconFgBlue = Color(0xFF3370FF)

    @Deprecated("Use MaterialTheme.colorScheme.secondary", level = DeprecationLevel.WARNING)
    val iconFgGreen = Color(0xFF00B578)

    @Deprecated("Use XcagiTheme.extra.warning", level = DeprecationLevel.WARNING)
    val iconFgOrange = Color(0xFFED7B2F)

    @Deprecated("Use XcagiTheme.extra.danger", level = DeprecationLevel.WARNING)
    val iconFgRed = Color(0xFFF54A45)

    @Deprecated("Use MaterialTheme.colorScheme.tertiary", level = DeprecationLevel.WARNING)
    val iconFgPurple = Color(0xFF8B5CF6)

    @Deprecated("Use MaterialTheme.colorScheme.primary", level = DeprecationLevel.WARNING)
    val iconFgCyan = Color(0xFF00ACC1)

    // ── 中性色 ──
    @Deprecated("Use MaterialTheme.colorScheme.onSurface", level = DeprecationLevel.WARNING)
    val textPrimary = Color(0xFF1F2329)

    @Deprecated("Use MaterialTheme.colorScheme.onSurfaceVariant", level = DeprecationLevel.WARNING)
    val textSecondary = Color(0xFF646A73)

    @Deprecated("Use MaterialTheme.colorScheme.outline", level = DeprecationLevel.WARNING)
    val textTertiary = Color(0xFF8F959E)

    @Deprecated("Use MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)", level = DeprecationLevel.WARNING)
    val textDisabled = Color(0xFFB0B5BD)

    @Deprecated("Use MaterialTheme.colorScheme.outlineVariant", level = DeprecationLevel.WARNING)
    val divider = Color(0xFFDEE0E3)

    @Deprecated("Use MaterialTheme.colorScheme.background", level = DeprecationLevel.WARNING)
    val surfaceBg = Color(0xFFF5F6F7)

    @Deprecated("Use MaterialTheme.colorScheme.surface", level = DeprecationLevel.WARNING)
    val surfaceWhite = Color(0xFFFFFFFF)

    // ── Auth 专用 ──
    @Deprecated("Use MaterialTheme.colorScheme.onSurface", level = DeprecationLevel.WARNING)
    val authTextPrimary = Color(0xFF1F2329)

    @Deprecated("Use MaterialTheme.colorScheme.outline", level = DeprecationLevel.WARNING)
    val authTextMuted = Color(0xFF8F959E)

    @Deprecated("Use MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)", level = DeprecationLevel.WARNING)
    val authPlaceholder = Color(0xFFB0B5BD)

    @Deprecated("Use MaterialTheme.colorScheme.outlineVariant", level = DeprecationLevel.WARNING)
    val authDivider = Color(0xFFDEE0E3)

    @Deprecated("Use MaterialTheme.colorScheme.background", level = DeprecationLevel.WARNING)
    val authPageBg = Color(0xFFF5F6F7)

    // ── 阴影层级 ──
    @Deprecated("Use Elevation.none", level = DeprecationLevel.WARNING)
    val elevationNone = 0.dp

    @Deprecated("Use Elevation.level1", level = DeprecationLevel.WARNING)
    val elevationSubtle = 0.5.dp

    @Deprecated("Use Elevation.level1", level = DeprecationLevel.WARNING)
    val elevationCard = 1.dp

    @Deprecated("Use Elevation.level2", level = DeprecationLevel.WARNING)
    val elevationRaised = 2.dp

    @Deprecated("Use MaterialTheme.colorScheme.primary", level = DeprecationLevel.WARNING)
    @Composable
    fun accent(): Color = MaterialTheme.colorScheme.primary

    @Deprecated("Use MaterialTheme.colorScheme.onSurfaceVariant", level = DeprecationLevel.WARNING)
    @Composable
    fun pending(): Color = MaterialTheme.colorScheme.onSurfaceVariant

    @Deprecated("Use XcagiTheme.extra.success", level = DeprecationLevel.WARNING)
    @Composable
    fun success(): Color = successGreen

    @Deprecated("Use MaterialTheme.colorScheme.error", level = DeprecationLevel.WARNING)
    @Composable
    fun danger(): Color = MaterialTheme.colorScheme.error

    @Deprecated("Use XcagiTheme.extra.warning", level = DeprecationLevel.WARNING)
    @Composable
    fun warning(): Color = warningOrange

    @Deprecated("Use MaterialTheme.colorScheme.primaryContainer", level = DeprecationLevel.WARNING)
    @Composable
    fun chipSelectedBg(): Color = MaterialTheme.colorScheme.primaryContainer

    @Deprecated("Use MaterialTheme.colorScheme.surfaceVariant", level = DeprecationLevel.WARNING)
    @Composable
    fun chipUnselectedBg(): Color = MaterialTheme.colorScheme.surfaceVariant
}
