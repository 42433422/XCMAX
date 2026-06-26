package com.xiuci.xcagi.mobile.core.repository

import com.xiuci.xcagi.mobile.core.model.DutyRosterSsot
import com.xiuci.xcagi.mobile.core.model.ModInfo
import com.xiuci.xcagi.mobile.core.model.WorkflowEmployeeInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdminDutyRosterNormalizerTest {
    @Test
    fun staleCloudRosterIsDedupedAndCompletedToSsot() {
        val missing = setOf("llm-ops-engineer", "mobile-harmony-release-officer")
        val staleEmployees =
            plannedIdsInOrder()
                .filterNot { it in missing }
                .map { WorkflowEmployeeInfo(id = it, label = it) }
                .let { it + WorkflowEmployeeInfo(id = "deploy-release-officer", label = "duplicate") }
        val staleMod =
            ModInfo(
                id = AdminDutyRosterNormalizer.ADMIN_DUTY_MOD_ID,
                description = "52 位管理端 duty AI 员工",
                workflow_employees = staleEmployees,
            )

        assertFalse(AdminDutyRosterNormalizer.isCurrent(listOf(staleMod)))

        val normalized = AdminDutyRosterNormalizer.normalize(listOf(staleMod)).single()
        val normalizedIds = normalized.workflow_employees.map { it.id }

        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_COUNT, normalizedIds.size)
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS, normalizedIds.toSet())
        assertTrue(AdminDutyRosterNormalizer.isCurrent(listOf(normalized)))
        assertEquals(
            "LLM 运维工程师",
            normalized.workflow_employees.first { it.id == "llm-ops-engineer" }.label,
        )
        assertEquals(
            "鸿蒙发版员",
            normalized.workflow_employees.first { it.id == "mobile-harmony-release-officer" }.label,
        )
    }

    @Test
    fun nonDutyModsAreLeftUntouched() {
        val mod = ModInfo(id = "public-mod", workflow_employees = listOf(WorkflowEmployeeInfo(id = "x")))

        assertEquals(listOf(mod), AdminDutyRosterNormalizer.normalize(listOf(mod)))
        assertTrue(AdminDutyRosterNormalizer.isCurrent(listOf(mod)))
    }

    private fun plannedIdsInOrder(): List<String> =
        DutyRosterSsot.AREA_EMPLOYEE_IDS.values.flatten().distinct()
}
