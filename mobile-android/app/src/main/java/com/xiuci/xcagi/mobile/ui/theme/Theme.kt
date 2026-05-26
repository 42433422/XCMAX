package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val XiuciBlue = Color(0xFF3584E4)
private val XiuciBlueDark = Color(0xFF1A5FB4)
private val BgDark = Color(0xFF0A0A0F)
private val SurfaceDark = Color(0xFF14141A)
private val OnSurfaceMuted = Color(0xFFB8B8C0)

private val DarkColors = darkColorScheme(
    primary = XiuciBlue,
    onPrimary = Color.White,
    primaryContainer = XiuciBlueDark,
    secondary = Color(0xFF34D399),
    background = BgDark,
    onBackground = Color(0xFFF0F0F5),
    surface = SurfaceDark,
    onSurface = Color(0xFFF0F0F5),
    onSurfaceVariant = OnSurfaceMuted,
    outline = Color(0x33FFFFFF),
)

@Composable
fun XcagiTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColors,
        content = content,
    )
}
