package com.xiuci.xcagi.mobile.core.repository

import com.xiuci.xcagi.mobile.core.network.ServerMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthRoutingPolicyTest {
    @Test
    fun enterpriseBuildWithBoundDesktopHostUsesUnifiedEnterpriseAuthSource() {
        assertTrue(AuthRoutingPolicy.shouldUseEnterpriseAuthHost(true, "192.168.1.8:5100"))
        assertEquals(
            ServerMode.LAN,
            AuthRoutingPolicy.preferredServerModeAfterLogin(true, "192.168.1.8:5100"),
        )
    }

    @Test
    fun enterpriseBuildWithoutBoundDesktopHostFallsBackToCloudMode() {
        assertFalse(AuthRoutingPolicy.shouldUseEnterpriseAuthHost(true, ""))
        assertEquals(ServerMode.CLOUD, AuthRoutingPolicy.preferredServerModeAfterLogin(true, ""))
    }

    @Test
    fun personalBuildDoesNotHijackToEnterpriseHostEvenWhenHostExists() {
        assertFalse(AuthRoutingPolicy.shouldUseEnterpriseAuthHost(false, "192.168.1.8:5100"))
        assertEquals(
            ServerMode.CLOUD,
            AuthRoutingPolicy.preferredServerModeAfterLogin(false, "192.168.1.8:5100"),
        )
    }
}
