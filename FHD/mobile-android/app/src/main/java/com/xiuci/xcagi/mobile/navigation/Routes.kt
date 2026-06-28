package com.xiuci.xcagi.mobile.navigation

import android.net.Uri

object Routes {
    const val LEGAL = "legal"
    const val SPLASH = "splash"
    const val CONNECT = "connect"
    const val CONNECT_PC = "connect_pc"
    const val AUTH = "auth"
    const val AUTH_AUTO_LOGIN = "auth_auto_login"
    const val REGISTER = "register"
    const val ONBOARDING = "onboarding"
    const val HOME_HUB = "home_hub"
    /** 4 Tab：AI 员工通讯录。路由名沿用 work 以兼容旧跳转和巡检。 */
    const val WORK = "work"
    /** 4 Tab：探索（AI交流圈优先，扫码 / OCR / 通知作为工具入口） */
    const val DISCOVER = "discover"
    const val PROFILE = "profile"
    /** @deprecated 仅高级入口保留，不再作为底栏 Tab */
    const val HOME = "home"
    const val CHAT = "chat"
    /** AI 对话（从会话列表进入的 AI 助手聊天） */
    const val AI_CHAT = "ai_chat"
    /** 普通会话对话（带 conversationId 参数） */
    const val CONVERSATION_CHAT = "conversation_chat"
    /** 专属客服对话 */
    const val CS_CHAT = "cs_chat"
    /** 管理端客服收件箱(运营者:企业客户↔企业专属客服) */
    const val ADMIN_CS_CONSOLE = "admin_cs_console"
    const val FIXED_PARTNER_PROFILE = "fixed_partner/{partnerKind}"

    fun conversationChat(conversationId: String): String = "$CONVERSATION_CHAT/$conversationId"
    fun fixedPartnerProfile(partnerKind: String): String = "fixed_partner/$partnerKind"

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
    /** AI 员工列表页。列表只来自当前账号的企业端/管理端生态。 */
    const val AI_EMPLOYEES = "ai_employees"
    const val AI_CIRCLE = "ai_circle"
    /** AI 群聊列表（默认 6 部门群 + 自定义群） */
    const val AI_GROUPS = "ai_groups"
    /** AI 群聊会话（当前群由 ViewModel.currentGroup 持有） */
    const val AI_GROUP_CHAT = "ai_group_chat"
    /** 发起群聊（多选 AI 员工建群） */
    const val AI_GROUP_CREATE = "ai_group_create"
    const val AI_EMPLOYEE_PROFILE = "ai_employee/{modId}/{employeeId}"
    fun aiEmployeeProfile(modId: String, employeeId: String) = "ai_employee/$modId/$employeeId"
    /** 智慧分析（Kitten Analyzer） */
    const val SMART_ANALYSIS = "smart_analysis"
    /** AIOPEN 开放智控 */
    const val AI_OPEN = "ai_open"
    /** 生产员工 / 智脑集成 */
    const val BRAIN = "brain"
    /** 员工商店 / 能力库 */
    const val MOD_STORE = "mod_store"
    /** 通知与公告 */
    const val NOTIFICATIONS = "notifications"

    /** 通用 WebView（探索 Tab 桌面工具入口，打开桌面端页面） */
    const val WEB_VIEW = "web_view?url={url}&title={title}"
    fun webView(url: String, title: String): String = "web_view?url=${Uri.encode(url)}&title=${Uri.encode(title)}"
}
