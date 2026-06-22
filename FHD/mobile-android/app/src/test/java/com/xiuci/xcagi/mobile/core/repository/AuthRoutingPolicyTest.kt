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
    fun enterpriseBuildKeepsCloudModeAfterLanFailoverEvenWhenOldHostExists() {
        assertEquals(
            ServerMode.CLOUD,
            AuthRoutingPolicy.preferredServerModeAfterLogin(
                isEnterprise = true,
                configuredHost = "192.168.0.38:17500",
                currentMode = "cloud",
            ),
        )
    }

    @Test
    fun enterpriseBuildKeepsLanModeWhenLanIsStillSelected() {
        assertEquals(
            ServerMode.LAN,
            AuthRoutingPolicy.preferredServerModeAfterLogin(
                isEnterprise = true,
                configuredHost = "192.168.0.38:17500",
                currentMode = "lan",
            ),
        )
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
