import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const lastShipmentExecution = ref<Record<string, unknown> | null>(null)
const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
const executePrintTask = vi.fn()
const buildPrintSummaryMessage = vi.fn(() => '打印完成')
const upsertTask = vi.fn()
const agentRunsApiMock = vi.hoisted(() => ({
  createRun: vi.fn(),
  createTask: vi.fn(),
  continueRun: vi.fn(),
  listTasks: vi.fn(),
  listRuns: vi.fn(),
  archiveTask: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
  getRun: vi.fn(),
}))

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: vi.fn(),
      addAndSaveMessage,
      saveMessage: vi.fn(),
      pushStreamingAiShell: vi.fn(() => 0),
      applyPlainTextToMessageIndex: vi.fn(),
      clearMessages: vi.fn(),
      loadMessages: vi.fn(),
      syncFromServer: vi.fn().mockResolvedValue(undefined),
      queueVoice: vi.fn(),
      clearVoiceQueue: vi.fn(),
    }),
  }
})
vi.mock('./useChatTaskList', () => ({
  useChatTaskList: () => ({
    taskList: ref([]),
    activeTaskId: ref(''),
    expandedTaskIds: ref([]),
    taskFilter: ref('all'),
    activeTask: ref(null),
    filteredTaskList: ref([]),
    createTaskId: (p: string) => `${p}-1`,
    sortTaskList: vi.fn(),
    upsertTask,
    finishTask: vi.fn(),
    failTask: vi.fn(),
    cancelTask: vi.fn(),
    retryTask: vi.fn(),
    toggleTaskExpanded: vi.fn(),
    setTaskFilter: vi.fn(),
    clearTaskHistory: vi.fn(),
    jumpToTaskMessage: vi.fn(),
  }),
}))
vi.mock('./useChatPersistence', () => ({
  readPersistedExcelAnalysisContext: vi.fn(() => null),
  persistExcelAnalysisContext: vi.fn(),
  resolveExcelFilePathFromAnalysis: vi.fn(),
  resolveExcelSheetOptionsFromContext: vi.fn(() => []),
  extractLikelyProductQueryKeyword: vi.fn(() => null),
  clearPersistedTaskPanelState: vi.fn(),
  useChatHistoryPersistence: () => ({
    toPlainText: (s: string) => s,
    isWelcomeMessage: () => false,
  }),
  useChatTaskPanelPersistence: () => ({
    persistTaskPanelStateForSession: vi.fn(),
    applyPersistedTaskPanelStateForSession: vi.fn(),
  }),
}))
vi.mock('./useShipmentTask', async () => {
  return {
    useShipmentTask: () => ({
      lastShipmentExecution,
      handleModifyCommand: vi.fn(),
      hydrateTaskOrderNumber: vi.fn(),
      enrichShipmentPreviewProducts: vi.fn(),
      getTaskTableColumns: vi.fn(() => []),
      getTaskTableItems: vi.fn(() => []),
      getTaskOrderNumber: vi.fn(() => ''),
      showTaskConfirm: vi.fn(),
      confirmTask: vi.fn(),
      cancelTask: vi.fn(),
      refetchTaskOrderNumber: vi.fn(),
      handleShipmentDownloadClick: vi.fn(),
      startPrintFromTaskCard: vi.fn(),
      handleAutoAction: vi.fn(),
    }),
  }
})
vi.mock('./usePrintService', async () => {
  const { ref } = await import('vue')
  return {
    usePrintService: () => ({
      isPrinting: ref(false),
      executePrintTask,
      buildPrintSummaryMessage,
    }),
  }
})
vi.mock('./useChatWorkflowPanel', () => ({
  useChatWorkflowPanel: () => ({
    registerWorkflowPanelWatchers: vi.fn(),
    mountWorkflowPanel: vi.fn(),
    unmountWorkflowPanel: vi.fn(),
    readWorkflowEmployeeEnabledMap: vi.fn(() => ({ shipment_mgmt: false })),
    upsertWorkflowEmployeeTask: vi.fn(),
  }),
}))
vi.mock('./useChatExcelContext', () => ({
  useChatExcelContext: () => ({
    bindExcelSheetToChat: vi.fn(),
    bindAllExcelSheetsToChat: vi.fn(),
    resolveExcelAnalysisContextForRequest: vi.fn(() => null),
    lastExcelAnalysisContext: ref(null),
    linkedExcelSheet: ref(''),
    linkedExcelAllSheets: ref(false),
    multimodalStaging: ref([]),
    multimodalPendingCount: ref(0),
    excelSheetOptions: ref([]),
    injectExcelContextPayload: vi.fn((p: unknown) => p),
    consumeMultimodalIntoPlannerContext: vi.fn(),
    onMultimodalFileChange: vi.fn(),
  }),
}))
vi.mock('./useChatRequest', () => ({
  useChatRequest: () => ({
    loadingProgressText: ref(''),
    chatBatchQueue: ref([]),
    enqueueChatBatchMessage: vi.fn(),
    buildPlannerChatRequestPayload: vi.fn(() => ({ body: {} })),
    requestChatByMode: vi.fn(),
    requestChatByModeBatch: vi.fn(),
    getChatBatchDebounceMs: () => 0,
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    stopLoadingProgress: vi.fn(),
    requestChatByModeWithTimeout: vi.fn(),
    requestChatByModeBatchWithTimeout: vi.fn(),
    resolveChatTimeoutMs: () => 30_000,
  }),
}))
vi.mock('./useChatResponseAttach', () => ({
  useChatResponseAttach: () => ({
    getLastAiMessageRef: vi.fn(() => '0'),
    attachThinkingStepsToLastAiMessage: vi.fn(),
    attachTodoStepsToLastAiMessage: vi.fn(),
    attachWorkflowTraceToLastAiMessage: vi.fn(),
    attachApprovalCardToLastAiMessage: vi.fn(),
    attachBusinessResultToLastAiMessage: vi.fn(),
    attachContextSummaryToLastAiMessage: vi.fn(),
    syncTaskFromChatResponse: vi.fn(),
  }),
}))
vi.mock('./useChatSessionHistory', () => ({
  useChatSessionHistory: () => ({
    showHistory: ref(false),
    historySessions: ref([]),
    historyLoading: ref(false),
    historyError: ref(''),
    refreshHistorySessions: vi.fn(),
    showHistoryPanel: vi.fn(),
    loadSession: vi.fn(),
    clearHistorySessions: vi.fn(),
    newConversation: vi.fn(),
    registerHistoryModWatch: vi.fn(),
    generateSessionId: () => 'gen-sid',
  }),
}))
vi.mock('@/stores/tutorial', () => ({ useTutorialStore: () => ({}) }))
vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({ activeModId: '', mods: [], modsForUi: [], setActiveModId: vi.fn() }),
}))
vi.mock('@/api/chat', () => ({ default: {}, parseChatStreamErrorResponse: vi.fn() }))
vi.mock('@/api/agentRuns', () => ({ default: agentRunsApiMock }))
vi.mock('@/api/products', () => ({ default: { searchProducts: vi.fn() } }))
vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: vi.fn(),
  isChatStreamEnabled: () => false,
}))
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({
  fetchShipmentRecordsForUnit: vi.fn(),
  summarizeShipmentRecordsForAudit: vi.fn().mockResolvedValue('audit ok'),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({ dispatchCoreWorkflowModRun: vi.fn() }))
vi.mock('@/constants/coreWorkflowMod', () => ({ isCoreWorkflowModInstalled: () => false }))

import { useChatOrchestration } from './useChatOrchestration'

describe('useChatOrchestration task/print', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    lastShipmentExecution.value = null
    executePrintTask.mockResolvedValue({ success: true, message: 'ok' })
    agentRunsApiMock.listRuns.mockResolvedValue({ success: true, data: [] })
    agentRunsApiMock.listTasks.mockResolvedValue({ success: true, data: [] })
    agentRunsApiMock.createTask.mockReset()
    agentRunsApiMock.getRun.mockReset()
    agentRunsApiMock.continueRun.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sendMessage start print without context replies hint', async () => {
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('开始打印')
    expect(addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('暂无可打印'), 'ai', undefined, expect.any(Object))
    expect(executePrintTask).not.toHaveBeenCalled()
  })

  it('routes the seeded first AI order through a bound durable AgentRun', async () => {
    const { queueFirstAiTaskPrompt, readPendingFirstAiTaskRunId } = await import('@/constants/productFlow')
    const prompt = '这是我的新手第一单：先查询“XC 演示客户”，再查询“XC 演示饰品包装品”，最后创建数量 1 的演示出货单。'
    queueFirstAiTaskPrompt(prompt)
    agentRunsApiMock.createRun.mockResolvedValue({
      success: true,
      data: {
        run_id: 'run-onboarding-1',
        user_id: 'u1',
        message: prompt,
        status: 'queued',
        intent: 'onboarding_first_order',
      },
    })

    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage(prompt)

    expect(agentRunsApiMock.createRun).toHaveBeenCalledWith({
      message: prompt,
      auto_execute: true,
      runtime_context: {
        conversation_id: 's',
        source: 'product_onboarding_first_order',
      },
    })
    expect(readPendingFirstAiTaskRunId()).toBe('run-onboarding-1')
    expect(addAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('任务工作区'),
      'ai',
      undefined,
      { sessionId: 's', speak: true },
    )
  })

  it('keeps the first AI order pending when durable creation fails', async () => {
    const { isFirstAiTaskPending, queueFirstAiTaskPrompt, readPendingFirstAiTaskRunId } = await import(
      '@/constants/productFlow'
    )
    const prompt = '这是我的新手第一单，请创建演示出货单'
    queueFirstAiTaskPrompt(prompt)
    agentRunsApiMock.createRun.mockRejectedValue(new Error('runtime offline'))

    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage(prompt)

    expect(isFirstAiTaskPending()).toBe(true)
    expect(readPendingFirstAiTaskRunId()).toBe('')
    expect(addAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('runtime offline'),
      'ai',
      undefined,
      { sessionId: 's', speak: true },
    )
  })

  it('sendMessage start print runs executePrintTask when context exists', async () => {
    lastShipmentExecution.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
    }
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('开始打印')
    expect(executePrintTask).toHaveBeenCalled()
    expect(buildPrintSummaryMessage).toHaveBeenCalled()
  })

  it.each(['GET', 'POST'])('rejects an API-only %s task before any HTTP effect', async method => {
    const legacyFetch = vi.fn()
    vi.stubGlobal('fetch', legacyFetch)
    const api = useChatOrchestration({ sessionId: ref('s') })
    api.showTaskConfirm({ type: 'shipment_generate', title: 't', api_url: '/api/retired-write', method, payload: {} })
    await api.confirmTask()
    expect(addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('缺少有效能力契约'), 'ai', { workflowAction: 'not_started' }, expect.any(Object))
    expect(api.currentTask.value).toMatchObject({ completed: false, data: { execution_state: 'not_started' } })
    expect(legacyFetch).not.toHaveBeenCalled()
    expect(agentRunsApiMock.createTask).not.toHaveBeenCalled()
    expect(agentRunsApiMock.getRun).not.toHaveBeenCalled()
    expect(agentRunsApiMock.continueRun).not.toHaveBeenCalled()
  })

  it('keeps a completed canonical receipt without using the legacy URL', async () => {
    const legacyFetch = vi.fn()
    vi.stubGlobal('fetch', legacyFetch)
    const receipt = { success: true, data: {
      run_id: 'read-run', status: 'completed',
      final_output: { node_outputs: { read: { success: true, message: '执行成功' } } },
    } }
    agentRunsApiMock.createTask.mockResolvedValue(receipt)
    agentRunsApiMock.getRun.mockResolvedValue(receipt)
    const api = useChatOrchestration({ sessionId: ref('s') })
    api.showTaskConfirm({
      type: 'custom',
      title: '测试任务',
      api_url: '/api/test',
      method: 'POST',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'customers' } },
    })
    await api.confirmTask()
    expect(legacyFetch).not.toHaveBeenCalled()
    expect(agentRunsApiMock.createTask).toHaveBeenCalledTimes(1)
    expect(api.currentTask.value?.completed).toBe(true)
  })

  it.each(['waiting_auth', 'unknown'])('keeps a legacy %s receipt without a second POST on confirmation or unlock', async state => {
    vi.stubGlobal('fetch', vi.fn())
    const api = useChatOrchestration({ sessionId: ref('s') })
    api.showTaskConfirm({
      type: 'custom',
      title: '支付',
      api_url: '/api/pay',
      description: state === 'unknown' ? '原任务结果待核对' : '需要支付授权令牌',
      completed: false,
      data: { requires_token: true, execution_state: state },
      payload: {},
    })
    await api.confirmTask()
    expect(api.currentTask.value?.description).toContain(state === 'unknown' ? '待核对' : '令牌')
    expect(api.currentTask.value?.description).not.toContain('已弹出')
    expect(api.currentTask.value?.completed).toBe(false)
    expect(api.currentTask.value?.data?.execution_state).toBe(state)
    window.dispatchEvent(new CustomEvent('fhd-db-write-unlocked'))
    await api.confirmTask()
    expect(fetch).not.toHaveBeenCalled()
    expect(agentRunsApiMock.createTask).not.toHaveBeenCalled()
    expect(agentRunsApiMock.continueRun).not.toHaveBeenCalled()
    expect(addAndSaveMessage).toHaveBeenLastCalledWith(expect.any(String), 'ai', { workflowAction: state }, expect.any(Object))
  })

  it('reads an existing run without a capability contract but cannot approve or create it', async () => {
    const legacyFetch = vi.fn()
    vi.stubGlobal('fetch', legacyFetch)
    agentRunsApiMock.getRun.mockResolvedValue({
      success: true, data: { run_id: 'original-run', status: 'waiting_user' },
      approval: { grant: 'original-grant' },
    })
    const api = useChatOrchestration({ sessionId: ref('s') })
    api.showTaskConfirm({
      type: 'custom', title: '原任务', agentRunId: 'original-run', agentTaskId: 'original-task',
      data: { requires_token: true }, api_url: '/api/retired-write', payload: {},
    })
    await api.confirmTask()
    expect(agentRunsApiMock.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(agentRunsApiMock.continueRun).not.toHaveBeenCalled()
    expect(agentRunsApiMock.createTask).not.toHaveBeenCalled()
    expect(legacyFetch).not.toHaveBeenCalled()
    expect(api.currentTask.value?.completed).toBe(false)
  })

  it('allows a waiting card to query and approve its existing run with the real grant', async () => {
    const legacyFetch = vi.fn()
    vi.stubGlobal('fetch', legacyFetch)
    const waiting = {
      success: true, data: { run_id: 'original-run', status: 'waiting_user' },
      approval: { grant: 'original-grant' },
    }
    agentRunsApiMock.getRun.mockResolvedValue(waiting)
    agentRunsApiMock.createTask.mockResolvedValue({ ...waiting, deduplicated: true })
    agentRunsApiMock.continueRun.mockResolvedValue({
      success: true, data: {
        run_id: 'original-run', status: 'completed',
        final_output: { node_outputs: { write: { success: true, message: '原任务已完成' } } },
      },
    })
    const api = useChatOrchestration({ sessionId: ref('s') })
    api.showTaskConfirm({
      type: 'custom', title: '原任务', agentRunId: 'original-run', agentTaskId: 'original-task',
      data: { requires_token: true }, api_url: '/api/retired-write',
      payload: { tool_id: 'business_db', action: 'write', params: {} },
    })
    await api.confirmTask()
    expect(agentRunsApiMock.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(agentRunsApiMock.continueRun).toHaveBeenCalledExactlyOnceWith('original-run', {
      approval_grant: 'original-grant', runtime_context: { source: 'chat_task_card_approval' },
    })
    expect(agentRunsApiMock.createTask).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      task_id: 'original-task', tool_id: 'business_db', action: 'write', params: {},
    }))
    expect(legacyFetch).not.toHaveBeenCalled()
    expect(api.currentTask.value?.completed).toBe(true)
  })

  it('routes a registered task through durable creation and bound approval', async () => {
    const legacyFetch = vi.fn()
    vi.stubGlobal('fetch', legacyFetch)
    agentRunsApiMock.createTask.mockResolvedValue({
      success: true,
      data: { run_id: 'run-1', user_id: 'u1', message: '发货', status: 'waiting_user' },
      approval: { grant: 'grant-1' },
    })
    agentRunsApiMock.continueRun.mockResolvedValue({
      success: true,
      data: {
        run_id: 'run-1',
        user_id: 'u1',
        message: '发货',
        status: 'completed',
        final_output: {
          node_outputs: {
            shipment: { success: true, message: '发货单已生成', order_id: 41 },
          },
        },
      },
    })
    const api = useChatOrchestration({
      sessionId: ref('s'),
      proIntentExperienceEnabled: ref(false),
    })
    api.showTaskConfirm({
      type: 'shipment_generate',
      title: '发货单预览',
      order_number: 'ORD-001',
      api_url: '/api/tools/execute',
      payload: {
        tool_id: 'shipment_orders',
        action: 'generate',
        params: { unit_name: '客户甲', products: [{ quantity: 1 }] },
      },
    })

    await api.confirmTask()

    expect(agentRunsApiMock.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: 'chat_task-1',
        tool_id: 'shipment_orders',
        action: 'generate',
        params: expect.objectContaining({ order_number: 'ORD-001' }),
      }),
    )
    expect(agentRunsApiMock.continueRun).toHaveBeenCalledWith('run-1', {
      approval_grant: 'grant-1',
      runtime_context: { source: 'chat_task_card_approval' },
    })
    expect(legacyFetch).not.toHaveBeenCalled()
    expect(api.currentTask.value?.completed).toBe(true)
  })
})
