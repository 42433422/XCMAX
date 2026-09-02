/**
 * 选中员工的派生只读状态（健康 / 依赖 / 能力 / LLM / Run 节点）。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { computed } from 'vue'
import type { EmployeeCapabilityView } from '../../../domain/butlerEmployeeProfile'
import { isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { HealthSt, EmpLlmCfg, EmpCapability, DutyGraphRunNode } from './adminDutyTypes'

export function useAdminDutySelection(s: AdminDutyState) {
  const { selectedEmp, healthMap, depsMap, empCapabilityViewMap, empLlmMap, capabilityMap, latestRun } = s

const selectedHealth = computed<HealthSt | null>(() =>
  selectedEmp.value ? (healthMap.value[selectedEmp.value.id] ?? null) : null,
)

const selectedDeps = computed<string[]>(() =>
  selectedEmp.value ? (depsMap.value[selectedEmp.value.id] ?? []) : [],
)

const selectedCapabilityView = computed<EmployeeCapabilityView | null>(() =>
  selectedEmp.value ? (empCapabilityViewMap.value[selectedEmp.value.id] ?? null) : null,
)

const isSelectedVirtual = computed<boolean>(() =>
  Boolean(selectedEmp.value && isVirtualEmployee(selectedEmp.value.id)),
)

const selectedLlm = computed<EmpLlmCfg | null>(() =>
  selectedEmp.value ? (empLlmMap.value[selectedEmp.value.id] ?? null) : null,
)

const selectedCapability = computed<EmpCapability | null>(() =>
  selectedEmp.value ? (capabilityMap.value[selectedEmp.value.id] ?? null) : null,
)

const selectedRunNode = computed<DutyGraphRunNode | null>(() => {
  const eid = selectedEmp.value?.id
  if (!eid || !latestRun.value?.nodes?.length) return null
  return latestRun.value.nodes.find((n) => n.employee_id === eid) ?? null
})


  return { selectedHealth, selectedDeps, selectedCapabilityView, isSelectedVirtual, selectedLlm, selectedCapability, selectedRunNode }
}

export type AdminDutySelection = ReturnType<typeof useAdminDutySelection>
