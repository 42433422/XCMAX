import { directoryToWorkflowMods, syncEnterpriseWorkflowRegistry } from './syncEnterpriseWorkflowRegistry'
import { mergeModManifestEntries } from './workflowEmployeeRegistry'
import { resolveEnterpriseOrgLayer } from '@/constants/enterpriseWorkflowEstablishment'

const mocks = vi.hoisted(() => ({
  scope: 'account-a',
  fetchEmployeeDirectory: vi.fn(),
  resolveEnterpriseModStack: vi.fn(),
  modsStore: {
    entitledModIds: ['xcagi-core-workflow-employees'],
    modsForWorkflowUi: [
      {
        id: 'xcagi-core-workflow-employees',
        workflow_employees: [{ id: 'label_print', label: '标签打印' }],
      },
    ],
  },
  workflowStore: {
    hydrateFromMods: vi.fn(),
    pruneOrphanWorkflowEmployeeToggles: vi.fn(),
    loadRegistry: vi.fn(),
    registerEmployee: vi.fn(),
    ensureEnabledKeys: vi.fn(),
  },
}))

vi.mock('@/api/employeeDirectory', () => ({ fetchEmployeeDirectory: mocks.fetchEmployeeDirectory, employeeDirectoryScope: () => mocks.scope }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => mocks.modsStore }))
vi.mock('@/stores/workflowAiEmployees', () => ({ useWorkflowAiEmployeesStore: () => mocks.workflowStore }))
vi.mock('@/utils/enterpriseModStackApi', () => ({ resolveEnterpriseModStack: mocks.resolveEnterpriseModStack }))

describe('syncEnterpriseWorkflowRegistry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.scope = 'account-a'
    mocks.fetchEmployeeDirectory.mockResolvedValue([
      { pack_id: 'directory-employee', label: '目录员工', prompt_only: true },
    ])
    mocks.resolveEnterpriseModStack.mockResolvedValue({
      industryId: '涂料',
      industryModId: 'coating-industry',
      industryLabel: '涂料行业包',
      customModIds: [],
      customLabels: {},
      packageModIds: ['coating-industry'],
      hostLineModIds: [],
      stackLabel: '涂料行业包',
      stackShortLabel: '涂料行业包',
    })
    mocks.workflowStore.loadRegistry.mockResolvedValue(undefined)
  })

  it('uses the unified directory and supplements installed official carrier employees', async () => {
    await syncEnterpriseWorkflowRegistry({ forceDirectory: true })

    const directoryMods = [
      {
        id: 'directory-employee',
        directory_sourced: true,
        workflow_employees: [{ id: 'directory-employee', label: '目录员工', prompt_only: true }],
      },
    ]
    expect(mocks.fetchEmployeeDirectory).toHaveBeenCalledWith({ force: true })
    expect(mocks.workflowStore.hydrateFromMods).toHaveBeenCalledWith(directoryMods)
    expect(mocks.workflowStore.pruneOrphanWorkflowEmployeeToggles).toHaveBeenCalledWith(directoryMods)
    expect(mocks.workflowStore.loadRegistry).toHaveBeenCalledWith(directoryMods, expect.any(Function))
    expect(mocks.workflowStore.registerEmployee).toHaveBeenCalledWith(expect.objectContaining({
      id: 'label_print',
      carrierModId: 'xcagi-core-workflow-employees',
      hostModId: 'coating-industry',
    }))
    expect(mocks.workflowStore.ensureEnabledKeys).toHaveBeenCalledOnce()
  })

  it('preserves an explicit department through directory, registry and graph resolution', () => {
    const [entry] = mergeModManifestEntries({ schemaVersion: 1, employees: [] }, directoryToWorkflowMods([
      { pack_id: 'print-support', label: '打印客服', enterprise_layer: 'service' },
    ]))
    expect(resolveEnterpriseOrgLayer(entry.id, entry.label, '', entry.enterprise_layer)).toBe('service')
    expect(entry.hostModId).toBe('print-support')
  })

  it('preserves the current registry and toggles when the directory request fails', async () => {
    mocks.fetchEmployeeDirectory.mockRejectedValueOnce(new Error('network unavailable'))
    await expect(syncEnterpriseWorkflowRegistry({ forceDirectory: true })).rejects.toThrow('network unavailable')
    expect(mocks.workflowStore.hydrateFromMods).not.toHaveBeenCalled()
    expect(mocks.workflowStore.pruneOrphanWorkflowEmployeeToggles).not.toHaveBeenCalled()
    expect(mocks.workflowStore.loadRegistry).not.toHaveBeenCalled()
  })

  it('ignores a late directory response after the account changes', async () => {
    let resolve!: (rows: unknown[]) => void
    mocks.fetchEmployeeDirectory.mockReturnValueOnce(new Promise(result => { resolve = result }))
    const pending = syncEnterpriseWorkflowRegistry()
    await Promise.resolve()
    mocks.scope = 'account-b'
    resolve([{ pack_id: 'old-account-employee', label: '旧账号员工' }])
    await expect(pending).rejects.toThrow('上下文已变更')
    expect(mocks.workflowStore.loadRegistry).not.toHaveBeenCalled()
    expect(mocks.workflowStore.pruneOrphanWorkflowEmployeeToggles).not.toHaveBeenCalled()
  })
})
