package com.xiuci.xcagi.mobile.feature.web

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlHostPolicyTest {
    @Test
    fun marketTokensRequireHttpsProductionHost() {
        assertTrue(UrlHostPolicy.shouldInjectMarketTokens("https://xiu-ci.com/market"))
        assertTrue(UrlHostPolicy.shouldInjectMarketTokens("https://sub.xiu-ci.com/path"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("http://xiu-ci.com/market"))
    }

    @Test
    fun marketTokensRejectHostConfusion() {
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://evil.com/?ref=xiu-ci.com"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://xiu-ci.com.evil.com/"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://xiu-ci.com@evil.com/"))
    }

    @Test
    fun fhdSessionAcceptsPrivateLanHttp() {
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://127.0.0.1:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://192.168.1.23:17500/chat"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://10.0.0.5:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://172.31.255.1:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://localhost:17500/"))
    }

    @Test
    fun fhdSessionRejectsPublicAndHostConfusion() {
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://evil.com/10.html"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://192.168.evil.com/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://8.8.8.8/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://172.32.0.1/"))
    }

    @Test
    fun trustedWebViewRejectsPlaintextProductionAndUnsafeSchemes() {
        assertTrue(UrlHostPolicy.isTrustedWebViewUrl("https://xiu-ci.com/mods/foo"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("http://xiu-ci.com/mods/foo"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("javascript:alert(1)"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("file:///data/local/tmp/token"))
    }

    @Test
    fun trustedWebViewAcceptsOnlyMatchingPairedLanHost() {
        assertTrue(
            UrlHostPolicy.isTrustedWebViewUrl(
                "http://my-desktop.lan:17500/",
                "my-desktop.lan:17500",
            )
        )
        assertFalse(
            UrlHostPolicy.isTrustedWebViewUrl(
                "http://other-host.lan:17500/",
                "my-desktop.lan:17500",
            )
        )
    }
}
