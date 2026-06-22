package com.xiuci.xcagi.mobile.core.push

import android.content.Context
import cn.jpush.android.api.CmdMessage
import cn.jpush.android.api.CustomMessage
import cn.jpush.android.api.NotificationMessage
import cn.jpush.android.service.JPushMessageReceiver
import org.json.JSONObject

/**
 * JPush 消息接收器（国内推送通道）。
 *
 * JPush SDK 5.x 的 JPushMessageReceiver 继承自 BroadcastReceiver，
 * SDK 收到推送后通过广播转发给开发者 App。
 * onMessage 处理自定义消息（不显示在通知栏，需自行弹通知）。
 * onNotifyMessageOpened 处理通知点击。
 *
 * 注册在 AndroidManifest.xml 中，intent-filter 包含
 * cn.jpush.android.intent.MESSAGE_RECEIVED 等多个 action。
 */
class JPushReceiver : JPushMessageReceiver() {

    override fun onMessage(context: Context, customMessage: CustomMessage) {
        // customMessage.message 是后端 send_jpush 中 message.msg_content
        // customMessage.extra 是后端 send_jpush 中 message.extras
        val extras = customMessage.extra
        val payload = if (extras != null) {
            runCatching { JSONObject(extras) }.getOrElse { JSONObject() }
        } else {
            JSONObject()
        }
        val parsed = PushMessageHandler.parse(
            title = payload.optString("title").ifBlank { customMessage.title },
            body = payload.optString("body").ifBlank { customMessage.message },
            route = payload.optString("route", "xcagi://chat"),
            channel = payload.optString("channel", NotificationChannels.CHAT),
            messageId = payload.optString("message_id").ifBlank { null },
            sessionId = payload.optString("session_id").ifBlank { null },
            source = payload.optString("source").ifBlank { null },
        )
        PushMessageHandler.showNotification(context, parsed)
    }

    override fun onNotifyMessageOpened(context: Context, message: NotificationMessage) {
        // JPush 通知点击：交给 MainActivity 的 intent-filter 处理 deep link
        // 这里不做额外处理，JPush SDK 会自动打开应用
    }

    override fun onCommandResult(context: Context, cmdMessage: CmdMessage) {
        // JPush 注册成功后 PushRegistrar 会拿到 registrationId
        // 这里不需要额外处理
    }
}
