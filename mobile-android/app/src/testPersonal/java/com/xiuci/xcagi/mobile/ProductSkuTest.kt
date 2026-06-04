package com.xiuci.xcagi.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class ProductSkuTest {
    @Test
    fun personalSkuConstant_isPersonal() {
        assertEquals("personal", BuildConfig.PRODUCT_SKU)
    }
}
