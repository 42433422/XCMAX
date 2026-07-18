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
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.concurrent.TimeUnit
import org.json.JSONObject

private const val SessionFileName = "xcagi_session.json"
private const val CloudBaseUrl = "https://xiu-ci.com/fhd-api"
private const val ClientHeader = "android"
private const val ProductSku = "enterprise"

object XcagiBackgroundWork {
    private const val MobileSyncWork = "xcagi_mobile_sync"
    private const val PushPollWork = "xcagi_push_poll"
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
                ExistingPeriodicWorkPolicy.UPDATE,
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
            ExistingPeriodicWorkPolicy.UPDATE,
            pushReq,
        )

        if (autoLanProbe) {
            val lanReq =
                PeriodicWorkRequestBuilder<XcagiLanProbeWorker>(15, TimeUnit.MINUTES)
                    .build()
            wm.enqueueUniquePeriodicWork(
                LanProbeWork,
                ExistingPeriodicWorkPolicy.UPDATE,
                lanReq,
            )
        } else {
            wm.cancelUniqueWork(LanProbeWork)
        }

        return mapOf(
            "mobileSync" to autoSync,
            "pushPoll" to true,
            "lanProbe" to autoLanProbe,
        )
    }
}

class XcagiMobileSyncWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {
    override fun doWork(): Result {
        val session = XcagiWorkerSession.load(applicationContext)
        if (!session.autoSync) return Result.success()
        if (session.accessToken.isBlank()) return Result.success()
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
        if (session.accessToken.isBlank()) return Result.success()

        return try {
            val response =
                XcagiWorkerHttp.getJson(
                    session = session,
                    path = "api/mobile/v1/notifications/pending",
                    query = "limit=50",
                )
            if (!response.optBoolean("success", response.optBoolean("ok", false))) {
                return Result.retry()
            }
            val data = response.optJSONObject("data") ?: JSONObject()
            val items = data.optJSONArray("notifications") ?: data.optJSONArray("items")
            if (items != null) {
                for (index in 0 until items.length()) {
                    val row = items.optJSONObject(index) ?: continue
                    XcagiNotification.show(applicationContext, row)
                }
            }
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
        val host = session.fhdHost.substringBefore("/").trim()
        if (host.isBlank()) return Result.success()

        val ok =
            runCatching {
                val url = URL("http://$host/fhd-api/api/mobile/v1/health")
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
    val sessionId: String = json.optString("session_id")
    val serverMode: String = json.optString("server_mode", "cloud")
    val fhdHost: String = json.optString("fhd_host")
    val relayBaseUrl: String = json.optString("relay_base_url")
    val autoSync: Boolean = json.optBoolean("auto_sync", true)
    val syncCursor: Int = json.optInt("sync_cursor", 0)

    fun baseUrl(): String {
        if (serverMode.lowercase() == "lan" && fhdHost.isNotBlank()) {
            return "http://${fhdHost.trim()}/fhd-api"
        }
        if (relayBaseUrl.isNotBlank()) return relayBaseUrl.trim()
        return CloudBaseUrl
    }

    fun update(block: JSONObject.() -> Unit) {
        val next = JSONObject(json.toString()).apply(block)
        sessionFile(context).writeText(next.toString())
    }

    companion object {
        fun load(context: Context): XcagiWorkerSession {
            val file = sessionFile(context)
            val json =
                if (file.exists() && file.readText().trim().isNotBlank()) {
                    JSONObject(file.readText())
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
    ): JSONObject {
        val suffix = if (query.isBlank()) "" else "?$query"
        return requestJson(session, "GET", path, null, suffix)
    }

    fun postJson(
        session: XcagiWorkerSession,
        path: String,
        body: JSONObject,
    ): JSONObject {
        return requestJson(session, "POST", path, body, "")
    }

    private fun requestJson(
        session: XcagiWorkerSession,
        method: String,
        path: String,
        body: JSONObject?,
        suffix: String,
    ): JSONObject {
        val base = session.baseUrl().trimEnd('/')
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
            if (session.accessToken.isNotBlank()) {
                setRequestProperty("Authorization", "Bearer ${session.accessToken}")
            }
            if (session.sessionId.isNotBlank()) {
                setRequestProperty("X-Session-ID", session.sessionId)
                setRequestProperty("Cookie", "session_id=${session.sessionId}")
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

    fun show(context: Context, row: JSONObject) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val title = row.optString("title").ifBlank { "XCAGI" }
        val body = row.optString("body")
        val route = row.optString("route")
        ensureChannel(context)
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
        val notification =
            NotificationCompat.Builder(context, ChannelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pending)
                .setAutoCancel(true)
                .build()
        NotificationManagerCompat.from(context).notify(row.optInt("id", title.hashCode()), notification)
    }

    private fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(ChannelId) != null) return
        manager.createNotificationChannel(
            NotificationChannel(ChannelId, "XCAGI", NotificationManager.IMPORTANCE_DEFAULT),
        )
    }
}

private fun sessionFile(context: Context): File = File(context.filesDir, SessionFileName)
