package com.xiuci.xcagi.mobile

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject

private const val SessionFileName = "xcagi_session.json"
private const val CloudBaseUrl = "https://xiu-ci.com/fhd-api"
private const val ClientHeader = "android"
private const val ProductSku = "enterprise"

internal object XcagiWorkerCredentialPolicy {
    private val managementKinds = setOf("admin", "admin_portal")

    fun localPairingMatchesActiveIdentity(
        accountKind: String,
        userId: Int,
        tenantId: Int,
        localAccountKind: String,
        localTokenScope: String,
        localUserId: Int,
        localTenantId: Int,
    ): Boolean {
        val activeKind = accountKind.trim().lowercase()
        val pairedKind = localAccountKind.trim().lowercase()
        val kindsMatch =
            when (localTokenScope.trim()) {
                "management_pairing" ->
                    activeKind in managementKinds && pairedKind in managementKinds
                "enterprise_pairing" ->
                    activeKind == "enterprise" && pairedKind == "enterprise"
                else -> false
            }
        if (!kindsMatch || userId <= 0 || localUserId <= 0 || userId != localUserId) {
            return false
        }
        return tenantId <= 0 || localTenantId <= 0 || tenantId == localTenantId
    }

    fun isCloudCredential(
        accessToken: String,
        sessionId: String,
        localAccessToken: String,
        localSessionId: String,
    ): Boolean {
        if (accessToken.isBlank()) return false
        val duplicatesLocalPairing =
            localAccessToken.isNotBlank() &&
                accessToken == localAccessToken &&
                (sessionId.isBlank() || sessionId == localSessionId)
        return !duplicatesLocalPairing
    }
}

object XcagiBackgroundWork {
    private const val SchedulerPreferences = "xcagi_background_work"
    private const val LastImmediateReconcileAt = "last_immediate_reconcile_at"
    private const val ImmediateReconcileCooldownMs = 60_000L
    private const val MobileSyncWork = "xcagi_mobile_sync"
    private const val PushPollWork = "xcagi_push_poll"
    private const val PushPollNowWork = "xcagi_push_poll_now"
    private const val ManagementWorkPoll = "xcagi_management_work_poll"
    private const val ManagementWorkPollNow = "xcagi_management_work_poll_now"
    private const val LanProbeWork = "xcagi_lan_probe"

    fun reconcile(
        context: Context,
        autoSync: Boolean,
        autoLanProbe: Boolean,
    ): Map<String, Boolean> {
        val appContext = context.applicationContext
        val wm = WorkManager.getInstance(appContext)
        val constraints =
            Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        if (autoSync) {
            val req =
                PeriodicWorkRequestBuilder<XcagiMobileSyncWorker>(15, TimeUnit.MINUTES)
                    .setConstraints(constraints)
                    .build()
            wm.enqueueUniquePeriodicWork(
                MobileSyncWork,
                ExistingPeriodicWorkPolicy.KEEP,
                req,
            )
        } else {
            wm.cancelUniqueWork(MobileSyncWork)
        }

        val pushReq =
            PeriodicWorkRequestBuilder<XcagiPushPollWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
        wm.enqueueUniquePeriodicWork(
            PushPollWork,
            ExistingPeriodicWorkPolicy.KEEP,
            pushReq,
        )

        val managementWorkReq =
            PeriodicWorkRequestBuilder<XcagiManagementWorkPollWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
        wm.enqueueUniquePeriodicWork(
            ManagementWorkPoll,
            ExistingPeriodicWorkPolicy.KEEP,
            managementWorkReq,
        )

        // Flutter can reconcile several times during one startup while session
        // state settles. Persist a short cooldown so those calls produce one
        // catch-up poll, not a burst of already-completed unique work records.
        if (shouldEnqueueImmediateCatchUp(appContext)) {
            wm.enqueueUniqueWork(
                PushPollNowWork,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<XcagiPushPollWorker>()
                    .setConstraints(constraints)
                    .build(),
            )
            wm.enqueueUniqueWork(
                ManagementWorkPollNow,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<XcagiManagementWorkPollWorker>()
                    .setConstraints(constraints)
                    .build(),
            )
        }

        if (autoLanProbe) {
            val lanReq =
                PeriodicWorkRequestBuilder<XcagiLanProbeWorker>(15, TimeUnit.MINUTES)
                    .build()
            wm.enqueueUniquePeriodicWork(
                LanProbeWork,
                ExistingPeriodicWorkPolicy.KEEP,
                lanReq,
            )
        } else {
            wm.cancelUniqueWork(LanProbeWork)
        }

        return mapOf(
            "mobileSync" to autoSync,
            "pushPoll" to true,
            "managementWorkPoll" to true,
            "lanProbe" to autoLanProbe,
        )
    }

