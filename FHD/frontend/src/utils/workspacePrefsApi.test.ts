import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  applyWorkspacePrefsToLocalCache,
  hydrateWorkspacePrefsFromServer,
  queueWorkspacePrefsSync,
  fetchWorkspacePrefs,
} from './workspacePrefsApi'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 5000,
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  workflowAiEmployeesStorageKey: () => 'xcagi_workflow_ai_employees',
}))

import { apiFetch } from '@/utils/apiBase'

describe('workspacePrefsApi', () => {
  beforeEach(() => {
    localStorage.clear()
    invalidateTenantStorageScopeCache()
    vi.clearAllMocks()
  })

  it('applyWorkspacePrefsToLocalCache writes flags', () => {
    applyWorkspacePrefsToLocalCache({
      product_flow_completed: true,
      host_pack_acknowledged: false,
      workflow_ai_employees: { label_print: true },
    })
    expect(localStorage.getItem('xcagi_product_flow_completed')).toBe('1')
    expect(localStorage.getItem('xcagi_product_flow_host_ack')).toBe('0')
    const emp = JSON.parse(localStorage.getItem('xcagi_workflow_ai_employees') || '{}')
    expect(emp.label_print).toBe(true)
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
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        owner_id: 'u1',
        data: { product_flow_completed: true },
      }),
    } as Response)
    const prefs = await hydrateWorkspacePrefsFromServer()
    expect(prefs?.product_flow_completed).toBe(true)
    expect(localStorage.getItem('xcagi_product_flow_completed')).toBe('1')
  })

  it('hydrateWorkspacePrefsFromServer returns null on failure', async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error('offline'))
    await expect(hydrateWorkspacePrefsFromServer()).resolves.toBeNull()
  })

  it('queueWorkspacePrefsSync debounces patch', async () => {
    vi.useFakeTimers()
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: {} }),
    } as Response)
    queueWorkspacePrefsSync({ product_flow_completed: true }, 100)
    await vi.advanceTimersByTimeAsync(150)
    expect(apiFetch).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
