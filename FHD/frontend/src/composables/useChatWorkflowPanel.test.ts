import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { apiFetch } from '@/utils/apiBase'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'

const enabledState = ref<Record<string, boolean>>({})

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    modsForWorkflowUi: [],
    modsForUi: [],
    activeModId: '',
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
  buildModWorkflowPanelMeta: vi.fn(() => ({})),
  findWorkflowEmployeeEntry: vi.fn(),
  resolvePhoneAgentApiBase: vi.fn(() => ''),
  listPhoneAgentEmployeeIds: vi.fn(() => []),
  resolvePhoneChannelForEmployee: vi.fn(() => 'wechat'),
}))

vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowEmployeeId: () => false,
  isCoreWorkflowModInstalled: () => false,
}))

vi.mock('@/workflow/coreWorkflowMonitor', () => ({
  appendCoreWorkflowSummaryParts: vi.fn(),
  buildCoreWorkflowMonitorLine: vi.fn(),
  buildCoreWorkflowStepsForEmployee: vi.fn(() => []),
  computeCoreWorkflowCurrentHint: vi.fn(),
  computeCoreWorkflowProgressState: vi.fn(),
  computeCoreWorkflowStageLine: vi.fn(),
  computeWorkflowProgressFromSteps: vi.fn(() => 0),
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

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
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
    createTaskId: (prefix: string) => `${prefix}-${Date.now()}`,
    persistTaskPanelStateForSession: vi.fn(),
    showTaskConfirm: vi.fn(),
    emitAssistantPush: vi.fn(),
    maybeCloseAssistantFloatForShipmentTask: vi.fn(),
  }
}

describe('useChatWorkflowPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    enabledState.value = {}
    localStorage.clear()
  })

  it('returns workflow panel API', () => {
    const panel = useChatWorkflowPanel(makeDeps())
    expect(typeof panel.mountWorkflowPanel).toBe('function')
    expect(typeof panel.unmountWorkflowPanel).toBe('function')
    expect(typeof panel.onWechatAiTaskEnqueue).toBe('function')
  })

  it('onWechatAiTaskEnqueue creates task from custom event', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.onWechatAiTaskEnqueue(
      new CustomEvent('xcagi:wechat-ai-task-enqueue', {
        detail: { messageText: '你好', contactId: 'c1' },
      }),
    )
    expect(deps.upsertTask).toHaveBeenCalled()
  })

  it('onWechatAiTaskEnqueue ignores empty detail', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.onWechatAiTaskEnqueue(new CustomEvent('xcagi:wechat-ai-task-enqueue', { detail: {} }))
    expect(deps.upsertTask).not.toHaveBeenCalled()
  })

  it('mount and unmount register window listeners', () => {
    const panel = useChatWorkflowPanel(makeDeps())
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    panel.mountWorkflowPanel()
    expect(addSpy).toHaveBeenCalledWith('xcagi:wechat-ai-task-enqueue', expect.any(Function))
    panel.unmountWorkflowPanel()
    expect(removeSpy).toHaveBeenCalledWith('xcagi:wechat-ai-task-enqueue', expect.any(Function))
    addSpy.mockRestore()
    removeSpy.mockRestore()
  })

  it('readWorkflowEmployeeEnabledMap reads store enabled map', () => {
    enabledState.value = { emp1: true }
    const panel = useChatWorkflowPanel(makeDeps())
    const map = panel.readWorkflowEmployeeEnabledMap()
    expect(map.emp1).toBe(true)
  })

  it('syncWorkflowEmployeePanelTasks no-ops when empty meta', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.syncWorkflowEmployeePanelTasks({})
    expect(deps.upsertTask).not.toHaveBeenCalled()
  })

  it('starts phone-agent through apiFetch so mutation requests receive CSRF handling', async () => {
    const workflowEmployees = await import('@/utils/modWorkflowEmployees')
    vi.mocked(workflowEmployees.buildModWorkflowPanelMeta).mockReturnValue({
      phone: { employeeId: 'phone', label: '电话员工', title: '电话员工', summary: '待命' },
    } as never)
    vi.mocked(workflowEmployees.findWorkflowEmployeeEntry).mockReturnValue({
      id: 'phone',
      modId: 'phone-mod',
    } as never)
    vi.mocked(workflowEmployees.resolvePhoneAgentApiBase).mockReturnValue('/api/mod/phone/phone-agent')
    vi.mocked(workflowEmployees.listPhoneAgentEmployeeIds).mockReturnValue(['phone'] as never)
    vi.mocked(workflowEmployees.resolvePhoneChannelForEmployee).mockReturnValue('wechat')
    enabledState.value = { phone: true }

    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ success: true }),
    } as Response)
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: { running: true } }),
    } as Response)

    const panel = useChatWorkflowPanel(makeDeps())
    panel.mountWorkflowPanel()
    await vi.waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith('/api/mod/phone/phone-agent/start?channel=wechat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: 'wechat' }),
      })
    })
    await vi.waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith('/api/mod/phone/phone-agent/status?channel=wechat')
    })
    panel.unmountWorkflowPanel()
    fetchSpy.mockRestore()
  })
})
