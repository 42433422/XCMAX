// 编制矩阵 SSOT composable: 运行时从后端 /api/system/duty-roster 派生
// 单一真相源: FHD/config/duty_roster.json + mods/_employees/*/manifest.json
// 后端派生: app/fastapi_routes/system_routes.py::get_duty_roster
// 首次调用触发 API 请求, 后续共享同一响应 (模块级单例 cache)
// API 不可用时回退到 yuangonDutyRoster.ts 的构建时硬编码常量
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { systemApi, type DutyRosterData } from '@/api/system'
import {
  YUANGON_AREAS as FALLBACK_AREAS,
  ALL_PLANNED_YUANGON_PKG_IDS as FALLBACK_IDS,
  YUANGON_PKG_ROLE_LABELS as FALLBACK_LABELS,
  YUANGON_PKG_DESCRIPTIONS as FALLBACK_DESCRIPTIONS,
} from '@/domain/yuangonDutyRoster'

interface DutyRosterState {
  data: DutyRosterData | null
  loading: boolean
  error: Error | null
}

// 模块级单例 state (多个组件共享同一请求结果)
const reactiveState = {
  data: ref<DutyRosterData | null>(null),
  loading: ref<boolean>(false),
  error: ref<Error | null>(null),
}

let fetchPromise: Promise<DutyRosterData | null> | null = null

async function fetchDutyRoster(force = false): Promise<DutyRosterData | null> {
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

  fetchPromise = (async () => {
    try {
      const resp = await systemApi.getDutyRoster()
      const data = (resp as { data?: DutyRosterData }).data ?? null
      reactiveState.data.value = data
      return data
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err))
      reactiveState.error.value = error
      // API 失败时回退到构建时硬编码常量
      return null
    } finally {
      reactiveState.loading.value = false
      fetchPromise = null
    }
  })()

  return fetchPromise
}

export function useDutyRoster() {
  const areas: ComputedRef<Record<string, { label: string; ids: string[] }>> = computed(() => {
    return reactiveState.data.value?.areas ?? FALLBACK_AREAS
  })

  const allPlannedIds: ComputedRef<ReadonlySet<string>> = computed(() => {
    const apiIds = reactiveState.data.value?.all_planned_ids
    if (apiIds && apiIds.length > 0) {
      return new Set(apiIds)
    }
    return FALLBACK_IDS
  })

  const employeeLabels: ComputedRef<Record<string, string>> = computed(() => {
    return reactiveState.data.value?.employee_labels ?? FALLBACK_LABELS
  })

  const employeeDescriptions: ComputedRef<Record<string, string>> = computed(() => {
    return reactiveState.data.value?.employee_descriptions ?? FALLBACK_DESCRIPTIONS
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
