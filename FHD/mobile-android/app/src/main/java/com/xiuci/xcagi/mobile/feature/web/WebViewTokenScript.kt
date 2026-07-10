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
    UrlHostPolicy.shouldInjectMarketTokens(url)

/** 局域网 FHD Web 页：注入 session cookie 供 SPA credentials 鉴权 */
fun shouldInjectFhdSession(url: String): Boolean =
    UrlHostPolicy.shouldInjectFhdSession(url)
