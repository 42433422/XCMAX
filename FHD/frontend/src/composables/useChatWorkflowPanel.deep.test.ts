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
    wechat_msg: { employeeId: 'wechat_msg', label: '微信', title: '微信', summary: '微信摘要' },
    label_print: { employeeId: 'label_print', label: '标签', title: '标签', summary: '标签摘要' },
    receipt_confirm: { employeeId: 'receipt_confirm', label: '收货', title: '收货', summary: '收货摘要' },
  })),
  findWorkflowEmployeeEntry: vi.fn(() => ({ id: 'emp1' })),
  resolvePhoneAgentApiBase: vi.fn(() => ''),
  listPhoneAgentEmployeeIds: vi.fn(() => []),
  resolvePhoneChannelForEmployee: vi.fn(() => 'wechat'),
}))
const coreEmployees = new Set(['wechat_msg', 'label_print', 'shipment_mgmt', 'receipt_confirm'])

vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowEmployeeId: (id: string) => coreEmployees.has(id),
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
  buildLabelPrintHostUpdate: vi.fn(() => ({
    lastLabelPrint: { at: 1, line: 'print' },
  })),
  buildReceiptFeedbackHostUpdate: vi.fn(() => ({
    lastReceiptFeedback: { at: 1, line: '已收货', detail: '对账完成' },
    pushTitle: '客户反馈',
    pushDescription: '收到收货确认',
  })),
  buildWechatMonitorUpdate: vi.fn(),
  dispatchCoreWorkflowModRun: vi.fn(),
  runLabelPrintSideEffect: vi.fn().mockResolvedValue(undefined),
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

  it('onWechatAiTaskEnqueue upserts wechat intent task', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.onWechatAiTaskEnqueue(
      new CustomEvent('xcagi:wechat-ai-task', {
        detail: { messageText: '要5003清漆', contactName: '甲公司', contactId: 9 },
      }),
    )
    expect(deps.upsertTask).toHaveBeenCalled()
    const call = vi.mocked(deps.upsertTask).mock.calls.at(-1)?.[0] as { type?: string; title?: string }
    expect(call?.type).toBe('wechat_intent')
    expect(call?.title).toContain('甲公司')
  })

  it('onWechatAiTaskEnqueue with workflow task dispatches core ack', async () => {
    const { dispatchCoreWorkflowModRun } = await import('@/workflow/coreWorkflowDispatcher')
    const deps = makeDeps()
    deps.taskList.value = [{ id: 'workflow_emp_wechat_msg', type: 'workflow_employee', title: 'wx' }]
    const panel = useChatWorkflowPanel(deps)
    panel.onWechatAiTaskEnqueue(
      new CustomEvent('xcagi:wechat-ai-task', {
        detail: { messageText: 'hello', contactName: 'Bob', sourceApi: 'intent_test' },
      }),
    )
    expect(dispatchCoreWorkflowModRun).toHaveBeenCalled()
    expect(deps.upsertTask).toHaveBeenCalled()
  })

  it('upsertWorkflowEmployeeTask for core wechat_msg updates workflow task', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    panel.upsertWorkflowEmployeeTask('wechat_msg', {
      lastWechat: { at: Date.now(), line: '新消息' },
    })
    expect(deps.upsertTask).toHaveBeenCalled()
    const task = vi.mocked(deps.upsertTask).mock.calls.at(-1)?.[0] as { id?: string }
    expect(task?.id).toBe('workflow_emp_wechat_msg')
  })

  it('mountWorkflowPanel and unmountWorkflowPanel are idempotent', () => {
    const panel = useChatWorkflowPanel(makeDeps())
    panel.mountWorkflowPanel()
    panel.unmountWorkflowPanel()
    expect(() => panel.unmountWorkflowPanel()).not.toThrow()
  })

  it('onWechatAiTaskEnqueue ignores empty detail', () => {
    const deps = makeDeps()
    const panel = useChatWorkflowPanel(deps)
    vi.mocked(deps.upsertTask).mockClear()
    panel.onWechatAiTaskEnqueue(new CustomEvent('xcagi:wechat-ai-task', { detail: {} }))
    expect(deps.upsertTask).not.toHaveBeenCalled()
  })

  it('mountWorkflowPanel handles receipt feedback signal event', async () => {
    const { dispatchCoreWorkflowModRun } = await import('@/workflow/coreWorkflowDispatcher')
    enabledState.value = { receipt_confirm: true }
    const deps = makeDeps()
    deps.taskList.value = [{ id: 'workflow_emp_receipt_confirm', type: 'workflow_employee', title: 'rcpt' }]
    const panel = useChatWorkflowPanel(deps)
    panel.mountWorkflowPanel()
    window.dispatchEvent(
      new CustomEvent('xcagi:workflow-receipt-feedback-signal', {
        detail: { line: '已签收', contactName: '甲公司' },
      }),
    )
    expect(dispatchCoreWorkflowModRun).toHaveBeenCalled()
    expect(deps.emitAssistantPush).toHaveBeenCalled()
    panel.unmountWorkflowPanel()
  })

  it('mountWorkflowPanel label print signal when enabled', async () => {
    const { runLabelPrintSideEffect } = await import('@/workflow/coreWorkflowDispatcher')
    enabledState.value = { label_print: true }
    const deps = makeDeps()
    deps.taskList.value = [{ id: 'workflow_emp_label_print', type: 'workflow_employee', title: 'lp' }]
    const panel = useChatWorkflowPanel(deps)
    panel.mountWorkflowPanel()
    window.dispatchEvent(
      new CustomEvent('xcagi:workflow-label-print-signal', { detail: { line: '打印' } }),
    )
    await Promise.resolve()
    expect(runLabelPrintSideEffect).toHaveBeenCalled()
    panel.unmountWorkflowPanel()
  })
})
