package com.xiuci.xcagi.mobile.core.speech

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceInputDesignTest {
    @Test
    fun `voice status labels are centralized`() {
        assertEquals("正在听", VoiceInputDesign.statusLabel(SpeechState.LISTENING))
        assertEquals("识别中", VoiceInputDesign.statusLabel(SpeechState.PROCESSING))
        assertEquals("没听清", VoiceInputDesign.statusLabel(SpeechState.ERROR))
        assertEquals("网络异常", VoiceInputDesign.statusLabel(SpeechState.ERROR, "网络异常"))
        assertEquals("语音输入", VoiceInputDesign.statusLabel(SpeechState.IDLE))
        assertEquals("识别完成", VoiceInputDesign.statusLabel(SpeechState.IDLE, hasResult = true))
    }

    @Test
    fun `voice action labels are centralized`() {
        assertEquals("完成", VoiceInputDesign.primaryActionLabel(SpeechState.LISTENING))
        assertEquals("识别中", VoiceInputDesign.primaryActionLabel(SpeechState.PROCESSING))
        assertEquals("重试", VoiceInputDesign.primaryActionLabel(SpeechState.ERROR))
        assertEquals("插入", VoiceInputDesign.primaryActionLabel(SpeechState.IDLE, hasResult = true))
    }

    @Test
    fun `waveform uses stable balanced bars`() {
        assertEquals(8, VoiceInputDesign.waveformWeights.size)
        assertTrue(VoiceInputDesign.waveformWeights.all { it in 0.3f..1f })
    }
}
