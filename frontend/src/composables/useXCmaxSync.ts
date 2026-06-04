/**
 * useXCmaxSync — 共享的 XCmax 双向同步状态 composable。
 *
 * 用法（在任意 Vue 组件/视图中）：
 *   import { useXCmaxSync } from '@/composables/useXCmaxSync'
 *   const { syncStatus, isSyncing, syncNow, syncLabel } = useXCmaxSync()
 */

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api'

export interface SyncStatus {
  healthy: boolean
  localCursor: number | null
  remoteCursor: number | null
  outboxCount: number
  conflictCount: number
  lastSyncAt: string | null
}

const _status = ref<SyncStatus>({
  healthy: false,
  localCursor: null,
  remoteCursor: null,
  outboxCount: 0,
  conflictCount: 0,
  lastSyncAt: null,
})
const _apiReachable = ref(false)
const _isSyncing = ref(false)
let _pollTimer: ReturnType<typeof setInterval> | null = null
let _pollingCount = 0

async function _loadStatus(): Promise<void> {
  try {
    const r = await api.get('/api/xcmax/sync/status')
    if (r?.success && r?.data) {
      const d = r.data
      _status.value = {
        healthy: d.healthy === true,
        localCursor: d.local_cursor ?? null,
        remoteCursor: d.remote_cursor ?? null,
        outboxCount: d.outbox_count ?? 0,
        conflictCount: d.conflict_count ?? 0,
        lastSyncAt: d.last_sync_at || null,
      }
      _apiReachable.value = true
    }
  } catch {
    _apiReachable.value = false
  }
}

function _startPolling(intervalMs = 30_000): void {
  if (_pollingCount > 0) { _pollingCount++; return }
  _pollingCount = 1
  _pollTimer = setInterval(_loadStatus, intervalMs)
}

function _stopPolling(): void {
  _pollingCount = Math.max(0, _pollingCount - 1)
  if (_pollingCount === 0 && _pollTimer !== null) {
    clearInterval(_pollTimer)
    _pollTimer = null
  }
}

export function useXCmaxSync(autoRefresh = true) {
  if (autoRefresh) {
    onMounted(async () => {
      await _loadStatus()
      _startPolling()
    })
    onUnmounted(_stopPolling)
  }

  const syncLabel = computed<string>(() => {
    const s = _status.value
    if (s.conflictCount > 0) return `冲突 ${s.conflictCount}`
    if (!s.healthy && s.outboxCount > 0) return `待同步 ${s.outboxCount}`
    if (s.healthy) return '已同步'
    if (!_apiReachable.value) return '未连接'
    return '就绪'
  })

  const syncClass = computed<string>(() => {
    const s = _status.value
    if (s.conflictCount > 0) return 'sync-badge--conflict'
    if (!s.healthy && s.outboxCount > 0) return 'sync-badge--pending'
    if (s.healthy) return 'sync-badge--ok'
    if (!_apiReachable.value) return 'sync-badge--offline'
    return 'sync-badge--ok'
  })

  async function syncNow(direction: 'push' | 'pull' | 'both' = 'both'): Promise<void> {
    if (_isSyncing.value) return
    _isSyncing.value = true
    try {
      if (direction === 'push' || direction === 'both') {
        await api.post('/api/xcmax/sync/push', {})
      }
      if (direction === 'pull' || direction === 'both') {
        await api.post('/api/xcmax/sync/pull', {})
      }
      await _loadStatus()
    } catch {
      /* swallow — caller can handle errors */
    } finally {
      _isSyncing.value = false
    }
  }

  return {
    syncStatus: _status,
    isSyncing: _isSyncing,
    syncLabel,
    syncClass,
    syncNow,
    refreshStatus: _loadStatus,
  }
}
