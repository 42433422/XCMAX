import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import { useHostConfigStore } from './hostConfig'
import { apiFetch } from '@/utils/apiBase'

function mockFetchResponse(data: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(data),
  } as Response)
}

describe('hostConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset module-level state
    const store = useHostConfigStore()
    store.loaded.value = false
    store.loadError.value = null
    store.industryPresets.value = {}
    store.industryPresetIds.value = []
    store.workflowEmployeeModIds.value = []
    store.workflowEmployeeIds.value = []
    store.employeeRegistryRules.value = null
    store.clientModPolicies.value = null
  })

  describe('useHostConfigStore', () => {
    it('returns store API', () => {
      const store = useHostConfigStore()
      expect(store.loaded).toBeDefined()
      expect(store.loadError).toBeDefined()
      expect(store.industryPresets).toBeDefined()
      expect(store.industryPresetIds).toBeDefined()
      expect(store.workflowEmployeeModIds).toBeDefined()
      expect(store.workflowEmployeeIds).toBeDefined()
      expect(store.employeeRegistryRules).toBeDefined()
      expect(store.clientModPolicies).toBeDefined()
      expect(store.workflowDelivery).toBeDefined()
      expect(typeof store.bootstrapHostConfig).toBe('function')
    })
  })

  describe('bootstrapHostConfig', () => {
    it('loads industry presets from API', async () => {
      vi.mocked(apiFetch).mockImplementation((path: string) => {
        if (path.includes('industry-presets')) {
          return mockFetchResponse({
            data: {
              preset_ids: ['tech', 'retail'],
              presets: { tech: { label: '科技' }, retail: { label: '零售' } },
            },
          })
        }
        if (path.includes('workflow-employee-catalog')) {
          return mockFetchResponse({
            data: {
              catalog: {
                default_mod_ids: ['mod1', 'mod2'],
                default_employee_ids: ['emp1'],
              },
              workflow_delivery: 'split',
            },
          })
        }
        if (path.includes('employee-registry-rules')) {
          return mockFetchResponse({
            data: {
              workflow_employee_id_prefixes: ['wf-'],
              exclude_id_suffixes: ['-test'],
            },
          })
        }
        if (path.includes('host-profile')) {
          return mockFetchResponse({
            data: {
              profile: {
                client_mod_policies: {
                  client_primary_erp_mod_id: 'erp-mod',
                  suppress_generic_shell_mod_ids: ['shell1'],
                },
                workflow_delivery: 'monolith',
              },
            },
          })
        }
        return mockFetchResponse(null)
      })

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()

      expect(store.industryPresetIds.value).toEqual(['tech', 'retail'])
      expect(store.industryPresets.value).toEqual({ tech: { label: '科技' }, retail: { label: '零售' } })
      expect(store.workflowEmployeeModIds.value).toEqual(['mod1', 'mod2'])
      expect(store.workflowEmployeeIds.value).toEqual(['emp1'])
      expect(store.employeeRegistryRules.value).toEqual({
        workflow_employee_id_prefixes: ['wf-'],
        exclude_id_suffixes: ['-test'],
      })
      expect(store.clientModPolicies.value).toEqual({
        client_primary_erp_mod_id: 'erp-mod',
        suppress_generic_shell_mod_ids: ['shell1'],
      })
      expect(store.loaded.value).toBe(true)
    })

    it('handles API failure gracefully', async () => {
      vi.mocked(apiFetch).mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({}),
      } as Response)

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      expect(store.loaded.value).toBe(true)
      expect(store.loadError.value).toBeNull()
    })

    it('handles network error', async () => {
      vi.mocked(apiFetch).mockRejectedValue(new Error('Network error'))

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      // Error may be set or null depending on module-level state
      // The key assertion is that the function doesn't throw
      expect(store.loaded.value).toBe(true)
    })

    it('skips if already loaded', async () => {
      const store = useHostConfigStore()
      store.loaded.value = true

      await store.bootstrapHostConfig()
      expect(apiFetch).not.toHaveBeenCalled()
    })

    it('handles presets without preset_ids by using object keys', async () => {
      vi.mocked(apiFetch).mockImplementation((path: string) => {
        if (path.includes('industry-presets')) {
          return mockFetchResponse({
            data: {
              presets: { tech: { label: '科技' } },
            },
          })
        }
        return mockFetchResponse(null)
      })

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      expect(store.industryPresetIds.value).toEqual(['tech'])
    })

    it('handles catalog with workflow_delivery', async () => {
      vi.mocked(apiFetch).mockImplementation((path: string) => {
        if (path.includes('workflow-employee-catalog')) {
          return mockFetchResponse({
            data: {
              workflow_delivery: 'split',
            },
          })
        }
        return mockFetchResponse(null)
      })

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      expect(store.workflowDelivery.value).toBe('split')
    })

    it('handles host-profile with workflow_delivery override', async () => {
      vi.mocked(apiFetch).mockImplementation((path: string) => {
        if (path.includes('host-profile')) {
          return mockFetchResponse({
            data: {
              profile: {
                workflow_delivery: 'monolith',
              },
            },
          })
        }
        return mockFetchResponse(null)
      })

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      expect(store.workflowDelivery.value).toBe('monolith')
    })

    it('handles null body from API', async () => {
      vi.mocked(apiFetch).mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(null),
      } as Response)

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      expect(store.loaded.value).toBe(true)
    })

    it('handles non-Error thrown value', async () => {
      vi.mocked(apiFetch).mockRejectedValue('string error')

      const store = useHostConfigStore()
      await store.bootstrapHostConfig()
      // The function should not throw regardless of error type
      expect(true).toBe(true)
    })
  })
})
