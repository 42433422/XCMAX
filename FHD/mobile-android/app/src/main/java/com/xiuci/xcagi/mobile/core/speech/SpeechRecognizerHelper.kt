package com.xiuci.xcagi.mobile.core.speech

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
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
 * 使用中文语言模型，支持部分结果实时回调。
 */
class SpeechRecognizerHelper(private val context: Context) {

    private var recognizer: SpeechRecognizer? = null

    private val _state = MutableStateFlow(SpeechState.IDLE)
    val state: StateFlow<SpeechState> = _state.asStateFlow()

    private val _partialResult = MutableStateFlow("")
    val partialResult: StateFlow<String> = _partialResult.asStateFlow()

    private val _finalResult = MutableStateFlow("")
    val finalResult: StateFlow<String> = _finalResult.asStateFlow()

    /** 语音识别是否可用 */
    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    /** 开始监听语音 */
    fun start() {
        if (!isAvailable()) {
            _state.value = SpeechState.ERROR
            return
        }
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    _state.value = SpeechState.LISTENING
                }

                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}

                override fun onEndOfSpeech() {
                    _state.value = SpeechState.PROCESSING
                }

                override fun onError(error: Int) {
                    _state.value = SpeechState.ERROR
                }

                override fun onResults(results: Bundle?) {
                    val matches =
                            results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    _finalResult.value = matches?.firstOrNull().orEmpty()
                    _state.value = SpeechState.IDLE
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val partial =
                            partialResults
                                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                                    ?.firstOrNull()
                                    .orEmpty()
                    if (partial.isNotBlank()) _partialResult.value = partial
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }

        _partialResult.value = ""
        _finalResult.value = ""

        val intent =
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(
                            RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                            RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
                    )
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                }
        recognizer?.startListening(intent)
    }

    /** 停止监听 */
    fun stop() {
        recognizer?.stopListening()
        _state.value = SpeechState.IDLE
    }

    /** 释放资源 */
    fun destroy() {
        recognizer?.destroy()
        recognizer = null
        _state.value = SpeechState.IDLE
    }
}
