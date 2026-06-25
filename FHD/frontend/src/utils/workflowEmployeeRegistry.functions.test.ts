import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockModWorkflow } = vi.hoisted(() => ({
  mockModWorkflow: {
    buildModWorkflowPanelMeta: vi.fn(() => ({})),
    isNonWorkflowDeskEmployeeId: vi.fn(() => false),
    filterWorkflowRegistrySourceMods: vi.fn((mods: unknown[]) => mods),
    type: {},
  },
}))

vi.mock('@/utils/modWorkflowEmployees', () => mockModWorkflow)

import {
  loadWorkflowEmployeeRegistry,
  invalidateWorkflowEmployeeRegistryCache,
  loadWorkflowEmployeeRegistryCached,
  mergeModManifestEntries,
  resolveLabel,
  loadRegistryFromJson,
} from './workflowEmployeeRegistry'
import type { WorkflowEmployeeRegistryV1, WorkflowEmployeeRegistryEntry } from '@/types/workflow-employee'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'

function makeRegistry(employees: WorkflowEmployeeRegistryEntry[] = []): WorkflowEmployeeRegistryV1 {
  return { schemaVersion: 1, employees }
}

function makeMod(overrides: Partial<ModWithWorkflowEmployees> = {}): ModWithWorkflowEmployees {
  return {
    id: 'mod1',
    name: 'Mod 1',
    workflow_employees: [],
    ...overrides,
  } as unknown as ModWithWorkflowEmployees
}

