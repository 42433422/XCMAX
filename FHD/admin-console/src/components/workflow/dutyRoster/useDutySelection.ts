/**
 * 选中员工的详情派生视图。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { HealthSt, EmpLlmCfg, EmpCapability, DutyGraphRunNode } from './dutyRosterTypes'
import { type EmployeeCapabilityView } from '@host/domain/butlerEmployeeProfile'
import { isVirtualEmployee } from './dutyRosterConstants'
export function useDutySelection(s: DutyRosterState) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s

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
// Phase 4
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


  return {
    selectedHealth,
    selectedDeps,
    selectedCapabilityView,
    isSelectedVirtual,
    selectedLlm,
    selectedCapability,
    selectedRunNode,
  }
}

export type DutySelection = ReturnType<typeof useDutySelection>
