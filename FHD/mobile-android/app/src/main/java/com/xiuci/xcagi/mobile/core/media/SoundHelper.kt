package com.xiuci.xcagi.mobile.core.media

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool
import com.xiuci.xcagi.mobile.R

/**
 * 短音效播放工具（基于 SoundPool，低延迟适合 UI 反馈）
 *
 * 使用方式： SoundHelper.init(context) // Application.onCreate 中调用一次 SoundHelper.playSuccess() // 成功提示音
 * SoundHelper.playError() // 错误提示音 SoundHelper.playNotify() // 通知提示音（消息到达）
 */
object SoundHelper {

    private const val SOUND_ENABLED = false

    private var pool: SoundPool? = null
    private var soundSuccess: Int = 0
    private var soundError: Int = 0
    private var soundNotify: Int = 0

    @Volatile private var initialized = false

    fun init(context: Context) {
        if (!SOUND_ENABLED) return
        if (initialized) return
        pool =
                SoundPool.Builder()
                        .setMaxStreams(3)
                        .setAudioAttributes(
                                AudioAttributes.Builder()
                                        .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                                        .build()
                        )
                        .build()
        soundSuccess = pool!!.load(context, R.raw.im_in, 1)
        soundError = pool!!.load(context, R.raw.im_in, 2) // 复用现有资源
        soundNotify = pool!!.load(context, R.raw.im_in, 3) // 复用现有资源
        initialized = true
    }

    fun playSuccess() {
        if (!SOUND_ENABLED) return
        pool?.play(soundSuccess, 0.18f, 0.18f, 0, 0, 0.95f)
    }

    fun playError() {
        if (!SOUND_ENABLED) return
        pool?.play(soundError, 0.12f, 0.12f, 0, 0, 0.85f)
    }

    fun playNotify() {
        if (!SOUND_ENABLED) return
        pool?.play(soundNotify, 0.14f, 0.14f, 0, 0, 1.0f)
    }

    fun release() {
        pool?.release()
        pool = null
        initialized = false
    }
}
