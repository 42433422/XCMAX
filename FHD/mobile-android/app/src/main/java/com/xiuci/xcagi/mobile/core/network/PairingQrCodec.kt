package com.xiuci.xcagi.mobile.core.network

import android.net.Uri
import org.json.JSONObject

/** 电脑端配对 QR 载荷。v1 含 host/port/nonce，v2 仅含 token（配对码）。 */
data class PairingQrPayload(
    val host: String = "",
    val port: Int = 0,
    val nonce: String = "",
    val token: String = "", // v2: shortCode（6位数字）或 nonce
    val version: Int = 1,   // 1=旧格式(host:port:nonce), 2=纯token格式
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

            // v2 格式：{ "v": 2, "t": "847293" } — 纯 token 模式
            if (v >= 2) {
                val t = o.optString("t").trim()
                if (t.isNotBlank()) {
                    return PairingQrPayload(token = t, version = 2)
                }
                // 兼容：v2 但仍带 nonce
                val nonce = o.optString("nonce").trim()
                if (nonce.isNotBlank()) {
                    return PairingQrPayload(nonce = nonce, token = nonce, version = 2)
                }
                return null
            }

            // v1 格式：{ "v": 1, "host": "...", "port": 5100, "nonce": "..." }
            val nonce = o.optString("nonce").trim()
            val host = o.optString("host").trim().removePrefix("http://").removePrefix("https://")
            val port = when {
                o.has("port") -> o.optInt("port", 0)
                host.contains(":") -> host.substringAfter(":").toIntOrNull() ?: 0
                else -> 0
            }
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
