package com.xiuci.xcagi.mobile.core.network

import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder

/** 电脑端配对 QR 载荷。v1 含 host/port/nonce，v2 含短码 token，可选带 host/port/nonce。 */
data class PairingQrPayload(
    val host: String = "",
    val port: Int = 0,
    val nonce: String = "",
    val token: String = "", // v2: shortCode（6位数字）或 nonce
    val apiBaseUrl: String = "",
    val relayId: String = "",
    val relayBaseUrl: String = "",
    val version: Int = 1,   // 1=旧格式(host:port:nonce), 2=短码优先格式, 3=云中继绑定
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
            val kind = o.optString("kind")
            val relayId = firstNonBlank(o.optString("relay_id"), o.optString("relayId"))
            val relayBaseUrl = firstNonBlank(
                o.optString("relay_base_url"),
                o.optString("relayBaseUrl"),
            )
            if (v >= 3 || kind.contains("relay", ignoreCase = true)) {
                val t = firstNonBlank(
                    o.optString("t"),
                    o.optString("code"),
                    o.optString("shortCode"),
                    o.optString("short_code"),
                    o.optString("token"),
                )
                if (relayId.isNotBlank() && t.isNotBlank()) {
                    return PairingQrPayload(
                        token = t,
                        relayId = relayId,
                        relayBaseUrl = relayBaseUrl,
                        version = 3,
                    )
                }
            }
            val apiBaseUrl = firstNonBlank(
                o.optString("api_base_url"),
                o.optString("base_url"),
                o.optString("apiBaseUrl"),
            )
            val fromBase = parseApiBase(apiBaseUrl)
            val host = normalizeHost(o.optString("host").trim()).ifBlank { fromBase.first }
            val port = parsePort(o, host).takeIf { it > 0 } ?: fromBase.second
            val bareHost = host.substringBefore(":").trim()
            val hasHostPort = bareHost.isNotBlank() && port in 1..65535

            // v2 格式：优先短码，同时兼容带 host/port/nonce 的直连兜底。
            if (v >= 2 || kind.contains("pairing", ignoreCase = true)) {
                val t = firstNonBlank(
                    o.optString("t"),
                    o.optString("code"),
                    o.optString("shortCode"),
                    o.optString("short_code"),
                    o.optString("token"),
                )
                if (t.isNotBlank()) {
                    return PairingQrPayload(
                        host = if (hasHostPort) bareHost else "",
                        port = if (hasHostPort) port else 0,
                        nonce = o.optString("nonce").trim(),
                        token = t,
                        apiBaseUrl = apiBaseUrl,
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
                        apiBaseUrl = apiBaseUrl,
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

    private fun firstNonBlank(vararg values: String): String =
        values.firstOrNull { it.trim().isNotBlank() }?.trim().orEmpty()

    private fun parseApiBase(apiBaseUrl: String): Pair<String, Int> {
        if (apiBaseUrl.isBlank()) return "" to 0
        return try {
            val normalized = if (apiBaseUrl.contains("://")) apiBaseUrl else "http://$apiBaseUrl"
            val uri = URI(normalized)
            val host = uri.host.orEmpty().trim()
            val port = if (uri.port in 1..65535) uri.port else {
                when (uri.scheme?.lowercase()) {
                    "https" -> 443
                    "http" -> 80
                    else -> 0
                }
            }
            host to port
        } catch (_: Exception) {
            "" to 0
        }
    }

    private fun parsePort(o: JSONObject, host: String): Int =
        when {
            o.has("port") -> o.optInt("port", 0)
            host.contains(":") -> host.substringAfter(":").toIntOrNull() ?: 0
            else -> 0
        }

    private fun parseDeepLink(text: String): PairingQrPayload? {
        return try {
            val uri = URI(text)
            val route = listOf(uri.host.orEmpty(), uri.path.orEmpty()).joinToString("/")
            if (!route.contains("pair", ignoreCase = true)) return null
            val params = parseQueryParams(uri.rawQuery)
            val nonce = params["nonce"].orEmpty()
            val code = firstNonBlank(
                params["code"].orEmpty(),
                params["shortCode"].orEmpty(),
                params["short_code"].orEmpty(),
                params["token"].orEmpty(),
            )
            val apiBaseUrl = firstNonBlank(
                params["api_base_url"].orEmpty(),
                params["api_base"].orEmpty(),
                params["base_url"].orEmpty(),
            )
            val relayId = firstNonBlank(
                params["relay_id"].orEmpty(),
                params["relayId"].orEmpty(),
            )
            val relayBaseUrl = firstNonBlank(
                params["relay_base_url"].orEmpty(),
                params["relayBaseUrl"].orEmpty(),
            )
            if (relayId.isNotBlank() && code.isNotBlank()) {
                return PairingQrPayload(
                    token = code,
                    relayId = relayId,
                    relayBaseUrl = relayBaseUrl,
                    version = 3,
                )
            }
            val fromBase = parseApiBase(apiBaseUrl)
            val host =
                params["host"]?.trim()?.removePrefix("http://")?.removePrefix("https://")
                    .orEmpty()
                    .ifBlank { fromBase.first }
            val port = params["port"]?.toIntOrNull()?.takeIf { it in 1..65535 }
                ?: fromBase.second
            val bareHost = host.substringBefore(":").trim()
            if (code.isNotBlank()) {
                PairingQrPayload(
                    host = bareHost,
                    port = if (port in 1..65535) port else 0,
                    nonce = nonce,
                    token = code,
                    apiBaseUrl = apiBaseUrl,
                    version = 2,
                )
            } else if (nonce.length >= 8 && bareHost.isNotBlank() && port in 1..65535) {
                PairingQrPayload(bareHost, port, nonce, apiBaseUrl = apiBaseUrl, version = 1)
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun parseQueryParams(rawQuery: String?): Map<String, String> =
        rawQuery.orEmpty()
            .split("&")
            .filter { it.isNotBlank() }
            .mapNotNull { pair ->
                val key = pair.substringBefore("=", "").trim()
                if (key.isBlank()) {
                    null
                } else {
                    key to decodeQueryValue(pair.substringAfter("=", ""))
                }
            }
            .toMap()

    private fun decodeQueryValue(value: String): String =
        try {
            URLDecoder.decode(value, Charsets.UTF_8.name()).trim()
        } catch (_: Exception) {
            value.trim()
        }

    fun formatHostPort(host: String, port: Int): String {
        val bare = host.trim().removePrefix("http://").removePrefix("https://").substringBefore(":").trim()
        return "$bare:$port"
    }
}
