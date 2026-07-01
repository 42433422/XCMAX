package com.xiuci.xcagi.mobile.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DutyRosterSsotTest {
    @Test
    fun generatedRosterContainsFiftyFiveUniqueEmployees() {
        assertEquals(55, DutyRosterSsot.PLANNED_EMPLOYEE_COUNT)
        assertEquals(55, DutyRosterSsot.PLANNED_EMPLOYEE_IDS.size)
        assertTrue(DutyRosterSsot.PLANNED_EMPLOYEE_IDS.contains("llm-ops-engineer"))
        assertTrue(DutyRosterSsot.PLANNED_EMPLOYEE_IDS.contains("mobile-harmony-release-officer"))
    }

    @Test
    fun generatedAreaGroupsCoverEveryEmployeeOnce() {
        val grouped = DutyRosterSsot.AREA_EMPLOYEE_IDS.values.flatten()
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS.size, grouped.size)
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS, grouped.toSet())
    }

    @Test
    fun generatedEmployeeMetadataCoversEveryEmployee() {
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS, DutyRosterSsot.EMPLOYEE_AREA_IDS.keys)
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS, DutyRosterSsot.EMPLOYEE_LABELS.keys)
        assertEquals(DutyRosterSsot.PLANNED_EMPLOYEE_IDS, DutyRosterSsot.EMPLOYEE_DESCRIPTIONS.keys)
        assertEquals("LLM 运维工程师", DutyRosterSsot.EMPLOYEE_LABELS["llm-ops-engineer"])
        assertEquals("鸿蒙发版员", DutyRosterSsot.EMPLOYEE_LABELS["mobile-harmony-release-officer"])
    }
}
