/**
 * 客户端车间侧栏与节点点击分发（client 视图 → 车间详情；其余 → 员工详情）。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { computed, nextTick } from 'vue'
import type { Node } from '@vue-flow/core'
import type { Router } from 'vue-router'
import { getClientWorkshop, linkedRosterEmployeeIds, parseClientWorkshopNodeId, resolveClientWorkshopRoute } from '../../../domain/clientWorkshops'
import { CENTER_ID, CLIENT_CENTER_ID } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { EmpRow } from './adminDutyTypes'

export function useAdminDutyWorkshop(
  s: AdminDutyState,
  ctx: {
    focusEmployee: (id: string) => void
    syncEmployeeRouteQuery: (employeeId?: string | null) => void
    router: Router
  },
) {
  const { focusEmployee, syncEmployeeRouteQuery, router } = ctx
  const {
    viewMode, selectedEmp, selectedWorkshop, workshopRouteCopied, onDutyEmployees,
    runTargetId, showDispatch, taskResult, taskError, taskBrief, taskInputJson,
    dispatchConfirmHighRisk, employees,
  } = s

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
    selectedWorkshopLinkedEmployees, selectedWorkshopRouteHref, openSelectedWorkshopInClient,
    copySelectedWorkshopRoute, onClientWorkshopNodeClick, focusEmployeeFromWorkshop, onNodeClick,
  }
}

export type AdminDutyWorkshop = ReturnType<typeof useAdminDutyWorkshop>
