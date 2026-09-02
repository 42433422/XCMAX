/**
 * 缺岗分析（gap rows/summary）。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { GapState } from './dutyRosterTypes'
import { YUANGON_PKG_ROLE_LABELS } from '@host/domain/yuangonDutyRoster'
import { ALL_AREAS, isVirtualEmployee } from './dutyRosterConstants'
export function useDutyGap(s: DutyRosterState) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s

const gapRows = computed(() => {
  const rows: Array<{ id: string; name: string; area: string; state: GapState }> = []

  for (const [area, { label, ids }] of Object.entries(ALL_AREAS)) {
    for (const id of ids) {
      const row = employees.value.find((e) => e.id === id)
      const name = row?.name || YUANGON_PKG_ROLE_LABELS[id] || id
      const deployed =
        isVirtualEmployee(id)
        || (row?.source === 'catalog' && !missingLocalPackIds.value.has(id))
      rows.push({
        id,
        name,
        area: label,
        state: deployed ? 'deployed' : 'missing',
      })
    }
  }
  return rows
})

const gapSummary = computed(() => ({
  deployed:  gapRows.value.filter((r) => r.state === 'deployed').length,
  missing:   gapRows.value.filter((r) => r.state === 'missing').length,
  untracked: gapRows.value.filter((r) => r.state === 'untracked').length,
}))

  return {
    gapRows,
    gapSummary,
  }
}

export type DutyGap = ReturnType<typeof useDutyGap>
