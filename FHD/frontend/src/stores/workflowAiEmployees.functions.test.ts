import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const {
  mockFilterWorkflowRegistrySourceMods,
  mockIsNonWorkflowDeskEmployeeId,
  mockLoadWorkflowEmployeeRegistry,
  mockMergeModManifestEntries,
  mockResolveLabel,
  mockInvalidateCache,
  mockBuildTenantScopedStorageKey,
  mockResolveTenantStorageScope,
  mockQueueWorkspacePrefsSync,
} = vi.hoisted(() => ({
  mockFilterWorkflowRegistrySourceMods: vi.fn((mods: unknown[]) => mods || []),
  mockIsNonWorkflowDeskEmployeeId: vi.fn(() => false),
  mockLoadWorkflowEmployeeRegistry: vi.fn(async () => ({ employees: [] })),
  mockMergeModManifestEntries: vi.fn((registry: { employees: unknown[] }, _mods: unknown) => registry.employees),
  mockResolveLabel: vi.fn((entry: { id: string }, resolver?: (k: string) => string) => {
    if (resolver) return resolver(entry.id)
    return entry.id
  }),
  mockInvalidateCache: vi.fn(),
  mockBuildTenantScopedStorageKey: vi.fn((base: string, scope: string) => `${base}:${scope}`),
  mockResolveTenantStorageScope: vi.fn(() => 'local'),
  mockQueueWorkspacePrefsSync: vi.fn(),
}))

vi.mock('@/utils/modWorkflowEmployees', () => ({
  filterWorkflowRegistrySourceMods: mockFilterWorkflowRegistrySourceMods,
  isNonWorkflowDeskEmployeeId: mockIsNonWorkflowDeskEmployeeId,
}))

vi.mock('@/utils/workflowEmployeeRegistry', () => ({
  loadWorkflowEmployeeRegistry: mockLoadWorkflowEmployeeRegistry,
  mergeModManifestEntries: mockMergeModManifestEntries,
  resolveLabel: mockResolveLabel,
  invalidateWorkflowEmployeeRegistryCache: mockInvalidateCache,
}))

vi.mock('@/utils/tenantStorageScope', () => ({
  buildTenantScopedStorageKey: mockBuildTenantScopedStorageKey,
  resolveTenantStorageScopeFromRuntime: mockResolveTenantStorageScope,
}))

vi.mock('@/utils/workspacePrefsApi', () => ({
  queueWorkspacePrefsSync: mockQueueWorkspacePrefsSync,
}))

import { useWorkflowAiEmployeesStore } from './workflowAiEmployees'

describe('useWorkflowAiEmployeesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    mockFilterWorkflowRegistrySourceMods.mockClear()
    mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods || [])
    mockIsNonWorkflowDeskEmployeeId.mockClear()
    mockIsNonWorkflowDeskEmployeeId.mockReturnValue(false)
    mockLoadWorkflowEmployeeRegistry.mockClear()
    mockLoadWorkflowEmployeeRegistry.mockResolvedValue({ employees: [] })
    mockMergeModManifestEntries.mockClear()
    mockMergeModManifestEntries.mockImplementation((registry: { employees: unknown[] }) => registry.employees)
    mockResolveLabel.mockClear()
    mockResolveLabel.mockImplementation((entry: { id: string }, resolver?: (k: string) => string) => {
      if (resolver) return resolver(entry.id)
      return entry.id
    })
    mockInvalidateCache.mockClear()
    mockBuildTenantScopedStorageKey.mockClear()
    mockBuildTenantScopedStorageKey.mockImplementation((base: string, scope: string) => `${base}:${scope}`)
    mockResolveTenantStorageScope.mockClear()
    mockResolveTenantStorageScope.mockReturnValue('local')
    mockQueueWorkspacePrefsSync.mockClear()
  })

  describe('initial state', () => {
    it('starts with empty enabled', () => {
      const store = useWorkflowAiEmployeesStore()
      expect(store.enabled).toEqual({})
    })

    it('starts with empty registryEntries', () => {
      const store = useWorkflowAiEmployeesStore()
      expect(store.registryEntries).toEqual([])
    })

    it('starts with registryLoaded false', () => {
      const store = useWorkflowAiEmployeesStore()
      expect(store.registryLoaded).toBe(false)
    })

    it('registeredIds is empty Set initially', () => {
      const store = useWorkflowAiEmployeesStore()
      expect(store.registeredIds.size).toBe(0)
    })
  })

  describe('registerEmployee', () => {
    it('adds new employee to registry', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'Employee 1', order: 1 })
      expect(store.registryEntries.length).toBe(1)
      expect(store.registryEntries[0].id).toBe('emp1')
    })

    it('adds employee id to enabled as false', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'Employee 1', order: 1 })
      expect(store.enabled).toHaveProperty('emp1', false)
    })

    it('updates existing employee by id', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'Old', order: 1 })
      store.registerEmployee({ id: 'emp1', label: 'New', order: 1 })
      expect(store.registryEntries.length).toBe(1)
      expect(store.registryEntries[0].label).toBe('New')
    })

    it('sorts entries by order', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp2', label: 'B', order: 2 })
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      expect(store.registryEntries[0].id).toBe('emp1')
      expect(store.registryEntries[1].id).toBe('emp2')
    })

    it('does not add to enabled if id already exists', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // adds emp1: true
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      // Should not overwrite the existing enabled value
      expect(store.enabled.emp1).toBe(true)
    })
  })

  describe('unregisterEmployee', () => {
    it('removes employee from registry', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      store.unregisterEmployee('emp1')
      expect(store.registryEntries.length).toBe(0)
    })

    it('removes employee from enabled', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      store.unregisterEmployee('emp1')
      expect(store.enabled).not.toHaveProperty('emp1')
    })

    it('does nothing when id not found', () => {
      const store = useWorkflowAiEmployeesStore()
      store.unregisterEmployee('nonexistent')
      expect(store.registryEntries.length).toBe(0)
    })
  })

  describe('toggle', () => {
    it('sets id to true when not in enabled', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1')
      expect(store.enabled.emp1).toBe(true)
    })

    it('toggles id from false to true', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      store.toggle('emp1')
      expect(store.enabled.emp1).toBe(true)
    })

    it('toggles id from true to false', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // true
      store.toggle('emp1') // false
      expect(store.enabled.emp1).toBe(false)
    })
  })

  describe('setAll', () => {
    it('replaces enabled with new record', () => {
      const store = useWorkflowAiEmployeesStore()
      store.setAll({ emp1: true, emp2: false })
      expect(store.enabled).toEqual({ emp1: true, emp2: false })
    })

    it('overwrites previous values', () => {
      const store = useWorkflowAiEmployeesStore()
      store.setAll({ emp1: true })
      store.setAll({ emp2: false })
      expect(store.enabled).toEqual({ emp2: false })
    })
  })

  describe('enableAllOn', () => {
    it('sets all existing keys to true', () => {
      const store = useWorkflowAiEmployeesStore()
      store.setAll({ emp1: false, emp2: false })
      store.enableAllOn()
      expect(store.enabled.emp1).toBe(true)
      expect(store.enabled.emp2).toBe(true)
    })

    it('does nothing when enabled is empty', () => {
      const store = useWorkflowAiEmployeesStore()
      store.enableAllOn()
      expect(store.enabled).toEqual({})
    })
  })

  describe('enableEmployees', () => {
    it('enables specified employee ids', () => {
      const store = useWorkflowAiEmployeesStore()
      const turnedOn = store.enableEmployees(['emp1', 'emp2'])
      expect(store.enabled.emp1).toBe(true)
      expect(store.enabled.emp2).toBe(true)
      expect(turnedOn).toEqual(['emp1', 'emp2'])
    })

    it('skips empty ids', () => {
      const store = useWorkflowAiEmployeesStore()
      store.enableEmployees(['', 'emp1'])
      // empty string is trimmed and skipped by !id check
      expect(store.enabled.emp1).toBe(true)
    })

    it('skips non-workflow desk employee ids', () => {
      mockIsNonWorkflowDeskEmployeeId.mockReturnValue(true)
      const store = useWorkflowAiEmployeesStore()
      store.enableEmployees(['desk-emp'])
      expect(store.enabled).not.toHaveProperty('desk-emp')
    })

    it('with onlyNew, skips already-true ids', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // true
      const turnedOn = store.enableEmployees(['emp1', 'emp2'], { onlyNew: true })
      expect(turnedOn).toEqual(['emp2'])
    })

    it('trims whitespace from ids', () => {
      const store = useWorkflowAiEmployeesStore()
      store.enableEmployees(['  emp1  '])
      expect(store.enabled.emp1).toBe(true)
    })
  })

  describe('assignHostMod', () => {
    it('does nothing when hostModId is empty', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1, hostModId: '' })
      store.assignHostMod(['emp1'], '')
      expect(store.registryEntries[0].hostModId).toBe('')
    })

    it('updates hostModId for matching employees', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1, hostModId: '' })
      store.assignHostMod(['emp1'], 'host-mod-1')
      expect(store.registryEntries[0].hostModId).toBe('host-mod-1')
    })

    it('does not update when hostModId is same', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1, hostModId: 'host-mod-1' })
      store.assignHostMod(['emp1'], 'host-mod-1')
      expect(store.registryEntries[0].hostModId).toBe('host-mod-1')
    })

    it('skips employees not in the list', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1, hostModId: '' })
      store.registerEmployee({ id: 'emp2', label: 'B', order: 2, hostModId: '' })
      store.assignHostMod(['emp1'], 'host-mod-1')
      expect(store.registryEntries[0].hostModId).toBe('host-mod-1')
      expect(store.registryEntries[1].hostModId).toBe('')
    })
  })

  describe('getEmployeeLabel', () => {
    it('returns label from registry entry', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'Employee One', order: 1 })
      mockResolveLabel.mockReturnValue('Employee One')
      expect(store.getEmployeeLabel('emp1')).toBe('Employee One')
    })

    it('returns id when employee not found', () => {
      const store = useWorkflowAiEmployeesStore()
      expect(store.getEmployeeLabel('nonexistent')).toBe('nonexistent')
    })

    it('passes i18nResolver to resolveLabel', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      const resolver = vi.fn((key: string) => `translated-${key}`)
      mockResolveLabel.mockImplementation((entry: { id: string }, r?: (k: string) => string) => {
        return r ? r(entry.id) : entry.id
      })
      store.getEmployeeLabel('emp1', resolver)
      expect(resolver).toHaveBeenCalledWith('emp1')
    })
  })

  describe('loadRegistry', () => {
    it('loads registry and sets registryLoaded to true', async () => {
      mockLoadWorkflowEmployeeRegistry.mockResolvedValue({
        employees: [{ id: 'emp1', label: 'A', order: 1 }],
      })
      const store = useWorkflowAiEmployeesStore()
      await store.loadRegistry()
      expect(store.registryLoaded).toBe(true)
      expect(store.registryEntries.length).toBe(1)
    })

    it('merges mod manifest entries when mods provided', async () => {
      mockLoadWorkflowEmployeeRegistry.mockResolvedValue({
        employees: [{ id: 'emp1', label: 'A', order: 1 }],
      })
      mockMergeModManifestEntries.mockReturnValue([
        { id: 'emp1', label: 'A', order: 1 },
        { id: 'emp2', label: 'B', order: 2 },
      ])
      const store = useWorkflowAiEmployeesStore()
      await store.loadRegistry([{ id: 'mod1', workflow_employees: [] }])
      expect(store.registryEntries.length).toBe(2)
    })

    it('does not throw on error, logs warning', async () => {
      mockLoadWorkflowEmployeeRegistry.mockRejectedValue(new Error('network'))
      const store = useWorkflowAiEmployeesStore()
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      await expect(store.loadRegistry()).resolves.toBeUndefined()
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
    })
  })

  describe('refreshRegistry', () => {
    it('invalidates cache and reloads', async () => {
      mockLoadWorkflowEmployeeRegistry.mockResolvedValue({
        employees: [{ id: 'emp1', label: 'A', order: 1 }],
      })
      const store = useWorkflowAiEmployeesStore()
      await store.refreshRegistry()
      expect(mockInvalidateCache).toHaveBeenCalled()
      expect(store.registryLoaded).toBe(true)
    })
  })

  describe('hydrateFromMods', () => {
    it('merges mod workflow ids into enabled', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([
        { workflow_employees: [{ id: 'emp1' }, { id: 'emp2' }] },
      ])
      const store = useWorkflowAiEmployeesStore()
      store.hydrateFromMods([])
      expect(store.enabled).toHaveProperty('emp1', false)
      expect(store.enabled).toHaveProperty('emp2', false)
    })

    it('does not overwrite existing enabled keys', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([
        { workflow_employees: [{ id: 'emp1' }] },
      ])
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // true
      store.hydrateFromMods([])
      expect(store.enabled.emp1).toBe(true)
    })

    it('skips non-workflow desk employee ids', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([
        { workflow_employees: [{ id: 'desk-emp' }] },
      ])
      mockIsNonWorkflowDeskEmployeeId.mockReturnValue(true)
      const store = useWorkflowAiEmployeesStore()
      store.hydrateFromMods([])
      expect(store.enabled).not.toHaveProperty('desk-emp')
    })
  })

  describe('stripModWorkflowEmployeeKeys', () => {
    it('removes keys not in registry', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // not in registry
      store.registerEmployee({ id: 'emp2', label: 'B', order: 1 })
      store.toggle('emp2')
      store.stripModWorkflowEmployeeKeys()
      expect(store.enabled).not.toHaveProperty('emp1')
      expect(store.enabled).toHaveProperty('emp2')
    })
  })

  describe('pruneOrphanWorkflowEmployeeToggles', () => {
    it('removes keys not in registry or manifest', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([])
      const store = useWorkflowAiEmployeesStore()
      store.toggle('orphan-id')
      store.pruneOrphanWorkflowEmployeeToggles([])
      expect(store.enabled).not.toHaveProperty('orphan-id')
    })

    it('keeps keys in registry', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([])
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      store.toggle('emp1')
      store.pruneOrphanWorkflowEmployeeToggles([])
      expect(store.enabled).toHaveProperty('emp1')
    })

    it('keeps keys in manifest', () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([
        { workflow_employees: [{ id: 'manifest-emp' }] },
      ])
      const store = useWorkflowAiEmployeesStore()
      store.toggle('manifest-emp')
      store.pruneOrphanWorkflowEmployeeToggles([])
      expect(store.enabled).toHaveProperty('manifest-emp')
    })
  })

  describe('reloadFromLocalStorage', () => {
    it('reads enabled from localStorage', () => {
      const store = useWorkflowAiEmployeesStore()
      localStorage.setItem('xcagi_workflow_ai_employees:local', JSON.stringify({ emp1: true }))
      store.reloadFromLocalStorage()
      expect(store.enabled).toHaveProperty('emp1', true)
    })

    it('returns empty when localStorage is empty', () => {
      const store = useWorkflowAiEmployeesStore()
      store.reloadFromLocalStorage()
      expect(store.enabled).toEqual({})
    })
  })

  describe('reloadForTenantScope', () => {
    it('resets registryLoaded to false', () => {
      const store = useWorkflowAiEmployeesStore()
      store.refreshRegistry()
      store.reloadForTenantScope('tenant:1')
      expect(store.registryLoaded).toBe(false)
    })

    it('reads enabled for new scope', () => {
      mockBuildTenantScopedStorageKey.mockImplementation((base: string, scope: string) => `${base}:${scope}`)
      localStorage.setItem('xcagi_workflow_ai_employees:tenant:1', JSON.stringify({ emp1: true }))
      const store = useWorkflowAiEmployeesStore()
      store.reloadForTenantScope('tenant:1')
      expect(store.enabled).toHaveProperty('emp1', true)
    })
  })

  describe('persistAndNotify', () => {
    it('writes enabled to localStorage', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1')
      // persistAndNotify is called internally by toggle
      expect(localStorage.getItem('xcagi_workflow_ai_employees:local')).toContain('emp1')
    })

    it('dispatches custom event', () => {
      const store = useWorkflowAiEmployeesStore()
      const eventSpy = vi.fn()
      window.addEventListener('xcagi:workflow-ai-employees-changed', eventSpy)
      store.toggle('emp1')
      expect(eventSpy).toHaveBeenCalled()
      window.removeEventListener('xcagi:workflow-ai-employees-changed', eventSpy)
    })

    it('queues workspace prefs sync', async () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1')
      // dynamic import is async, wait for it to resolve
      await new Promise((resolve) => setTimeout(resolve, 10))
      expect(mockQueueWorkspacePrefsSync).toHaveBeenCalled()
    })
  })

  describe('ensureEnabledKeys', () => {
    it('adds missing registry ids to enabled as false', () => {
      const store = useWorkflowAiEmployeesStore()
      store.registerEmployee({ id: 'emp1', label: 'A', order: 1 })
      // registerEmployee already calls ensureEnabledKeys indirectly
      // Let's add another entry directly
      store.registryEntries.push({ id: 'emp2', label: 'B', order: 2 })
      store.ensureEnabledKeys()
      expect(store.enabled).toHaveProperty('emp2', false)
    })

    it('does not change existing enabled values', () => {
      const store = useWorkflowAiEmployeesStore()
      store.toggle('emp1') // true
      store.registryEntries.push({ id: 'emp1', label: 'A', order: 1 })
      store.ensureEnabledKeys()
      expect(store.enabled.emp1).toBe(true)
    })
  })
})
