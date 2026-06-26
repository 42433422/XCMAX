package com.xiuci.xcagi.mobile.core.push

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.xiuci.xcagi.mobile.MainActivity
import com.xiuci.xcagi.mobile.R

/**
 * 推送消息公共处理器：FCM 与自建推送（PushSocket / PushPollWorker）共用。
 *
 * 职责：
 * - 解析推送 data（title/body/route/channel/message_id/session_id/source）
 * - 弹通知（点击 deep link 跳转）
 *
 * 注意：写 Room 预览由 MobileSyncWorker 在收到推送后触发 sync/pull 完成，
 * 这里只负责弹通知，不直接写 Room（避免在推送接收线程做 DB IO）。
 */
object PushMessageHandler {

    data class PushPayload(
        val title: String,
        val body: String,
        val route: String,
        val channel: String,
        val messageId: String?,
        val sessionId: String?,
        val source: String?,
    )

    fun parse(
        title: String?,
        body: String?,
        route: String?,
        channel: String?,
        messageId: String?,
        sessionId: String?,
        source: String?,
    ): PushPayload {
        return PushPayload(
            title = title?.takeIf { it.isNotBlank() } ?: "XCAGI",
            body = body ?: "",
            route = route?.takeIf { it.isNotBlank() } ?: "xcagi://chat",
            channel = channel?.takeIf { it.isNotBlank() } ?: NotificationChannels.CHAT,
            messageId = messageId,
            sessionId = sessionId,
            source = source,
        )
    }

    fun showNotification(context: Context, payload: PushPayload) {
        NotificationChannels.ensure(context)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, android.Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("deep_link_route", payload.route)
        }
        val pending = PendingIntent.getActivity(
            context,
            payload.route.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, payload.channel)
            .setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle(payload.title)
            .setContentText(payload.body)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(payload.route.hashCode(), notification)
        } catch (_: SecurityException) {
            /* 用户拒绝通知权限时不拖垮推送回调 */
        }
    }
}
