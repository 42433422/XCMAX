package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.R

@Composable
fun CodexAppAvatar(
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    cornerRadius: Dp = 13.dp,
    contentPadding: Dp = 0.dp,
) {
    Box(
        modifier = modifier
            .size(size)
            .clip(RoundedCornerShape(cornerRadius)),
        contentAlignment = Alignment.Center,
    ) {
        Image(
            painter = painterResource(R.drawable.codex_app_icon),
            contentDescription = null,
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding),
            contentScale = ContentScale.Fit,
        )
    }
}
