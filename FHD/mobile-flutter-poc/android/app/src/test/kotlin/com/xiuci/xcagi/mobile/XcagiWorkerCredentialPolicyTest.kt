package com.xiuci.xcagi.mobile

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XcagiWorkerCredentialPolicyTest {
    @Test
    fun managementPairingRequiresCurrentAdminWithSameSubject() {
        assertTrue(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "admin_portal",
                userId = 7,
                tenantId = 11,
                localAccountKind = "admin",
                localTokenScope = "management_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
        assertFalse(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "enterprise",
                userId = 7,
                tenantId = 11,
                localAccountKind = "admin",
                localTokenScope = "management_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
        assertFalse(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "admin",
                userId = 8,
                tenantId = 11,
                localAccountKind = "admin",
                localTokenScope = "management_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
    }

    @Test
    fun enterprisePairingRejectsManagementAndTenantMismatch() {
        assertTrue(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "enterprise",
                userId = 7,
                tenantId = 11,
                localAccountKind = "enterprise",
                localTokenScope = "enterprise_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
        assertFalse(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "admin",
                userId = 7,
                tenantId = 11,
                localAccountKind = "enterprise",
                localTokenScope = "enterprise_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
        assertFalse(
            XcagiWorkerCredentialPolicy.localPairingMatchesActiveIdentity(
                accountKind = "enterprise",
                userId = 7,
                tenantId = 12,
                localAccountKind = "enterprise",
                localTokenScope = "enterprise_pairing",
                localUserId = 7,
                localTenantId = 11,
            ),
        )
    }

    @Test
    fun copiedPairingCredentialIsNotTreatedAsCloudCredential() {
        assertFalse(
            XcagiWorkerCredentialPolicy.isCloudCredential(
                accessToken = "pair-token",
                sessionId = "pair-session",
                localAccessToken = "pair-token",
                localSessionId = "pair-session",
            ),
        )
        assertTrue(
            XcagiWorkerCredentialPolicy.isCloudCredential(
                accessToken = "cloud-token",
                sessionId = "cloud-session",
                localAccessToken = "pair-token",
                localSessionId = "pair-session",
            ),
        )
    }
}
