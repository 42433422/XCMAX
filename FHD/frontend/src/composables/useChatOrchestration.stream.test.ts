import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const {
  handleChatRequiresToken,
  applyPlainTextToMessageIndex,
  pushStreamingAiShell,
  saveMessage,
  sendChatStream,
  readPlannerSseResponse,
  requestChatByModeWithTimeout,
} = vi.hoisted(() => ({
  handleChatRequiresToken: vi.fn(),
  applyPlainTextToMessageIndex: vi.fn(),
  pushStreamingAiShell: vi.fn(() => 0),
  saveMessage: vi.fn().mockResolvedValue(undefined),
  sendChatStream: vi.fn(),
  readPlannerSseResponse: vi.fn(),
  requestChatByModeWithTimeout: vi.fn(),
}))

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: vi.fn(),
      addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
      saveMessage,
      pushStreamingAiShell,
      applyPlainTextToMessageIndex,
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
    upsertTask: vi.fn(),
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
      lastShipmentExecution: ref(null),
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
      executePrintTask: vi.fn(),
      buildPrintSummaryMessage: vi.fn(),
    }),
  }
})
vi.mock('./useChatWorkflowPanel', () => ({
  useChatWorkflowPanel: () => ({
    registerWorkflowPanelWatchers: vi.fn(),
    mountWorkflowPanel: vi.fn(),
    unmountWorkflowPanel: vi.fn(),
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
    buildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hello' } })),
    requestChatByMode: vi.fn(),
    requestChatByModeBatch: vi.fn(),
    getChatBatchDebounceMs: () => 0,
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    stopLoadingProgress: vi.fn(),
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout: vi.fn(),
    resolveChatTimeoutMs: () => 30_000,
  }),
}))
vi.mock('./useChatResponseAttach', () => ({
  useChatResponseAttach: () => ({
    getLastAiMessageRef: vi.fn(),
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
vi.mock('@/api/chat', () => ({
  default: { sendChatStream },
  parseChatStreamErrorResponse: vi.fn().mockResolvedValue('流式接口错误'),
}))
vi.mock('@/api/products', () => ({ default: { searchProducts: vi.fn() } }))
vi.mock('@/utils/chatSseStream', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/chatSseStream')>()
  return {
    ...actual,
    isChatStreamEnabled: () => true,
    readPlannerSseResponse,
  }
})
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({
  fetchShipmentRecordsForUnit: vi.fn(),
  summarizeShipmentRecordsForAudit: vi.fn(),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({ dispatchCoreWorkflowModRun: vi.fn() }))
vi.mock('@/constants/coreWorkflowMod', () => ({ isCoreWorkflowModInstalled: () => false }))

import { useChatOrchestration } from './useChatOrchestration'

describe('useChatOrchestration stream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    pushStreamingAiShell.mockReturnValue(0)
    sendChatStream.mockResolvedValue({ ok: true, body: {} })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '你' })
      onEvent({ type: 'done', result: { success: true, response: '你好' } })
    })
  })

  it('sendMessage uses SSE stream when enabled', async () => {
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('hello')
    expect(sendChatStream).toHaveBeenCalled()
    expect(readPlannerSseResponse).toHaveBeenCalled()
    expect(applyPlainTextToMessageIndex).toHaveBeenCalled()
    expect(saveMessage).toHaveBeenCalledWith('ai', '你好')
    expect(requestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('sendMessage stream handles requires_token event', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入' })
      onEvent({ type: 'done', result: { success: true, response: '' } })
    })
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('导入数据库')
    expect(handleChatRequiresToken).toHaveBeenCalled()
    expect(applyPlainTextToMessageIndex).toHaveBeenCalled()
  })

  it('sendMessage stream surfaces HTTP error', async () => {
    sendChatStream.mockResolvedValue({ ok: false, status: 502 })
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('hello')
    expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('处理失败'))
  })

  it('sendMessage stream surfaces SSE error event', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'error', message: '模型不可用' })
    })
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('hello')
    expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('模型不可用'))
  })
})
