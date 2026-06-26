import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/utils/modWorkflowEmployees', () => ({
  buildModWorkflowPanelMeta: vi.fn(() => ({})),
  isNonWorkflowDeskEmployeeId: vi.fn((id: string) => {
    const blocked = ['office_pack', 'host_desk', 'employee_pack']
    return blocked.includes(String(id || '').trim())
  }),
  filterWorkflowRegistrySourceMods: vi.fn((mods: unknown[]) => mods || []),
}))

import {
  loadWorkflowEmployeeRegistry,
  invalidateWorkflowEmployeeRegistryCache,
  loadWorkflowEmployeeRegistryCached,
  mergeModManifestEntries,
  resolveLabel,
  loadRegistryFromJson,
} from './workflowEmployeeRegistry'
import type { WorkflowEmployeeRegistryV1, WorkflowEmployeeRegistryEntry } from '@/types/workflow-employee'

describe('workflowEmployeeRegistry', () => {
  describe('loadWorkflowEmployeeRegistry', () => {
    it('returns empty registry', async () => {
      const result = await loadWorkflowEmployeeRegistry()
      expect(result.schemaVersion).toBe(1)
      expect(result.employees).toEqual([])
    })
  })

  describe('invalidateWorkflowEmployeeRegistryCache', () => {
    it('does not throw', () => {
      expect(() => invalidateWorkflowEmployeeRegistryCache()).not.toThrow()
    })
  })

  describe('loadWorkflowEmployeeRegistryCached', () => {
    beforeEach(() => {
      invalidateWorkflowEmployeeRegistryCache()
    })

    it('returns cached registry on first call', async () => {
      const result = await loadWorkflowEmployeeRegistryCached()
      expect(result.schemaVersion).toBe(1)
      expect(result.employees).toEqual([])
    })

    it('returns same resolved value on subsequent calls (caching)', async () => {
      const r1 = await loadWorkflowEmployeeRegistryCached()
      const r2 = await loadWorkflowEmployeeRegistryCached()
      expect(r1).toBe(r2)
    })

    it('returns new value after cache invalidation', async () => {
      const r1 = await loadWorkflowEmployeeRegistryCached()
      invalidateWorkflowEmployeeRegistryCache()
      const r2 = await loadWorkflowEmployeeRegistryCached()
      expect(r1).not.toBe(r2)
    })
  })

  describe('mergeModManifestEntries', () => {
    it('returns empty array for empty registry and no mods', () => {
      const registry: WorkflowEmployeeRegistryV1 = { schemaVersion: 1, employees: [] }
      const result = mergeModManifestEntries(registry, [])
      expect(result).toEqual([])
    })

    it('returns existing employees when no mods provided', () => {
      const registry: WorkflowEmployeeRegistryV1 = {
        schemaVersion: 1,
        employees: [
          { id: 'emp1', label: 'Employee 1', kind: 'mod_extension', order: 1, source: 'json' },
        ],
      }
      const result = mergeModManifestEntries(registry, [])
      expect(result).toHaveLength(1)
      expect(result[0].id).toBe('emp1')
    })

    it('adds employees from mod manifests', () => {
      const registry: WorkflowEmployeeRegistryV1 = { schemaVersion: 1, employees: [] }
      const mods = [
        {
          id: 'mod1',
          workflow_employees: [
            { id: 'emp1', label: 'Employee 1' },
          ],
        },
      ]
      const result = mergeModManifestEntries(registry, mods as any)
      expect(result.some((e) => e.id === 'emp1')).toBe(true)
    })

    it('skips non-workflow desk employee ids', () => {
      const registry: WorkflowEmployeeRegistryV1 = { schemaVersion: 1, employees: [] }
      const mods = [
        {
          id: 'mod1',
          workflow_employees: [
            { id: 'office_pack', label: 'Office Pack' },
            { id: 'emp1', label: 'Employee 1' },
          ],
        },
      ]
      const result = mergeModManifestEntries(registry, mods as any)
      expect(result.some((e) => e.id === 'office_pack')).toBe(false)
      expect(result.some((e) => e.id === 'emp1')).toBe(true)
    })

    it('sorts by order', () => {
      const registry: WorkflowEmployeeRegistryV1 = {
        schemaVersion: 1,
        employees: [
          { id: 'emp_b', label: 'B', kind: 'mod_extension', order: 2, source: 'json' },
          { id: 'emp_a', label: 'A', kind: 'mod_extension', order: 1, source: 'json' },
        ],
      }
      const result = mergeModManifestEntries(registry, [])
      expect(result[0].id).toBe('emp_a')
      expect(result[1].id).toBe('emp_b')
    })
  })

  describe('resolveLabel', () => {
    it('returns label when no i18n key', () => {
      const entry: WorkflowEmployeeRegistryEntry = {
        id: 'emp1',
        label: '员工1',
        kind: 'mod_extension',
        order: 1,
        source: 'json',
      }
      expect(resolveLabel(entry)).toBe('员工1')
    })

    it('returns label when no i18n resolver', () => {
      const entry: WorkflowEmployeeRegistryEntry = {
        id: 'emp1',
        label: '员工1',
        kind: 'mod_extension',
        order: 1,
        source: 'json',
        labelI18nKey: 'employee.emp1',
      }
      expect(resolveLabel(entry)).toBe('员工1')
    })

    it('returns resolved label when i18n resolver returns different value', () => {
      const entry: WorkflowEmployeeRegistryEntry = {
        id: 'emp1',
        label: '员工1',
        kind: 'mod_extension',
        order: 1,
        source: 'json',
        labelI18nKey: 'employee.emp1',
      }
      const resolver = (key: string) => (key === 'employee.emp1' ? 'Employee One' : key)
      expect(resolveLabel(entry, resolver)).toBe('Employee One')
    })

    it('returns label when i18n resolver returns same key', () => {
      const entry: WorkflowEmployeeRegistryEntry = {
        id: 'emp1',
        label: '员工1',
        kind: 'mod_extension',
        order: 1,
        source: 'json',
        labelI18nKey: 'employee.emp1',
      }
      const resolver = (key: string) => key
      expect(resolveLabel(entry, resolver)).toBe('员工1')
    })

    it('returns label when i18n resolver returns empty string', () => {
      const entry: WorkflowEmployeeRegistryEntry = {
        id: 'emp1',
        label: '员工1',
        kind: 'mod_extension',
        order: 1,
        source: 'json',
        labelI18nKey: 'employee.emp1',
      }
      const resolver = () => ''
      expect(resolveLabel(entry, resolver)).toBe('员工1')
    })
  })

  describe('loadRegistryFromJson (deprecated)', () => {
    it('returns same as loadWorkflowEmployeeRegistry', async () => {
      const result = await loadRegistryFromJson()
      expect(result.schemaVersion).toBe(1)
      expect(result.employees).toEqual([])
    })
  })
})
