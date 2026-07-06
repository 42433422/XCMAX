package com.xiuci.xcagi.mobile.feature.web

import android.net.Uri
import com.xiuci.xcagi.mobile.BuildConfig

object WebViewUrlPolicy {
    /**
     * WebView 内允许直接加载的 URL；域外链接交给 Custom Tabs。
     *
     * 委托 [UrlHostPolicy] 严格 host 判定：生产域（含子域）、loopback、
     * RFC1918 私网 IPv4（10/8、172.16/12、192.168/16）、localhost 或显式配对的 LAN 主机。
     * 相比旧实现补全了 10.x / 172.16-31.x 网段，并把 `192.168.` 前缀匹配收紧为
     * 严格 IPv4 字面量解析（`192.168.evil.com` 不再放行）。
     */
    fun isAllowed(url: String, extraLanHost: String? = null): Boolean =
        UrlHostPolicy.isTrustedWebViewUrl(url, extraLanHost)

    fun modstoreHost(): String = Uri.parse(BuildConfig.MODSTORE_BASE_URL).host.orEmpty()
}
