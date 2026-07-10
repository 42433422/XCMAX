package com.xiuci.xcagi.mobile.feature.web

import java.net.URI

/** Strict URL policy for credential-bearing WebViews. */
object UrlHostPolicy {
    private const val PROD_HOST = "xiu-ci.com"

    private fun parseUri(url: String): URI? =
        try {
            URI(url.trim())
        } catch (_: Exception) {
            null
        }

    fun parseHttpHost(url: String): String? {
        val uri = parseUri(url) ?: return null
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        return uri.host?.trim()?.trimEnd('.')?.lowercase()?.takeIf { it.isNotEmpty() }
    }

    private fun scheme(url: String): String? = parseUri(url)?.scheme?.lowercase()

    fun isProductionHost(host: String?): Boolean =
        !host.isNullOrBlank() && (host == PROD_HOST || host.endsWith(".$PROD_HOST"))

    fun isPrivateLanHost(host: String?): Boolean {
        if (host.isNullOrBlank()) return false
        if (host == "localhost" || host == "::1") return true
        val octets = parseIpv4(host) ?: return false
        val (a, b, _, _) = octets
        return a == 127 || a == 10 || (a == 192 && b == 168) || (a == 172 && b in 16..31)
    }

    private fun parseIpv4(host: String): List<Int>? {
        val parts = host.split(".")
        if (parts.size != 4) return null
        return parts.map { part ->
            if (part.isEmpty() || part.length > 3 || !part.all(Char::isDigit)) return null
            part.toInt().takeIf { it <= 255 } ?: return null
        }
    }

    fun shouldInjectMarketTokens(url: String): Boolean =
        scheme(url) == "https" && isProductionHost(parseHttpHost(url))

    fun shouldInjectFhdSession(url: String): Boolean =
        scheme(url) == "http" && isPrivateLanHost(parseHttpHost(url))

    fun isTrustedWebViewUrl(url: String, extraLanHost: String? = null): Boolean {
        val host = parseHttpHost(url) ?: return false
        if (isProductionHost(host)) return scheme(url) == "https"
        if (isPrivateLanHost(host)) return scheme(url) == "http"
        val lan = extraLanHost?.substringBefore(':')?.trim()?.trimEnd('.')?.lowercase()
        return scheme(url) == "http" && !lan.isNullOrBlank() && host == lan
    }
}
