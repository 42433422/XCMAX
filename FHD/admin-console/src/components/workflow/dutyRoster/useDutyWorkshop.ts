/**
 * 客户端车间选择/详情与节点点击路由。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed, nextTick } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { Router } from 'vue-router'
import { getClientWorkshop, linkedRosterEmployeeIds, parseClientWorkshopNodeId, resolveClientWorkshopRoute } from '@host/domain/clientWorkshops'
import type { Node, Edge } from '@vue-flow/core'
import { CENTER_ID, CLIENT_CENTER_ID } from './dutyRosterConstants'
export function useDutyWorkshop(s: DutyRosterState, ctx: { focusEmployee: (id: string) => void; syncEmployeeRouteQuery: (employeeId?: string | null) => void; router: Router }) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { focusEmployee, syncEmployeeRouteQuery, router } = ctx

const selectedWorkshopLinkedEmployees = computed(() => {
  const ws = selectedWorkshop.value
  if (!ws) return []
  const ids = new Set(linkedRosterEmployeeIds(ws))
  if (!ids.size) return []
  return onDutyEmployees.value.filter((e) => ids.has(e.id))
})

const selectedWorkshopRouteHref = computed(() => {
  const ws = selectedWorkshop.value
  if (!ws) return ''
  const loc = resolveClientWorkshopRoute(ws)
  if (!loc) return ''
  try {
    return router.resolve(loc).href
  } catch {
    return ''
  }
})

function openSelectedWorkshopInClient() {
  const ws = selectedWorkshop.value
  if (!ws) return
  const loc = resolveClientWorkshopRoute(ws)
  if (!loc) return
  const href = router.resolve(loc).href
  window.open(href, '_blank', 'noopener,noreferrer')
}

async function copySelectedWorkshopRoute() {
  const href = selectedWorkshopRouteHref.value
  if (!href) return
  const path = href.startsWith('http') ? href : `${window.location.origin}${href}`
  try {
    await navigator.clipboard.writeText(path)
    workshopRouteCopied.value = true
    setTimeout(() => {
      workshopRouteCopied.value = false
    }, 2000)
  } catch {
    /* ignore */
  }
}

function onClientWorkshopNodeClick(node: Node) {
  if (node.id === CLIENT_CENTER_ID) {
    selectedWorkshop.value = null
    return
  }
  const wsId = parseClientWorkshopNodeId(node.id)
  if (!wsId) {
    selectedWorkshop.value = null
    return
  }
  selectedWorkshop.value = getClientWorkshop(wsId) ?? null
  selectedEmp.value = null
  syncEmployeeRouteQuery(null)
}


function focusEmployeeFromWorkshop(id: string) {
  viewMode.value = 'hub'
  selectedWorkshop.value = null
  nextTick(() => focusEmployee(id))
}

function onNodeClick({ node }: { node: Node }) {
  if (viewMode.value === 'client') {
    onClientWorkshopNodeClick(node)
    return
  }
  let id = node.id
  if (id === CENTER_ID || id === '__untracked__' || node.type === 'group') {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
    return
  }
  if (id.includes('::')) id = id.split('::')[1] ?? id
  const emp = employees.value.find((e) => e.id === id)
  if (!emp) {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
    return
  }
  selectedEmp.value = emp
  runTargetId.value = emp.id
  showDispatch.value = false
  taskResult.value  = null
  taskError.value   = null
  taskBrief.value   = ''
  taskInputJson.value = '{}'
  dispatchConfirmHighRisk.value = false
  syncEmployeeRouteQuery(emp.id)
}

  return {
    selectedWorkshopLinkedEmployees,
    selectedWorkshopRouteHref,
    openSelectedWorkshopInClient,
    copySelectedWorkshopRoute,
    onClientWorkshopNodeClick,
    focusEmployeeFromWorkshop,
    onNodeClick,
  }
}

export type DutyWorkshop = ReturnType<typeof useDutyWorkshop>
