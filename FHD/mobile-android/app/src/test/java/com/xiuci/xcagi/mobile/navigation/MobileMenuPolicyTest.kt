package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.core.model.ModIndustry
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.ModMenuItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileMenuPolicyTest {
    private val erpBridge =
        ModInfo(
            id = "xcagi-erp-domain-bridge",
            name = "ERP 门面",
            frontend_menu =
                listOf(
                    ModMenuItem(id = "mod-erp-products", label = "业务对象", path = "/products"),
                    ModMenuItem(id = "mod-erp-orders", label = "业务单据", path = "/orders"),
                    ModMenuItem(id = "mod-erp-data-sources", label = "数据来源", path = "/data-sources"),
                ),
        )

    @Test
    fun hidesIndustryBusinessMenusWithoutIndustryScope() {
        assertFalse(MobileMenuPolicy.hasIndustryScope(listOf(erpBridge)))

        val visible = MobileMenuPolicy.visibleMenus(erpBridge, hasIndustryScope = false)

        assertEquals(emptyList<ModMenuItem>(), visible)
    }

    @Test
    fun allowsIndustryBusinessMenusWhenIndustryPackIsInstalled() {
        val industryPack =
            ModInfo(
                id = "coating-industry",
                name = "涂料行业包",
                industry = ModIndustry(id = "涂料", name = "涂料/化工行业"),
            )

        assertTrue(MobileMenuPolicy.hasIndustryScope(listOf(erpBridge, industryPack)))

        val visible = MobileMenuPolicy.visibleMenus(erpBridge, hasIndustryScope = true)

        assertEquals(3, visible.size)
    }

    @Test
    fun keepsGenericPlannerMenusVisible() {
        val planner =
            ModInfo(
                id = "xcagi-planner-bridge",
                name = "Planner",
                frontend_menu =
                    listOf(
                        ModMenuItem(id = "mod-planner-ai-ecosystem", label = "智能生态"),
                        ModMenuItem(id = "mod-planner-brain", label = "智脑集成"),
                    ),
            )

        val visible = MobileMenuPolicy.visibleMenus(planner, hasIndustryScope = false)

        assertEquals(2, visible.size)
    }
}
