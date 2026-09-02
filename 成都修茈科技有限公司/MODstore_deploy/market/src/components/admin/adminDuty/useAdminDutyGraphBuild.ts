/**
 * 节点图重建 watch（数据/视图变化 → 布局重算 + fitView）与顶部统计条。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { watch, nextTick, computed } from 'vue'
import { isDutyGraphMember, isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyLayout } from './adminDutyLayout'
import type { EmpRow } from './adminDutyTypes'

type DutyFitView = (opts?: { padding?: number; maxZoom?: number; duration?: number; nodes?: string[] }) => void | Promise<boolean>

export function useAdminDutyGraphBuild(
  s: AdminDutyState,
  layout: AdminDutyLayout,
  ctx: { fitView: DutyFitView; syncEmployeeRouteQuery: (employeeId?: string | null) => void },
) {
  const { fitView, syncEmployeeRouteQuery } = ctx
  const {
    employees, healthMap, depsMap, empLlmMap, capabilityMap, runNodeStatusMap,
    viewMode, selectedEmp, selectedWorkshop, depsMap: depsMapRef,
    onDutyEmployees, healthLevel, llmActLevel,
  } = s
  const { buildHubGraph, buildDepartmentGraph, buildAreaGraph, buildClientWorkshopGraph } = layout

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
  nextTick(() => { void fitView(fitOpts) })
}, { deep: true })


watch(viewMode, (mode) => {
  if (mode === 'client') {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
  } else {
    selectedWorkshop.value = null
  }
})


const stats = computed(() => ({
  total:     employees.value.length,
  catalogOk: employees.value.filter((e) => e.source === 'catalog').length,
  v1Only:    employees.value.filter((e) => e.source === 'v1_catalog').length,
  healthy:   employees.value.filter((e) => healthLevel(e.id) === 'healthy').length,
  depEdges:  Object.values(depsMap.value).reduce((s, d) => s + d.length, 0),
  // Phase 4（llmNoKey 不含前端虚拟员工：与 /duty-graph/no-key-employees 可修复列表一致）
  llmActive: employees.value.filter((e) => llmActLevel(e.id) === 'activated').length,
  llmNoKey:  employees.value.filter(
    (e) => !isVirtualEmployee(e.id) && llmActLevel(e.id) === 'no_key',
  ).length,
  execReady: employees.value.filter((e) => capabilityMap.value[e.id]?.executable).length,
  highRisk: employees.value.filter((e) => capabilityMap.value[e.id]?.risk?.high_risk).length,
}))


  return { stats }
}

export type AdminDutyGraphBuild = ReturnType<typeof useAdminDutyGraphBuild>
