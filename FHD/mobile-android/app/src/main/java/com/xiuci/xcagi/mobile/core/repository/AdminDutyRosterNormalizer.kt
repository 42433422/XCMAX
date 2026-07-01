package com.xiuci.xcagi.mobile.core.repository

import com.xiuci.xcagi.mobile.core.model.DutyRosterSsot
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo

internal object AdminDutyRosterNormalizer {
    const val ADMIN_DUTY_MOD_ID = "admin-duty-employees"

    fun normalize(mods: List<ModInfo>): List<ModInfo> =
        mods.map { mod ->
            if (mod.id == ADMIN_DUTY_MOD_ID || mod.id == "admin-duty") normalizeDutyMod(mod) else mod
        }

    fun isCurrent(mods: List<ModInfo>): Boolean {
        val dutyMod = mods.firstOrNull { it.id == ADMIN_DUTY_MOD_ID } ?: return true
        val ids =
            dutyMod.workflow_employees
                .map { it.id.trim() }
                .filter { it.isNotBlank() }
        return ids.size == DutyRosterSsot.PLANNED_EMPLOYEE_COUNT &&
            ids.toSet() == DutyRosterSsot.PLANNED_EMPLOYEE_IDS
    }

    private fun normalizeDutyMod(mod: ModInfo): ModInfo {
        val remoteById =
            mod.workflow_employees
                .asSequence()
                .map { it.id.trim() to it }
                .filter { (id, _) -> id.isNotBlank() }
                .distinctBy { (id, _) -> id }
                .toMap()
        val employees =
            plannedIdsInOrder().map { id ->
                remoteById[id]?.normalizedDutyEmployee(id) ?: fallbackEmployee(id)
            }
        val featureCount = mod.frontend_menu.size
        return mod.copy(
            id = ADMIN_DUTY_MOD_ID,
            description =
                "${DutyRosterSsot.PLANNED_EMPLOYEE_COUNT} 位管理端 duty AI 员工与 ${featureCount} 个管理功能入口",
            workflow_employees = employees,
        )
    }

    private fun WorkflowEmployeeInfo.normalizedDutyEmployee(employeeId: String): WorkflowEmployeeInfo {
        val fallback = fallbackEmployee(employeeId)
        val resolvedLabel =
            if (employeeId == "user-customer-service-officer") {
                fallback.label
            } else {
                label.ifBlank { panel_title }.ifBlank { DutyRosterSsot.EMPLOYEE_LABELS[employeeId].orEmpty() }
            }
                .ifBlank { employeeId }
        return copy(
            id = employeeId,
            label = resolvedLabel,
            panel_title =
                if (employeeId == "user-customer-service-officer") resolvedLabel
                else panel_title.ifBlank { resolvedLabel },
            panel_summary =
                if (employeeId == "user-customer-service-officer") fallback.panel_summary
                else panel_summary.ifBlank { fallback.panel_summary },
            api_base_path = api_base_path.ifBlank { fallback.api_base_path },
            phone_channel = phone_channel.ifBlank { fallback.phone_channel },
            workflow_placeholder = false,
            profile_source = profile_source.ifBlank { fallback.profile_source },
        )
    }

    private fun fallbackEmployee(employeeId: String): WorkflowEmployeeInfo {
        val label = DutyRosterSsot.EMPLOYEE_LABELS[employeeId]?.takeIf { it.isNotBlank() } ?: employeeId
        val areaId = DutyRosterSsot.EMPLOYEE_AREA_IDS[employeeId].orEmpty()
        val areaLabel = DutyRosterSsot.AREA_LABELS[areaId].orEmpty()
        val summary =
            DutyRosterSsot.EMPLOYEE_DESCRIPTIONS[employeeId]
                ?.takeIf { it.isNotBlank() }
                ?: "管理端 ${areaLabel.ifBlank { "duty" }} 员工"
        return WorkflowEmployeeInfo(
            id = employeeId,
            label = label,
            panel_title = label,
            panel_summary = summary,
            api_base_path = "/api/admin/employees/$employeeId",
            phone_channel = "admin-duty",
            workflow_placeholder = false,
            profile_source = "duty_roster",
        )
    }

    private fun plannedIdsInOrder(): List<String> =
        listOf("user-customer-service-officer") +
            DutyRosterSsot.AREA_EMPLOYEE_IDS.values
                .flatten()
                .filterNot { it == "user-customer-service-officer" }
                .distinct()
}
