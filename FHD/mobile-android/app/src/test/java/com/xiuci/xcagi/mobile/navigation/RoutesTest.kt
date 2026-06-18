package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.core.audit.SurfaceAudit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 签约级交付：NavHost 路由与 SurfaceAudit 对齐。 */
class RoutesTest {

    @Test
    fun surfaceAudit_includesCoreDeliveryRoutes() {
        val core = setOf(
            Routes.AUTH,
            Routes.CONNECT,
            Routes.CHAT,
            Routes.WORK,
            Routes.DISCOVER,
            Routes.PROFILE,
            Routes.SETTINGS,
            Routes.SCAN_QR,
        )
        core.forEach { route ->
            assertTrue("SurfaceAudit missing route: $route", route in SurfaceAudit.navigableRoutes)
        }
    }

    @Test
    fun erpTab_buildsParameterizedRoute() {
        assertTrue(Routes.erpTab(1).startsWith("erp_tab/"))
    }

    @Test
    fun aiEmployeeRoutes_keepWechatStyleProductShape() {
        val bottomTabs = listOf(Routes.CHAT, Routes.WORK, Routes.DISCOVER, Routes.PROFILE)

        assertEquals(listOf("chat", "work", "discover", "profile"), bottomTabs)
        assertEquals("ai_employees", Routes.AI_EMPLOYEES)
        assertEquals("ai_circle", Routes.AI_CIRCLE)
        assertEquals("ai_employee/mod-a/employee-1", Routes.aiEmployeeProfile("mod-a", "employee-1"))
        assertFalse(bottomTabs.any { it.contains("home", ignoreCase = true) })
    }
}
