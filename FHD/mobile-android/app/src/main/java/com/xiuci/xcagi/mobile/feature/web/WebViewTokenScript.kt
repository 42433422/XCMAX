package com.xiuci.xcagi.mobile.feature.web

fun buildTokenInjectScript(
    accessToken: String,
    refreshToken: String,
    fhdAccessToken: String = "",
): String {
    fun esc(s: String) = s.replace("\\", "\\\\").replace("'", "\\'")
    val refreshLine = if (refreshToken.isNotBlank()) {
        "localStorage.setItem('modstore_refresh_token','${esc(refreshToken)}');"
    } else {
        ""
    }
    val fhdLines = if (fhdAccessToken.isNotBlank()) {
        val tok = esc(fhdAccessToken)
        "document.cookie = 'session_id=$tok; path=/; SameSite=Lax';"
    } else {
        ""
    }
    return """
        (function() {
          try {
            localStorage.setItem('modstore_token','${esc(accessToken)}');
            $refreshLine
            $fhdLines
            window.__XCAGI_CLIENT__ = 'android';
            document.documentElement.classList.add('xcagi-client-android');
            window.dispatchEvent(new Event('xcagi-client-ready'));
          } catch (e) {}
        })();
    """.trimIndent()
}

fun shouldInjectMarketTokens(url: String): Boolean =
    url.contains("xiu-ci.com", ignoreCase = true)

/** 局域网 FHD Web 页：注入 session cookie 供 SPA credentials 鉴权 */
fun shouldInjectFhdSession(url: String): Boolean {
    if (shouldInjectMarketTokens(url)) return false
    val lower = url.lowercase()
    return lower.startsWith("http://") &&
        (
            lower.contains("127.0.0.1") ||
                lower.contains("192.168.") ||
                lower.contains("10.") ||
                lower.contains("localhost")
            )
}
