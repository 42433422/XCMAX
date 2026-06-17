package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

object MobileTokens {
    val horizontalPagePadding = 16.dp
    val itemSpacing = 8.dp
    val cornerCard = RoundedCornerShape(12.dp)
    val cornerChip = RoundedCornerShape(6.dp)
    val cornerInputBar = RoundedCornerShape(20.dp)

    @Composable
    fun accent(): Color = MaterialTheme.colorScheme.primary

    @Composable
    fun pending(): Color = MaterialTheme.colorScheme.onSurfaceVariant

    @Composable
    fun success(): Color = Color(0xFF07C160)

    @Composable
    fun danger(): Color = MaterialTheme.colorScheme.error

    @Composable
    fun warning(): Color = Color(0xFFFA9D3B)

    @Composable
    fun chipSelectedBg(): Color = MaterialTheme.colorScheme.primaryContainer

    @Composable
    fun chipUnselectedBg(): Color = MaterialTheme.colorScheme.surfaceVariant
}
