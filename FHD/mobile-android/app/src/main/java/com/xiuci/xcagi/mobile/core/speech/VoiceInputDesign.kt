package com.xiuci.xcagi.mobile.core.speech

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

object VoiceInputDesign {
    val sheetTopCornerRadius = 28.dp
    val sheetHorizontalPadding = 20.dp
    val sheetTopPadding = 6.dp
    val sheetBottomPadding = 28.dp
    val cardCornerRadius = 22.dp
    val cardVerticalPadding = 18.dp
    val micOuterSize = 92.dp
    val micInnerSize = 64.dp
    val micIconSize = 30.dp
    val waveformHeight = 42.dp
    val waveformBarWidth = 4.dp
    val waveformBarGap = 5.dp
    val actionHeight = 48.dp
    val dragHandleWidth = 42.dp
    val dragHandleHeight = 5.dp
    val dragHandleCornerRadius = 999.dp
    val previewMinHeight = 42.dp
    val previewCornerRadius = 16.dp

    val waveformWeights = listOf(0.36f, 0.52f, 0.78f, 1f, 0.72f, 0.9f, 0.6f, 0.42f)

    data class Palette(
        val sheetBackground: Color,
        val dragHandle: Color,
        val statusBackground: Color,
        val statusForeground: Color,
        val cardBackground: Color,
        val cardBorder: Color,
        val micBackground: Color,
        val micForeground: Color,
        val pulse: Color,
        val waveform: Color,
        val previewBackground: Color,
        val previewForeground: Color,
        val previewPlaceholder: Color,
        val cancelForeground: Color,
        val primaryBackground: Color,
        val primaryForeground: Color,
        val disabledPrimaryBackground: Color,
        val disabledPrimaryForeground: Color,
    )

    @Composable
    fun palette(state: SpeechState): Palette {
        val extra = XcagiTheme.extra
        val isError = state == SpeechState.ERROR
        val isListening = state == SpeechState.LISTENING
        val statusTint =
            when (state) {
                SpeechState.LISTENING -> extra.success
                SpeechState.PROCESSING -> extra.brandBlue
                SpeechState.ERROR -> MaterialTheme.colorScheme.error
                SpeechState.IDLE -> extra.n700
            }

        return Palette(
            sheetBackground = extra.n50,
            dragHandle = extra.n300.copy(alpha = 0.72f),
            statusBackground = statusTint.copy(alpha = if (isError) 0.13f else 0.10f),
            statusForeground = statusTint,
            cardBackground = extra.n100.copy(alpha = 0.62f),
            cardBorder = extra.n200.copy(alpha = 0.78f),
            micBackground = extra.n00,
            micForeground = if (isError) MaterialTheme.colorScheme.error else extra.n900,
            pulse = if (isListening) extra.success else extra.n400,
            waveform = if (isError) MaterialTheme.colorScheme.error else extra.n700,
            previewBackground = extra.n00,
            previewForeground = extra.n800,
            previewPlaceholder = if (isError) MaterialTheme.colorScheme.error else extra.n500,
            cancelForeground = extra.n700,
            primaryBackground = if (isError) MaterialTheme.colorScheme.error else extra.n900,
            primaryForeground = extra.n00,
            disabledPrimaryBackground = extra.n200,
            disabledPrimaryForeground = extra.n500,
        )
    }

    fun statusLabel(state: SpeechState, errorText: String = "", hasResult: Boolean = false): String =
        if (hasResult) {
            "识别完成"
        } else when (state) {
            SpeechState.LISTENING -> "正在听"
            SpeechState.PROCESSING -> "识别中"
            SpeechState.ERROR -> errorText.ifBlank { "没听清" }
            SpeechState.IDLE -> "语音输入"
        }

    fun primaryActionLabel(state: SpeechState, hasResult: Boolean = false): String =
        if (hasResult) {
            "插入"
        } else when (state) {
            SpeechState.ERROR -> "重试"
            SpeechState.PROCESSING -> "识别中"
            else -> "完成"
        }
}
