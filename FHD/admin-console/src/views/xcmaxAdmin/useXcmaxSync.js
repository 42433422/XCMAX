import { ref } from 'vue'
import { api } from '@/api'
import { appAlert } from '@/utils/appDialog'

export function useXcmaxSync({ recentErrors }) {
  const syncing = ref(false)
  const syncStatus = ref(statusSnapshot())
  let statusRevision = 0
  function statusSnapshot(data = {}, state = 'unknown') {
    return { state, healthy: data.healthy, localCursor: data.local_cursor, remoteCursor: data.remote_cursor,
      outboxCount: data.outbox_count, lastSyncAt: data.last_sync_at, conflictCount: data.conflict_count }
  }
  const conflicts = ref([])

  async function loadSyncStatus() {
    const revision = ++statusRevision
    syncStatus.value = statusSnapshot({}, 'loading')
    try {
      const r = await api.get('/api/xcmax/sync/status')
      if (!r?.success || typeof r?.data?.healthy !== 'boolean' || r.data.note) throw new Error('同步状态不可用')
      if (revision === statusRevision) syncStatus.value = statusSnapshot(r.data, 'ready')
    } catch {
      if (revision === statusRevision) syncStatus.value = statusSnapshot({}, 'error')
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
    const source = new EventSource(url)
    syncEventSource = source
    syncStreamCreatedAt = Date.now()
    source.onmessage = (e) => {
      if (source !== syncEventSource || !syncStreamActive) return
      try {
        const data = JSON.parse(e.data)
        if (data?.type === 'connected') {
          syncStreamReconnectDelay = 3000
        }
        if (data?.type === 'heartbeat' && typeof data?.status?.healthy === 'boolean') {
          ++statusRevision
          syncStatus.value = statusSnapshot(data.status, data.status.note ? 'error' : 'ready')
        }
      } catch { /* Ignore malformed events or an already closed stream. */ }
    }
    source.onerror = () => {
      if (source !== syncEventSource || !syncStreamActive) return
      ++statusRevision
      syncStatus.value = statusSnapshot({}, 'error')
      const es = syncEventSource
      syncEventSource = null
      if (es) {
        try { es.close() } catch { /* Ignore malformed events or an already closed stream. */ }
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
    ++statusRevision
    syncStatus.value = statusSnapshot()
    syncStreamActive = false
    if (syncStreamReconnectTimer != null) {
      clearTimeout(syncStreamReconnectTimer)
      syncStreamReconnectTimer = null
    }
    const age = Date.now() - syncStreamCreatedAt
    if (age < 2000 && syncEventSource) {
      const es = syncEventSource
      syncEventSource = null
      setTimeout(() => { try { es.close() } catch { /* Ignore malformed events or an already closed stream. */ } }, 500)
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
