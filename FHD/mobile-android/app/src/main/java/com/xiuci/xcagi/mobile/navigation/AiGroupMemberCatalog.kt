package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.ui.components.mobile.AppAvatarFallback

internal const val XIAOC_ASSISTANT_EMPLOYEE_ID = "xcagi-assistant"
internal const val CODEX_SUPER_EMPLOYEE_ID = "codex-super-employee"
internal const val CURSOR_SUPER_EMPLOYEE_ID = "cursor-super-employee"
internal const val CLAUDE_SUPER_EMPLOYEE_ID = "claude-super-employee"
internal const val TRAE_SUPER_EMPLOYEE_ID = "trae-super-employee"

internal val XIAOC_GROUP_PROFILE = AiEmployeeProfile(
    modId = "xcagi-core-assistant",
    modName = "XCAGI 助理",
    modDescription = "企业智能助手",
    modVersion = "",
    modAuthor = "XCAGI",
    industryName = "通用",
    employeeId = XIAOC_ASSISTANT_EMPLOYEE_ID,
    name = "小C助理",
    title = "企业智能助手",
    summary = "负责群内上下文、任务拆解和工作汇报串联。",
    apiBasePath = "",
    phoneChannel = "mobile-chat",
    workflowPlaceholder = false,
    profileSource = "fixed-assistant",
    marketConnected = false,
    marketPkgId = "",
    marketVersion = "",
    marketAuthor = "XCAGI",
    marketMaterialCategory = "",
    marketLicenseScope = "",
    marketSecurityLevel = "",
    avatarUrl = null,
)

internal fun List<ModInfo>.aiGroupMemberCatalog(): List<AiEmployeeProfile> {
    val fixed = listOf(
        XIAOC_GROUP_PROFILE,
        superEmployeeProfile(
            employeeId = CODEX_SUPER_EMPLOYEE_ID,
            name = "超级员工-Codex",
            summary = "Codex CLI 超级员工，支持代码任务、测试和汇报。",
        ),
        superEmployeeProfile(
            employeeId = CURSOR_SUPER_EMPLOYEE_ID,
            name = "超级员工-Cursor",
            summary = "Cursor Agent 超级员工，支持工程修改和上下文协作。",
        ),
        superEmployeeProfile(
            employeeId = CLAUDE_SUPER_EMPLOYEE_ID,
            name = "超级员工-Claude",
            summary = "Claude CLI 超级员工，支持分析、编写和任务复盘。",
        ),
        superEmployeeProfile(
            employeeId = TRAE_SUPER_EMPLOYEE_ID,
            name = "超级员工-Trae",
            summary = "Trae CLI 超级员工，支持 IDE 执行端、备用额度和补位协作。",
        ),
    )
    return (fixed + aiEmployeeProfiles()).distinctBy { it.employeeId }
}

internal fun aiGroupMemberFallback(employeeId: String): AppAvatarFallback =
    when (employeeId.trim()) {
        XIAOC_ASSISTANT_EMPLOYEE_ID -> AppAvatarFallback.ASSISTANT
        CODEX_SUPER_EMPLOYEE_ID -> AppAvatarFallback.CODEX
        CURSOR_SUPER_EMPLOYEE_ID -> AppAvatarFallback.CURSOR
        CLAUDE_SUPER_EMPLOYEE_ID -> AppAvatarFallback.CLAUDE
        TRAE_SUPER_EMPLOYEE_ID -> AppAvatarFallback.TRAE
        else -> AppAvatarFallback.AI_EMPLOYEE
    }

internal fun isRequiredAiGroupMember(employeeId: String): Boolean =
    employeeId.trim() == XIAOC_ASSISTANT_EMPLOYEE_ID

internal fun AiEmployeeProfile.matchesGroupMemberQuery(query: String): Boolean {
    val q = query.trim()
    if (q.isBlank()) return true
    return name.contains(q, ignoreCase = true) ||
        title.contains(q, ignoreCase = true) ||
        summary.contains(q, ignoreCase = true) ||
        employeeId.contains(q, ignoreCase = true) ||
        modName.contains(q, ignoreCase = true)
}

private fun superEmployeeProfile(
    employeeId: String,
    name: String,
    summary: String,
): AiEmployeeProfile =
    AiEmployeeProfile(
        modId = "super-employee",
        modName = "超级员工",
        modDescription = "绑定桌面 CLI 的超级员工",
        modVersion = "",
        modAuthor = "XCAGI",
        industryName = "工程协作",
        employeeId = employeeId,
        name = name,
        title = name,
        summary = summary,
        apiBasePath = "",
        phoneChannel = "mobile-chat",
        workflowPlaceholder = false,
        profileSource = "fixed-super-employee",
        marketConnected = false,
        marketPkgId = "",
        marketVersion = "",
        marketAuthor = "XCAGI",
        marketMaterialCategory = "",
        marketLicenseScope = "",
        marketSecurityLevel = "",
        avatarUrl = null,
    )
