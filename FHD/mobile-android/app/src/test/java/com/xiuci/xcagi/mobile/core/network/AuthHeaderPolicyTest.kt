package com.xiuci.xcagi.mobile.core.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthHeaderPolicyTest {
    private val modstoreBase = "https://xiu-ci.com"
    private val enterpriseFhdBase = "https://xiu-ci.com/fhd-api"

    @Test
    fun fhdApiUnderSameDomainUsesFhdTokenNotMarketToken() {
        val bearer =
            AuthHeaderPolicy.selectBearer(
                url = "https://xiu-ci.com/fhd-api/api/mobile/v1/admin/home",
                fhdToken = "fhd-token",
                marketToken = "stale-market-token",
                modstoreBaseUrl = modstoreBase,
                enterpriseFhdBaseUrl = enterpriseFhdBase,
            )

        assertEquals("fhd-token", bearer)
    }

    @Test
    fun fhdApiDoesNotFallBackToMarketTokenWhenFhdTokenIsMissing() {
        val bearer =
            AuthHeaderPolicy.selectBearer(
                url = "https://xiu-ci.com/fhd-api/api/mobile/v1/me",
                fhdToken = "",
                marketToken = "stale-market-token",
                modstoreBaseUrl = modstoreBase,
                enterpriseFhdBaseUrl = enterpriseFhdBase,
            )

        assertEquals("", bearer)
    }

    @Test
    fun modstorePathStillUsesMarketToken() {
        val bearer =
            AuthHeaderPolicy.selectBearer(
                url = "https://xiu-ci.com/api/market/catalog",
                fhdToken = "fhd-token",
                marketToken = "market-token",
                modstoreBaseUrl = modstoreBase,
                enterpriseFhdBaseUrl = enterpriseFhdBase,
            )

        assertEquals("market-token", bearer)
    }

    @Test
    fun fhdApiPrefixDoesNotMatchSiblingPath() {
        assertTrue(
            AuthHeaderPolicy.isEnterpriseFhdRequest(
                "https://xiu-ci.com/fhd-api/api/mobile/v1/me",
                enterpriseFhdBase,
            ),
        )
        assertFalse(
            AuthHeaderPolicy.isEnterpriseFhdRequest(
                "https://xiu-ci.com/fhd-api-old/api/mobile/v1/me",
                enterpriseFhdBase,
            ),
        )
    }

    @Test
    fun explicitChatAuthorizationIsNotOverwrittenByInterceptor() {
        assertFalse(
            AuthHeaderPolicy.shouldAttachSelectedBearer(
                isPublicAuthWriteRequest = false,
                callerAuthorization = "Bearer refreshed-market-token",
                selectedBearer = "fhd-token",
            ),
        )
        assertTrue(
            AuthHeaderPolicy.shouldAttachSelectedBearer(
                isPublicAuthWriteRequest = false,
                callerAuthorization = "",
                selectedBearer = "fhd-token",
            ),
        )
    }
}
