package com.xiuci.xcagi.mobile.core.speech

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** 语音识别状态 */
enum class SpeechState {
    IDLE,       // 空闲
    LISTENING,  // 正在听
    PROCESSING, // 识别中
    ERROR,      // 出错
}

/**
 * 封装 Android SpeechRecognizer，提供语音转文字能力。
 * 使用中文语言模型，支持部分结果、实时音量与错误码友好提示。
 */
class SpeechRecognizerHelper(private val context: Context) {

    private var recognizer: SpeechRecognizer? = null

    private val _state = MutableStateFlow(SpeechState.IDLE)
    val state: StateFlow<SpeechState> = _state.asStateFlow()

    private val _partialResult = MutableStateFlow("")
    val partialResult: StateFlow<String> = _partialResult.asStateFlow()

    private val _finalResult = MutableStateFlow("")
    val finalResult: StateFlow<String> = _finalResult.asStateFlow()

    /** 归一化音量 0f..1f，驱动波形动画 */
    private val _rms = MutableStateFlow(0f)
    val rms: StateFlow<Float> = _rms.asStateFlow()

    /** 出错时的友好提示文案 */
    private val _errorText = MutableStateFlow("")
    val errorText: StateFlow<String> = _errorText.asStateFlow()

    /** 语音识别是否可用 */
    fun isAvailable(): Boolean =
        SpeechRecognizer.isRecognitionAvailable(context) || recognitionServiceComponent() != null

    /** 开始监听语音（重试也调用此方法）。 */
    fun start() {
        if (!isAvailable()) {
            _errorText.value = "当前设备未提供语音识别服务"
            _state.value = SpeechState.ERROR
            return
        }
        recognizer?.destroy()
        _partialResult.value = ""
        _finalResult.value = ""
        _errorText.value = ""
        _rms.value = 0f
        val serviceComponent = recognitionServiceComponent()
        recognizer = (serviceComponent?.let { component ->
            SpeechRecognizer.createSpeechRecognizer(context, component)
        } ?: SpeechRecognizer.createSpeechRecognizer(context)).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    _state.value = SpeechState.LISTENING
                }

                override fun onBeginningOfSpeech() {}

                override fun onRmsChanged(rmsdB: Float) {
                    // SpeechRecognizer 的 rmsdB 大致 -2f..12f，归一化到 0f..1f。
                    _rms.value = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
                }

                override fun onBufferReceived(buffer: ByteArray?) {}

                override fun onEndOfSpeech() {
                    _rms.value = 0f
                    _state.value = SpeechState.PROCESSING
                }

                override fun onError(error: Int) {
                    _rms.value = 0f
                    _errorText.value = friendlyError(error)
                    _state.value = SpeechState.ERROR
                }

                override fun onResults(results: Bundle?) {
                    val text = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        .orEmpty()
                    if (text.isBlank()) {
                        _errorText.value = "没听清，请再说一次"
                        _state.value = SpeechState.ERROR
                    } else {
                        _finalResult.value = text
                        _state.value = SpeechState.IDLE
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val partial = partialResults
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        .orEmpty()
                    if (partial.isNotBlank()) _partialResult.value = partial
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            // 静音判定时长（OEM 实现可能忽略，作为提示）：说完 1.2s 静音即结束，体验更跟手。
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1200L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 800L)
        }
        recognizer?.startListening(intent)
    }

    /** 停止监听 */
    fun stop() {
        recognizer?.stopListening()
        _rms.value = 0f
        if (_state.value == SpeechState.LISTENING) {
            _state.value = SpeechState.PROCESSING
        }
    }

    /** 释放资源 */
    fun destroy() {
        recognizer?.destroy()
        recognizer = null
        _rms.value = 0f
        _state.value = SpeechState.IDLE
    }

    private fun recognitionServiceComponent(): ComponentName? {
        val serviceIntent = Intent(RecognitionService.SERVICE_INTERFACE)
        @Suppress("DEPRECATION")
        val services = context.packageManager.queryIntentServices(
            serviceIntent,
            0,
        )
        return services.firstOrNull()?.serviceInfo?.let { serviceInfo ->
            ComponentName(serviceInfo.packageName, serviceInfo.name)
        }
    }

    /** 错误码 → 友好中文提示。 */
    private fun friendlyError(error: Int): String =
        when (error) {
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
                "网络异常，请检查网络后重试"
            SpeechRecognizer.ERROR_AUDIO -> "录音出错，请重试"
            SpeechRecognizer.ERROR_NO_MATCH -> "没听清，请再说一次"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有检测到说话，请再试一次"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别服务忙，请稍后重试"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "缺少麦克风权限"
            SpeechRecognizer.ERROR_SERVER -> "识别服务异常，请稍后重试"
            SpeechRecognizer.ERROR_CLIENT -> "识别服务启动失败，请重试"
            else -> "识别失败，请重试"
        }
}
