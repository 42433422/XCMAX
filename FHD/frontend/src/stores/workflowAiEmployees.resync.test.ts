import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiFetch } from '@/utils/apiBase'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { hydrateWorkspacePrefsFromServer, resetWorkspacePrefsSyncState } from '@/utils/workspacePrefsApi'
import { useWorkflowAiEmployeesStore } from './workflowAiEmployees'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn(), DEFAULT_MOD_API_TIMEOUT_MS: 5000 }))

function serverPrefs() {
  const server = { owner: 'tenant:1', revision: 7, enabled: false }
  const writes: Record<string, unknown>[] = []
  const response = () => {
    const receipt = { success: true, owner_id: server.owner, revision: server.revision,
      data: { workflow_ai_employees: { label_print: server.enabled } } }
    return { ok: true, status: 200, json: async () => receipt } as Response
  }
  vi.mocked(apiFetch).mockImplementation(async (_path, options) => {
    if (options?.method === 'PATCH') {
      const payload = JSON.parse(String(options.body))
      if (payload.expected_owner_id !== server.owner || payload.expected_revision !== server.revision) {
        return { ok: false, status: 409 } as Response
      }
      writes.push(payload)
      server.enabled = payload.workflow_ai_employees.label_print
      server.revision++
    }
    return response()
  })
  return { server, writes, response }
}

function employeeStore() {
  const store = useWorkflowAiEmployeesStore()
  store.registerEmployee({ id: 'label_print', label: '标签打印', kind: 'core', order: 1, source: 'json' })
  return store
}

describe('employee preferences with the real workspace CAS client', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
    resetWorkspacePrefsSyncState()
    setRuntimeTenantStorageScopeInput({ tenantId: 1 })
    productReadAccountEpoch.value++
    setActivePinia(createPinia())
  })
  afterEach(() => {
    resetWorkspacePrefsSyncState()
    setRuntimeTenantStorageScopeInput(null)
  })

  it('recovers from a cross-device conflict after explicit resynchronization', async () => {
    const { server, writes } = serverPrefs()
    const store = employeeStore()
    await hydrateWorkspacePrefsFromServer('tenant:1', () => true,
      prefs => store.acceptConfirmedPreferences(prefs.workflow_ai_employees || {}))
    server.revision = 8
    server.enabled = true
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(store.prefsError).toBe('workspace_prefs_version_conflict')
    expect(store.prefsReady).toBe(false)
    expect(writes).toHaveLength(0)

    await store.refreshConfirmedPreferences()
    expect(store.prefsReady).toBe(true)
    expect(store.confirmedEnabled.label_print).toBe(true)
    await store.setEmployeeEnabledConfirmed('label_print', false)
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({ expected_revision: 8, expected_owner_id: 'tenant:1' })
    expect(server.revision).toBe(9)
    expect(store.confirmedEnabled.label_print).toBe(false)
    expect(store.prefsError).toBe('')
  })

  it('confirms an ordinary first read and uses its owner and revision for one PATCH', async () => {
    const { writes, server } = serverPrefs()
    const store = employeeStore()
    await store.refreshConfirmedPreferences()
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({ expected_revision: 7, expected_owner_id: 'tenant:1' })
    expect(server.revision).toBe(8)
    expect(store.confirmedEnabled.label_print).toBe(true)
    expect(store.prefsReady).toBe(true)
  })

  it('still rejects a newer remote edit made after explicit resynchronization', async () => {
    const { server, writes } = serverPrefs()
    const store = employeeStore()
    await store.refreshConfirmedPreferences()
    server.revision = 8
    server.enabled = true
    await store.refreshConfirmedPreferences()
    server.revision = 9
    server.enabled = false
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(writes).toHaveLength(0)
    expect(store.prefsReady).toBe(false)
    expect(store.prefsError).toBe('workspace_prefs_version_conflict')
    expect(server.enabled).toBe(false)
  })

  it.each([1, 2])('ignores a late response after switching away and ending in tenant %i', async tenant => {
    const { server, writes, response } = serverPrefs()
    const store = employeeStore()
    await store.refreshConfirmedPreferences()
    const staleResponse = response()
    let release!: (value: Response) => void
    vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const staleRead = store.refreshConfirmedPreferences()
    await vi.waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2))
    setRuntimeTenantStorageScopeInput({ tenantId: 2 })
    productReadAccountEpoch.value++
    store.reloadForTenantScope('tenant:2')
    if (tenant === 1) {
      setRuntimeTenantStorageScopeInput({ tenantId: 1 })
      productReadAccountEpoch.value++
      store.reloadForTenantScope('tenant:1')
    }
    server.owner = `tenant:${tenant}`
    server.revision = 10
    server.enabled = true
    store.registerEmployee({ id: 'label_print', label: '标签打印', kind: 'core', order: 1, source: 'json' })
    await store.refreshConfirmedPreferences()
    release(staleResponse)
    await staleRead
    expect(store.confirmedEnabled.label_print).toBe(true)
    await store.setEmployeeEnabledConfirmed('label_print', false)
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({ expected_revision: 10, expected_owner_id: `tenant:${tenant}` })
    expect(store.prefsError).toBe('')
  })

  it('does not enable writes or replace displayed values from an unversioned resync response', async () => {
    const { writes } = serverPrefs()
    const store = employeeStore()
    await store.refreshConfirmedPreferences()
    vi.mocked(apiFetch).mockResolvedValueOnce({ ok: true, json: async () => ({
      success: true, owner_id: 'tenant:1', data: { workflow_ai_employees: { label_print: true } },
    }) } as Response)
    await store.refreshConfirmedPreferences()
    expect(store.prefsReady).toBe(false)
    expect(store.prefsError).toBe('workspace_prefs_revision_missing')
    expect(store.confirmedEnabled.label_print).toBe(false)
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(writes).toHaveLength(0)
  })
})
