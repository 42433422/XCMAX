import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  applyWorkspacePrefsToLocalCache,
  hydrateWorkspacePrefsFromServer,
  queueWorkspacePrefsSync,
  flushWorkspacePrefsSync,
  fetchWorkspacePrefs,
  patchWorkspacePrefs,
  resetWorkspacePrefsSyncState,
  WorkspacePrefsConflictError,
} from './workspacePrefsApi'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 5000,
}))

import { apiFetch } from '@/utils/apiBase'

describe('workspacePrefsApi', () => {
  beforeEach(() => {
    localStorage.clear()
    invalidateTenantStorageScopeCache()
    vi.clearAllMocks()
    resetWorkspacePrefsSyncState()
  })

  it('applyWorkspacePrefsToLocalCache writes flags', () => {
    applyWorkspacePrefsToLocalCache({
      product_flow_completed: true,
      host_pack_acknowledged: false,
      workflow_ai_employees: { label_print: true },
    })
    expect(localStorage.getItem('xcagi_product_flow_completed')).toBe('1')
    expect(localStorage.getItem('xcagi_product_flow_host_ack')).toBe('0')
    expect(Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .some(key => key?.startsWith('xcagi_workflow_ai_employees'))).toBe(false)
  })

  it('applyWorkspacePrefsToLocalCache writes tenant-scoped flags', () => {
    applyWorkspacePrefsToLocalCache(
      {
        product_flow_completed: true,
        host_pack_acknowledged: false,
      },
      'tenant:10',
    )
    expect(localStorage.getItem('xcagi_product_flow_completed')).toBeNull()
    expect(localStorage.getItem('xcagi_product_flow_completed:tenant:10')).toBe('1')
    expect(localStorage.getItem('xcagi_product_flow_host_ack:tenant:10')).toBe('0')
  })

  it('fetchWorkspacePrefs throws on HTTP error', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: false, status: 500 } as Response)
    await expect(fetchWorkspacePrefs()).rejects.toThrow('HTTP 500')
  })

  it('hydrateWorkspacePrefsFromServer applies cache when owner_id present', async () => {
    const onOwnedPreferences = vi.fn()
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        owner_id: 'u1',
        data: { product_flow_completed: true, workflow_ai_employees: { label_print: true } },
      }),
    } as Response)
    const prefs = await hydrateWorkspacePrefsFromServer(undefined, undefined, onOwnedPreferences)
    expect(prefs?.product_flow_completed).toBe(true)
    expect(localStorage.getItem('xcagi_product_flow_completed')).toBe('1')
    expect(onOwnedPreferences).toHaveBeenCalledExactlyOnceWith(prefs)
  })

  it('hydrateWorkspacePrefsFromServer completes when prefs data is empty and owner_id is null', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, owner_id: null, data: {} }),
    } as Response)
    await expect(hydrateWorkspacePrefsFromServer()).resolves.toEqual({})
  })

  it('does not write prefs when the owning scope changed before response', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, owner_id: 'u1', data: { product_flow_completed: true } }),
    } as Response)
    const onOwnedPreferences = vi.fn()
    await hydrateWorkspacePrefsFromServer('tenant:10', () => false, onOwnedPreferences)
    expect(localStorage.getItem('xcagi_product_flow_completed:tenant:10')).toBeNull()
    expect(onOwnedPreferences).not.toHaveBeenCalled()
  })

  it('hydrateWorkspacePrefsFromServer returns null on failure', async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error('offline'))
    await expect(hydrateWorkspacePrefsFromServer()).resolves.toBeNull()
  })

  it('queueWorkspacePrefsSync debounces and writes only with server revision', async () => {
    vi.useFakeTimers()
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, owner_id: 'tenant:42', revision: 4, data: {} }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, owner_id: 'tenant:42', revision: 5, data: {} }),
      } as Response)
    queueWorkspacePrefsSync({ product_flow_completed: true }, 100)
    await vi.advanceTimersByTimeAsync(150)
    expect(apiFetch).toHaveBeenCalledTimes(2)
    const request = vi.mocked(apiFetch).mock.calls[1]
    expect(request[0]).toBe('/api/workspace/prefs')
    expect(JSON.parse(String(request[1]?.body))).toEqual({
      product_flow_completed: true,
      expected_revision: 4,
      expected_owner_id: 'tenant:42',
    })
    vi.useRealTimers()
  })

  it('rejects another device revision without sending a stale PATCH', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, owner_id: 'tenant:42', revision: 7, data: {} }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, owner_id: 'tenant:42', revision: 8, data: {} }),
      } as Response)
    await hydrateWorkspacePrefsFromServer()
    await expect(patchWorkspacePrefs({ host_pack_acknowledged: true }))
      .rejects.toBeInstanceOf(WorkspacePrefsConflictError)
    expect(apiFetch).toHaveBeenCalledTimes(2) // hydration GET, verification GET, no PATCH
  })

  it('drains queued employee settings in order using each confirmed account revision', async () => {
    let revision = 4
    const writes: object[] = []
    vi.mocked(apiFetch).mockImplementation(async (_path, options) => {
      if (options?.method === 'PATCH') {
        const payload = JSON.parse(String(options.body))
        expect(payload.expected_revision).toBe(revision)
        expect(payload.expected_owner_id).toBe('tenant:42')
        writes.push(payload.workflow_ai_employees)
        revision += 1
      }
      return { ok: true, json: async () => ({ success: true, owner_id: 'tenant:42', revision }) } as Response
    })
    queueWorkspacePrefsSync({ workflow_ai_employees: { one: true } })
    const first = flushWorkspacePrefsSync()
    queueWorkspacePrefsSync({ workflow_ai_employees: { two: false } })
    await Promise.all([first, flushWorkspacePrefsSync()])
    expect(writes).toEqual([{ one: true }, { two: false }])
    expect(revision).toBe(6)
  })

  it('surfaces a server 409 and never resubmits the same intent', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, owner_id: 'tenant:42', revision: 3, data: {} }),
      } as Response)
      .mockResolvedValueOnce({ ok: false, status: 409 } as Response)
    await expect(patchWorkspacePrefs({ host_pack_acknowledged: false }))
      .rejects.toBeInstanceOf(WorkspacePrefsConflictError)
    expect(apiFetch).toHaveBeenCalledTimes(2)
    const payload = JSON.parse(String(vi.mocked(apiFetch).mock.calls[1][1]?.body))
    expect(payload.expected_revision).toBe(3)
    expect(payload.expected_owner_id).toBe('tenant:42')
  })

  it('invalidates an old pending workspace draft on teardown', async () => {
    vi.useFakeTimers()
    queueWorkspacePrefsSync({ workflow_ai_employees: { 'employee-one': true } }, 100)
    resetWorkspacePrefsSyncState()
    await vi.advanceTimersByTimeAsync(150)
    expect(apiFetch).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
