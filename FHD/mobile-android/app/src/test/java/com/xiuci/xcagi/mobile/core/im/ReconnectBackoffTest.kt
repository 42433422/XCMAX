package com.xiuci.xcagi.mobile.core.im

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReconnectBackoffTest {
    @Test
    fun firstAttemptReturnsBaseDelay() {
        assertEquals(5000L, ReconnectBackoff.delayForAttempt(0))
    }

    @Test
    fun secondAttemptDoublesDelay() {
        assertEquals(10_000L, ReconnectBackoff.delayForAttempt(1))
    }

    @Test
    fun thirdAttemptQuadruplesDelay() {
        assertEquals(20_000L, ReconnectBackoff.delayForAttempt(2))
    }

    @Test
    fun delayCappedAtFiveMinutes() {
        assertEquals(300_000L, ReconnectBackoff.delayForAttempt(10))
        assertEquals(300_000L, ReconnectBackoff.delayForAttempt(100))
    }

    @Test
    fun allDelaysArePositive() {
        for (i in 0..20) {
            assertTrue("attempt $i", ReconnectBackoff.delayForAttempt(i) > 0)
        }
    }
}
