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

/**
 * 是否注入 MODstore market token。
 *
 * 安全修复：旧实现 `url.contains("xiu-ci.com")` 是子串匹配，
 * `https://evil.com/?xiu-ci.com` 即可骗取 token；现委托 [UrlHostPolicy]
 * 做严格 host 解析（HTTPS + 精确域/子域）。
 */
fun shouldInjectMarketTokens(url: String): Boolean =
    UrlHostPolicy.shouldInjectMarketTokens(url)

/**
 * 局域网 FHD Web 页：注入 session cookie 供 SPA credentials 鉴权。
 *
 * 安全修复：旧实现 `lower.contains("10.")` 会匹配 `http://evil.com/10.html`；
 * 现要求 host 为字面 loopback / RFC1918 私网 IPv4 / localhost。
 */
fun shouldInjectFhdSession(url: String): Boolean =
    UrlHostPolicy.shouldInjectFhdSession(url)
