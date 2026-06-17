package com.xiuci.xcagi.mobile.core.network

import android.net.Uri
import org.json.JSONObject

/** 电脑端配对 QR 载荷。v1 含 host/port/nonce，v2 含短码 token，可选带 host/port/nonce。 */
data class PairingQrPayload(
    val host: String = "",
    val port: Int = 0,
    val nonce: String = "",
    val token: String = "", // v2: shortCode（6位数字）或 nonce
    val version: Int = 1,   // 1=旧格式(host:port:nonce), 2=短码优先格式
)

object PairingQrCodec {
    fun parse(raw: String): PairingQrPayload? {
        val text = raw.trim()
        if (text.isBlank() || text.contains("auth-qr", ignoreCase = true)) return null

        // 纯数字6位 → 直接作为配对码处理
        if (text.length == 6 && text.all { it.isDigit() }) {
            return PairingQrPayload(token = text, version = 2)
        }

        if (text.startsWith("{")) {
            return parseJson(text)
        }
        if (text.startsWith("xcagi://", ignoreCase = true)) {
            return parseDeepLink(text)
        }
        return null
    }

    private fun parseJson(text: String): PairingQrPayload? {
        return try {
            val o = JSONObject(text)
            val v = o.optInt("v", 1)
            val host = normalizeHost(o.optString("host").trim())
            val port = parsePort(o, host)
            val bareHost = host.substringBefore(":").trim()
            val hasHostPort = bareHost.isNotBlank() && port in 1..65535

            // v2 格式：优先短码，同时兼容带 host/port/nonce 的直连兜底。
            if (v >= 2) {
                val t = o.optString("t").trim()
                if (t.isNotBlank()) {
                    return PairingQrPayload(
                        host = if (hasHostPort) bareHost else "",
                        port = if (hasHostPort) port else 0,
                        nonce = o.optString("nonce").trim(),
                        token = t,
                        version = 2,
                    )
                }
                val nonce = o.optString("nonce").trim()
                if (nonce.isNotBlank()) {
                    return PairingQrPayload(
                        host = if (hasHostPort) bareHost else "",
                        port = if (hasHostPort) port else 0,
                        nonce = nonce,
                        token = nonce,
                        version = 2,
                    )
                }
                return null
            }

            // v1 格式：{ "v": 1, "host": "...", "port": 5100, "nonce": "..." }
            val nonce = o.optString("nonce").trim()
            if (nonce.length >= 8 && hasHostPort) {
                PairingQrPayload(bareHost, port, nonce, version = 1)
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun normalizeHost(host: String): String =
        host.removePrefix("http://").removePrefix("https://").trimEnd('/')

    private fun parsePort(o: JSONObject, host: String): Int =
        when {
            o.has("port") -> o.optInt("port", 0)
            host.contains(":") -> host.substringAfter(":").toIntOrNull() ?: 0
            else -> 0
        }

    private fun parseDeepLink(text: String): PairingQrPayload? {
        return try {
            val uri = Uri.parse(text)
            if (uri.host != "pair" && uri.path?.contains("pair") != true) return null
            val nonce = uri.getQueryParameter("nonce")?.trim().orEmpty()
            val host =
                uri.getQueryParameter("host")?.trim()?.removePrefix("http://")?.removePrefix("https://")
                    .orEmpty()
            val port = uri.getQueryParameter("port")?.toIntOrNull() ?: 0
            val bareHost = host.substringBefore(":").trim()
            if (nonce.length >= 8 && bareHost.isNotBlank() && port in 1..65535) {
                PairingQrPayload(bareHost, port, nonce, version = 1)
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    fun formatHostPort(host: String, port: Int): String {
        val bare = host.trim().removePrefix("http://").removePrefix("https://").substringBefore(":").trim()
        return "$bare:$port"
    }
}
