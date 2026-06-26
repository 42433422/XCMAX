package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.annotation.DrawableRes
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.xiuci.xcagi.mobile.R

/**
 * 固定的图片头像兜底。禁止用姓名首字母或随机颜色生成头像，确保所有页面身份一致。
 */
enum class AppAvatarFallback(@DrawableRes val drawableRes: Int) {
    USER(R.drawable.avatar_default_user),
    ASSISTANT(R.drawable.avatar_assistant),
    CUSTOMER_SERVICE(R.drawable.avatar_default_ai_employee),
    AI_EMPLOYEE(R.drawable.avatar_default_ai_employee),
    CODEX(R.drawable.codex_app_icon),
    CLAUDE(R.drawable.claude_app_icon),
    CURSOR(R.drawable.cursor_app_icon),
    TRAE(R.drawable.trae_app_icon),
}

@Composable
fun AppAvatar(
    imageSource: Any? = null,
    fallback: AppAvatarFallback,
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    shape: Shape,
    contentDescription: String? = null,
) {
    val source = imageSource?.takeUnless { it is String && it.isBlank() }
    val fallbackPainter = painterResource(fallback.drawableRes)
    val imageModifier = modifier.size(size).clip(shape)

    if (source == null) {
        Image(
            painter = fallbackPainter,
            contentDescription = contentDescription,
            modifier = imageModifier,
            contentScale = ContentScale.Crop,
        )
    } else {
        AsyncImage(
            model = source,
            contentDescription = contentDescription,
            modifier = imageModifier,
            placeholder = fallbackPainter,
            error = fallbackPainter,
            fallback = fallbackPainter,
            contentScale = ContentScale.Crop,
        )
    }
}
