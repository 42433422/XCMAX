import { ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

/**
 * 自治健康卡片：审批服务存活、最近 loop 与闭环缺口。
 * 从 XCmaxAdminView.vue 逐字迁移，行为零变更。
 */
export function useXcmaxAutonomyHealth() {
  const autonomyHealthLoading = ref(false)
  const autonomyHealth = ref({
    alive: false,
    service: '',
    loopStatus: '',
    loopRunId: '',
    gapCount: null,
    error: '',
  })

  async function loadAutonomyHealth() {
    autonomyHealthLoading.value = true
    autonomyHealth.value = { ...autonomyHealth.value, error: '' }
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
        alive: Boolean(health?.ok),
        service: health?.service || '',
        loopStatus: last.status || latest.status || runtime?.status || 'unknown',
        loopRunId: last.run_id || latest.run_id || '',
        gapCount,
        error: '',
      }
    } catch (e) {
      autonomyHealth.value = {
        ...autonomyHealth.value,
        alive: false,
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
