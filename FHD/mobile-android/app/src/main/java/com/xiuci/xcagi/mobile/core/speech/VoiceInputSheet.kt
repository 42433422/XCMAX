package com.xiuci.xcagi.mobile.core.speech

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.Spacing

/**
 * 语音输入底部弹窗。
 *
 * @param onResult 识别完成回调，返回识别到的文字
 * @param onDismiss 关闭回调
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceInputSheet(
        onResult: (String) -> Unit,
        onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val helper = remember { SpeechRecognizerHelper(context) }
    val state by helper.state.collectAsState()
    val partial by helper.partialResult.collectAsState()
    val final by helper.finalResult.collectAsState()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    // 进入时自动开始监听
    LaunchedEffect(Unit) { helper.start() }

    // 识别完成时回调
    LaunchedEffect(final) {
        if (final.isNotBlank()) {
            onResult(final)
            helper.destroy()
            onDismiss()
        }
    }

    // 出错时自动关闭
    LaunchedEffect(state) {
        if (state == SpeechState.ERROR) {
            helper.destroy()
            onDismiss()
        }
    }

    ModalBottomSheet(
            onDismissRequest = {
                helper.destroy()
                onDismiss()
            },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(
                modifier = Modifier.fillMaxWidth().padding(bottom = 48.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
        ) {
            // 麦克风动画
            val infiniteTransition = rememberInfiniteTransition(label = "mic")
            val scale by
                    infiniteTransition.animateFloat(
                            initialValue = 1f,
                            targetValue = 1.3f,
                            animationSpec =
                                    infiniteRepeatable(
                                            animation = tween(800),
                                            repeatMode = RepeatMode.Reverse,
                                    ),
                            label = "micScale",
                    )

            val isListening = state == SpeechState.LISTENING || state == SpeechState.PROCESSING
            val micColor =
                    when (state) {
                        SpeechState.LISTENING -> MaterialTheme.colorScheme.error
                        SpeechState.PROCESSING -> MaterialTheme.colorScheme.primary
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    }

            Box(
                    modifier = Modifier.size(80.dp).clip(CircleShape).background(micColor.copy(alpha = 0.12f)),
                    contentAlignment = Alignment.Center,
            ) {
                Icon(
                        Icons.Default.Mic,
                        contentDescription = "语音输入",
                        tint = micColor,
                        modifier = Modifier.size(40.dp).scale(if (isListening) scale else 1f),
                )
            }

            Spacer(Modifier.height(Spacing.md))

            // 状态文字
            val statusText =
                    when (state) {
                        SpeechState.LISTENING -> "正在聆听…"
                        SpeechState.PROCESSING -> "识别中…"
                        SpeechState.ERROR -> "识别失败，请重试"
                        SpeechState.IDLE -> "点击麦克风开始说话"
                    }
            Text(
                    statusText,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
            )

            // 部分识别结果
            if (partial.isNotBlank()) {
                Spacer(Modifier.height(Spacing.sm))
                Text(
                        partial,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = Spacing.lg),
                )
            }

            Spacer(Modifier.height(Spacing.lg))

            // 取消按钮
            Box(
                    modifier = Modifier
                            .size(40.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.surfaceVariant)
                            .padding(0.dp),
                    contentAlignment = Alignment.Center,
            ) {
                Icon(
                        Icons.Default.Close,
                        contentDescription = "取消",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}