describe('workflowEmployeeRegistry functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockModWorkflow.buildModWorkflowPanelMeta.mockReturnValue({})
    mockModWorkflow.isNonWorkflowDeskEmployeeId.mockReturnValue(false)
    mockModWorkflow.filterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
    invalidateWorkflowEmployeeRegistryCache()
  })

  describe('loadWorkflowEmployeeRegistry', () => {
    it('returns empty registry (host no longer bundles employees)', async () => {
      const registry = await loadWorkflowEmployeeRegistry()
      expect(registry.schemaVersion).toBe(1)
      expect(registry.employees).toEqual([])
    })
  })

  describe('invalidateWorkflowEmployeeRegistryCache', () => {
    it('does not throw', () => {
      expect(() => invalidateWorkflowEmployeeRegistryCache()).not.toThrow()
    })
  })

  describe('loadWorkflowEmployeeRegistryCached', () => {
    it('returns a promise', () => {
      const result = loadWorkflowEmployeeRegistryCached()
      expect(result).toBeInstanceOf(Promise)
    })

    it('caches the result', async () => {
      const r1 = loadWorkflowEmployeeRegistryCached()
      const r2 = loadWorkflowEmployeeRegistryCached()
      const [v1, v2] = await Promise.all([r1, r2])
      expect(v1).toEqual(v2)
    })

    it('reloads after cache invalidation', async () => {
      const r1 = loadWorkflowEmployeeRegistryCached()
      await r1
      invalidateWorkflowEmployeeRegistryCache()
      const r2 = loadWorkflowEmployeeRegistryCached()
      expect(r1).not.toBe(r2)
      await r2
    })
  })

  describe('loadRegistryFromJson (deprecated)', () => {
    it('returns same as loadWorkflowEmployeeRegistry', async () => {
      const result = await loadRegistryFromJson()
      expect(result.schemaVersion).toBe(1)
      expect(result.employees).toEqual([])
    })
  })

  describe('mergeModManifestEntries', () => {
    it('returns empty array when registry and mods are empty', () => {
      const result = mergeModManifestEntries(makeRegistry(), [])
      expect(result).toEqual([])
    })

    it('preserves registry entries', () => {
      const registry = makeRegistry([
        { id: 'emp1', label: 'Employee 1', kind: 'core', order: 1, source: 'json' },
      ])
      const result = mergeModManifestEntries(registry, [])
      expect(result.length).toBe(1)
      expect(result[0].id).toBe('emp1')
    })

    it('adds entries from mod manifest', () => {
      const mods = [makeMod({
        id: 'mod1',
        workflow_employees: [{ id: 'new_emp', label: 'New Emp' }],
      })]
      const result = mergeModManifestEntries(makeRegistry(), mods)
      expect(result.some(e => e.id === 'new_emp')).toBe(true)
    })

    it('skips entries with empty id', () => {
      const mods = [makeMod({
        workflow_employees: [{ id: '', label: 'Empty' }],
      })]
      const result = mergeModManifestEntries(makeRegistry(), mods)
      expect(result.length).toBe(0)
    })

    it('skips non-workflow desk employee ids', () => {
      mockModWorkflow.isNonWorkflowDeskEmployeeId.mockImplementation((id: string) => id === 'skip_me')
      const mods = [makeMod({
        workflow_employees: [{ id: 'skip_me', label: 'Skip' }],
      })]
      const result = mergeModManifestEntries(makeRegistry(), mods)
      expect(result.length).toBe(0)
    })

    it('updates carrierModId and hostModId for existing entries', () => {
      const registry = makeRegistry([
        { id: 'emp1', label: 'Emp1', kind: 'core', order: 1, source: 'json' },
      ])
      const mods = [makeMod({
        id: 'mod1',
        workflow_employees: [{ id: 'emp1', label: 'Emp1' }],
      })]
      const result = mergeModManifestEntries(registry, mods)
      expect(result[0].carrierModId).toBe('mod1')
    })

    it('uses explicit host_mod_id when available', () => {
      const mods = [makeMod({
        id: 'mod1',
        workflow_employees: [{ id: 'emp1', label: 'Emp1', host_mod_id: 'host_mod' }],
      })]
      const result = mergeModManifestEntries(makeRegistry(), mods)
      expect(result[0].hostModId).toBe('host_mod')
    })

    it('uses enterprise_mod_id as fallback for host', () => {
      const mods = [makeMod({
        id: 'mod1',
        workflow_employees: [{ id: 'emp1', label: 'Emp1', enterprise_mod_id: 'ent_mod' }],
      })]
      const result = mergeModManifestEntries(makeRegistry(), mods)
      expect(result[0].hostModId).toBe('ent_mod')
    })

    it('adds entries from modMeta when not in manifest', () => {
      mockModWorkflow.buildModWorkflowPanelMeta.mockReturnValue({
        meta_emp: { title: '工作流 · Meta Emp' },
      })
      const result = mergeModManifestEntries(makeRegistry(), [])
      expect(result.some(e => e.id === 'meta_emp')).toBe(true)
    })

    it('strips "工作流 ·" prefix from meta title', () => {
      mockModWorkflow.buildModWorkflowPanelMeta.mockReturnValue({
        emp1: { title: '工作流 · Employee 1' },
      })
      const result = mergeModManifestEntries(makeRegistry(), [])
      expect(result[0].label).toBe('Employee 1')
    })

    it('sorts entries by order', () => {
      const registry = makeRegistry([
        { id: 'emp2', label: 'Emp2', kind: 'core', order: 5, source: 'json' },
        { id: 'emp1', label: 'Emp1', kind: 'core', order: 1, source: 'json' },
      ])
      const result = mergeModManifestEntries(registry, [])
      expect(result[0].id).toBe('emp1')
      expect(result[1].id).toBe('emp2')
    })
  })

  describe('resolveLabel', () => {
    it('returns label when no i18n resolver', () => {
      const entry = { id: '1', label: 'Test', kind: 'core', order: 1, source: 'json' }
      expect(resolveLabel(entry)).toBe('Test')
    })

    it('returns label when labelI18nKey is not set', () => {
      const entry = { id: '1', label: 'Test', kind: 'core', order: 1, source: 'json' }
      expect(resolveLabel(entry, () => 'resolved')).toBe('Test')
    })

    it('returns resolved label when i18nResolver returns different value', () => {
      const entry = { id: '1', label: 'Test', kind: 'core', order: 1, source: 'json', labelI18nKey: 'key.1' }
      expect(resolveLabel(entry, () => 'Resolved')).toBe('Resolved')
    })

    it('returns original label when i18nResolver returns same value as key', () => {
      const entry = { id: '1', label: 'Test', kind: 'core', order: 1, source: 'json', labelI18nKey: 'key.1' }
      expect(resolveLabel(entry, (k) => k)).toBe('Test')
    })

    it('returns original label when i18nResolver returns empty string', () => {
      const entry = { id: '1', label: 'Test', kind: 'core', order: 1, source: 'json', labelI18nKey: 'key.1' }
      expect(resolveLabel(entry, () => '')).toBe('Test')
    })
  })
})