    @Synchronized
    private fun shouldEnqueueImmediateCatchUp(context: Context): Boolean {
        val preferences =
            context.getSharedPreferences(SchedulerPreferences, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val last = preferences.getLong(LastImmediateReconcileAt, 0L)
        if (last > 0L && now - last in 0 until ImmediateReconcileCooldownMs) {
            return false
        }
        return preferences.edit().putLong(LastImmediateReconcileAt, now).commit()
    }
}

class XcagiMobileSyncWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {
    override fun doWork(): Result {
        val session = XcagiWorkerSession.load(applicationContext)
        if (!session.autoSync) return Result.success()
        if (session.effectiveAccessToken.isBlank()) return Result.success()
        if (session.fhdHost.isBlank() && session.serverMode.lowercase() != "cloud") {
            return Result.success()
        }

        return try {
            val response =
                XcagiWorkerHttp.postJson(
                    session = session,
                    path = "api/mobile/v1/sync/pull",
                    body = JSONObject().put("since_cursor", session.syncCursor),
                )
            if (!response.optBoolean("success", response.optBoolean("ok", false))) {
                return Result.retry()
            }
            val data = response.optJSONObject("data") ?: JSONObject()
            val cursor = data.optInt("cursor", session.syncCursor)
            session.update {
                put("sync_cursor", cursor.coerceAtLeast(0))
                put("last_sync_at", Instant.now().toString())
            }
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

class XcagiPushPollWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {
    override fun doWork(): Result {
        val session = XcagiWorkerSession.load(applicationContext)
        if (!session.hasAnyCredential) return Result.success()

        var targetSucceeded = false
        for (preferLocal in session.notificationTargetModes()) {
            try {
                val response =
                    XcagiWorkerHttp.getJson(
                        session = session,
                        path = "api/mobile/v1/notifications/pending",
                        query = "limit=50",
                        preferLocal = preferLocal,
                    )
                if (!response.optBoolean("success", response.optBoolean("ok", false))) {
                    continue
                }
                val data = response.optJSONObject("data") ?: JSONObject()
                val items = data.optJSONArray("notifications") ?: data.optJSONArray("items")
                if (items != null) {
                    for (index in 0 until items.length()) {
                        val row = items.optJSONObject(index) ?: continue
                        if (XcagiNotification.show(applicationContext, row)) {
                            val notificationId = row.optInt("id", 0)
                            if (notificationId > 0) {
                                XcagiWorkerHttp.postJson(
                                    session = session,
                                    path = "api/mobile/v1/notifications/$notificationId/ack",
                                    body = JSONObject(),
                                    preferLocal = preferLocal,
                                )
                            }
                        }
                    }
                }
                targetSucceeded = true
            } catch (_: Exception) {
                // A paired desktop can be asleep while cloud remains online,
                // or vice versa. Try every configured notification origin.
            }
        }
        return if (targetSucceeded) Result.success() else Result.retry()
    }
}

class XcagiManagementWorkPollWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {
    override fun doWork(): Result {
        val session = XcagiWorkerSession.load(applicationContext)
        if (!session.hasAnyCredential) return Result.success()
        if (session.accountKind !in setOf("admin", "admin_portal")) return Result.success()
        if (!session.hasVerifiedManagementPairing) return Result.success()

        return try {
            val response =
                XcagiWorkerHttp.getJson(
                    session = session,
                    path = "api/mobile/v1/admin/employee-work",
                    query =
                        "status=assigned%2Cwaiting_decision%2Cdelivered%2Cblocked%2Cfailed%2Ccancel_requested%2Ccancelled&limit=100",
                    preferLocal = true,
                )
            if (!response.optBoolean("success", response.optBoolean("ok", false))) {
                return Result.retry()
            }
            val data = response.optJSONObject("data") ?: JSONObject()
            val items = data.optJSONArray("items") ?: JSONArray()
            XcagiManagementWorkNotifications.showTransitions(applicationContext, session, items)
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

class XcagiLanProbeWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {
    override fun doWork(): Result {
        val session = XcagiWorkerSession.load(applicationContext)
        if (!session.hasLocalTarget) return Result.success()
        val localOrigin = session.localOrigin()

        val ok =
            runCatching {
                val url = URL("${localOrigin.trimEnd('/')}/api/mobile/v1/health")
                val connection = (url.openConnection() as HttpURLConnection).apply {
                    connectTimeout = 3_000
                    readTimeout = 3_000
                    requestMethod = "GET"
                }
                try {
                    connection.responseCode in 200..299
                } finally {
                    connection.disconnect()
                }
            }.getOrDefault(false)

        if (!ok && session.serverMode.lowercase() == "lan") {
            session.update { put("server_mode", "cloud") }
        } else if (ok && session.serverMode.lowercase() == "cloud") {
            session.update { put("server_mode", "lan") }
        }
        return Result.success()
    }
}

private data class XcagiWorkerSession(
    val context: Context,
    val json: JSONObject,
) {
    val accessToken: String = json.optString("access_token")
    val localAccessToken: String = json.optString("local_access_token")
    val localAccountKind: String = json.optString("local_account_kind").trim().lowercase()
    val localTokenScope: String = json.optString("local_token_scope").trim()
    val localUserId: Int = json.optInt("local_user_id", 0)
    val localTenantId: Int = json.optInt("local_tenant_id", 0)
    val accountKind: String = json.optString("account_kind").trim().lowercase()
    val userId: Int = json.optInt("user_id", 0)
    val tenantId: Int = json.optInt("tenant_id", 0)
    val sessionId: String = json.optString("session_id")
    val localSessionId: String = json.optString("local_session_id")
    val serverMode: String = json.optString("server_mode", "cloud")
    val fhdHost: String = json.optString("fhd_host")
    val localBaseUrl: String = json.optString("local_base_url")
    val relayBaseUrl: String = json.optString("relay_base_url")
    val autoSync: Boolean = json.optBoolean("auto_sync", true)
    val syncCursor: Int = json.optInt("sync_cursor", 0)
    val effectiveAccessToken: String
        get() =
            if (serverMode.lowercase() == "lan" && hasLocalTarget) {
                localAccessToken
            } else {
                accessToken
            }
    val effectiveSessionId: String
        get() =
            if (serverMode.lowercase() == "lan" && hasLocalTarget) {
                localSessionId
            } else {
                sessionId
            }

    val hasLocalTarget: Boolean
        get() =
            localOrigin().isNotBlank() &&
                localAccessToken.isNotBlank() &&
                localSessionId.isNotBlank() &&
                localPairingMatchesActiveIdentity

    val hasCloudCredential: Boolean
        get() =
            XcagiWorkerCredentialPolicy.isCloudCredential(
                accessToken = accessToken,
                sessionId = sessionId,
                localAccessToken = localAccessToken,
                localSessionId = localSessionId,
            )

    val hasAnyCredential: Boolean
        get() = hasCloudCredential || hasLocalTarget

    val localPairingMatchesActiveIdentity: Boolean
        get() =
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = accountKind,
                userId = userId,
                tenantId = tenantId,
                localAccountKind = localAccountKind,
                localTokenScope = localTokenScope,
                localUserId = localUserId,
                localTenantId = localTenantId,
            )

    val hasVerifiedManagementPairing: Boolean
        get() =
            localAccessToken.isNotBlank() &&
                localSessionId.isNotBlank() &&
                localTokenScope == "management_pairing" &&
                localAccountKind in setOf("admin", "admin_portal") &&
                localPairingMatchesActiveIdentity

    fun localOrigin(): String {
        localBaseUrl.trim().takeIf { it.isNotBlank() }?.let { raw ->
            return raw.trimEnd('/')
        }
        val rawHost = fhdHost.trim().trimEnd('/')
        if (rawHost.isBlank()) return ""
        return if (rawHost.startsWith("http://") || rawHost.startsWith("https://")) {
            rawHost
        } else {
            "http://$rawHost"
        }
    }

    fun notificationTargetModes(): List<Boolean> {
        val modes = mutableListOf<Boolean>()
        if (hasLocalTarget) modes += true
        if (hasCloudCredential) modes += false
        return modes.distinct()
    }

    fun baseUrl(preferLocal: Boolean = false): String {
        if (preferLocal && hasLocalTarget) return localOrigin()
        if (serverMode.lowercase() == "lan" && hasLocalTarget) {
            return localOrigin()
        }
        if (relayBaseUrl.isNotBlank()) return relayBaseUrl.trim()
        return CloudBaseUrl
    }

    fun accessToken(preferLocal: Boolean): String =
        if (preferLocal && hasLocalTarget) localAccessToken else effectiveAccessToken

    fun sessionId(preferLocal: Boolean): String =
        if (preferLocal && hasLocalTarget) localSessionId else effectiveSessionId

    fun update(block: JSONObject.() -> Unit) {
        val next = JSONObject(json.toString()).apply(block)
        val encrypted = CredentialCipher.encrypt(next.toString())
        if (encrypted.isNotBlank()) sessionFile(context).writeText(encrypted)
    }

    companion object {
        fun load(context: Context): XcagiWorkerSession {
            val file = sessionFile(context)
            val json =
                if (file.exists() && file.readText().trim().isNotBlank()) {
                    val decoded = CredentialCipher.decrypt(file.readText())
                    if (decoded.isBlank()) JSONObject() else JSONObject(decoded)
                } else {
                    JSONObject()
                }
            return XcagiWorkerSession(context.applicationContext, json)
        }
    }
}

private object XcagiWorkerHttp {
    fun getJson(
        session: XcagiWorkerSession,
        path: String,
        query: String = "",
        preferLocal: Boolean = false,
    ): JSONObject {
        val suffix = if (query.isBlank()) "" else "?$query"
        return requestJson(session, "GET", path, null, suffix, preferLocal)
    }

    fun postJson(
        session: XcagiWorkerSession,
        path: String,
        body: JSONObject,
        preferLocal: Boolean = false,
    ): JSONObject {
        return requestJson(session, "POST", path, body, "", preferLocal)
    }

    private fun requestJson(
        session: XcagiWorkerSession,
        method: String,
        path: String,
        body: JSONObject?,
        suffix: String,
        preferLocal: Boolean,
    ): JSONObject {
        val base = session.baseUrl(preferLocal).trimEnd('/')
        val normalizedPath = path.trimStart('/')
        val url = URL("$base/$normalizedPath$suffix")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 15_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("X-XCAGI-Client", ClientHeader)
            setRequestProperty("X-XCAGI-SKU", ProductSku)
            val accessToken = session.accessToken(preferLocal)
            if (accessToken.isNotBlank()) {
                setRequestProperty("Authorization", "Bearer $accessToken")
            }
            val sessionId = session.sessionId(preferLocal)
            if (sessionId.isNotBlank()) {
                setRequestProperty("X-Session-ID", sessionId)
                setRequestProperty("Cookie", "session_id=$sessionId")
            }
            if (body != null) doOutput = true
        }
        try {
            if (body != null) {
                connection.outputStream.use { output ->
                    output.write(body.toString().toByteArray(Charsets.UTF_8))
                }
            }
            val text =
                if (connection.responseCode in 200..299) {
                    connection.inputStream.bufferedReader().readText()
                } else {
                    connection.errorStream?.bufferedReader()?.readText().orEmpty()
                }
            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${connection.responseCode}: $text")
            }
            return JSONObject(text.ifBlank { "{}" })
        } finally {
            connection.disconnect()
        }
    }
}

private object XcagiNotification {
    private const val ChannelId = "xcagi_mobile"
    private const val DedupePreferenceName = "xcagi_notification_event_dedupe"

    @Synchronized
    fun show(context: Context, row: JSONObject): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }

        val data = row.optJSONObject("data") ?: JSONObject()
        val title = row.optString("title").ifBlank { "XCAGI" }
        val body = row.optString("body")
        val route = row.optString("route")
        val eventId = row.optString("event_id").ifBlank { data.optString("event_id") }
        val eventKey = if (eventId.isBlank()) "" else sha256(eventId)
        val dedupe = context.getSharedPreferences(DedupePreferenceName, Context.MODE_PRIVATE)
        if (eventKey.isNotBlank() && dedupe.getBoolean(eventKey, false)) {
            // The durable outbox can race the management-ledger fallback poll.
            // Treat an already displayed event as delivered so the outbox ACKs it.
            return true
        }
        val requestedChannelId =
            row.optString("channel_id").ifBlank { data.optString("channel_id") }
        val channelId = normalizedChannelId(requestedChannelId)
        val channelName =
            row.optString("channel_name").ifBlank {
                data.optString("channel_name").ifBlank { "XCAGI" }
            }
        val highPriority =
            row.optBoolean("high_priority", false) ||
                data.optBoolean("high_priority", false) ||
                data.optString("priority").equals("high", ignoreCase = true)
        ensureChannel(context, channelId, channelName, highPriority)
        val intent =
            Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                if (route.isNotBlank()) putExtra("deep_link_route", route)
            }
        val pending =
            PendingIntent.getActivity(
                context,
                row.optInt("id", route.hashCode()),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        val publicNotification =
            NotificationCompat.Builder(context, channelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("XCAGI 管理提醒")
                .setContentText("解锁后查看任务详情")
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .build()
        val notification =
            NotificationCompat.Builder(context, channelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pending)
                .setPriority(
                    if (highPriority) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT,
                )
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPublicVersion(publicNotification)
                .setAutoCancel(true)
                .build()
        NotificationManagerCompat.from(context).notify(row.optInt("id", title.hashCode()), notification)
        if (eventKey.isNotBlank()) {
            dedupe.edit().putBoolean(eventKey, true).commit()
        }
        return true
    }

    private fun normalizedChannelId(raw: String): String {
        val value = raw.trim()
        return if (value.matches(Regex("[A-Za-z0-9_.-]{1,64}"))) value else ChannelId
    }

    private fun ensureChannel(
        context: Context,
        channelId: String,
        channelName: String,
        highPriority: Boolean,
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(channelId) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                channelId,
                channelName,
                if (highPriority) NotificationManager.IMPORTANCE_HIGH else NotificationManager.IMPORTANCE_DEFAULT,
            ),
        )
    }
}

private object XcagiManagementWorkNotifications {
    private const val PreferenceName = "xcagi_management_work_notifications"

