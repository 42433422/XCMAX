package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun CodexAppAvatar(
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    cornerRadius: Dp = 13.dp,
    contentPadding: Dp = 0.dp,
) {
    AppAvatar(
        fallback = AppAvatarFallback.CODEX,
        modifier = modifier,
        size = size - (contentPadding * 2),
        shape = RoundedCornerShape(cornerRadius),
    )
}
