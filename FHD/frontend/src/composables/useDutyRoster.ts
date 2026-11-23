// 编制矩阵 SSOT composable: 运行时从后端 /api/system/duty-roster 派生
// 单一真相源: FHD/config/duty_roster.json + mods/_employees/*/manifest.json
// 后端派生: app/fastapi_routes/system_routes.py::get_duty_roster
// 首次调用触发 API 请求, 后续共享同一响应 (模块级单例 cache)
// 宿主编制属于平台内部数据：接口只对平台管理员返回内容，未返回时一律视为空，
// 客户端不再内置宿主编制常量（避免企业构建把宿主部门/员工名单打进产物）。
import { ref, computed, watch, type Ref, type ComputedRef } from 'vue'
import { systemApi, type DutyRosterData } from '@/api/system'
import { productReadScopeKey } from '@/utils/productReadAccountScope'

const EMPTY_AREAS: Record<string, { label: string; ids: string[] }> = {}
const EMPTY_IDS: ReadonlySet<string> = new Set()
const EMPTY_LABELS: Record<string, string> = {}

// 模块级单例 state (多个组件共享同一请求结果)
const reactiveState = {
  data: ref<DutyRosterData | null>(null),
  loading: ref<boolean>(false),
  error: ref<Error | null>(null),
}

let fetchPromise: Promise<DutyRosterData | null> | null = null
let currentScope = ''
let requestGeneration = 0

function resetChangedScope() {
  const scope = productReadScopeKey('duty-roster')
  if (scope === currentScope) return
  currentScope = scope
  requestGeneration++
  fetchPromise = null
  reactiveState.data.value = null
  reactiveState.error.value = null
  reactiveState.loading.value = false
}

async function fetchDutyRoster(force = false): Promise<DutyRosterData | null> {
  resetChangedScope()
  // 已有数据且非强制刷新: 直接返回
  if (reactiveState.data.value && !force) {
    return reactiveState.data.value
  }
  // 正在请求中: 复用同一 promise 避免重复请求
  if (fetchPromise && !force) {
    return fetchPromise
  }

  reactiveState.loading.value = true
  reactiveState.error.value = null
  const scope = currentScope
  const generation = ++requestGeneration
  const isCurrent = () => scope === productReadScopeKey('duty-roster') && generation === requestGeneration

  fetchPromise = (async () => {
    try {
      const resp = await systemApi.getDutyRoster()
      const data = (resp as { data?: DutyRosterData }).data ?? null
      if (!isCurrent()) return null
      reactiveState.data.value = data
      return data
    } catch (err) {
      if (!isCurrent()) return null
      const error = err instanceof Error ? err : new Error(String(err))
      reactiveState.error.value = error
      return null
    } finally {
      if (isCurrent()) {
        reactiveState.loading.value = false
        fetchPromise = null
      }
    }
  })()

  return fetchPromise
}

export function useDutyRoster() {
  resetChangedScope()
  // Retire a previous account's roster before the next render, then restore only API-authorized rows.
  watch(() => productReadScopeKey('duty-roster'), () => {
    resetChangedScope()
    void fetchDutyRoster()
  }, { flush: 'sync' })
  const areas: ComputedRef<Record<string, { label: string; ids: string[] }>> = computed(() => {
    return reactiveState.data.value?.areas ?? EMPTY_AREAS
  })

  const allPlannedIds: ComputedRef<ReadonlySet<string>> = computed(() => {
    const apiIds = reactiveState.data.value?.all_planned_ids
    return apiIds && apiIds.length > 0 ? new Set(apiIds) : EMPTY_IDS
  })

  const employeeLabels: ComputedRef<Record<string, string>> = computed(() => {
    return reactiveState.data.value?.employee_labels ?? EMPTY_LABELS
  })

  const employeeDescriptions: ComputedRef<Record<string, string>> = computed(() => {
    return reactiveState.data.value?.employee_descriptions ?? EMPTY_LABELS
  })

  const departments: ComputedRef<Record<string, unknown>> = computed(() => {
    return reactiveState.data.value?.departments ?? {}
  })

  const loading: Ref<boolean> = reactiveState.loading
  const error: Ref<Error | null> = reactiveState.error

  return {
    areas,
    allPlannedIds,
    employeeLabels,
    employeeDescriptions,
    departments,
    loading,
    error,
    refresh: () => fetchDutyRoster(true),
    ensureLoaded: () => fetchDutyRoster(false),
  }
}
