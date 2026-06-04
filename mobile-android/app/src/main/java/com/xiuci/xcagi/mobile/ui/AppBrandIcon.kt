package com.xiuci.xcagi.mobile.ui

import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.core.graphics.drawable.toBitmap

/**
 * 应用内品牌图标。勿对 [R.mipmap.ic_launcher] 使用 [painterResource]：
 * API 26+ 为 adaptive-icon XML，Compose 仅支持 VectorDrawable 与位图。
 */
@Composable
fun AppBrandIcon(
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
) {
    val context = LocalContext.current
    val bitmap = remember(context.packageName) {
        context.packageManager.getApplicationIcon(context.packageName).toBitmap()
    }
    Image(
        bitmap = bitmap.asImageBitmap(),
        contentDescription = contentDescription,
        modifier = modifier,
        contentScale = ContentScale.Fit,
    )
}
