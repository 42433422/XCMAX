package com.xiuci.xcagi.mobile.core.speech

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing

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
    val finalText = final.trim()
    val recognizedText = finalText.ifBlank { partial }
    val hasFinalResult = finalText.isNotBlank()

    LaunchedEffect(Unit) { helper.start() }

    DisposableEffect(Unit) {
        onDispose { helper.destroy() }
    }

    fun dismiss() {
        helper.destroy()
        onDismiss()
    }

    fun primaryAction() {
        when {
            hasFinalResult -> {
                onResult(finalText)
                dismiss()
            }
            state == SpeechState.ERROR -> helper.start()
            state == SpeechState.PROCESSING -> Unit
            else -> helper.stop()
        }
    }

    ModalBottomSheet(
        onDismissRequest = { dismiss() },
        sheetState = sheetState,
        containerColor = VoiceInputDesign.palette(state).sheetBackground,
        tonalElevation = Elevation.level3,
        shape = RoundedCornerShape(
            topStart = VoiceInputDesign.sheetTopCornerRadius,
            topEnd = VoiceInputDesign.sheetTopCornerRadius,
        ),
        dragHandle = { VoiceDragHandle() },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = VoiceInputDesign.sheetHorizontalPadding)
                .padding(top = VoiceInputDesign.sheetTopPadding, bottom = VoiceInputDesign.sheetBottomPadding),
            verticalArrangement = Arrangement.spacedBy(Spacing.lg),
        ) {
            VoiceSheetHeader(
                state = state,
                errorText = errorText,
                hasResult = hasFinalResult,
                onDismiss = { dismiss() },
            )
            VoiceListeningCard(
                state = state,
                rms = rms,
                preview = recognizedText,
                errorText = errorText,
                hasResult = hasFinalResult,
            )
            VoiceActionRow(
                state = state,
                hasResult = hasFinalResult,
                onPrimary = { primaryAction() },
                onCancel = { dismiss() },
            )
        }
    }
}

@Composable
private fun VoiceDragHandle() {
    val palette = VoiceInputDesign.palette(SpeechState.IDLE)
    Box(
        modifier = Modifier
            .padding(top = Spacing.sm, bottom = Spacing.xs)
            .size(width = VoiceInputDesign.dragHandleWidth, height = VoiceInputDesign.dragHandleHeight)
            .clip(RoundedCornerShape(VoiceInputDesign.dragHandleCornerRadius))
            .background(palette.dragHandle),
    )
}

@Composable
private fun VoiceSheetHeader(
    state: SpeechState,
    errorText: String,
    hasResult: Boolean,
    onDismiss: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = "语音输入",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.xs))
            VoiceStatusPill(state = state, errorText = errorText, hasResult = hasResult)
        }
        IconButton(onClick = onDismiss) {
            Icon(
                Icons.Default.Close,
                contentDescription = "关闭",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun VoiceStatusPill(state: SpeechState, errorText: String, hasResult: Boolean) {
    val palette = VoiceInputDesign.palette(state)
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = palette.statusBackground,
    ) {
        Text(
            text = VoiceInputDesign.statusLabel(state, errorText, hasResult),
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = 5.dp),
            style = MaterialTheme.typography.labelMedium,
            color = palette.statusForeground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun VoiceListeningCard(
    state: SpeechState,
    rms: Float,
    preview: String,
    errorText: String,
    hasResult: Boolean,
) {
    val isListening = state == SpeechState.LISTENING
    val palette = VoiceInputDesign.palette(state)
    val micScale by animateFloatAsState(
        targetValue = if (isListening) 1f + rms * 0.22f else 1f,
        animationSpec = spring(),
        label = "voiceMicScale",
    )

    val cardShape = RoundedCornerShape(VoiceInputDesign.cardCornerRadius)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(cardShape)
            .background(palette.cardBackground)
            .border(1.dp, palette.cardBorder, cardShape),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = Spacing.lg, vertical = VoiceInputDesign.cardVerticalPadding),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.lg),
            ) {
                Box(
                    modifier = Modifier.size(VoiceInputDesign.micOuterSize),
                    contentAlignment = Alignment.Center,
                ) {
                    if (isListening) VoicePulse(palette.pulse)
                    Box(
                        modifier = Modifier
                            .size(VoiceInputDesign.micInnerSize)
                            .clip(CircleShape)
                            .background(palette.micBackground),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Default.Mic,
                            contentDescription = "语音输入",
                            tint = palette.micForeground,
                            modifier = Modifier
                                .size(VoiceInputDesign.micIconSize)
                                .scale(micScale),
                        )
                    }
                }
                VoiceWaveform(
                    level = if (isListening) rms else 0.16f,
                    color = palette.waveform,
                    modifier = Modifier.weight(1f),
                )
            }

            val previewShape = RoundedCornerShape(VoiceInputDesign.previewCornerRadius)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = VoiceInputDesign.previewMinHeight)
                    .clip(previewShape)
                    .background(palette.previewBackground),
            ) {
                val displayText = preview.ifBlank { VoiceInputDesign.statusLabel(state, errorText, hasResult) }
                Text(
                    text = displayText,
                    modifier = Modifier.padding(horizontal = Spacing.lg, vertical = Spacing.md),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (preview.isBlank()) palette.previewPlaceholder else palette.previewForeground,
                    textAlign = TextAlign.Start,
                )
            }
        }
    }
}

