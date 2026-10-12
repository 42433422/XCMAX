import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useXcmaxSync } from '../../../admin-console/src/views/xcmaxAdmin/useXcmaxSync'
import { useXcmaxOverview } from '../../../admin-console/src/views/xcmaxAdmin/useXcmaxOverview'
import { useXcmaxAutonomyHealth } from '../../../admin-console/src/views/xcmaxAdmin/useXcmaxAutonomyHealth'
const mocks = vi.hoisted(() => ({ get: vi.fn(), health: vi.fn(), runtime: vi.fn(), closure: vi.fn() }))
vi.mock('@/constants/personnelModApi', () => ({ getPersonnelModApiBase: () => '/api/personnel' }))
vi.mock('@/api', () => ({ api: { get: mocks.get } }))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchAutonomyHealth: mocks.health } }))
vi.mock('@/api/xcmaxOps', () => ({ xcmaxOpsApi: { closureStatus: mocks.closure } }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { selfMaintenanceRuntimeStatus: mocks.runtime } }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn() }))
const snapshot = {
  healthy: false,
  local_cursor: 22917,
  remote_cursor: 9013,
  outbox_count: 22917,
  conflict_count: 0,
  last_sync_at: '2026-08-03',
}
const eventSource = vi.fn(function () {
  this.close = vi.fn()
})
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('EventSource', eventSource)
})
afterEach(() => {
  vi.unstubAllGlobals()
})
describe('admin status observations', () => {
  it('does not fabricate initial zero counts and clears failed or unavailable snapshots', async () => {
    const { syncStatus, loadSyncStatus } = useXcmaxSync({ recentErrors: ref([]) })
    expect(syncStatus.value.state).toBe('unknown')
    expect(syncStatus.value.outboxCount).toBeUndefined()
    mocks.get.mockResolvedValueOnce({ success: true, data: snapshot })
    await loadSyncStatus()
    expect(syncStatus.value.outboxCount).toBe(22917)
    mocks.get.mockRejectedValueOnce(new Error('offline'))
    const pending = loadSyncStatus()
    expect(syncStatus.value.state).toBe('loading')
    expect(syncStatus.value.lastSyncAt).toBeUndefined()
    await pending
    expect(syncStatus.value.state).toBe('error')
    expect(syncStatus.value.localCursor).toBeUndefined()
    mocks.get.mockResolvedValueOnce({ success: true, data: { ...snapshot, note: 'uninitialized' } })
    await loadSyncStatus()
    expect(syncStatus.value.state).toBe('error')
    mocks.get.mockResolvedValueOnce({ success: true, data: { healthy: true, outbox_count: 0, conflict_count: 0 } })
    await loadSyncStatus()
    expect(syncStatus.value.outboxCount).toBe(0)
  })
  it('keeps newer SSE observations over a late HTTP failure and invalidates on disconnect', async () => {
    const sync = useXcmaxSync({ recentErrors: ref([]) })
    let reject
    mocks.get.mockReturnValue(new Promise((_, fail) => {
      reject = fail
    }))
    const pending = sync.loadSyncStatus()
    sync.startSyncStream()
    const source = eventSource.mock.instances[0]
    const heartbeat = status => source.onmessage({ data: JSON.stringify({ type: 'heartbeat', status }) })
    heartbeat({ ...snapshot, note: 'uninitialized' })
    expect(sync.syncStatus.value).toMatchObject({ state: 'error', outboxCount: undefined })
    heartbeat(snapshot)
    reject(new Error('late'))
    await pending
    expect(sync.syncStatus.value.state).toBe('ready')
    source.onerror()
    expect(sync.syncStatus.value.state).toBe('error')
    expect(sync.syncStatus.value.outboxCount).toBeUndefined()
    sync.stopSyncStream()
    heartbeat(snapshot)
    expect(sync.syncStatus.value.state).toBe('unknown')
  })
  it('keeps initial/loading/failed remote status distinct from observed offline', async () => {
    const overview = useXcmaxOverview()
    expect(overview.remoteStatus.value.reachable).toBeNull()
    let resolve
    mocks.get.mockReturnValue(new Promise(done => {
      resolve = done
    }))
    const pending = overview.loadRemoteStatus()
    await overview.loadRemoteStatus()
    expect(mocks.get).toHaveBeenCalledTimes(1)
    expect(overview.remoteStatus.value.state).toBe('loading')
    resolve({ data: { reachable: false } })
    await pending
    expect(overview.remoteStatus.value).toMatchObject({ state: 'ready', reachable: false })
    mocks.get.mockRejectedValueOnce(new Error('offline'))
    await overview.loadRemoteStatus()
    expect(overview.remoteStatus.value).toEqual({ state: 'error' })
    mocks.get.mockResolvedValueOnce({ status: 'healthy' })
    await overview.loadLocalStatus()
    expect(overview.localStatus.value.database).toBe('—')
  })
  it('distinguishes unavailable autonomy data from an observed false health check', async () => {
    const state = useXcmaxAutonomyHealth()
    expect(state.autonomyHealth.value.alive).toBeNull()
    mocks.health.mockRejectedValue(new Error('offline'))
    mocks.runtime.mockResolvedValue({})
    mocks.closure.mockResolvedValue({})
    await state.loadAutonomyHealth()
    expect(state.autonomyHealth.value.alive).toBeNull()
    expect(state.autonomyHealth.value.error).toBeTruthy()
    mocks.health.mockResolvedValue({ ok: false })
    await state.loadAutonomyHealth()
    expect(state.autonomyHealth.value.alive).toBe(false)
  })
})
