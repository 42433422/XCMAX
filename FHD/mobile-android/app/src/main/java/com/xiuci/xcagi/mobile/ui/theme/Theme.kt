package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * XCAGI 企业级品牌色系 v3
 *
 * 对标飞书/钉钉/企业微信的克制专业风格。
 * - Primary: #3370FF 飞书蓝
 * - Secondary: #00B578 企业微信绿
 * - 中性色系：#1F2329 系（飞书同系灰）
 */

private val BrandBlue = Color(0xFF3370FF)
private val BrandBlueLight = Color(0xFF5B8FFF)
private val BrandBlueDark = Color(0xFF1A50CC)

private val BrandGreen = Color(0xFF00B578)
private val BrandGreenLight = Color(0xFF33C793)
private val BrandGreenDark = Color(0xFF008F60)

private val FuncDanger = Color(0xFFF54A45)
private val FuncWarning = Color(0xFFED7B2F)
private val FuncSuccess = Color(0xFF00B578)
private val FuncInfo = Color(0xFF3370FF)

// 飞书同系中性色
private val N50 = Color(0xFFF5F6F7)
private val N100 = Color(0xFFE8E9EB)
private val N200 = Color(0xFFD0D3D6)
private val N300 = Color(0xFFB0B5BD)
private val N400 = Color(0xFF8F959E)
private val N500 = Color(0xFF646A73)
private val N600 = Color(0xFF494E56)
private val N700 = Color(0xFF33363D)
private val N800 = Color(0xFF1F2329)
private val N900 = Color(0xFF141619)

private val DarkColors = darkColorScheme(
    primary = BrandBlueLight,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF1A3A80),
    onPrimaryContainer = Color(0xFFB8CCFF),
    secondary = BrandGreen,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFF005B3F),
    onSecondaryContainer = BrandGreenLight,
    tertiary = FuncInfo,
    background = N900,
    onBackground = N100,
    surface = N800,
    onSurface = N100,
    surfaceVariant = N700,
    onSurfaceVariant = N400,
    outline = N600,
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
    primaryContainer = Color(0xFFE8F0FF),
    onPrimaryContainer = Color(0xFF0A1F6B),
    secondary = BrandGreen,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE6F9F1),
    onSecondaryContainer = Color(0xFF004D35),
    tertiary = FuncInfo,
    background = N50,
    onBackground = N800,
    surface = Color.White,
    onSurface = N800,
    surfaceVariant = N100,
    onSurfaceVariant = N500,
    outline = N200,
    outlineVariant = N100,
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
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
