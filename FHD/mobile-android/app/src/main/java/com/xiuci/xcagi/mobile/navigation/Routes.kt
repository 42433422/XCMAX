package com.xiuci.xcagi.mobile.navigation

object Routes {
    const val LEGAL = "legal"
    const val SPLASH = "splash"
    const val CONNECT = "connect"
    const val CONNECT_PC = "connect_pc"
    const val AUTH = "auth"
    const val REGISTER = "register"
    const val HOME_HUB = "home_hub"
    /** 4 Tab：工作（审批 + 业务聚合入口） */
    const val WORK = "work"
    /** 4 Tab：发现（工作台 / Mod / 市场 / 扫一扫） */
    const val DISCOVER = "discover"
    const val WORKBENCH = "workbench"
    const val PROFILE = "profile"
    /** @deprecated 仅高级入口保留，不再作为底栏 Tab */
    const val HOME = "home"
    const val CHAT = "chat"
    /** IM V0 原生会话（SurfaceAudit / 高级入口） */
    const val IM = "im"
    const val APPROVAL = "approval"
    const val APPROVAL_DETAIL = "approval/{id}"
    const val ERP = "erp"
    /** 与 config/surface_audit_pages.json android_route 对齐 */
    const val ERP_OVERVIEW = "erp_overview"
    const val ERP_TAB = "erp_tab/{tabIndex}"
    fun erpTab(tabIndex: Int) = "erp_tab/$tabIndex"
    const val BRIDGE = "bridge"
    const val MARKET = "market"
    const val MODS = "mods"
    const val MOD_WEB = "mod/{modId}"
    const val OCR = "ocr"
    const val LONGTAIL = "longtail"
    const val SETTINGS = "settings"
    const val ABOUT = "about"
    const val SCAN_QR = "scan_qr"
}
