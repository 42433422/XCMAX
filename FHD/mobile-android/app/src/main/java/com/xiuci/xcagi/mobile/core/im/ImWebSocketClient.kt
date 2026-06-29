package com.xiuci.xcagi.mobile.core.im

import android.util.Log
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

/**
 * IM V0 WebSocket（/ws/im?session_id=）— 以会话 ID 鉴权，避免客户端自报 user_id 带来的安全风险。
 *
 * 含心跳 ping（30s）+ 断线指数退避重连（5s→10s→...→5min cap）。
 */
@Singleton
class ImWebSocketClient @Inject constructor(
    private val okHttp: OkHttpClient,
    private val serverRouter: ServerRouter,
) {
    private var socket: WebSocket? = null
    private val _events = MutableSharedFlow<JSONObject>(extraBufferCapacity = 32)
    val events: SharedFlow<JSONObject> = _events.asSharedFlow()

    @Volatile
    var connected: Boolean = false
        private set

    private var currentSessionId: String = ""
    private var reconnectAttempts: Int = 0
    private var heartbeatJob: Job? = null
    private var reconnectJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    @Synchronized
    fun connect(sessionId: String) {
        if (sessionId.isBlank()) return
        currentSessionId = sessionId
        disconnectSocket()
        cancelReconnect()
        doConnect(sessionId)
    }

    private fun doConnect(sessionId: String) {
        val url = serverRouter.fhdImWebSocketUrl(sessionId)
        val request = Request.Builder().url(url).build()
        socket = okHttp.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                    reconnectAttempts = 0
                    if (BuildConfig.DEBUG) {
                        Log.d(TAG, "ws onOpen host=${request.url.host}")
                    }
                    startHeartbeat()
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { JSONObject(text) }.onSuccess {
                        val emitted = _events.tryEmit(it)
                        if (BuildConfig.DEBUG) {
                            Log.d(
                                TAG,
                                "ws event type=${it.optString("type")} conv=${it.optInt("conversation_id", 0)} emitted=$emitted",
                            )
                        }
                    }.onFailure { err ->
                        Log.w(TAG, "ws parse fail: $err rawLength=${text.length}")
                    }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    connected = false
                    Log.w(TAG, "ws onClosed code=$code reason=$reason")
                    stopHeartbeat()
                    scheduleReconnect()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    connected = false
                    Log.w(TAG, "ws onFailure err=$t")
                    stopHeartbeat()
                    scheduleReconnect()
                }
            },
        )
    }

    private fun startHeartbeat() {
        stopHeartbeat()
        heartbeatJob = scope.launch {
            while (connected) {
                delay(30_000)
                if (connected) {
                    socket?.send("""{"type":"ping"}""")
                }
            }
        }
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }

    private fun scheduleReconnect() {
        if (currentSessionId.isBlank()) return
        cancelReconnect()
        val delayMs = ReconnectBackoff.delayForAttempt(reconnectAttempts)
        reconnectAttempts++
        reconnectJob = scope.launch {
            delay(delayMs)
            if (currentSessionId.isNotBlank()) {
                doConnect(currentSessionId)
            }
        }
    }

    private fun cancelReconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
    }

    private fun disconnectSocket() {
        stopHeartbeat()
        socket?.close(1000, "client_close")
        socket = null
        connected = false
    }

    @Synchronized
    fun disconnect() {
        currentSessionId = ""
        cancelReconnect()
        disconnectSocket()
    }

    companion object {
        private const val TAG = "XcagiImWs"

        fun parseEvent(json: JSONObject): ImWsEvent? = when (json.optString("type")) {
            "im.message", "message" -> parseMessage(json)
            "im.read", "read" -> parseRead(json)
            else -> null
        }

        private fun parseMessage(json: JSONObject): ImWsEvent.Message? {
            val conversationId = json.optInt("conversation_id", 0)
            val msg = json.optJSONObject("message")
            val messageId = when {
                msg != null -> msg.optLong("id", 0L)
                else -> json.optLong("message_id", 0L)
            }
            if (conversationId <= 0 || messageId <= 0L) return null
            val senderUserId = when {
                msg != null -> msg.optInt("sender_user_id", 0)
                else -> json.optInt("sender_user_id", 0)
            }
            val body = when {
                msg != null -> msg.optString("body", "")
                else -> json.optString("body", "")
            }
            val createdAtMs = when {
                msg != null -> ImRepository.parseTimestampMs(msg.opt("created_at"))
                else -> ImRepository.parseTimestampMs(json.opt("created_at"))
            } ?: System.currentTimeMillis()
            return ImWsEvent.Message(
                conversationId = conversationId,
                messageId = messageId,
                senderUserId = senderUserId,
                body = body,
                createdAtMs = createdAtMs,
                updatedAtMs = System.currentTimeMillis(),
            )
        }

        private fun parseRead(json: JSONObject): ImWsEvent.Read? {
            val conversationId = json.optInt("conversation_id", 0)
            val lastRead = json.optLong("last_read_message_id", 0L)
                .takeIf { it > 0L }
                ?: json.optLong("last_message_id", 0L)
            if (conversationId <= 0 || lastRead <= 0L) return null
            return ImWsEvent.Read(
                conversationId = conversationId,
                lastReadMessageId = lastRead,
                updatedAtMs = System.currentTimeMillis(),
            )
        }
    }
}