    fun showTransitions(
        context: Context,
        session: XcagiWorkerSession,
        items: JSONArray,
    ) {
        val preferences = context.getSharedPreferences(PreferenceName, Context.MODE_PRIVATE)
        val editor = preferences.edit()
        for (index in 0 until items.length()) {
            val row = items.optJSONObject(index) ?: continue
            val taskId = row.optString("task_id").trim()
            val status = row.optString("status").trim()
            val stage = row.optString("current_stage").trim()
            val isReassigned = status == "assigned" && stage == "reassigned"
            if (
                taskId.isBlank() ||
                    (status !in setOf(
                        "waiting_decision",
                        "delivered",
                        "blocked",
                        "failed",
                        "cancel_requested",
                        "cancelled",
                    ) && !isReassigned)
            ) {
                continue
            }
            val fingerprint =
                listOf(
                    status,
                    row.optString("updated_at"),
                    row.optString("last_update"),
                    row.optString("result_summary"),
                    row.optString("error"),
                    row.optString("owner_employee_id"),
                    stage,
                ).joinToString("|")
            val preferenceKey = sha256("${session.localSessionId}|$taskId")
            val fingerprintHash = sha256(fingerprint)
            if (preferences.getString(preferenceKey, "") == fingerprintHash) continue

            val employee = row.optString("owner_employee_id").ifBlank { "AI 员工" }
            val taskTitle = row.optString("title").ifBlank { taskId }
            val title =
                when (status) {
                    "waiting_decision" -> "$employee 等你决策"
                    "delivered" -> "$employee 已交付，等待验收"
                    "cancel_requested" -> "任务正在安全停止"
                    "cancelled" -> "任务已停止"
                    "assigned" -> "任务已改派给 $employee"
                    else -> "$employee 的任务需要介入"
                }
            val detail =
                when (status) {
                    "waiting_decision" -> row.optString("last_update")
                    "delivered" -> row.optString("result_summary")
                    "cancel_requested", "cancelled", "assigned" -> row.optString("last_update")
                    else -> row.optString("error").ifBlank { row.optString("last_update") }
                }
            val notificationId = taskId.hashCode() and 0x7fffffff
            val eventName =
                when (status) {
                    "waiting_decision" -> "management_work.decision_required"
                    "delivered" -> "management_work.delivered"
                    "blocked" -> "management_work.blocked"
                    "failed" -> "management_work.failed"
                    "cancel_requested" -> "management_work.cancel_requested"
                    "cancelled" -> "management_work.cancelled"
                    "assigned" -> "management_work.reassigned"
                    else -> "management_work.updated"
                }
            val notification =
                JSONObject()
                    .put("id", notificationId)
                    .put("title", title)
                    .put("body", if (detail.isBlank()) taskTitle else "$taskTitle：$detail")
                    .put("route", "management_work/$taskId")
                    .put(
                        "event_id",
                        "$eventName:$taskId:$status:${row.optString("updated_at")}",
                    )
                    .put(
                        "channel_id",
                        if (status == "waiting_decision") {
                            "xcagi_management_work_urgent"
                        } else {
                            "xcagi_management_work"
                        },
                    )
                    .put("channel_name", if (status == "waiting_decision") "员工决策提醒" else "员工任务进展")
                    .put("high_priority", status == "waiting_decision")
            if (XcagiNotification.show(context, notification)) {
                editor.putString(preferenceKey, fingerprintHash)
            }
        }
        editor.apply()
    }
}

private fun sha256(value: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }

private fun sessionFile(context: Context): File = File(context.filesDir, SessionFileName)
