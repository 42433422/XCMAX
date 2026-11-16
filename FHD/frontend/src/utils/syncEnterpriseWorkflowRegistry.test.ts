import { syncEnterpriseWorkflowRegistry } from './syncEnterpriseWorkflowRegistry'

const mocks = vi.hoisted(() => ({
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

vi.mock('@/api/employeeDirectory', () => ({ fetchEmployeeDirectory: mocks.fetchEmployeeDirectory }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => mocks.modsStore }))
vi.mock('@/stores/workflowAiEmployees', () => ({ useWorkflowAiEmployeesStore: () => mocks.workflowStore }))
vi.mock('@/utils/enterpriseModStackApi', () => ({ resolveEnterpriseModStack: mocks.resolveEnterpriseModStack }))

describe('syncEnterpriseWorkflowRegistry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    expect(mocks.workflowStore.loadRegistry).toHaveBeenCalledWith(directoryMods)
    expect(mocks.workflowStore.registerEmployee).toHaveBeenCalledWith(expect.objectContaining({
      id: 'label_print',
      carrierModId: 'xcagi-core-workflow-employees',
      hostModId: 'coating-industry',
    }))
    expect(mocks.workflowStore.ensureEnabledKeys).toHaveBeenCalledOnce()
  })
})
