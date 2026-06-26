package com.xiuci.xcagi.mobile.core.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileSyncPolicyTest {
    @Test
    fun cloudModeDoesNotSkipAutoSyncWhenDesktopHostIsBlank() {
        assertFalse(MobileSyncPolicy.shouldSkipAutoSync(host = "", mode = "cloud"))
    }

    @Test
    fun lanModeSkipsAutoSyncWhenDesktopHostIsBlank() {
        assertTrue(MobileSyncPolicy.shouldSkipAutoSync(host = "", mode = "lan"))
    }

    @Test
    fun cloudStatusLabelDoesNotRequireDesktop() {
        assertEquals(
            "云端同步 2026-06-25 12:30:00",
            MobileSyncPolicy.statusLabel(
                lastSyncAt = "2026-06-25T12:30:00Z",
                mode = "cloud",
                pcOnline = false,
            ),
        )
    }

    @Test
    fun lanStatusLabelTreatsDesktopAsOptionalExecutor() {
        assertEquals(
            "桌面执行端未连接",
            MobileSyncPolicy.statusLabel(
                lastSyncAt = "2026-06-25T12:30:00Z",
                mode = "lan",
                pcOnline = false,
            ),
        )
    }

    @Test
    fun adminAccountsRefreshEmployeeRosterDuringSync() {
        assertTrue(MobileSyncPolicy.shouldRefreshEmployeeRoster("admin", showsEnterpriseNav = false))
        assertTrue(MobileSyncPolicy.shouldRefreshEmployeeRoster("admin_portal", showsEnterpriseNav = false))
        assertTrue(MobileSyncPolicy.shouldRefreshEmployeeRoster("enterprise", showsEnterpriseNav = true))
        assertFalse(MobileSyncPolicy.shouldRefreshEmployeeRoster("personal", showsEnterpriseNav = false))
    }
}
