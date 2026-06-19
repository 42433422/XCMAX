package com.xiuci.xcagi.mobile.core.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class XcagiMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        PushTokenHolder.fcmToken = token
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val payload = PushMessageHandler.parse(
            title = message.notification?.title ?: message.data["title"],
            body = message.notification?.body ?: message.data["body"],
            route = message.data["route"],
            channel = message.data["channel"],
            messageId = message.data["message_id"],
            sessionId = message.data["session_id"],
            source = message.data["source"],
        )
        PushMessageHandler.showNotification(this, payload)
    }
}

object PushTokenHolder {
    @Volatile var fcmToken: String = ""
    @Volatile var jpushRegistrationId: String = ""
}
