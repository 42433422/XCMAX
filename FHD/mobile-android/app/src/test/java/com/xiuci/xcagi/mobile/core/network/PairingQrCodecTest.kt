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
}
