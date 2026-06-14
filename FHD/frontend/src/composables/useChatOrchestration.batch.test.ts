import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const {
  requestChatByModeWithTimeout,
  requestChatByModeBatchWithTimeout,
  enqueueChatBatchMessage,
  addAndSaveMessage,
} = vi.hoisted(() => ({
  requestChatByModeWithTimeout: vi.fn(),
  requestChatByModeBatchWithTimeout: vi.fn(),
  enqueueChatBatchMessage: vi.fn(),
  addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
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
    handleChatRequiresToken: vi.fn(),
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
    enqueueChatBatchMessage,
    buildPlannerChatRequestPayload: vi.fn(() => ({ body: {} })),
    requestChatByMode: vi.fn(),
    requestChatByModeBatch: vi.fn(),
    getChatBatchDebounceMs: () => 300,
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    stopLoadingProgress: vi.fn(),
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs: () => 30_000,
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
  summarizeShipmentRecordsForAudit: vi.fn(),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({ dispatchCoreWorkflowModRun: vi.fn() }))
vi.mock('@/constants/coreWorkflowMod', () => ({ isCoreWorkflowModInstalled: () => false }))

import { useChatOrchestration } from './useChatOrchestration'

describe('useChatOrchestration batch/json', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    enqueueChatBatchMessage.mockImplementation((_msg: string, _ms: number, cb: (m: string[]) => void) => {
      cb(['first', 'second'])
    })
    requestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1' },
        { success: true, response: 'part-2', autoAction: { type: 'show_products_float', query: '5003' } },
      ],
    })
    requestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '请确认工作流',
      data: { action: 'workflow_confirmation_required', data: { pending_workflow_id: 'wf-1' } },
    })
  })

  it('sendMessage debounce triggers batch chat round', async () => {
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('批量问题')
    expect(enqueueChatBatchMessage).toHaveBeenCalled()
    expect(requestChatByModeBatchWithTimeout).toHaveBeenCalledWith(['first', 'second'], expect.any(Number))
    expect(addAndSaveMessage).toHaveBeenCalledWith('part-1', 'ai', undefined, expect.any(Object))
  })

  it('single json path handles workflow confirmation response', async () => {
    enqueueChatBatchMessage.mockImplementation((_m: string, _d: number, cb: (msgs: string[]) => void) => {
      cb(['only-one'])
    })
    requestChatByModeWithTimeout.mockResolvedValueOnce({
      success: true,
      response: '请确认',
      data: { action: 'workflow_confirmation_required', data: { pending_workflow_id: 'wf-2' } },
    })
    const api = useChatOrchestration({ sessionId: ref('s'), proIntentExperienceEnabled: ref(false) })
    await api.sendMessage('执行计划')
    expect(requestChatByModeWithTimeout).toHaveBeenCalled()
    expect(addAndSaveMessage).toHaveBeenCalledWith('请确认', 'ai', undefined, expect.any(Object))
  })
})
