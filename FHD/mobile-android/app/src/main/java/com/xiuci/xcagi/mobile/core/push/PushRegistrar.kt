package com.xiuci.xcagi.mobile.core.push

import android.content.Context
import android.content.pm.PackageManager
import cn.jpush.android.api.JPushInterface
import com.google.firebase.messaging.FirebaseMessaging
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.repository.XcagiRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.tasks.await
import javax.inject.Inject
import javax.inject.Singleton

data class PushRegisterResult(
    val fcmRegistered: Boolean,
    val jpushRegistered: Boolean,
    val hint: String?,
)

@Singleton
class PushRegistrar @Inject constructor(
    @ApplicationContext private val context: Context,
    private val sessionStore: SessionStore,
    private val repo: XcagiRepository,
) {
    fun initSdk() {
        NotificationChannels.ensure(context)
        try {
            JPushInterface.setDebugMode(false)
            JPushInterface.init(context)
        } catch (_: Exception) {
        }
    }

    private fun isJpushConfigured(): Boolean {
        return try {
            val ai = context.packageManager.getApplicationInfo(
                context.packageName,
                PackageManager.GET_META_DATA,
            )
            val key = ai.metaData?.getString("JPUSH_APPKEY").orEmpty().trim()
            key.isNotBlank() && !key.contains("placeholder", ignoreCase = true)
        } catch (_: Exception) {
            false
        }
    }

    suspend fun registerAll(): PushRegisterResult {
        initSdk()
        var fcmOk = false
        var jpushOk = false
        val hints = mutableListOf<String>()

        var fcm = PushTokenHolder.fcmToken
        if (fcm.isBlank()) {
            try {
                fcm = FirebaseMessaging.getInstance().token.await()
                PushTokenHolder.fcmToken = fcm
            } catch (e: Exception) {
                hints.add("FCM 未就绪：${e.message ?: "请检查 google-services.json"}")
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

        if (!isJpushConfigured()) {
            hints.add("极光推送未配置（local.properties 缺少 JPUSH_APPKEY）")
        } else {
            try {
                val rid = JPushInterface.getRegistrationID(context)
                if (!rid.isNullOrBlank()) {
                    PushTokenHolder.jpushRegistrationId = rid
                    try {
                        repo.registerDeviceToken(pushProvider = "jpush", pushToken = rid)
                        jpushOk = true
                    } catch (_: Exception) {
                        hints.add("极光注册失败")
                    }
                } else {
                    hints.add("极光 RegistrationID 为空")
                }
            } catch (e: Exception) {
                hints.add("极光 SDK 异常：${e.message ?: "未知"}")
            }
        }

        return PushRegisterResult(
            fcmRegistered = fcmOk,
            jpushRegistered = jpushOk,
            hint = hints.takeIf { it.isNotEmpty() }?.joinToString("；"),
        )
    }

    fun unregisterAll() {
        try {
            JPushInterface.deleteAlias(context, 0)
        } catch (_: Exception) {
        }
    }
}
