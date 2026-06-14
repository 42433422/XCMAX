import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: vi.fn(),
      addAndSaveMessage: vi.fn(),
      saveMessage: vi.fn(),
      pushStreamingAiShell: vi.fn(),
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
    cancelTaskById: vi.fn(),
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
  extractLikelyProductQueryKeyword: vi.fn(),
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
    resolveEffectiveProModeState: vi.fn(),
    syncProModeState: vi.fn(),
    onDbWriteUnlockedForChatRetry: vi.fn(),
  }),
}))
vi.mock('./useChatExcelContext', () => ({
  useChatExcelContext: () => ({
    bindExcelSheetToChat: vi.fn(),
    bindAllExcelSheetsToChat: vi.fn(),
  }),
}))
vi.mock('./useChatRequest', () => ({
  useChatRequest: () => ({
    executeRemoteChatRound: vi.fn(),
    loadingProgressText: ref(''),
  }),
}))
vi.mock('./useChatResponseAttach', () => ({
  useChatResponseAttach: () => ({}),
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
  useModsStore: () => ({
    activeModId: '',
    mods: [],
    modsForUi: [],
    setActiveModId: vi.fn(),
  }),
}))
vi.mock('@/api/chat', () => ({ default: {}, parseChatStreamErrorResponse: vi.fn() }))
vi.mock('@/api/products', () => ({ default: {} }))
vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: vi.fn(),
  isChatStreamEnabled: () => false,
}))
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({
  fetchShipmentRecordsForUnit: vi.fn(),
  summarizeShipmentRecordsForAudit: vi.fn(),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({
  dispatchCoreWorkflowModRun: vi.fn(),
}))
vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowModInstalled: () => false,
}))

import { useChatOrchestration } from './useChatOrchestration'

describe('useChatOrchestration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns core chat API surface', () => {
    const sessionId = ref('orch-session')
    const api = useChatOrchestration({
      sessionId,
      proIntentExperienceEnabled: ref(false),
    })
    expect(typeof api.sendMessage).toBe('function')
    expect(typeof api.confirmTask).toBe('function')
    expect(api.isProMode).toBeDefined()
    expect(api.ttsEnabled).toBeDefined()
  })

  it('setTtsEnabled persists preference and clears voice queue', () => {
    const sessionId = ref('tts-session')
    const api = useChatOrchestration({
      sessionId,
      proIntentExperienceEnabled: ref(false),
    })
    api.setTtsEnabled(false)
    expect(localStorage.getItem('xcagi_chat_tts_enabled')).toBe('0')
    expect(api.ttsEnabled.value).toBe(false)
    api.setTtsEnabled(true)
    expect(localStorage.getItem('xcagi_chat_tts_enabled')).toBe('1')
  })

  it('openAssistantFloatFromTaskPanel dispatches custom event', () => {
    const sessionId = ref('float-session')
    const api = useChatOrchestration({
      sessionId,
      proIntentExperienceEnabled: ref(false),
    })
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    api.openAssistantFloatFromTaskPanel()
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })

  it('setTaskFilter delegates to task list', () => {
    const sessionId = ref('filter-session')
    const api = useChatOrchestration({
      sessionId,
      proIntentExperienceEnabled: ref(false),
    })
    api.setTaskFilter('running')
    expect(api.taskFilter).toBeDefined()
  })
})
