import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockBundledDocs, mockDocIds, mockModWorkflow } = vi.hoisted(() => ({
  mockBundledDocs: {
    schemaVersion: 1,
    pageTitle: 'Test',
    pageSubtitle: 'Sub',
    pipelineBranchLabel: 'Pipeline',
    overviewNote: 'Note',
    floatPanelHint: 'Hint',
    branches: [{ id: 'core_emp', kind: 'core', title: 'Core', trigger: 't' }],
    flows: [{ id: 'core_emp', kind: 'core', title: 'Core Flow', lead: 'l', steps: [], notes: [] }],
  },
  mockDocIds: {
    isWorkflowDocCoreEmployeeId: vi.fn((id: string) => id === 'core_emp'),
    isWorkflowDocFixedModServiceId: vi.fn((id: string) => id === 'fixed_svc'),
  },
  mockModWorkflow: {
    countManifestWorkflowEmployeeRows: vi.fn(() => 0),
    resolvePhoneAgentApiBase: vi.fn(() => ''),
    type: {},
  },
}))

vi.mock('@/data/workflow-employee-docs.json', () => ({ default: mockBundledDocs }))
vi.mock('@/constants/workflowEmployeeDocIds', () => mockDocIds)
vi.mock('@/utils/modWorkflowEmployees', () => mockModWorkflow)

