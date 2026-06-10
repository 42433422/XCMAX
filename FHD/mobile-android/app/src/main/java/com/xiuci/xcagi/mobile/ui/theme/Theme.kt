package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** GPT 灰点缀 + 微信分组灰底 */
private val GptGray = Color(0xFF353740)
private val GptGrayMuted = Color(0xFF8E8EA0)
private val WeChatBg = Color(0xFFEDEDED)
private val WeChatGreen = Color(0xFF07C160)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFECECF1),
    onPrimary = Color(0xFF111111),
    primaryContainer = Color(0xFF2A2B32),
    onPrimaryContainer = Color(0xFFECECF1),
    secondary = WeChatGreen,
    onSecondary = Color.White,
    background = Color(0xFF111111),
    onBackground = Color(0xFFECECF1),
    surface = Color(0xFF1E1E1E),
    onSurface = Color(0xFFECECF1),
    onSurfaceVariant = GptGrayMuted,
    outline = Color(0xFF3A3A3A),
    surfaceVariant = Color(0xFF2A2B32),
    error = Color(0xFFFA5151),
)

private val LightColors = lightColorScheme(
    primary = GptGray,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF0F0F0),
    onPrimaryContainer = GptGray,
    secondary = WeChatGreen,
    onSecondary = Color.White,
    background = WeChatBg,
    onBackground = Color(0xFF191919),
    surface = Color.White,
    onSurface = Color(0xFF191919),
    onSurfaceVariant = GptGrayMuted,
    outline = Color(0xFFD9D9D9),
    surfaceVariant = Color(0xFFF5F5F5),
    error = Color(0xFFFA5151),
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
