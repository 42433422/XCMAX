import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modStore', () => ({
  reloadEmployeePacks: vi.fn(),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: vi.fn(() => ({
    modsForUi: [],
    refresh: vi.fn().mockResolvedValue(undefined),
  })),
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: vi.fn(() => ({
    refreshRegistry: vi.fn().mockResolvedValue(undefined),
    assignHostMod: vi.fn(),
    enableEmployees: vi.fn(() => []),
  })),
}))

vi.mock('@/utils/enterpriseModStackApi', () => ({
  resolveEnterpriseModStack: vi.fn().mockResolvedValue({
    stackLabel: 'Test Stack',
    hostModId: 'host-mod-1',
  }),
}))

vi.mock('@/utils/workflowEmployeeScope', () => ({
  filterModsForEnterpriseWorkflowRegistry: vi.fn(() => []),
}))

vi.mock('@/utils/modWorkflowEmployees', () => ({
  filterWorkflowRegistrySourceMods: vi.fn((mods: unknown[]) => mods || []),
  isNonWorkflowDeskEmployeeId: vi.fn((id: string) => {
    const blocked = ['office_pack', 'host_desk']
    return blocked.includes(String(id || '').trim())
  }),
}))

vi.mock('@/constants/enterpriseModStack', () => ({
  defaultHostModIdForMarketEmployee: vi.fn(() => 'host-mod-1'),
}))

import {
  collectDeskEmployeeIdsFromCatalogItem,
  autoOnboardInstalledMarketItem,
  autoOnboardWorkflowEmployeesForMod,
  autoOnboardWorkflowEmployeesFromMods,
} from './workflowEmployeeOnboard'

describe('workflowEmployeeOnboard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe('collectDeskEmployeeIdsFromCatalogItem', () => {
    it('returns empty array for undefined item', () => {
      expect(collectDeskEmployeeIdsFromCatalogItem(undefined)).toEqual([])
    })

    it('returns empty array for null item', () => {
      expect(collectDeskEmployeeIdsFromCatalogItem(null as any)).toEqual([])
    })

    it('collects ids from workflow_employees', () => {
      const item = {
        workflow_employees: [
          { id: 'emp1', label: 'Emp1' },
          { id: 'emp2', label: 'Emp2' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp1', 'emp2'])
    })

    it('filters out non-workflow desk employee ids', () => {
      const item = {
        workflow_employees: [
          { id: 'office_pack', label: 'Office' },
          { id: 'emp1', label: 'Emp1' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp1'])
    })

    it('falls back to employee.id when no workflow_employees', () => {
      const item = {
        employee: { id: 'emp_from_employee', label: 'Emp' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp_from_employee'])
    })

    it('returns empty when employee.id is a non-workflow desk id', () => {
      const item = {
        employee: { id: 'office_pack', label: 'Office' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })

    it('skips empty ids in workflow_employees', () => {
      const item = {
        workflow_employees: [
          { id: '', label: 'Empty' },
          { id: 'emp1', label: 'Emp1' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp1'])
    })

    it('prefers workflow_employees over employee.id', () => {
      const item = {
        workflow_employees: [{ id: 'wf_emp', label: 'WF' }],
        employee: { id: 'fallback_emp', label: 'Fallback' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['wf_emp'])
    })
  })

  describe('autoOnboardInstalledMarketItem', () => {
    it('returns result with expected shape', async () => {
      const item = { id: 'mod1', pkg_id: 'mod1', name: 'Test Mod' }
      const result = await autoOnboardInstalledMarketItem(item)
      expect(result).toHaveProperty('plannerRefreshed')
      expect(result).toHaveProperty('onboardedIds')
      expect(result).toHaveProperty('enterpriseStackLabel')
      expect(result).toHaveProperty('hostModId')
      expect(Array.isArray(result.onboardedIds)).toBe(true)
    })

    it('refreshes employee packs for employee_pack artifact', async () => {
      const { reloadEmployeePacks } = await import('@/api/modStore')
      const item = { id: 'mod1', pkg_id: 'mod1', artifact: 'employee_pack' }
      await autoOnboardInstalledMarketItem(item)
      expect(reloadEmployeePacks).toHaveBeenCalled()
    })

    it('does not refresh employee packs for non-employee_pack artifact', async () => {
      const { reloadEmployeePacks } = await import('@/api/modStore')
      const item = { id: 'mod1', pkg_id: 'mod1', artifact: 'other' }
      await autoOnboardInstalledMarketItem(item)
      expect(reloadEmployeePacks).not.toHaveBeenCalled()
    })
  })

  describe('autoOnboardWorkflowEmployeesForMod (deprecated)', () => {
    it('returns onboarded ids array', async () => {
      const result = await autoOnboardWorkflowEmployeesForMod('mod1')
      expect(Array.isArray(result)).toBe(true)
    })
  })

  describe('autoOnboardWorkflowEmployeesFromMods', () => {
    it('returns empty array for undefined mods', async () => {
      const result = await autoOnboardWorkflowEmployeesFromMods(undefined)
      expect(result).toEqual([])
    })

    it('returns empty array for mods without workflow employees', async () => {
      const result = await autoOnboardWorkflowEmployeesFromMods([
        { id: 'mod1', workflow_employees: [] },
      ])
      expect(result).toEqual([])
    })
  })
})
