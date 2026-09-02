import { ref } from 'vue'
import { api } from '@/api'
import { appAlert } from '@/utils/appDialog'

/**
 * 双向同步状态、推拉动作、冲突处理与 SSE 同步流。
 * 从 XCmaxAdminView.vue 逐字迁移，行为零变更。
 * @param {{ recentErrors: import('vue').Ref<Array> }} refs 共享的最近错误列表
 */
export function useXcmaxSync({ recentErrors }) {
  const syncing = ref(false)
  const syncStatus = ref({ healthy: false, localCursor: null, remoteCursor: null, outboxCount: 0, lastSyncAt: '', conflictCount: 0 })
  const conflicts = ref([])

  async function loadSyncStatus() {
    try {
      const r = await api.get('/api/xcmax/sync/status')
      if (r?.success && r?.data) {
        const d = r.data
        syncStatus.value = {
          healthy: d.healthy === true,
          localCursor: d.local_cursor ?? null,
          remoteCursor: d.remote_cursor ?? null,
          outboxCount: d.outbox_count ?? 0,
          lastSyncAt: d.last_sync_at || '—',
          conflictCount: d.conflict_count ?? 0
        }
      }
    } catch {
      /* not yet wired up */
    }
  }

  async function triggerPush() {
    if (syncing.value) return
    syncing.value = true
    try {
      const res = await api.post('/api/xcmax/sync/push', {})
      if (res?.success) {
        const d = res.data || {}
        await loadSyncStatus()
        await appAlert(`推送完成：发送 ${d.sent ?? 0} 条，失败 ${d.failed ?? 0} 条`)
      }
    } catch (e) {
      recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `同步推送失败: ${e.message}` })
      await appAlert('推送失败: ' + (e.message || '未知错误'))
    } finally {
      syncing.value = false
    }
  }

  async function triggerPull() {
    if (syncing.value) return
    syncing.value = true
    try {
      const res = await api.post('/api/xcmax/sync/pull', {})
      if (res?.success) {
        const d = res.data || {}
        await loadSyncStatus()
        await appAlert(`拉取完成：获取 ${d.pull?.pulled ?? 0} 条，应用 ${d.apply?.applied ?? 0} 条，冲突 ${d.apply?.conflicts ?? 0} 条`)
      }
    } catch (e) {
      recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `拉取失败: ${e.message}` })
      await appAlert('拉取失败: ' + (e.message || '未知错误'))
    } finally {
      syncing.value = false
    }
  }

  async function loadConflicts() {
    try {
      const r = await api.get('/api/xcmax/sync/conflicts', { limit: 50 })
      if (r?.success) conflicts.value = r.data || []
    } catch { conflicts.value = [] }
  }

  async function resolveConflict(id, action) {
    try {
      const res = await api.post(`/api/xcmax/sync/conflicts/${id}/resolve`, { action })
      if (res?.success) {
        conflicts.value = conflicts.value.filter(c => c.id !== id)
        await loadSyncStatus()
      }
    } catch (e) {
      recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `解决冲突失败: ${e.message}` })
    }
  }

  let syncEventSource = null
  let syncStreamReconnectTimer = null
  let syncStreamReconnectDelay = 3000
  let syncStreamActive = false
  let syncStreamCreatedAt = 0

  function startSyncStream() {
    if (syncEventSource) return
    syncStreamActive = true
    const cursorParam = syncStatus.value.localCursor ?? 0
    const url = `/api/xcmax/sync/stream?since_cursor=${cursorParam}`
    syncEventSource = new EventSource(url)
    syncStreamCreatedAt = Date.now()
    syncEventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data?.type === 'connected') {
          syncStreamReconnectDelay = 3000
        }
        if (data?.type === 'heartbeat' && data?.status) {
          const s = data.status
          syncStatus.value = {
            healthy: s.healthy === true,
            localCursor: s.local_cursor ?? syncStatus.value.localCursor,
            remoteCursor: s.remote_cursor ?? syncStatus.value.remoteCursor,
            outboxCount: s.outbox_count ?? 0,
            lastSyncAt: s.last_sync_at || syncStatus.value.lastSyncAt,
            conflictCount: s.conflict_count ?? 0,
          }
        }
      } catch (_) {}
    }
    syncEventSource.onerror = () => {
      const es = syncEventSource
      syncEventSource = null
      if (es) {
        try { es.close() } catch (_) {}
      }
      if (!syncStreamActive) return
      if (syncStreamReconnectTimer != null) return
      syncStreamReconnectTimer = window.setTimeout(() => {
        syncStreamReconnectTimer = null
        if (syncStreamActive) startSyncStream()
      }, syncStreamReconnectDelay)
      syncStreamReconnectDelay = Math.min(syncStreamReconnectDelay * 2, 30000)
    }
  }

  function stopSyncStream() {
    syncStreamActive = false
    if (syncStreamReconnectTimer != null) {
      clearTimeout(syncStreamReconnectTimer)
      syncStreamReconnectTimer = null
    }
    const age = Date.now() - syncStreamCreatedAt
    if (age < 2000 && syncEventSource) {
      const es = syncEventSource
      syncEventSource = null
      setTimeout(() => { try { es.close() } catch (_) {} }, 500)
    } else {
      syncEventSource?.close()
      syncEventSource = null
    }
  }

  return {
    syncing,
    syncStatus,
    conflicts,
    loadSyncStatus,
    triggerPush,
    triggerPull,
    loadConflicts,
    resolveConflict,
    startSyncStream,
    stopSyncStream,
  }
}
