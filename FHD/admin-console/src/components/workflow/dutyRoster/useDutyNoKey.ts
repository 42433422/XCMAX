/**
 * 无密钥员工修复面板逻辑。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import type { DutyRosterState } from './useDutyRosterState'
import type { NoKeyRow, NoKeyResponse } from './dutyRosterTypes'
import type { DutyData } from './useDutyRosterData'
import type { Router } from 'vue-router'
import api from '@/api/xcmaxMarketProxy'
export function useDutyNoKey(s: DutyRosterState, data: DutyData, ctx: { router: Router }) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { router } = ctx
  const { buildRosterEmployeeRows, load, butlerEmployeeRow, seedVirtualEmployees, loadPhase2, loadCapabilities, startAutoRefresh, stopAutoRefresh } = data

async function loadNoKeyEmployees() {
  noKeyLoading.value = true
  noKeyError.value = ''
  try {
    const r = (await api.adminListNoKeyEmployees()) as NoKeyResponse
    noKeyData.value = r
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyLoading.value = false
  }
}

async function alignSingleEmployeeToAuto(row: NoKeyRow) {
  if (noKeyBusyRow.value[row.pkg_id]) return
  noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: true }
  try {
    await api.adminAlignSingleEmployeeLlmToAuto(row.pkg_id, false)
    await loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
    await loadCapabilities(employees.value.filter(isDeployedDutyRosterRow))
    await loadNoKeyEmployees()
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: false }
  }
}

function gotoAddKey() {
  router.push({ name: 'account', hash: '#api-keys' })
}

  return {
    loadNoKeyEmployees,
    alignSingleEmployeeToAuto,
    gotoAddKey,
  }
}

export type DutyNoKey = ReturnType<typeof useDutyNoKey>
