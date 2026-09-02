/**
 * AdminDutyEmployeeGraph 的 watch / 生命周期装配。
 *
 * 由 AdminDutyEmployeeGraph.vue 原顶层 watch 块机械迁出：观察源、回调与选项逐字保留，行为不变。
 */
import { nextTick, onUnmounted, watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { useVueFlow } from '@vue-flow/core'
import type { useAdminDutyState } from './useAdminDutyState'
import type { createAdminDutyLayout } from './adminDutyLayout'
import type { useAdminDutyData } from './useAdminDutyData'
import type { useAdminDutyRun } from './useAdminDutyRun'
import type { useAdminDutyAllHands } from './useAdminDutyAllHands'
import type { useAdminDutyExec } from './useAdminDutyExec'

interface AdminDutyWatchesDeps {
  state: ReturnType<typeof useAdminDutyState>
  layout: ReturnType<typeof createAdminDutyLayout>
  props: { open: boolean; variant: 'modal' | 'page' }
  route: RouteLocationNormalizedLoaded
  fitView: ReturnType<typeof useVueFlow>['fitView']
  syncEmployeeRouteQuery: (employeeId?: string | null) => void
  applyEmployeeQueryFromRoute: () => Promise<void>
  data: ReturnType<typeof useAdminDutyData>
  run: ReturnType<typeof useAdminDutyRun>
  allhands: ReturnType<typeof useAdminDutyAllHands>
  exec: ReturnType<typeof useAdminDutyExec>
}

export function useAdminDutyWatches(deps: AdminDutyWatchesDeps): void {
  const { props, route, fitView, syncEmployeeRouteQuery, applyEmployeeQueryFromRoute, layout, data, run, allhands, exec } = deps
  const state = deps.state
  const {
    onDutyEmployees, healthMap, depsMap, viewMode, empLlmMap, capabilityMap, runNodeStatusMap,
    selectedEmp, selectedWorkshop, autoRefresh, allHandsBusy, allHandsSessionId,
    showGapPanel, latestRun, employees, runTargetId,
    execItems, execTotal, execError, dispatchConfirmHighRisk,
  } = state
  const { buildAreaGraph, buildHubGraph, buildDepartmentGraph, buildClientWorkshopGraph } = layout
  const { load, startAutoRefresh, stopAutoRefresh } = data
  const { stopRunPolling } = run
  const { stopAllHandsPolling, resetAllHandsProgress } = allhands
  const { fetchExecMetrics } = exec

  /** 图随数据 / 视图模式变化自动重建（原单文件同款响应式逻辑） */
  watch([onDutyEmployees, healthMap, depsMap, viewMode, empLlmMap, capabilityMap, runNodeStatusMap], () => {
    if (viewMode.value === 'client') {
      buildClientWorkshopGraph()
    } else if (viewMode.value === 'department') {
      buildDepartmentGraph(onDutyEmployees.value)
    } else if (viewMode.value === 'legacy-area') {
      buildAreaGraph(onDutyEmployees.value)
    } else {
      buildHubGraph(onDutyEmployees.value)
    }
    const fitOpts =
      viewMode.value === 'department'
        ? { padding: 0.04, maxZoom: 0.72, duration: 300 }
        : { padding: 0.12, maxZoom: 1, duration: 300 }
    nextTick(() => fitView(fitOpts))
  }, { deep: true })

  watch(viewMode, (mode) => {
    if (mode === 'client') {
      selectedEmp.value = null
      syncEmployeeRouteQuery(null)
    } else {
      selectedWorkshop.value = null
    }
  })

  watch(
    () => route.query.employee,
    () => { void applyEmployeeQueryFromRoute() },
  )

  watch(autoRefresh, (v) => {
    if (v) startAutoRefresh(); else stopAutoRefresh()
  })

  watch(
    () => [props.open, props.variant] as const,
    ([open, variant]) => {
      const active = variant === 'page' || open
      if (active) {
        void load()
      } else {
        stopAutoRefresh()
        stopRunPolling()
        stopAllHandsPolling()
        autoRefresh.value = false
        allHandsBusy.value = false
        allHandsSessionId.value = ''
        resetAllHandsProgress()
        selectedEmp.value = null
        showGapPanel.value = false
        latestRun.value = null
        runNodeStatusMap.value = {}
      }
    },
    { immediate: true },
  )

  watch(
    employees,
    (rows) => {
      if (!rows.length) {
        runTargetId.value = ''
        return
      }
      if (!rows.some((r) => r.id === runTargetId.value)) {
        runTargetId.value = rows[0].id
      }
    },
    { deep: true },
  )

  onUnmounted(() => {
    stopAutoRefresh()
    stopRunPolling()
    stopAllHandsPolling()
  })

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
}
