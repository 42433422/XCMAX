import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'

const enabledState = ref<Record<string, boolean>>({})

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    modsForWorkflowUi: [{ id: 'emp1', name: '员工1' }],
    modsForUi: [{ id: 'mod1' }],
    activeModId: 'mod1',
  }),
}))
vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    get enabled() {
      return enabledState.value
    },
    hydrateFromMods: vi.fn(),
    pruneOrphanWorkflowEmployeeToggles: vi.fn(),
    reloadFromLocalStorage: vi.fn(),
  }),
  workflowAiEmployeesStorageKey: () => 'xcagi_workflow_ai_employees',
}))
vi.mock('@/utils/modWorkflowEmployees', () => ({
  buildModWorkflowPanelMeta: vi.fn(() => ({
    emp1: { employeeId: 'emp1', label: '员工1', title: '员工1', summary: '摘要' },
  })),
  findWorkflowEmployeeEntry: vi.fn(() => ({ id: 'emp1' })),
  resolvePhoneAgentApiBase: vi.fn(() => ''),
  listPhoneAgentEmployeeIds: vi.fn(() => []),
  resolvePhoneChannelForEmployee: vi.fn(() => 'wechat'),
}))
vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowEmployeeId: () => false,
  isCoreWorkflowModInstalled: () => true,
}))
vi.mock('@/workflow/coreWorkflowMonitor', () => ({
  appendCoreWorkflowSummaryParts: vi.fn(),
  buildCoreWorkflowMonitorLine: vi.fn(() => 'monitor'),
  buildCoreWorkflowStepsForEmployee: vi.fn(() => [{ id: 's1', label: 'step', status: 'done' }]),
  computeCoreWorkflowCurrentHint: vi.fn(() => 'hint'),
  computeCoreWorkflowProgressState: vi.fn(() => ({ progressPct: 50, progressLabel: '1/2', workflowProgressStarted: true })),
  computeCoreWorkflowStageLine: vi.fn(() => 'stage'),
  computeWorkflowProgressFromSteps: vi.fn(() => ({ pct: 50, label: '1/2' })),
  mergeCorePayloadFromExisting: vi.fn((a) => a),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({
  buildLabelPrintHostUpdate: vi.fn(),
  buildReceiptFeedbackHostUpdate: vi.fn(),
  buildWechatMonitorUpdate: vi.fn(),
  dispatchCoreWorkflowModRun: vi.fn(),
  runLabelPrintSideEffect: vi.fn(),
}))
vi.mock('@/workflow/coreWorkflowPrefs', () => ({
  formatWorkflowClock: (n: number) => String(n),
}))

function makeDeps() {
  return {
    taskList: ref([]),
    activeTaskId: ref(''),
    expandedTaskIds: ref<string[]>([]),
    taskFilter: ref<'all' | 'running' | 'success' | 'failed'>('all'),
    currentTask: ref(null),
    upsertTask: vi.fn(),
    sortTaskList: vi.fn(),
    createTaskId: (prefix: string) => `${prefix}-1`,
    persistTaskPanelStateForSession: vi.fn(),
    showTaskConfirm: vi.fn(),
    emitAssistantPush: vi.fn(),
    maybeCloseAssistantFloatForShipmentTask: vi.fn(),
  }
}

describe('useChatWorkflowPanel deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    enabledState.value = { emp1: true }
    localStorage.clear()
  })

  it('registerWorkflowPanelWatchers is callable', () => {
    const panel = useChatWorkflowPanel(makeDeps())
    expect(() => panel.registerWorkflowPanelWatchers()).not.toThrow()
  })

  it('upsertWorkflowEmployeeTask creates task entry', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.upsertWorkflowEmployeeTask('emp1')
    expect(deps.upsertTask).toHaveBeenCalled()
  })

  it('syncWorkflowEmployeePanelTasks with meta upserts tasks', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.syncWorkflowEmployeePanelTasks({
      emp1: { employeeId: 'emp1', label: '员工1', tasks: [{ id: 't1', title: 'T1' }] },
    })
    expect(deps.upsertTask).toHaveBeenCalled()
  })

  it('readWorkflowEmployeeEnabledMap returns enabled snapshot', () => {
    const panel = useChatWorkflowPanel(makeDeps())
    expect(panel.readWorkflowEmployeeEnabledMap().emp1).toBe(true)
  })
})
