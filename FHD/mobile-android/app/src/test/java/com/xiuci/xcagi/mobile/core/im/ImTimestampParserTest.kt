package com.xiuci.xcagi.mobile.core.im

import org.junit.Assert.assertEquals
import org.junit.Test

class ImTimestampParserTest {
    @Test
    fun `parses millisecond timestamp strings`() {
        assertEquals(1_750_000_000_123L, ImRepository.parseTimestampMs("1750000000123"))
    }

    @Test
    fun `normalizes second timestamp strings to milliseconds`() {
        assertEquals(1_750_000_000_000L, ImRepository.parseTimestampMs("1750000000"))
    }
}
