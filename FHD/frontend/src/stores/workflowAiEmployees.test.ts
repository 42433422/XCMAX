import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkflowAiEmployeesStore, workflowAiEmployeesStorageKey, defaultWorkflowBuiltinEnabled } from './workflowAiEmployees'
import { setTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { fetchWorkspacePrefs, flushWorkspacePrefsSync, patchWorkspacePrefs } from '@/utils/workspacePrefsApi'

vi.mock('@/utils/workspacePrefsApi', () => ({
  fetchWorkspacePrefs: vi.fn(),
  flushWorkspacePrefsSync: vi.fn(async () => {}),
  patchWorkspacePrefs: vi.fn(),
  queueWorkspacePrefsSync: vi.fn(),
}))

const confirmed = (enabled: boolean) => ({
  success: true,
  owner_id: 'tenant-owner',
  data: { workflow_ai_employees: { label_print: enabled } },
})

describe('workflowAiEmployees store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setTenantStorageScopeCache('tenant:1')
    setActivePinia(createPinia())
    useWorkflowAiEmployeesStore().reloadForTenantScope('tenant:1')
    vi.spyOn(window, 'dispatchEvent').mockImplementation(() => true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reads keys from localStorage without builtin defaults', () => {
    localStorage.setItem(
      workflowAiEmployeesStorageKey('tenant:1'),
      JSON.stringify({
        label_print: true,
        custom_mod_emp: false,
      }),
    )
    const store = useWorkflowAiEmployeesStore()
    store.reloadFromLocalStorage()
    expect(store.enabled.label_print).toBe(true)
    expect(store.enabled.shipment_mgmt).toBeUndefined()
    expect(store.enabled.custom_mod_emp).toBe(false)
  })

  it('falls back to empty defaults on invalid JSON', () => {
    localStorage.setItem(workflowAiEmployeesStorageKey('tenant:1'), '{not json')
    const store = useWorkflowAiEmployeesStore()
    expect(store.enabled).toEqual(defaultWorkflowBuiltinEnabled())
  })

  it('hydrateFromMods adds dynamic ids with default false', () => {
    const store = useWorkflowAiEmployeesStore()
    store.hydrateFromMods([
      {
        id: 'm',
        workflow_employees: [{ id: 'from_manifest', label: 'X' }],
      },
    ])
    expect(store.enabled.from_manifest).toBe(false)
  })

  it('stripModWorkflowEmployeeKeys keeps only registry keys', async () => {
    const store = useWorkflowAiEmployeesStore()
    await store.loadRegistry([{ id: 'm', workflow_employees: [{ id: 'label_print', label: 'L' }] }])
    store.setAll({
      ...store.enabled,
      extra: true,
      label_print: true,
    })
    vi.mocked(window.dispatchEvent).mockClear()
    store.stripModWorkflowEmployeeKeys()
    expect('extra' in store.enabled).toBe(false)
    expect(store.enabled.label_print).toBe(true)
    expect(window.dispatchEvent).toHaveBeenCalled()
  })

  it('pruneOrphanWorkflowEmployeeToggles removes keys not in manifest', () => {
    const store = useWorkflowAiEmployeesStore()
    store.hydrateFromMods([{ id: 'm', workflow_employees: [{ id: 'still_here', label: 'S' }] }])
    store.setAll({
      ...store.enabled,
      orphan: true,
      still_here: true,
      label_print: true,
    })
    vi.mocked(window.dispatchEvent).mockClear()
    store.pruneOrphanWorkflowEmployeeToggles([{ id: 'm', workflow_employees: [{ id: 'still_here', label: 'S' }] }])
    expect(store.enabled.orphan).toBeUndefined()
    expect(store.enabled.still_here).toBe(true)
    expect(store.enabled.label_print).toBeUndefined()
    expect(window.dispatchEvent).toHaveBeenCalled()
  })

  it('toggle flips and dispatches xcagi:workflow-ai-employees-changed', () => {
    const store = useWorkflowAiEmployeesStore()
    vi.mocked(window.dispatchEvent).mockClear()
    store.toggle('label_print')
    expect(store.enabled.label_print).toBe(true)
    const evt = vi
      .mocked(window.dispatchEvent)
      .mock.calls.find((c) => (c[0] as CustomEvent).type === 'xcagi:workflow-ai-employees-changed')?.[0] as CustomEvent
    expect(evt).toBeDefined()
    expect(evt.detail.enabled.label_print).toBe(true)
  })

  it('enableAllOn sets every known key to true', () => {
    const store = useWorkflowAiEmployeesStore()
    store.hydrateFromMods([{ id: 'm', workflow_employees: [{ id: 'dyn', label: 'D' }] }])
    store.enableAllOn()
    for (const k of Object.keys(store.enabled)) {
      expect(store.enabled[k]).toBe(true)
    }
  })

  it('reloadFromLocalStorage picks up external storage writes', () => {
    const store = useWorkflowAiEmployeesStore()
    localStorage.setItem(workflowAiEmployeesStorageKey('tenant:1'), JSON.stringify({ label_print: true }))
    store.reloadFromLocalStorage()
    expect(store.enabled.label_print).toBe(true)
  })

  it('reloadForTenantScope isolates toggles per tenant', () => {
    localStorage.setItem(workflowAiEmployeesStorageKey('tenant:1'), JSON.stringify({ label_print: true }))
    localStorage.setItem(workflowAiEmployeesStorageKey('tenant:2'), JSON.stringify({ label_print: false, shipment_mgmt: true }))
    const store = useWorkflowAiEmployeesStore()
    store.reloadForTenantScope('tenant:1')
    expect(store.enabled.label_print).toBe(true)
    expect(store.enabled.shipment_mgmt).toBeUndefined()
    store.reloadForTenantScope('tenant:2')
    expect(store.enabled.label_print).toBe(false)
    expect(store.enabled.shipment_mgmt).toBe(true)
  })

  it('keeps confirmed preferences out of browser storage and retires them on account change', () => {
    const store = useWorkflowAiEmployeesStore()
    const key = workflowAiEmployeesStorageKey('tenant:1')
    store.acceptConfirmedPreferences({ label_print: true })
    store.persistAndNotify(false)
    store.reloadFromLocalStorage()
    expect(store.enabled.label_print).toBe(true)
    expect(localStorage.getItem(key)).toBeNull()

    productReadAccountEpoch.value++
    store.reloadForTenantScope('tenant:1')
    expect(store.confirmedEnabled).toEqual({})
    expect(store.enabled.label_print).toBeUndefined()
    expect(store.prefsReady).toBe(false)
  })

  it('reads the owning workspace and waits for one confirmed change', async () => {
    const store = useWorkflowAiEmployeesStore()
    store.registerEmployee({ id: 'label_print', label: '标签打印', kind: 'core', order: 1, source: 'json' })
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(patchWorkspacePrefs).not.toHaveBeenCalled()
    vi.mocked(fetchWorkspacePrefs).mockResolvedValueOnce(confirmed(false))
    await store.refreshConfirmedPreferences()
    expect(store.prefsReady).toBe(true)
    expect(store.confirmedEnabled.label_print).toBe(false)

    let ack!: (receipt: ReturnType<typeof confirmed>) => void
    vi.mocked(patchWorkspacePrefs).mockImplementationOnce(() => new Promise(resolve => { ack = resolve }))
    const save = store.setEmployeeEnabledConfirmed('label_print', true)
    await vi.waitFor(() => expect(patchWorkspacePrefs).toHaveBeenCalledOnce())
    await store.setEmployeeEnabledConfirmed('label_print', false)
    await store.refreshConfirmedPreferences()
    expect(fetchWorkspacePrefs).toHaveBeenCalledOnce()
    expect(patchWorkspacePrefs).toHaveBeenCalledExactlyOnceWith({ workflow_ai_employees: { label_print: true } })
    expect(store.confirmedEnabled.label_print).toBe(false)
    ack(confirmed(true))
    await save
    expect(store.confirmedEnabled.label_print).toBe(true)
    expect(store.prefsSaving).toBe('')
    expect(localStorage.getItem(workflowAiEmployeesStorageKey('tenant:1'))).toBe('{"label_print":false}')
  })

  it('invalidates stale reads on account switch and handles unavailable ownership', async () => {
    const store = useWorkflowAiEmployeesStore()
    let ack!: (receipt: ReturnType<typeof confirmed>) => void
    vi.mocked(fetchWorkspacePrefs).mockImplementationOnce(() => new Promise(resolve => { ack = resolve }))
    const read = store.refreshConfirmedPreferences()
    await vi.waitFor(() => expect(fetchWorkspacePrefs).toHaveBeenCalledOnce())
    productReadAccountEpoch.value++
    store.reloadForTenantScope('tenant:2')
    ack(confirmed(true))
    await read
    expect(store.prefsReady).toBe(false)
    expect(store.confirmedEnabled).toEqual({})

    vi.mocked(fetchWorkspacePrefs).mockResolvedValueOnce({ success: true, owner_id: null })
    await store.refreshConfirmedPreferences()
    expect(store.prefsReady).toBe(false)
    expect(store.prefsError).toContain('无法确认工作区归属')
  })

  it('treats a mismatched change receipt as unconfirmed and does not change the cached state', async () => {
    const store = useWorkflowAiEmployeesStore()
    store.registerEmployee({ id: 'label_print', label: '标签打印', kind: 'core', order: 1, source: 'json' })
    store.acceptConfirmedPreferences({ label_print: false })
    vi.mocked(patchWorkspacePrefs).mockResolvedValueOnce(confirmed(false))
    await store.setEmployeeEnabledConfirmed('label_print', true)
    expect(flushWorkspacePrefsSync).toHaveBeenCalledOnce()
    expect(store.prefsReady).toBe(false)
    expect(store.prefsError).toContain('服务器未确认')
    expect(store.confirmedEnabled.label_print).toBe(false)
    expect(store.prefsSaving).toBe('')
  })
})
