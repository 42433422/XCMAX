/**
 * 员工最近执行记录（exec metrics）。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { watch } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { ExecRow } from './dutyRosterTypes'
import api from '@/api/xcmaxMarketProxy'
import { EXEC_METRICS_PAGE, isVirtualEmployee } from './dutyRosterConstants'
export function useDutyExec(s: DutyRosterState) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s

async function fetchExecMetrics(append: boolean) {
  const emp = selectedEmp.value
  if (!emp) return
  if (isVirtualEmployee(emp.id)) {
    execItems.value = []
    execTotal.value = 0
    execLoading.value = false
    execLoadingMore.value = false
    return
  }
  if (append) execLoadingMore.value = true
  else {
    execLoading.value = true
    execError.value = ''
  }
  try {
    const offset = append ? execItems.value.length : 0
    const res = (await api.adminEmployeeExecutionMetrics(emp.id, {
      limit: EXEC_METRICS_PAGE,
      offset,
    })) as { items?: ExecRow[]; total?: number }
    const raw = Array.isArray(res?.items) ? res.items : []
    const items: ExecRow[] = raw.map((r) => ({
      id: Number(r.id),
      user_id: Number(r.user_id),
      task: typeof r.task === 'string' ? r.task : '',
      status: typeof r.status === 'string' ? r.status : '',
      duration_ms: Number(r.duration_ms) || 0,
      llm_tokens: Number(r.llm_tokens) || 0,
      error: typeof r.error === 'string' ? r.error : '',
      created_at: typeof r.created_at === 'string' ? r.created_at : null,
    }))
    if (append) execItems.value = [...execItems.value, ...items]
    else execItems.value = items
    execTotal.value = Number(res?.total ?? 0)
  } catch (e: unknown) {
    execError.value = e instanceof Error ? e.message : String(e)
    if (!append) execItems.value = []
  } finally {
    execLoading.value = false
    execLoadingMore.value = false
  }
}

watch(
  () => selectedEmp.value?.id,
  (id) => {
    execItems.value = []
    execTotal.value = 0
    execError.value = ''
    if (id) runTargetId.value = id
    dispatchConfirmHighRisk.value = false
    if (id) void fetchExecMetrics(false)
  },
)

  return {
    fetchExecMetrics,
  }
}

export type DutyExec = ReturnType<typeof useDutyExec>
