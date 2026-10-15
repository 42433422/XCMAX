/**
 * useWorkflowPanelEvents 专属确定性单测。
 *
 * 此前该组合式函数只被父级 useChatWorkflowPanel / 视图测试间接覆盖，
 * 事件回调是否被执行取决于父测试的时序，导致全局 functions 覆盖率在
 * 90% 门禁线附近抖动（2026-09-06 CI 实测 main 90.01↔90.03、PR 89.99）。
 * 这里用受控 deps + window 事件把全部回调钉住，不再依赖父级链路。
 */
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { nextTick, reactive, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'

const dispatchCoreWorkflowModRun = vi.fn()
const runLabelPrintSideEffect = vi.fn(async () => {})
const buildLabelPrintHostUpdate = vi.fn(() => ({ lastLabelPrint: { at: 1, line: 'lp' } }))
const buildReceiptFeedbackHostUpdate = vi.fn(() => ({
  lastReceiptFeedback: { at: 2, line: 'rc', detail: 'd' },
  pushTitle: '收货反馈',
  pushDescription: '已写入收货确认',
}))
const buildWechatMonitorUpdate = vi.fn(() => ({ lastWechat: { at: 3, line: 'wm' } }))

vi.mock('@/workflow/coreWorkflowDispatcher', () => ({
  dispatchCoreWorkflowModRun: (...args: unknown[]) => dispatchCoreWorkflowModRun(...args),
  runLabelPrintSideEffect: (...args: unknown[]) => runLabelPrintSideEffect(...args),
  buildLabelPrintHostUpdate: (...args: unknown[]) => buildLabelPrintHostUpdate(...args),
  buildReceiptFeedbackHostUpdate: (...args: unknown[]) => buildReceiptFeedbackHostUpdate(...args),
  buildWechatMonitorUpdate: (...args: unknown[]) => buildWechatMonitorUpdate(...args),
}))

vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowModInstalled: vi.fn(() => true),
}))

const STORAGE_KEY = 'xcagi_workflow_ai_employees_test'
vi.mock('@/stores/workflowAiEmployees', () => ({
  workflowAiEmployeesStorageKey: () => STORAGE_KEY,
}))

import { useWorkflowPanelEvents, type WorkflowPanelEventsDeps } from './useWorkflowPanelEvents'
import type { TaskItem } from '../useChatPersistence'

function makeDeps(overrides?: Partial<WorkflowPanelEventsDeps>) {
  const taskList = ref<TaskItem[]>([])
  const modsStore = reactive({
    modsForUi: [] as Array<{ id?: string }>,
    modsForWorkflowUi: [] as Array<{ id?: string }>,
  })
  const workflowAiEmployeesStore = reactive({
    enabled: {} as Record<string, boolean>,
    reloadFromLocalStorage: vi.fn(),
    hydrateFromMods: vi.fn(),
    pruneOrphanWorkflowEmployeeToggles: vi.fn(),
  })
  const deps: WorkflowPanelEventsDeps = {
    taskList,
    activeTaskId: ref(''),
    expandedTaskIds: ref<string[]>([]),
    taskFilter: ref('all') as WorkflowPanelEventsDeps['taskFilter'],
    upsertTask: vi.fn(),
    createTaskId: (prefix: string) => `${prefix}_1`,
    showTaskConfirm: vi.fn(),
    emitAssistantPush: vi.fn(),
    maybeCloseAssistantFloatForShipmentTask: vi.fn(),
    modsStore: modsStore as unknown as WorkflowPanelEventsDeps['modsStore'],
    workflowAiEmployeesStore:
      workflowAiEmployeesStore as unknown as WorkflowPanelEventsDeps['workflowAiEmployeesStore'],
    readWorkflowEmployeeEnabledMap: vi.fn(() => ({ label_print: true, receipt_confirm: true, wechat_msg: true })),
    upsertWorkflowEmployeeTask: vi.fn(),
    syncWorkflowEmployeePanelTasks: vi.fn(),
    resyncEnabledWorkflowEmployeeTasks: vi.fn(),
    stopPhoneAgentStatusPoll: vi.fn(),
    ...overrides,
  }
  return { deps, taskList, modsStore, workflowAiEmployeesStore }
}

