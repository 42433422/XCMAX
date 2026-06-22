package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun LocalProfileAvatar(
    imageSource: String,
    modifier: Modifier = Modifier,
    size: Dp = 56.dp,
    shape: Shape = CircleShape,
) {
    AppAvatar(
        imageSource = imageSource,
        fallback = AppAvatarFallback.USER,
        modifier = modifier,
        size = size,
        shape = shape,
    )
}
