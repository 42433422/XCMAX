package com.xiuci.xcagi.mobile.core.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.push.PushMessageHandler
import com.xiuci.xcagi.mobile.core.repository.XcagiRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.first

/**
 * 自建推送后台通道：定时拉取 `/api/notifications/pending` 并弹本地通知。
 *
 * 极光移除后,App 退后台/被杀时的送达靠此 WorkManager 周期任务(最快约 15 分钟)+ FCM(有 GMS 的机型)。
 * 前台实时仍走 IM 长连(ImWebSocketClient)。
 */
@HiltWorker
class PushPollWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val sessionStore: SessionStore,
    private val repo: XcagiRepository,
) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        if (!sessionStore.isLoggedInFlow.first()) return Result.success()
        val items =
            try {
                repo.fetchPendingNotifications()
            } catch (_: Exception) {
                return Result.retry()
            }
        for (n in items) {
            val payload =
                PushMessageHandler.parse(
                    title = n.title,
                    body = n.body,
                    route = n.route,
                    channel = n.channel,
                    messageId = n.id.toString(),
                    sessionId = null,
                    source = "selfpush",
                )
            PushMessageHandler.showNotification(applicationContext, payload)
        }
        return Result.success()
    }
}