function dispatch(name: string, detail: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

const mounted: Array<ReturnType<typeof useWorkflowPanelEvents>> = []

function mountedApi(deps: WorkflowPanelEventsDeps) {
  const api = useWorkflowPanelEvents(deps)
  api.mountWorkflowPanel()
  mounted.push(api)
  return api
}

describe('useWorkflowPanelEvents', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmountWorkflowPanel()
    vi.useRealTimers()
  })

  it('mount 注册全部监听并做面板兜底同步；unmount 停轮询', () => {
    const { deps } = makeDeps()
    const api = mountedApi(deps)
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(200) // mount 的 120ms storage 兜底
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenCalledTimes(2)
    api.unmountWorkflowPanel()
    expect(deps.stopPhoneAgentStatusPoll).toHaveBeenCalledTimes(1)
  })

  it('微信 AI 任务入队：写任务卡；命中常驻微信员工时追加工作流回执', () => {
    const { deps, taskList } = makeDeps()
    taskList.value = [{ id: 'workflow_emp_wechat_msg' } as TaskItem]
    mountedApi(deps)
    dispatch('xcagi:wechat-ai-task-enqueue', {
      messageText: '  你好  ',
      contactId: 'c1',
      contactName: ' 李雷 ',
      intentLabel: '查订单',
      intentDetail: '明细',
      primaryIntent: 'order_query',
      toolKey: 'erp',
      sourceApi: 'intent_test',
    })
    const card = vi.mocked(deps.upsertTask).mock.calls[0][0]
    expect(card.id).toBe('wechat_ai_1')
    expect(card.title).toContain('李雷')
    expect(card.summary).toContain('最新消息：你好')
    expect(card.summary).toContain('primary_intent：order_query')
    expect(card.stage).toBe('专业模式·意图 API')
    expect(deps.upsertWorkflowEmployeeTask).toHaveBeenCalledWith(
      'wechat_msg',
      expect.objectContaining({ lastWechat: expect.objectContaining({ line: '李雷：你好' }) }),
    )
    expect(dispatchCoreWorkflowModRun).toHaveBeenCalled()
  })

  it('微信 AI 任务入队：空消息且无联系人直接忽略', () => {
    const { deps } = makeDeps()
    mountedApi(deps)
    dispatch('xcagi:wechat-ai-task-enqueue', {})
    expect(deps.upsertTask).not.toHaveBeenCalled()
  })

  it('微信发货单预览：组装标题与提示后弹确认、关浮层并推送', () => {
    const { deps } = makeDeps()
    mountedApi(deps)
    dispatch('xcagi:wechat-shipment-preview-task', {
      task: { type: 'shipment_generate', title: '发货单', description: '明细', payload: { a: 1 } },
      contactName: '韩梅梅',
      contactId: 'c2',
      messageText: '帮我开单',
    })
    const confirmed = vi.mocked(deps.showTaskConfirm).mock.calls[0][0]
    expect(confirmed.title).toContain('韩梅梅')
    expect(String(confirmed.description)).toContain('再加 / 删除第几行')
    expect(confirmed.payload.wechat_preview_source).toMatchObject({ contactName: '韩梅梅' })
    expect(deps.maybeCloseAssistantFloatForShipmentTask).toHaveBeenCalledTimes(1)
    expect(deps.emitAssistantPush).toHaveBeenCalledWith(expect.objectContaining({ title: '微信发货单预览' }))
  })

  it('微信发货单预览：非发货类型忽略', () => {
    const { deps } = makeDeps()
    mountedApi(deps)
    dispatch('xcagi:wechat-shipment-preview-task', { task: { type: 'other' } })
    expect(deps.showTaskConfirm).not.toHaveBeenCalled()
  })

  it('标签打印信号：已启用且面板有常驻项时分发并触发副作用', async () => {
    const { deps, taskList } = makeDeps()
    taskList.value = [{ id: 'workflow_emp_label_print' } as TaskItem]
    mountedApi(deps)
    dispatch('xcagi:workflow-label-print-signal', { line: '打印' })
    await flushPromises()
    expect(deps.upsertWorkflowEmployeeTask).toHaveBeenCalledWith('label_print', expect.anything())
    expect(runLabelPrintSideEffect).toHaveBeenCalledWith(expect.objectContaining({ line: '打印' }))
  })

  it('标签打印信号：未启用或无常驻项时短路', async () => {
    const { deps } = makeDeps()
    deps.readWorkflowEmployeeEnabledMap = () => ({ label_print: false })
    mountedApi(deps)
    dispatch('xcagi:workflow-label-print-signal', {})
    await flushPromises()
    expect(deps.upsertWorkflowEmployeeTask).not.toHaveBeenCalled()
  })

  it('收货反馈信号：写工作流回执并推送助手消息', () => {
    const { deps, taskList } = makeDeps()
    taskList.value = [{ id: 'workflow_emp_receipt_confirm' } as TaskItem]
    mountedApi(deps)
    dispatch('xcagi:workflow-receipt-feedback-signal', { line: '签收' })
    expect(deps.upsertWorkflowEmployeeTask).toHaveBeenCalledWith(
      'receipt_confirm',
      expect.objectContaining({ lastReceiptFeedback: expect.objectContaining({ line: 'rc' }) }),
    )
    expect(deps.emitAssistantPush).toHaveBeenCalledWith(
      expect.objectContaining({ title: '收货反馈', feature: 'assistant' }),
    )
  })

  it('星标轮询：已启用微信员工时写监控回执；未启用时短路', () => {
    const { deps, taskList } = makeDeps()
    taskList.value = [{ id: 'workflow_emp_wechat_msg' } as TaskItem]
    mountedApi(deps)
    dispatch('xcagi:wechat-star-feed-polled', { line: 'feed' })
    expect(deps.upsertWorkflowEmployeeTask).toHaveBeenCalledWith('wechat_msg', expect.anything())

    const { deps: deps2 } = makeDeps()
    deps2.readWorkflowEmployeeEnabledMap = () => ({ wechat_msg: false })
    mountedApi(deps2)
    dispatch('xcagi:wechat-star-feed-polled', {})
    expect(deps2.upsertWorkflowEmployeeTask).not.toHaveBeenCalled()
  })

  it('员工开关变更事件：带 enabled 用事件值，否则读本地映射', () => {
    const { deps } = makeDeps()
    mountedApi(deps)
    dispatch('xcagi:workflow-ai-employees-changed', { enabled: { wechat_msg: true } })
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenLastCalledWith({ wechat_msg: true })
    dispatch('xcagi:workflow-ai-employees-changed', {})
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenLastCalledWith({
      label_print: true,
      receipt_confirm: true,
      wechat_msg: true,
    })
  })

  it('storage 事件：仅处理员工开关 key，并刷新 store 与面板', () => {
    const { deps, workflowAiEmployeesStore } = makeDeps()
    mountedApi(deps)
    window.dispatchEvent(new StorageEvent('storage', { key: 'other_key' }))
    expect(workflowAiEmployeesStore.reloadFromLocalStorage).not.toHaveBeenCalled()
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }))
    expect(workflowAiEmployeesStore.reloadFromLocalStorage).toHaveBeenCalledTimes(1)
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenCalled()
  })

  it('focus / visibilitychange / auto-refresh 事件触发兜底重同步', () => {
    const { deps } = makeDeps()
    mountedApi(deps)
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange')) // jsdom 默认 visible
    dispatch('xcagi:auto-refresh-wechat-changed', {})
    expect(deps.resyncEnabledWorkflowEmployeeTasks).toHaveBeenCalledTimes(1)
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenCalled() // mount + focus 兜底
  })

  it('面板 watcher：任务面板状态持久化 + mods/开关变化重同步', async () => {
    const { deps, taskList, modsStore, workflowAiEmployeesStore } = makeDeps()
    const persist = vi.fn()
    const currentTask = ref(null)
    useWorkflowPanelEvents(deps).registerWorkflowPanelWatchers(persist, currentTask)
    taskList.value = [{ id: 't1' } as TaskItem]
    await nextTick()
    expect(persist).toHaveBeenCalled()

    modsStore.modsForWorkflowUi = [{ id: 'xcagi-core-workflow-employees' }]
    await nextTick()
    expect(workflowAiEmployeesStore.hydrateFromMods).toHaveBeenCalled()
    expect(workflowAiEmployeesStore.pruneOrphanWorkflowEmployeeToggles).toHaveBeenCalled()

    workflowAiEmployeesStore.enabled = { wechat_msg: true }
    await nextTick()
    // enabled watcher 触发后从 storage 映射重同步（实现语义如此）
    expect(deps.syncWorkflowEmployeePanelTasks).toHaveBeenLastCalledWith({
      label_print: true,
      receipt_confirm: true,
      wechat_msg: true,
    })
  })
})
