import { computed, onMounted, onUnmounted, ref } from 'vue'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { ALL_PLANNED_YUANGON_PKG_IDS } from '@/domain/yuangonDutyRoster'

type HealthPayload = Record<string, unknown>

export type DutyRosterLoopStatus = {
  ok: boolean
  source: string
  plannedCount: number
  catalogRegisteredCount: number
  localInstalledCount: number
  missingCatalogIds: string[]
  missingLocalIds: string[]
  extraIds: string[]
  missingCatalogCount: number
  missingLocalCount: number
  extraCount: number
  schedulerJobCount: number
  schedulerRunning: boolean | null
  checkedAt: number | null
  message: string
}

function objectValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
}

function stringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.map((x) => String(x ?? '').trim()).filter(Boolean)
}

function numberValue(raw: unknown, fallback: number): number {
  const n = Number(raw)
  return Number.isFinite(n) ? n : fallback
}

function boolOrNull(raw: unknown): boolean | null {
  if (typeof raw === 'boolean') return raw
  return null
}

export function normalizeDutyRosterLoopStatus(payload: HealthPayload | null | undefined): DutyRosterLoopStatus {
  const health = objectValue(payload)
  const staffing = objectValue(health.staffing)
  const scheduler = objectValue(health.employee_scheduler ?? health.scheduler)
  const plannedFallback = ALL_PLANNED_YUANGON_PKG_IDS.size
  const missingCatalogIds = stringArray(staffing.missing_employees)
  const missingLocalIds = stringArray(staffing.missing_local_employee_packs)
  const extraIds = stringArray(staffing.extra_employees ?? health.extra_local_employee_pack_ids)
  const missingCatalogCount = missingCatalogIds.length
  const missingLocalCount = missingLocalIds.length
  const plannedCount = numberValue(
    staffing.planned_count ?? health.planned_count,
    plannedFallback,
  )
  const catalogRegisteredCount = numberValue(
    staffing.registered_count ?? health.registered_count,
    Math.max(0, plannedCount - missingCatalogCount),
  )
  const localInstalledCount = numberValue(
    health.planned_local_installed_count ?? staffing.local_installed_count,
    Math.max(0, plannedCount - missingLocalCount),
  )
  const schedulerJobs = Array.isArray(health.employee_cron_jobs)
    ? health.employee_cron_jobs
    : Array.isArray(scheduler.jobs)
      ? scheduler.jobs
      : []
  const ok = Boolean(health.ok !== false)
  const source = String(health.source || '').trim() || 'unknown'
  const message = typeof staffing.error === 'string'
    ? staffing.error
    : typeof health.message === 'string'
      ? health.message
      : ''

  return {
    ok,
    source,
    plannedCount,
    catalogRegisteredCount,
    localInstalledCount,
    missingCatalogIds,
    missingLocalIds,
    extraIds,
    missingCatalogCount,
    missingLocalCount,
    extraCount: extraIds.length,
    schedulerJobCount: schedulerJobs.length,
    schedulerRunning: boolOrNull(scheduler.running ?? scheduler.started),
    checkedAt: Date.now(),
    message,
  }
}

function emptyStatus(): DutyRosterLoopStatus {
  return {
    ok: false,
    source: 'loading',
    plannedCount: ALL_PLANNED_YUANGON_PKG_IDS.size,
    catalogRegisteredCount: 0,
    localInstalledCount: 0,
    missingCatalogIds: [],
    missingLocalIds: [],
    extraIds: [],
    missingCatalogCount: 0,
    missingLocalCount: 0,
    extraCount: 0,
    schedulerJobCount: 0,
    schedulerRunning: null,
    checkedAt: null,
    message: '',
  }
}

export function useDutyRosterLoopStatus(options: { autoRefreshMs?: number } = {}) {
  const status = ref<DutyRosterLoopStatus>(emptyStatus())
  const loading = ref(false)
  const error = ref('')
  let timer: number | null = null

  const ready = computed(() =>
    status.value.ok
    && status.value.plannedCount > 0
    && status.value.missingCatalogCount === 0
    && status.value.missingLocalCount === 0,
  )

  const healthLabel = computed(() => {
    if (loading.value && !status.value.checkedAt) return '读取中'
    if (error.value) return '接口异常'
    if (!status.value.ok) return '异常'
    if (ready.value) return '编制已对齐'
    if (status.value.missingLocalCount > 0) return '本机缺包'
    if (status.value.missingCatalogCount > 0) return 'Catalog 缺岗'
    return '待校验'
  })

  const detailLine = computed(() => {
    if (error.value) return error.value
    if (status.value.message) return status.value.message
    return `编制 ${status.value.plannedCount} 岗，本机员工包 ${status.value.localInstalledCount}/${status.value.plannedCount}，Catalog ${status.value.catalogRegisteredCount}/${status.value.plannedCount}`
  })

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      const payload = await xcmaxMarketProxy.adminDutyGraphHealth() as HealthPayload
      status.value = normalizeDutyRosterLoopStatus(payload)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
      status.value = { ...status.value, ok: false, checkedAt: Date.now(), message: error.value }
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void refresh()
    const ms = Number(options.autoRefreshMs || 0)
    if (ms > 0 && typeof window !== 'undefined') {
      timer = window.setInterval(() => {
        void refresh()
      }, Math.max(5000, ms))
    }
  })

  onUnmounted(() => {
    if (timer != null) {
      window.clearInterval(timer)
      timer = null
    }
  })

  return {
    status,
    loading,
    error,
    ready,
    healthLabel,
    detailLine,
    refresh,
  }
}
