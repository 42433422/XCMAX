package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

object MobileTokens {
    val horizontalPagePadding = 20.dp
    val cornerCard = RoundedCornerShape(12.dp)
    val cornerPill = RoundedCornerShape(50)

    @Composable
    fun pageBackground(): Color = MaterialTheme.colorScheme.background

    @Composable
    fun surfaceRaised(): Color = MaterialTheme.colorScheme.surface
}
