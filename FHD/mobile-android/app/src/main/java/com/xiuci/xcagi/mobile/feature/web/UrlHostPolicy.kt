package com.xiuci.xcagi.mobile.feature.web

import java.net.URI

/**
 * WebView URL 信任判定（v10 线内迭代 · 安全审计修复）。
 *
 * 背景：历史实现用 `url.contains("xiu-ci.com")` / `url.contains("10.")` 之类的
 * **子串匹配**决定是否向页面注入 market/FHD token —— `https://evil.com/?xiu-ci.com`
 * 或 `http://evil.com/10.html` 都能骗过判定，把登录凭证注入到攻击者页面。
 *
 * 本对象统一为**严格 host 解析**（java.net.URI，纯 JVM 可单测）：
 * - 生产域：精确等于 `xiu-ci.com` 或其子域，且必须 HTTPS 才注入 market token；
 * - 局域网：host 必须是字面 loopback / RFC1918 私网 IPv4 或 `localhost`，
 *   才视为可注入 FHD session 的桌面配对页面；
 * - 其余（含解析失败、userinfo 混淆、非 http(s) scheme）一律不信任。
 */
object UrlHostPolicy {
    private const val PROD_HOST = "xiu-ci.com"

    /** 解析 URL 的 host（小写）；非 http/https 或解析失败返回 null。 */
    fun parseHttpHost(url: String): String? {
        val uri = try {
            URI(url.trim())
        } catch (_: Exception) {
            return null
        }
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        return uri.host?.trim()?.trimEnd('.')?.lowercase()?.takeIf { it.isNotEmpty() }
    }

    private fun scheme(url: String): String? =
        try {
            URI(url.trim()).scheme?.lowercase()
        } catch (_: Exception) {
            null
        }

    /** host 是否为生产域 xiu-ci.com（含子域）。 */
    fun isProductionHost(host: String?): Boolean {
        if (host.isNullOrBlank()) return false
        return host == PROD_HOST || host.endsWith(".$PROD_HOST")
    }

    /** host 是否为 loopback / RFC1918 私网 IPv4 / localhost（桌面 LAN 配对面）。 */
    fun isPrivateLanHost(host: String?): Boolean {
        if (host.isNullOrBlank()) return false
        if (host == "localhost") return true
        val octets = parseIpv4(host) ?: return false
        val (a, b, _, _) = octets
        return when {
            a == 127 -> true
            a == 10 -> true
            a == 192 && b == 168 -> true
            a == 172 && b in 16..31 -> true
            else -> false
        }
    }

    /** 严格 IPv4 字面量解析；非纯数字四段（如域名 `10.example.com`）返回 null。 */
    private fun parseIpv4(host: String): List<Int>? {
        val parts = host.split(".")
        if (parts.size != 4) return null
        val octets = parts.map { part ->
            if (part.isEmpty() || part.length > 3 || !part.all { it.isDigit() }) return null
            val v = part.toInt()
            if (v > 255) return null
            v
        }
        return octets
    }

    /** 是否向该页面注入 MODstore market token：必须 HTTPS + 生产域 host。 */
    fun shouldInjectMarketTokens(url: String): Boolean {
        if (scheme(url) != "https") return false
        return isProductionHost(parseHttpHost(url))
    }

    /**
     * 是否向该页面注入 FHD session（LAN 桌面配对页）：
     * 必须 http + loopback/私网 IP host（LAN FHD 默认明文 HTTP，域名部署走 HTTPS 生产链路）。
     */
    fun shouldInjectFhdSession(url: String): Boolean {
        if (shouldInjectMarketTokens(url)) return false
        if (scheme(url) != "http") return false
        return isPrivateLanHost(parseHttpHost(url))
    }

    /**
     * WebView 是否允许加载该 URL（Mod 宿主 / 桌面工具页）：
     * 生产域（http/https）、私网/loopback host，或显式配对的 LAN 主机。
     */
    fun isTrustedWebViewUrl(url: String, extraLanHost: String? = null): Boolean {
        val host = parseHttpHost(url) ?: return false
        if (isProductionHost(host)) return true
        if (isPrivateLanHost(host)) return true
        val lan = extraLanHost?.substringBefore(':')?.trim()?.trimEnd('.')?.lowercase()
        return !lan.isNullOrBlank() && host == lan
    }
}
