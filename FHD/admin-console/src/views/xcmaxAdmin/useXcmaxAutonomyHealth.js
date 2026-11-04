import { ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

export function useXcmaxAutonomyHealth() {
  const autonomyHealthLoading = ref(false)
  const autonomyHealth = ref({
    alive: null,
    service: '',
    loopStatus: '',
    loopRunId: '',
    gapCount: null,
    error: '',
  })

  async function loadAutonomyHealth() {
    if (autonomyHealthLoading.value) return
    autonomyHealthLoading.value = true
    autonomyHealth.value = { alive: null, error: '' }
    try {
      const [health, runtime, closure] = await Promise.all([
        xcmaxAdminApi.fetchAutonomyHealth().catch(() => null),
        xcmaxMarketProxy.selfMaintenanceRuntimeStatus(20).catch(() => null),
        xcmaxOpsApi.closureStatus().catch(() => null),
      ])
      const mem = runtime?.memory || {}
      const last = mem.last_run || {}
      const timelines = Array.isArray(runtime?.run_timelines) ? runtime.run_timelines : []
      const latest = timelines[0] || {}
      const closureData = closure?.data || closure || {}
      let gapCount = closureData.gap_count ?? closureData.closure_gap_count ?? null
      if (gapCount == null && Array.isArray(closureData.gaps)) gapCount = closureData.gaps.length
      if (gapCount == null && Array.isArray(closureData.missing_remote)) {
        gapCount = closureData.missing_remote.length
      }
      autonomyHealth.value = {
        alive: typeof health?.ok === 'boolean' ? health.ok : null,
        service: health?.service || '',
        loopStatus: last.status || latest.status || runtime?.status || 'unknown',
        loopRunId: last.run_id || latest.run_id || '',
        gapCount,
        error: health == null || runtime == null || closure == null ? '部分状态读取失败，未返回的数据不可用' : '',
      }
    } catch (e) {
      autonomyHealth.value = {
        ...autonomyHealth.value,
        alive: null,
        error: e?.message || String(e),
      }
    } finally {
      autonomyHealthLoading.value = false
    }
  }

  return {
    autonomyHealthLoading,
    autonomyHealth,
    loadAutonomyHealth,
  }
}
