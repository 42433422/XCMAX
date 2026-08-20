import { onBeforeUnmount, onMounted, ref } from 'vue'
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

/**
 * 自进化循环运行面板的运行状态与轮询逻辑。
 * 负责拉取 selfMaintenanceRuntimeStatus、维护 loading/error 状态，
 * 并在组件挂载后每 30s 轮询刷新（卸载时清理定时器）。
 * `getLimit` 由调用方提供，用于根据 compact 模式决定接口 limit。
 */
export function useLoopRuntimePanel(getLimit: () => number) {
  const raw = ref<AnyRecord | null>(null)
  const loading = ref(false)
  const error = ref('')
  let timer: number | null = null

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      raw.value = (await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(getLimit())) as AnyRecord
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void refresh()
    timer = window.setInterval(() => {
      void refresh()
    }, 30000)
  })

  onBeforeUnmount(() => {
    if (timer != null) window.clearInterval(timer)
    timer = null
  })

  return { raw, loading, error, refresh, asRecord, asArray, asString, asNumber, firstText }
}
