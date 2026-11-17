import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useVisiblePolling } from './messenger/useVisiblePolling'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

export type AnyRecord = Record<string, unknown>

export function asRecord(v: unknown): AnyRecord {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as AnyRecord) : {}
}

export function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

export function asString(v: unknown): string {
  return String(v ?? '').trim()
}

export function asNumber(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function firstText(...values: unknown[]): string {
  for (const value of values) {
    const s = asString(value)
    if (s) return s
  }
  return ''
}

/** Reuse the shared visibility-aware poller; writes are never retried here. */
export function useLoopRuntimePanel(getLimit: () => number, enabled: () => boolean = () => true) {
  const raw = ref<AnyRecord | null>(null),
    loading = ref(false),
    error = ref('')
  const lastSuccessAt = ref(''),
    now = ref(Date.now())
  let disposed = false
  let controller: AbortController | undefined
  let clock: ReturnType<typeof setInterval> | undefined
  const stale = computed(() => {
    const generated = Date.parse(asString(raw.value?.generated_at))
    return !!raw.value && (!Number.isFinite(generated) || now.value - generated > 120000 || generated > now.value + 60000)
  })
  const connection = computed(() =>
    error.value ? 'error' : !raw.value ? (loading.value ? 'loading' : 'empty') : stale.value ? 'stale' : 'connected',
  )

  async function refresh(): Promise<boolean> {
    if (loading.value || disposed || !enabled()) return false
    loading.value = true
    controller = new AbortController()
    try {
      const payload = asRecord(await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(getLimit(), controller.signal))
      if (disposed) return false
      if (
        payload.ok === false ||
        payload.schema_version !== 'self_maintenance_runtime.v1' ||
        !Array.isArray(payload.run_timelines) ||
        !Array.isArray(asRecord(payload.evidence).open_run_ids) ||
        !Number.isFinite(Date.parse(asString(payload.generated_at)))
      ) {
        throw new Error('维护状态数据不完整，请检查运营服务版本')
      }
      raw.value = payload
      now.value = Date.now()
      lastSuccessAt.value = new Date(now.value).toISOString()
      error.value = ''
      return true
    } catch (e: unknown) {
      if (!disposed) error.value = e instanceof Error ? e.message : '维护监控连接失败'
      return false
    } finally {
      if (!disposed) loading.value = false
    }
  }
  const polling = useVisiblePolling(refresh, 30000, 120000)
  onMounted(() => {
    void refresh()
    polling.start()
    clock = setInterval(() => {
      now.value = Date.now()
    }, 15000)
  })
  onBeforeUnmount(() => {
    disposed = true
    controller?.abort()
    polling.stop()
    if (clock) clearInterval(clock)
  })
  return { raw, loading, error, refresh, stale, connection, lastSuccessAt, asRecord, asArray, asString, asNumber, firstText }
}
