package com.xiuci.xcagi.mobile.core.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class PairingQrCodecTest {
    @Test
    fun parseV2QrKeepsHostPortNonceForFirstBinding() {
        val raw = """{"v":2,"t":"123456","host":"192.168.1.20","port":5100,"nonce":"nonce-abc"}"""

        val payload = PairingQrCodec.parse(raw)

        assertNotNull(payload)
        assertEquals(2, payload!!.version)
        assertEquals("123456", payload.token)
        assertEquals("192.168.1.20", payload.host)
        assertEquals(5100, payload.port)
        assertEquals("nonce-abc", payload.nonce)
    }

    @Test
    fun parseBareSixDigitCodeAsV2Token() {
        val payload = PairingQrCodec.parse("123456")

        assertNotNull(payload)
        assertEquals(2, payload!!.version)
        assertEquals("123456", payload.token)
        assertEquals("", payload.host)
        assertEquals(0, payload.port)
    }

    @Test
    fun parseMobileReadyJsonUsesApiBaseUrl() {
        val raw =
            """{"v":2,"kind":"xcagi_pairing","code":"654321","api_base_url":"http://192.168.0.38:17500/","nonce":"nonce-abc"}"""

        val payload = PairingQrCodec.parse(raw)

        assertNotNull(payload)
        assertEquals(2, payload!!.version)
        assertEquals("654321", payload.token)
        assertEquals("192.168.0.38", payload.host)
        assertEquals(17500, payload.port)
        assertEquals("http://192.168.0.38:17500/", payload.apiBaseUrl)
    }

    @Test
    fun parsePairingDeepLinkUsesCodeAndApiBaseUrl() {
        val raw =
            "xcagi://pairing?code=123456&api_base_url=http%3A%2F%2F192.168.0.38%3A17500%2F&nonce=nonce-abc"

        val payload = PairingQrCodec.parse(raw)

        assertNotNull(payload)
        assertEquals(2, payload!!.version)
        assertEquals("123456", payload.token)
        assertEquals("192.168.0.38", payload.host)
        assertEquals(17500, payload.port)
        assertEquals("nonce-abc", payload.nonce)
    }

    @Test
    fun parseRelayPairingJsonKeepsRelayFieldsOnly() {
        val raw =
            """{"v":3,"kind":"xcagi_relay_pairing","relay_id":"relay-abc","code":"123456","relay_base_url":"https://xiu-ci.com/fhd-api/"}"""

        val payload = PairingQrCodec.parse(raw)

        assertNotNull(payload)
        assertEquals(3, payload!!.version)
        assertEquals("relay-abc", payload.relayId)
        assertEquals("123456", payload.token)
        assertEquals("https://xiu-ci.com/fhd-api/", payload.relayBaseUrl)
        assertEquals("", payload.host)
        assertEquals(0, payload.port)
    }

    @Test
    fun parseRelayPairingDeepLinkKeepsRelayFields() {
        val raw =
            "xcagi://relay-pairing?relay_id=relay-abc&code=123456&relay_base_url=https%3A%2F%2Fxiu-ci.com%2Ffhd-api%2F"

        val payload = PairingQrCodec.parse(raw)

        assertNotNull(payload)
        assertEquals(3, payload!!.version)
        assertEquals("relay-abc", payload.relayId)
        assertEquals("123456", payload.token)
        assertEquals("https://xiu-ci.com/fhd-api/", payload.relayBaseUrl)
    }
}