@Composable
private fun VoicePulse(color: androidx.compose.ui.graphics.Color) {
    val pulse = rememberInfiniteTransition(label = "voicePulse")
    listOf(0, 520).forEach { delayMs ->
        val p by pulse.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(1320, delayMillis = delayMs),
                repeatMode = RepeatMode.Restart,
            ),
            label = "voicePulse$delayMs",
        )
        Box(
            modifier = Modifier
                .size((VoiceInputDesign.micInnerSize.value + 30f * p).dp)
                .clip(CircleShape)
                .background(color.copy(alpha = (1f - p) * 0.15f)),
        )
    }
}

@Composable
private fun VoiceWaveform(
    level: Float,
    color: androidx.compose.ui.graphics.Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.height(VoiceInputDesign.waveformHeight),
        horizontalArrangement = Arrangement.spacedBy(VoiceInputDesign.waveformBarGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        VoiceInputDesign.waveformWeights.forEachIndexed { index, weight ->
            val targetHeight = 8f + (level.coerceIn(0f, 1f) * 30f * weight)
            val animatedHeight by animateFloatAsState(
                targetValue = targetHeight,
                animationSpec = spring(),
                label = "voiceBar$index",
            )
            Box(
                modifier = Modifier
                    .width(VoiceInputDesign.waveformBarWidth)
                    .height(animatedHeight.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(color.copy(alpha = 0.34f + weight * 0.42f)),
            )
        }
    }
}

@Composable
private fun VoiceActionRow(
    state: SpeechState,
    hasResult: Boolean,
    onPrimary: () -> Unit,
    onCancel: () -> Unit,
) {
    val isProcessing = state == SpeechState.PROCESSING
    val palette = VoiceInputDesign.palette(state)
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md),
    ) {
        TextButton(
            onClick = onCancel,
            modifier = Modifier
                .weight(1f)
                .height(VoiceInputDesign.actionHeight),
        ) {
            Text("取消", color = palette.cancelForeground)
        }
        Button(
            onClick = onPrimary,
            enabled = !isProcessing,
            modifier = Modifier
                .weight(1f)
                .height(VoiceInputDesign.actionHeight),
            colors = ButtonDefaults.buttonColors(
                containerColor = palette.primaryBackground,
                contentColor = palette.primaryForeground,
                disabledContainerColor = palette.disabledPrimaryBackground,
                disabledContentColor = palette.disabledPrimaryForeground,
            ),
            shape = RoundedCornerShape(999.dp),
        ) {
            val icon = when {
                hasResult -> Icons.Default.Check
                state == SpeechState.ERROR -> Icons.Default.Refresh
                else -> Icons.Default.Mic
            }
            Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(Spacing.xs))
            Text(VoiceInputDesign.primaryActionLabel(state, hasResult))
        }
    }
}
