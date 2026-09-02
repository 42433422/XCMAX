/**
 * 顶部面板开合与详情折叠。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import type { DutyRosterState } from './useDutyRosterState'
import type { DutyNoKey } from './useDutyNoKey'
export function useDutyPanels(s: DutyRosterState, nokey: DutyNoKey) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { loadNoKeyEmployees, alignSingleEmployeeToAuto, gotoAddKey } = nokey

function closeOtherPanels(except?: string) {
  if (except !== 'gap') showGapPanel.value = false
  if (except !== 'run') showRunPanel.value = false
  if (except !== 'allhands') showAllHandsPanel.value = false
  if (except !== 'nokey') showNoKeyPanel.value = false
}

function togglePanel(panel: 'gap' | 'run' | 'allhands' | 'nokey') {
  const refs: Record<string, { value: boolean }> = {
    gap: showGapPanel,
    run: showRunPanel,
    allhands: showAllHandsPanel,
    nokey: showNoKeyPanel,
  }
  const isOpen = refs[panel].value
  closeOtherPanels(panel)
  refs[panel].value = !isOpen
  if (panel === 'nokey' && showNoKeyPanel.value) void loadNoKeyEmployees()
}

async function openNoKeyPanel() {
  togglePanel('nokey')
}

function isDetailOpen(key: string): boolean {
  return detailCollapsed.value[key] !== true
}

function toggleDetail(key: string) {
  detailCollapsed.value = { ...detailCollapsed.value, [key]: !detailCollapsed.value[key] }
}


/** 值班页工具栏「缺岗 N」：打开缺岗分析面板 */
function openGapPanel() {
  closeOtherPanels('gap')
  showGapPanel.value = true
  gapFocusHint.value = ''
}

  return {
    closeOtherPanels,
    togglePanel,
    openNoKeyPanel,
    isDetailOpen,
    toggleDetail,
    openGapPanel,
  }
}

export type DutyPanels = ReturnType<typeof useDutyPanels>
