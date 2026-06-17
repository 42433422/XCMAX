package com.xiuci.xcagi.mobile.core.network

import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import javax.inject.Inject
import javax.inject.Singleton

enum class ServerMode { LAN, CLOUD }

@Singleton
class ServerRouter @Inject constructor() {
    var fhdHost: String = "127.0.0.1"
    var mode: ServerMode = ServerMode.CLOUD

    fun fhdBaseUrl(): String {
        if (mode == ServerMode.CLOUD && ProductSkuConfig.isEnterprise) {
            return enterpriseFhdBaseUrl()
        }
        return lanFhdBaseUrl()
    }

    private fun lanFhdBaseUrl(): String {
        val host = fhdHost.trim().removePrefix("http://").removePrefix("https://").trimEnd('/')
        val bare = host.substringBefore(':')
        val port = host.substringAfter(':', "").ifBlank { BuildConfig.FHD_DEFAULT_PORT.toString() }
        return "http://$bare:$port/"
    }

    fun enterpriseFhdBaseUrl(): String {
        val base = BuildConfig.ENTERPRISE_FHD_BASE_URL.trimEnd('/')
        return "$base/"
    }

    fun modstoreBaseUrl(): String {
        val base = BuildConfig.MODSTORE_BASE_URL.trimEnd('/')
        return "$base/"
    }

    fun activeWriteBaseUrl(): String = when (mode) {
        ServerMode.LAN -> fhdBaseUrl()
        ServerMode.CLOUD -> modstoreBaseUrl()
    }

    /** IM V0 WebSocket：`/ws/im?session_id=`（与前端 `im.ts` 一致）。 */
    fun fhdImWebSocketUrl(sessionId: String): String {
        val http = fhdBaseUrl().trimEnd('/')
        val ws = when {
            http.startsWith("https://") -> "wss://" + http.removePrefix("https://")
            http.startsWith("http://") -> "ws://" + http.removePrefix("http://")
            else -> "ws://$http"
        }
        val encoded = java.net.URLEncoder.encode(sessionId, Charsets.UTF_8.name())
        return "$ws/ws/im?session_id=$encoded"
    }
}
