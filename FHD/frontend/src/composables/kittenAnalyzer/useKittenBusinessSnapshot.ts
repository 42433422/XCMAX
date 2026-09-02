/**
 * useKittenAnalyzer 拆分：业务库快照提示（缓存 + 开关联动 watch）。
 */
import { ref, watch, type Ref } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { KITTEN_SNAPSHOT_CACHE_MS, formatKittenSnapshotStatsHint } from './kittenAnalyzerShared'

export interface KittenBusinessSnapshotDeps {
  kittenIncludeBusinessDb: Ref<boolean>
}

export function useKittenBusinessSnapshot(deps: KittenBusinessSnapshotDeps) {
  const { kittenIncludeBusinessDb } = deps
  const kittenDbStatsHint = ref('')
  let kittenSnapshotCache = { at: 0, text: '' }

  const refreshKittenBusinessSnapshotHint = async () => {
    if (!kittenIncludeBusinessDb.value) {
      kittenDbStatsHint.value = ''
      return
    }
    const now = Date.now()
    if (now - kittenSnapshotCache.at < KITTEN_SNAPSHOT_CACHE_MS && kittenSnapshotCache.text) {
      kittenDbStatsHint.value = kittenSnapshotCache.text
      return
    }
    const r = await safeJsonRequest<{
      success?: boolean
      data?: { stats?: Record<string, unknown> }
    }>('/api/ai/kitten/business-snapshot')
    const payload = r.data?.data
    if (!r.ok || r.data?.success === false || !payload) {
      kittenDbStatsHint.value = '业务库快照预检失败，发送时服务端仍会重试聚合。'
      return
    }
    const hint = formatKittenSnapshotStatsHint(payload.stats) || '业务库快照已生成。'
    kittenSnapshotCache = { at: now, text: hint }
    kittenDbStatsHint.value = hint
  }

  const onKittenBusinessDbToggle = () => {
    void refreshKittenBusinessSnapshotHint()
  }

  watch(kittenIncludeBusinessDb, (on) => {
    if (!on) kittenDbStatsHint.value = ''
  })

  /** resetSession 用：与拆分前「重置 hint + 丢弃缓存」一致 */
  const resetKittenSnapshotCache = () => {
    kittenDbStatsHint.value = ''
    kittenSnapshotCache = { at: 0, text: '' }
  }

  return {
    kittenDbStatsHint,
    refreshKittenBusinessSnapshotHint,
    onKittenBusinessDbToggle,
    resetKittenSnapshotCache,
  }
}
