import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const lastShipmentExecution = ref<Record<string, unknown> | null>(null)
const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
const executePrintTask = vi.fn()
const buildPrintSummaryMessage = vi.fn(() => '打印完成')
const upsertTask = vi.fn()
const handleChatRequiresToken = vi.fn()

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
  useChatHistoryPersistence: () => ({ toPlainText: (s: string) => s, isWelcomeMessage: () => false }),
  useChatTaskPanelPersistence: () => ({
    persistTaskPanelStateForSession: vi.fn(),
    applyPersistedTaskPanelStateForSession: vi.fn(),
  }),
}))
vi.mock('./useExcelAnalysis', async () => {
  const { ref } = await import('vue')
  return {
    useExcelAnalysis: () => ({
      excelAnalyzeUploading: ref(false),
      excelAnalyzeInputRef: ref(null),
      triggerUpload: vi.fn(),
      onExcelAnalyzeFileChange: vi.fn(),
      setOnMultimodalFileChangeCallback: vi.fn(),
      lastExcelAnalysisContext: ref(null),
      excelSheetOptions: ref([]),
      linkedExcelSheet: ref(''),
      linkedExcelAllSheets: ref(false),
      multimodalPendingCount: ref(0),
    }),
  }
})
vi.mock('./useShipmentTask', async () => {
  const { ref } = await import('vue')
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
vi.mock('./useChatDbTokenGate', () => ({
  useChatDbTokenGate: () => ({
    handleChatRequiresToken,
    resolveEffectiveProModeState: vi.fn(() => false),
    syncProModeState: vi.fn(),
    onDbWriteUnlockedForChatRetry: vi.fn(),
    getModeScopedUserId: vi.fn(() => 'u1'),
    resolveChatDbTokensForPayload: vi.fn(() => ({})),
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
    lastShipmentExecution.value = null
    executePrintTask.mockResolvedValue({ success: true, message: 'ok' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sendMessage start print without context replies hint', async () => {
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('开始打印')
    expect(addAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('暂无可打印'),
      'ai',
      undefined,
      expect.any(Object),
    )
    expect(executePrintTask).not.toHaveBeenCalled()
  })

  it('sendMessage start print runs executePrintTask when context exists', async () => {
    lastShipmentExecution.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
    }
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('开始打印')
    expect(executePrintTask).toHaveBeenCalled()
    expect(buildPrintSummaryMessage).toHaveBeenCalled()
  })

  it('confirmTask without api_url reports failure', async () => {
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    api.showTaskConfirm({ type: 'custom', title: 't', api_url: '', payload: {} })
    await api.confirmTask()
    expect(addAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('缺少 API'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('confirmTask POST success keeps completed task card', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, message: '执行成功' }),
      }),
    )
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    api.showTaskConfirm({
      type: 'custom',
      title: '测试任务',
      api_url: '/api/test',
      method: 'POST',
      payload: { params: {} },
    })
    await api.confirmTask()
    expect(fetch).toHaveBeenCalled()
    expect(api.currentTask.value?.completed).toBe(true)
  })

  it('confirmTask handles requires_token response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          requires_token: true,
          token_name: 'PAYMENT_TOKEN',
          message: '需要支付授权令牌',
        }),
      }),
    )
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    api.showTaskConfirm({
      type: 'custom',
      title: '支付',
      api_url: '/api/pay',
      payload: {},
    })
    await api.confirmTask()
    expect(handleChatRequiresToken).toHaveBeenCalled()
    expect(api.currentTask.value?.description).toContain('令牌')
  })
})
