package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.delay

/** 消息类型 */
enum class SnackType {
	SUCCESS,
	ERROR,
	INFO
}

/** 消息数据 */
data class SnackData(
	val text: String,
	val type: SnackType = SnackType.INFO,
)

/**
 * 微信风格顶部消息提示条
 *
 * - 成功：绿色 + 对勾图标
 * - 错误：红色 + 感叹图标
 * - 信息：蓝色 + 信息图标
 * - 自动 2.5s 后消失，带滑入/滑出动画
 */
@Composable
fun WeSnackBar(
	message: SnackData?,
	onDismiss: () -> Unit,
	modifier: Modifier = Modifier,
) {
	val (bgColor, icon, tintColor) =
		when (message?.type) {
			SnackType.SUCCESS ->
				Triple(XcagiTheme.extra.success, Icons.Default.CheckCircle, Color.White)
			SnackType.ERROR ->
				Triple(XcagiTheme.extra.danger, Icons.Default.Error, Color.White)
			SnackType.INFO ->
				Triple(XcagiTheme.extra.brandBlue, Icons.Default.Info, Color.White)
			null -> return
		}

	var visible by remember { mutableStateOf(false) }

	LaunchedEffect(message) {
		if (message != null) {
			visible = true
			delay(2500)
			visible = false
			delay(300) // 等待退出动画完成
			onDismiss()
		}
	}

	AnimatedVisibility(
		visible = visible,
		enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(),
		exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut(),
		modifier = modifier.fillMaxWidth(),
	) {
		Box(
			modifier =
				Modifier.fillMaxWidth()
					.padding(horizontal = Spacing.lg, vertical = Spacing.sm),
			contentAlignment = Alignment.TopCenter,
		) {
			Row(
				Modifier.clip(MaterialTheme.shapes.small)
					.background(bgColor)
					.padding(horizontal = Spacing.lg, vertical = 10.dp),
				verticalAlignment = Alignment.CenterVertically,
			) {
				Icon(
					icon,
					contentDescription = null,
					tint = tintColor,
					modifier = Modifier.size(20.dp),
				)
				Text(
					text = message.text,
					color = Color.White,
					style = MaterialTheme.typography.bodySmall,
					fontWeight = FontWeight.Medium,
					modifier = Modifier.padding(start = Spacing.sm),
				)
			}
		}
	}
}
