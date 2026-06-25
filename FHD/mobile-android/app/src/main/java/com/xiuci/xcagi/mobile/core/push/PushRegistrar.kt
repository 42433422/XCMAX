package com.xiuci.xcagi.mobile.core.push

import android.content.Context
import com.google.firebase.messaging.FirebaseMessaging
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.repository.XcagiRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.tasks.await

data class PushRegisterResult(
    val fcmRegistered: Boolean,
    val hint: String?,
)

/**
 * 推送注册。
 *
 * 通道：
 * - FCM（有 Google 服务的机型）：拿 token 注册到后端，离线时由 FCM 唤醒。
 * - 自建推送（国产无 GMS 机型的主通道）：前台 [PushSocket] 长连实时下发，
 *   后台 [PushPollWorker] 定时拉 `/api/notifications/pending` 兜底——以会话态鉴权，
 *   不需要在这里单独注册 token。
 *
 * 极光 JPush 已移除（厂商通道随之失去，国产机后台送达率下降，属预期取舍）。
 */
@Singleton
class PushRegistrar @Inject constructor(
    @ApplicationContext private val context: Context,
    private val sessionStore: SessionStore,
    private val repo: XcagiRepository,
) {
    fun initSdk() {
        NotificationChannels.ensure(context)
    }

    suspend fun registerAll(): PushRegisterResult {
        initSdk()
        var fcmOk = false
        val hints = mutableListOf<String>()

        var fcm = PushTokenHolder.fcmToken
        if (fcm.isBlank()) {
            try {
                fcm = FirebaseMessaging.getInstance().token.await()
                PushTokenHolder.fcmToken = fcm
            } catch (e: Exception) {
                // Push is optional for the mobile control loop. Missing Firebase config
                // must not surface as a blocking product error during pairing/login.
            }
        }
        if (fcm.isNotBlank()) {
            sessionStore.setFcmToken(fcm)
            try {
                repo.registerDeviceToken(pushProvider = "fcm", pushToken = fcm)
                fcmOk = true
            } catch (_: Exception) {
                hints.add("FCM 注册失败")
            }
        }

        return PushRegisterResult(
            fcmRegistered = fcmOk,
            hint = hints.takeIf { it.isNotEmpty() }?.joinToString("；"),
        )
    }

    fun unregisterAll() {
        // 自建推送随会话登出而断连（见 PushSocket）；FCM token 由后端按设备清理。
        // 无第三方推送 SDK 需要反注册。
    }
}