import {
  buildSyntheticManifestWorkflowFlow,
  mergeManifestWorkflowEmployeesIntoDocs,
  normalizeWorkflowEmployeeDocs,
  loadWorkflowEmployeeDocs,
  getWorkflowEmployeeDocs,
  isModWorkflowEmployeesActive,
  applyWorkflowEmployeeDocsRuntime,
  type WorkflowDocsRuntimeContext,
} from './workflowEmployeeDocs'
import type { WorkflowEmployeeDocsV1, WorkflowBranchDoc, WorkflowFlowDoc } from '@/types/workflowEmployeeDocs'
import type { WorkflowEmployeeManifestEntry, ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'

function makeDocs(overrides: Partial<WorkflowEmployeeDocsV1> = {}): WorkflowEmployeeDocsV1 {
  return {
    schemaVersion: 1,
    pageTitle: 'Test',
    pageSubtitle: 'Sub',
    pipelineBranchLabel: 'Pipeline',
    overviewNote: 'Note',
    floatPanelHint: 'Hint',
    branches: [],
    flows: [],
    ...overrides,
  }
}

function makeCtx(overrides: Partial<WorkflowDocsRuntimeContext> = {}): WorkflowDocsRuntimeContext {
  return {
    clientModsUiOff: false,
    modsForUi: [],
    isModsListLoaded: true,
    modsDisabledByServer: false,
    ...overrides,
  }
}

describe('workflowEmployeeDocs functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDocIds.isWorkflowDocCoreEmployeeId.mockImplementation((id: string) => id === 'core_emp')
    mockDocIds.isWorkflowDocFixedModServiceId.mockImplementation((id: string) => id === 'fixed_svc')
    mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(0)
    mockModWorkflow.resolvePhoneAgentApiBase.mockReturnValue('')
  })

  describe('buildSyntheticManifestWorkflowFlow', () => {
    it('builds flow with id and label from manifest entry', () => {
      const entry = { id: 'emp1', label: 'Employee 1' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.id).toBe('emp1')
      expect(flow.title).toContain('Employee 1')
      expect(flow.kind).toBe('mod_extension')
    })

    it('uses id as label when label is empty', () => {
      const entry = { id: 'emp1', label: '' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.title).toContain('emp1')
    })

    it('uses id when both id and label are empty', () => {
      const entry = { id: '', label: '' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.id).toBe('')
    })

    it('uses panel_summary when available', () => {
      const entry = { id: 'emp1', label: 'Emp', panel_summary: 'Custom summary' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.lead).toBe('Custom summary')
    })

    it('generates default summary when panel_summary is empty', () => {
      const entry = { id: 'emp1', label: 'Emp' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.lead).toContain('Mod Name')
      expect(flow.lead).toContain('Emp')
    })

    it('adds phone agent steps when phoneBase is available', () => {
      mockModWorkflow.resolvePhoneAgentApiBase.mockReturnValue('http://phone/api')
      const entry = { id: 'emp1', label: 'Emp' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.steps.length).toBeGreaterThanOrEqual(3)
      expect(flow.steps.some(s => s.label.includes('电话'))).toBe(true)
    })

    it('adds placeholder steps for placeholder entries', () => {
      const entry = { id: 'emp1', label: 'Emp', workflow_ui_kind: 'placeholder' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.steps.some(s => s.label.includes('宿主业务页'))).toBe(true)
    })

    it('adds default extension steps when no phone and not placeholder', () => {
      const entry = { id: 'emp1', label: 'Emp' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.steps.some(s => s.label.includes('扩展包文档'))).toBe(true)
    })

    it('includes mod info in notes', () => {
      const entry = { id: 'emp1', label: 'Emp' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.notes.some(n => n.includes('mod1'))).toBe(true)
      expect(flow.notes.some(n => n.includes('Mod Name'))).toBe(true)
    })

    it('includes phone API root in notes when available', () => {
      mockModWorkflow.resolvePhoneAgentApiBase.mockReturnValue('http://phone/api')
      const entry = { id: 'emp1', label: 'Emp' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.notes.some(n => n.includes('http://phone/api'))).toBe(true)
    })

    it('includes relative API prefix in notes when phone_agent_base_path is set', () => {
      const entry = { id: 'emp1', label: 'Emp', phone_agent_base_path: '/custom/path/' } as WorkflowEmployeeManifestEntry
      const flow = buildSyntheticManifestWorkflowFlow(entry, 'mod1', 'Mod Name')
      expect(flow.notes.some(n => n.includes('/api/mod/mod1/custom/path'))).toBe(true)
    })
  })

  describe('mergeManifestWorkflowEmployeesIntoDocs', () => {
    it('returns original docs when mod workflow employees not active', () => {
      const docs = makeDocs()
      const ctx = makeCtx({ clientModsUiOff: true })
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result).toBe(docs)
    })

    it('returns original docs when no extra branches needed', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(0)
      const docs = makeDocs()
      const ctx = makeCtx()
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result).toBe(docs)
    })

    it('merges manifest entries into docs', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(1)
      const docs = makeDocs({
        branches: [{ id: 'existing', kind: 'core', title: 'Existing', trigger: 't' }],
        flows: [{ id: 'existing', kind: 'core', title: 'Existing Flow', lead: 'l', steps: [], notes: [] }],
      })
      const ctx = makeCtx({
        modsForUi: [{
          id: 'mod1',
          name: 'Mod 1',
          workflow_employees: [{ id: 'new_emp', label: 'New Employee' }],
        } as unknown as ModWithWorkflowEmployees],
      })
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result.branches.length).toBe(2)
      expect(result.flows.length).toBe(2)
      expect(result.branches.some(b => b.id === 'new_emp')).toBe(true)
    })

    it('skips entries with empty id', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(1)
      const docs = makeDocs()
      const ctx = makeCtx({
        modsForUi: [{
          id: 'mod1',
          name: 'Mod 1',
          workflow_employees: [{ id: '', label: 'Empty' }],
        } as unknown as ModWithWorkflowEmployees],
      })
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result.branches.length).toBe(0)
    })

    it('skips entries with duplicate id', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(1)
      const docs = makeDocs({
        branches: [{ id: 'dup', kind: 'core', title: 'Dup', trigger: 't' }],
        flows: [],
      })
      const ctx = makeCtx({
        modsForUi: [{
          id: 'mod1',
          name: 'Mod 1',
          workflow_employees: [{ id: 'dup', label: 'Duplicate' }],
        } as unknown as ModWithWorkflowEmployees],
      })
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result.branches.length).toBe(1)
    })
    it('deduplicates entries across mods', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(2)
      const docs = makeDocs()
      const ctx = makeCtx({
        modsForUi: [
          { id: 'mod1', name: 'Mod 1', workflow_employees: [{ id: 'same', label: 'Same' }] },
          { id: 'mod2', name: 'Mod 2', workflow_employees: [{ id: 'same', label: 'Same Again' }] },
        ] as unknown as ModWithWorkflowEmployees[],
      })
      const result = mergeManifestWorkflowEmployeesIntoDocs(docs, ctx)
      expect(result.branches.filter(b => b.id === 'same').length).toBe(1)
    })
  })

  describe('normalizeWorkflowEmployeeDocs', () => {
    it('resolves kind for branches based on id', () => {
      mockDocIds.isWorkflowDocCoreEmployeeId.mockImplementation((id: string) => id === 'core_emp')
      mockDocIds.isWorkflowDocFixedModServiceId.mockImplementation((id: string) => id === 'fixed_svc')
      const docs = makeDocs({
        branches: [
          { id: 'core_emp', kind: 'mod_extension', title: 'T', trigger: 't' },
          { id: 'fixed_svc', kind: 'core', title: 'T', trigger: 't' },
          { id: 'other', kind: 'mod_extension', title: 'T', trigger: 't' },
        ],
        flows: [],
      })
      const result = normalizeWorkflowEmployeeDocs(docs)
      expect(result.branches[0].kind).toBe('core')
      expect(result.branches[1].kind).toBe('fixed_extension')
      expect(result.branches[2].kind).toBe('mod_extension')
    })

    it('resolves kind for flows based on id', () => {
      mockDocIds.isWorkflowDocCoreEmployeeId.mockImplementation((id: string) => id === 'core_emp')
      mockDocIds.isWorkflowDocFixedModServiceId.mockImplementation((id: string) => id === 'fixed_svc')
      const docs = makeDocs({
        branches: [],
        flows: [
          { id: 'core_emp', kind: 'mod_extension', title: 'T', lead: 'l', steps: [], notes: [] },
          { id: 'fixed_svc', kind: 'core', title: 'T', lead: 'l', steps: [], notes: [] },
        ],
      })
      const result = normalizeWorkflowEmployeeDocs(docs)
      expect(result.flows[0].kind).toBe('core')
      expect(result.flows[1].kind).toBe('fixed_extension')
    })

    it('preserves valid kind from json when id does not match known patterns', () => {
      const docs = makeDocs({
        branches: [{ id: 'unknown', kind: 'mod_extension', title: 'T', trigger: 't' }],
        flows: [],
      })
      const result = normalizeWorkflowEmployeeDocs(docs)
      expect(result.branches[0].kind).toBe('mod_extension')
    })

    it('defaults to core when kind is invalid', () => {
      const docs = makeDocs({
        branches: [{ id: 'unknown', kind: 'invalid_kind' as unknown as string, title: 'T', trigger: 't' }],
        flows: [],
      })
      const result = normalizeWorkflowEmployeeDocs(docs)
      expect(result.branches[0].kind).toBe('core')
    })
  })

  describe('isModWorkflowEmployeesActive', () => {
    it('returns false when clientModsUiOff is true', () => {
      expect(isModWorkflowEmployeesActive(makeCtx({ clientModsUiOff: true }))).toBe(false)
    })

    it('returns false when modsDisabledByServer is true', () => {
      expect(isModWorkflowEmployeesActive(makeCtx({ modsDisabledByServer: true }))).toBe(false)
    })

    it('returns false when mods list not loaded', () => {
      expect(isModWorkflowEmployeesActive(makeCtx({ isModsListLoaded: false }))).toBe(false)
    })

    it('returns false when no manifest workflow employee rows', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(0)
      expect(isModWorkflowEmployeesActive(makeCtx())).toBe(false)
    })

    it('returns true when manifest has workflow employee rows', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(5)
      expect(isModWorkflowEmployeesActive(makeCtx())).toBe(true)
    })
  })

  describe('applyWorkflowEmployeeDocsRuntime', () => {
    it('sets original mode copy when clientModsUiOff', () => {
      const docs = makeDocs()
      const ctx = makeCtx({ clientModsUiOff: true })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pipelineBranchLabel).toContain('原版模式')
      expect(result.pageSubtitle).toContain('原版模式')
    })

    it('sets disabled copy when modsDisabledByServer', () => {
      const docs = makeDocs()
      const ctx = makeCtx({ modsDisabledByServer: true })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pipelineBranchLabel).toContain('后端已关闭扩展')
    })

    it('sets loading copy when mods list not loaded', () => {
      const docs = makeDocs()
      const ctx = makeCtx({ isModsListLoaded: false })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pipelineBranchLabel).toContain('同步扩展列表中')
    })

    it('sets no mods copy when no packages loaded', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(0)
      const docs = makeDocs()
      const ctx = makeCtx({ modsForUi: [], isModsListLoaded: true })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pipelineBranchLabel).toContain('未安装工作流员工')
      expect(result.pageSubtitle).toContain('未加载任何扩展包')
    })

    it('sets no employees copy when packages loaded but no workflow employees', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(0)
      const docs = makeDocs()
      const ctx = makeCtx({
        modsForUi: [{ id: 'm1', name: 'Mod1' } as unknown as ModWithWorkflowEmployees],
        isModsListLoaded: true,
      })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pageSubtitle).toContain('1 个扩展包')
    })

    it('sets active copy when workflow employees are active', () => {
      mockModWorkflow.countManifestWorkflowEmployeeRows.mockReturnValue(3)
      const docs = makeDocs()
      const ctx = makeCtx({
        modsForUi: [{ id: 'm1', name: 'Mod1' } as unknown as ModWithWorkflowEmployees],
        isModsListLoaded: true,
      })
      const result = applyWorkflowEmployeeDocsRuntime(docs, ctx)
      expect(result.pipelineBranchLabel).toContain('3 名工作流员工')
      expect(result.pageSubtitle).toContain('3 条')
    })
  })

  describe('loadWorkflowEmployeeDocs', () => {
    it('loads from bundled docs when fetch fails', async () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
      const docs = await loadWorkflowEmployeeDocs()
      expect(docs.schemaVersion).toBe(1)
      expect(docs.pageTitle).toBe('Test')
    })

    it('loads from fetched JSON when available', async () => {
      const fetchedDocs = makeDocs({ pageTitle: 'Fetched' })
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(fetchedDocs),
      } as Response)
      const docs = await loadWorkflowEmployeeDocs()
      expect(docs.pageTitle).toBe('Fetched')
    })

    it('falls back to bundled when fetch returns non-ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, status: 404 } as Response)
      const docs = await loadWorkflowEmployeeDocs()
      expect(docs.pageTitle).toBe('Test')
    })

    it('falls back to bundled when JSON is invalid', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ invalid: true }),
      } as Response)
      const docs = await loadWorkflowEmployeeDocs()
      expect(docs.pageTitle).toBe('Test')
    })

    it('throws when bundled docs is also invalid', async () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
      // Temporarily make bundled docs invalid
      const original = mockBundledDocs.schemaVersion
      mockBundledDocs.schemaVersion = 999
      await expect(loadWorkflowEmployeeDocs()).rejects.toThrow()
      mockBundledDocs.schemaVersion = original
    })
  })

  describe('getWorkflowEmployeeDocs', () => {
    it('returns a promise', () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
      const result = getWorkflowEmployeeDocs()
      expect(result).toBeInstanceOf(Promise)
    })
  })
})
