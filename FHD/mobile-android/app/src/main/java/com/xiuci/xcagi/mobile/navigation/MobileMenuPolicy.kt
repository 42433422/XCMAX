package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.ModMenuItem

internal object MobileMenuPolicy {
    private val genericBridgeModIds =
        setOf(
            "xcagi-erp-domain-bridge",
            "xcagi-planner-bridge",
            "xcagi-approval-bridge",
            "xcagi-customer-service-bridge",
            "xcagi-model-payment-bridge",
            "xcagi-workflow-visualization-bridge",
        )

    private val accountIndustryModIds =
        setOf(
            "attendance-industry",
            "taiyangniao-pro",
            "sz-qsm-pro",
        )

    private val industryScopedMenuIds =
        setOf(
            "products",
            "customers",
            "orders",
            "orders-create",
            "shipment-records",
            "materials",
            "materials-list",
            "traditional-mode",
            "business-docking",
            "data-sources",
            "print",
            "printer-list",
            "template-preview",
            "wechat-contacts",
            "approval-hub",
            "enterprise-customer-service",
            "internal-customer-service",
            "kitten-finance",
            "workflow-visualization",
        )

    fun hasIndustryScope(mods: List<ModInfo>): Boolean =
        mods.any { mod ->
            val id = mod.id.trim()
            id in accountIndustryModIds ||
                (id !in genericBridgeModIds && !mod.industry?.id.isNullOrBlank())
        }

    fun visibleMenus(
        mod: ModInfo,
        hasIndustryScope: Boolean,
    ): List<ModMenuItem> =
        mod.frontend_menu.filter { menu ->
            hasIndustryScope || !isIndustryScoped(menu)
        }

    fun isIndustryScoped(menu: ModMenuItem): Boolean {
        val normalizedId = normalizeMenuKey(menu.id)
        if (normalizedId in industryScopedMenuIds) return true

        val path = menu.path.trim().lowercase()
        return industryScopedMenuIds.any { key ->
            path == "/$key" || path.endsWith("/$key") || path.contains("/$key/")
        }
    }

    private fun normalizeMenuKey(raw: String): String =
        raw.trim()
            .removePrefix("mod-erp-")
            .removePrefix("mod-planner-")
            .removePrefix("mod-")
}
