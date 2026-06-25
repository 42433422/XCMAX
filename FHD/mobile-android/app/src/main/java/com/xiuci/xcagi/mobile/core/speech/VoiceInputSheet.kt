package com.xiuci.xcagi.mobile.core.speech

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.text.font.FontWeight
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
    val context = androidx.compose.ui.platform.LocalContext.current
    val helper = remember { SpeechRecognizerHelper(context) }
    val state by helper.state.collectAsState()
    val partial by helper.partialResult.collectAsState()
    val final by helper.finalResult.collectAsState()
    val rms by helper.rms.collectAsState()
    val errorText by helper.errorText.collectAsState()
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

    // 离开组合时释放识别器，避免泄漏（无论何种关闭路径）。
    DisposableEffect(Unit) {
        onDispose { helper.destroy() }
    }

    fun dismiss() {
        helper.destroy()
        onDismiss()
    }

    ModalBottomSheet(
            onDismissRequest = { dismiss() },
            sheetState = sheetState,
            containerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(
                modifier = Modifier.fillMaxWidth().padding(bottom = 48.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
        ) {
            val isError = state == SpeechState.ERROR
            val isListening = state == SpeechState.LISTENING
            val micColor =
                    when (state) {
                        SpeechState.LISTENING -> MaterialTheme.colorScheme.error
                        SpeechState.PROCESSING -> MaterialTheme.colorScheme.primary
                        SpeechState.ERROR -> MaterialTheme.colorScheme.onSurfaceVariant
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    }

            // 麦克风（聆听时随音量轻微缩放）
            val micScale by animateFloatAsState(
                    targetValue = if (isListening) 1f + rms * 0.35f else 1f,
                    animationSpec = spring(),
                    label = "micScale",
            )
            Box(
                    modifier = Modifier.size(132.dp),
                    contentAlignment = Alignment.Center,
            ) {
                // 聆听时的脉冲环（两层错相位向外扩散淡出）——premium「正在听」反馈
                if (isListening) {
                    val pulse = rememberInfiniteTransition(label = "voicePulse")
                    listOf(0, 750).forEach { delayMs ->
                        val p by pulse.animateFloat(
                                initialValue = 0f,
                                targetValue = 1f,
                                animationSpec = infiniteRepeatable(
                                        animation = tween(1500, delayMillis = delayMs),
                                        repeatMode = RepeatMode.Restart,
                                ),
                                label = "ring$delayMs",
                        )
                        Box(
                                modifier = Modifier
                                        .size((84 + p * 46).dp)
                                        .clip(CircleShape)
                                        .background(micColor.copy(alpha = (1f - p) * 0.16f)),
                        )
                    }
                }
                Box(
                        modifier = Modifier.size(84.dp).clip(CircleShape)
                                .background(micColor.copy(alpha = 0.12f)),
                        contentAlignment = Alignment.Center,
                ) {
                    Icon(
                            Icons.Default.Mic,
                            contentDescription = "语音输入",
                            tint = micColor,
                            modifier = Modifier.size(40.dp).scale(micScale),
                    )
                }
            }

            Spacer(Modifier.height(Spacing.md))

            // 音量波形（仅聆听态显示）
            if (isListening) {
                Waveform(level = rms, color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(Spacing.md))
            }

            // 状态文字
            val statusText =
                    when (state) {
                        SpeechState.LISTENING -> "正在聆听…"
                        SpeechState.PROCESSING -> "识别中…"
                        SpeechState.ERROR -> errorText.ifBlank { "识别失败，请重试" }
                        SpeechState.IDLE -> "点击麦克风开始说话"
                    }
            Text(
                    statusText,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (isError) FontWeight.Medium else FontWeight.Normal,
                    color = if (isError) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurface,
            )

            // 部分识别结果
            if (partial.isNotBlank() && !isError) {
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

            // 底部操作：出错时显示「重试 + 取消」，否则只显示「取消」
            Row(
                    horizontalArrangement = Arrangement.spacedBy(Spacing.xl),
                    verticalAlignment = Alignment.CenterVertically,
            ) {
                if (isError) {
                    CircleAction(
                            icon = Icons.Default.Refresh,
                            label = "重试",
                            tint = MaterialTheme.colorScheme.primary,
                            bg = MaterialTheme.colorScheme.primaryContainer,
                            onClick = { helper.start() },
                    )
                }
                CircleAction(
                        icon = Icons.Default.Close,
                        label = "取消",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        bg = MaterialTheme.colorScheme.surfaceVariant,
                        onClick = { dismiss() },
                )
            }
        }
    }
}

/** 圆形操作按钮（图标 + 文案）。 */
@Composable
private fun CircleAction(
        icon: androidx.compose.ui.graphics.vector.ImageVector,
        label: String,
        tint: androidx.compose.ui.graphics.Color,
        bg: androidx.compose.ui.graphics.Color,
        onClick: () -> Unit,
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
                modifier = Modifier.size(48.dp).clip(CircleShape).background(bg)
                        .clickable(onClick = onClick),
                contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = label, tint = tint, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.height(6.dp))
        Text(label, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** 简易音量波形：5 根随音量起伏的竖条。 */
@Composable
private fun Waveform(level: Float, color: androidx.compose.ui.graphics.Color) {
    val weights = listOf(0.3f, 0.5f, 0.72f, 0.9f, 1f, 0.9f, 0.72f, 0.5f, 0.3f)
    Row(
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.height(30.dp),
    ) {
        weights.forEach { w ->
            val target = (6f + level * 22f * w).dp
            val h by animateFloatAsState(
                    targetValue = target.value,
                    animationSpec = spring(),
                    label = "bar",
            )
            Box(
                    modifier = Modifier.width(4.dp).height(h.dp).clip(RoundedCornerShape(2.dp))
                            .background(color.copy(alpha = 0.85f)),
            )
        }
    }
}
