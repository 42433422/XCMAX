package com.xiuci.xcagi.mobile.core.im

import com.xiuci.xcagi.mobile.core.network.ServerRouter
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
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

    fun connect(sessionId: String) {
        if (sessionId.isBlank()) return
        disconnect()
        val url = serverRouter.fhdImWebSocketUrl(sessionId)
        val request = Request.Builder().url(url).build()
        socket = okHttp.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { JSONObject(text) }.onSuccess { _events.tryEmit(it) }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    connected = false
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    connected = false
                }
            },
        )
    }

    fun disconnect() {
        socket?.close(1000, "client_close")
        socket = null
        connected = false
    }
}
