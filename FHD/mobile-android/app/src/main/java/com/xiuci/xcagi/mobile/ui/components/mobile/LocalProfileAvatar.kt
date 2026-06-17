package com.xiuci.xcagi.mobile.ui.components.mobile

import android.graphics.BitmapFactory
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun LocalProfileAvatar(
        displayName: String,
        avatarUri: String,
        modifier: Modifier = Modifier,
        size: Dp = 56.dp,
        shape: Shape = CircleShape,
        containerColor: Color = MaterialTheme.colorScheme.primaryContainer,
        contentColor: Color = XcagiTheme.extra.brandBlue,
) {
    val context = LocalContext.current
    var image by remember(avatarUri) { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(avatarUri) {
        image =
                if (avatarUri.isBlank()) {
                    null
                } else {
                    withContext(Dispatchers.IO) {
                        runCatching {
                                    context.contentResolver
                                            .openInputStream(Uri.parse(avatarUri))
                                            ?.use { BitmapFactory.decodeStream(it) }
                                            ?.asImageBitmap()
                                }
                                .getOrNull()
                    }
                }
    }

    Box(
            modifier = modifier.size(size).clip(shape).background(containerColor),
            contentAlignment = Alignment.Center,
    ) {
        val bitmap = image
        if (bitmap != null) {
            Image(
                    bitmap = bitmap,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
            )
        } else {
            Text(
                    text = displayName.firstOrNull()?.uppercaseChar()?.toString() ?: "U",
                    style = MaterialTheme.typography.headlineMedium,
                    color = contentColor,
                    fontWeight = FontWeight.SemiBold,
            )
        }
    }
}
