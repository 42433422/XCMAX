package com.xiuci.xcagi.mobile.feature.web

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlHostPolicyTest {

    // ----- shouldInjectMarketTokens：生产域严格判定 -----

    @Test
    fun marketTokensInjectedOnHttpsProductionHost() {
        assertTrue(UrlHostPolicy.shouldInjectMarketTokens("https://xiu-ci.com/market"))
        assertTrue(UrlHostPolicy.shouldInjectMarketTokens("https://www.xiu-ci.com/"))
        assertTrue(UrlHostPolicy.shouldInjectMarketTokens("https://sub.xiu-ci.com/path?q=1"))
    }

    @Test
    fun marketTokensNotInjectedOnPlainHttpProductionHost() {
        // 明文 HTTP 下注入 token 可被中间人截获
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("http://xiu-ci.com/market"))
    }

    @Test
    fun marketTokensNotInjectedWhenHostOnlyAppearsInQueryOrPath() {
        // 旧 contains() 判定的绕过向量：域名出现在 query/path/userinfo 而非 host
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://evil.com/?ref=xiu-ci.com"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://evil.com/xiu-ci.com/login"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://xiu-ci.com.evil.com/"))
        assertFalse(UrlHostPolicy.shouldInjectMarketTokens("https://evilxiu-ci.com/"))
    }

    // ----- shouldInjectFhdSession：LAN 私网严格判定 -----

    @Test
    fun fhdSessionInjectedOnPrivateLanHosts() {
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://127.0.0.1:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://192.168.1.23:17500/chat"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://10.0.0.5:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://172.16.0.9:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://172.31.255.1:17500/"))
        assertTrue(UrlHostPolicy.shouldInjectFhdSession("http://localhost:17500/"))
    }

    @Test
    fun fhdSessionNotInjectedOnPublicHosts() {
        // 旧 contains("10.") 判定的绕过向量
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://evil.com/10.html"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://evil.com/?ip=192.168.1.1"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://192.168.evil.com/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://10.evil.com/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://8.8.8.8/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://172.32.0.1/"))
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("http://11.0.0.1/"))
    }

    @Test
    fun fhdSessionNotInjectedOnProductionDomain() {
        // 生产域走 market token 链路，不注入 LAN session
        assertFalse(UrlHostPolicy.shouldInjectFhdSession("https://xiu-ci.com/"))
    }

    // ----- isTrustedWebViewUrl：加载白名单 -----

    @Test
    fun trustedWebViewUrlAcceptsProductionAndLan() {
        assertTrue(UrlHostPolicy.isTrustedWebViewUrl("https://xiu-ci.com/mods/foo"))
        assertTrue(UrlHostPolicy.isTrustedWebViewUrl("http://192.168.0.10:17500/mods/foo"))
        assertTrue(UrlHostPolicy.isTrustedWebViewUrl("http://10.1.2.3:17500/"))
    }

    @Test
    fun trustedWebViewUrlAcceptsExplicitPairedLanHost() {
        assertTrue(UrlHostPolicy.isTrustedWebViewUrl("http://my-desktop.lan:17500/", "my-desktop.lan:17500"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("http://other-host.lan:17500/", "my-desktop.lan:17500"))
    }

    @Test
    fun trustedWebViewUrlRejectsUntrusted() {
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("https://evil.com/"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("javascript:alert(1)"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("file:///sdcard/secret.txt"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("about:blank"))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl(""))
        assertFalse(UrlHostPolicy.isTrustedWebViewUrl("not a url"))
    }

    // ----- host 解析细节 -----

    @Test
    fun parseHttpHostNormalizesCaseAndTrailingDot() {
        assertEquals("xiu-ci.com", UrlHostPolicy.parseHttpHost("HTTPS://XIU-CI.COM./x"))
    }

    @Test
    fun parseHttpHostRejectsNonHttpSchemes() {
        assertEquals(null, UrlHostPolicy.parseHttpHost("ftp://xiu-ci.com/"))
        assertEquals(null, UrlHostPolicy.parseHttpHost("javascript:alert(1)"))
    }

    @Test
    fun privateLanHostRejectsMalformedIpv4() {
        assertFalse(UrlHostPolicy.isPrivateLanHost("192.168.1"))
        assertFalse(UrlHostPolicy.isPrivateLanHost("192.168.1.999"))
        assertFalse(UrlHostPolicy.isPrivateLanHost("192.168.1.1.1"))
        assertFalse(UrlHostPolicy.isPrivateLanHost(""))
        assertFalse(UrlHostPolicy.isPrivateLanHost(null))
    }
}
