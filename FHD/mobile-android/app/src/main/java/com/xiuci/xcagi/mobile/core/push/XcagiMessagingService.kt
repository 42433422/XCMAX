package com.xiuci.xcagi.mobile.core.push

import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.xiuci.xcagi.mobile.MainActivity
import com.xiuci.xcagi.mobile.R
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class XcagiMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        PushTokenHolder.fcmToken = token
    }

    override fun onMessageReceived(message: RemoteMessage) {
        NotificationChannels.ensure(this)
        val title = message.notification?.title ?: message.data["title"] ?: "XCAGI"
        val body = message.notification?.body ?: message.data["body"] ?: ""
        val route = message.data["route"] ?: "xcagi://chat"
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("deep_link_route", route)
        }
        val pending = PendingIntent.getActivity(
            this,
            route.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val channel = message.data["channel"] ?: NotificationChannels.SYSTEM
        val notification = NotificationCompat.Builder(this, channel)
            .setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        try {
            NotificationManagerCompat.from(this).notify(route.hashCode(), notification)
        } catch (_: SecurityException) {
            /* 用户拒绝通知权限时不拖垮 FCM 回调 */
        }
    }
}

object PushTokenHolder {
    @Volatile var fcmToken: String = ""
    @Volatile var jpushRegistrationId: String = ""
}
