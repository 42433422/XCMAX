/**
 * useChatOrchestration.ts 增强测试
 * 覆盖：暴露的 API 表面、sendMessage 路径、confirmTask、
 * showTaskConfirm、cancelTask、handleAutoAction、
 * emitAssistantPush（间接）、copyAssistantPushContent、
 * generateSessionId、scrollToBottom、ttsEnabled、
 * handleStartPrintCommand（间接）、applyProRuntimeMode（间接）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

// ── Mocks ──────────────────────────────────────────────────

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: vi.fn(),
      addAndSaveMessage: vi.fn(),
      saveMessage: vi.fn(),
      pushStreamingAiShell: vi.fn(() => 0),
      applyPlainTextToMessageIndex: vi.fn(),
      patchMessageAtIndex: vi.fn(),
      clearMessages: vi.fn(),
      loadMessages: vi.fn(),
      syncFromServer: vi.fn().mockResolvedValue(undefined),
      queueVoice: vi.fn(),
      clearVoiceQueue: vi.fn(),
      persistMessagesCache: vi.fn(),
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
    }),
  }
})

vi.mock('./useShipmentTask', async () => {
  const { ref } = await import('vue')
  return {
    useShipmentTask: () => ({
      lastShipmentExecution: ref(null),
      handleModifyCommand: vi.fn().mockResolvedValue(false),
      hydrateTaskOrderNumber: vi.fn().mockResolvedValue(undefined),
      enrichShipmentPreviewProducts: vi.fn().mockResolvedValue(undefined),
      getTaskTableColumns: vi.fn(() => []),
      getTaskTableItems: vi.fn(() => []),
      getTaskOrderNumber: vi.fn(() => ''),
    }),
  }
})

vi.mock('./usePrintService', async () => {
  const { ref } = await import('vue')
  return {
    usePrintService: () => ({
      isPrinting: ref(false),
      executePrintTask: vi.fn().mockResolvedValue({ success: true, message: '打印成功' }),
      buildPrintSummaryMessage: vi.fn(() => '打印完成'),
    }),
  }
})

vi.mock('./useChatWorkflowPanel', () => ({
  useChatWorkflowPanel: () => ({
    registerWorkflowPanelWatchers: vi.fn(),
    mountWorkflowPanel: vi.fn(),
    unmountWorkflowPanel: vi.fn(),
    readWorkflowEmployeeEnabledMap: vi.fn(() => ({ shipment_mgmt: true })),
    upsertWorkflowEmployeeTask: vi.fn(),
  }),
}))

vi.mock('./useChatDbTokenGate', () => ({
  useChatDbTokenGate: () => ({
    handleChatRequiresToken: vi.fn(),
    resolveEffectiveProModeState: vi.fn(() => false),
    syncProModeState: vi.fn(),
    onDbWriteUnlockedForChatRetry: vi.fn(),
    getModeScopedUserId: vi.fn(() => 'user-1'),
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

const mockRequestChatByModeWithTimeout = vi.fn().mockResolvedValue({ success: true, response: '好的' })

vi.mock('./useChatRequest', () => ({
  useChatRequest: () => ({
    loadingProgressText: ref(''),
    chatBatchQueue: ref([]),
    enqueueChatBatchMessage: vi.fn(),
    buildPlannerChatRequestPayload: vi.fn(() => ({})),
    requestChatByMode: vi.fn(),
    requestChatByModeBatch: vi.fn(),
    getChatBatchDebounceMs: () => 0,
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    stopLoadingProgress: vi.fn(),
    requestChatByModeWithTimeout: mockRequestChatByModeWithTimeout,
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
    attachDownloadUrlToLastAiMessage: vi.fn(),
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

vi.mock('@/stores/tutorial', () => ({ useTutorialStore: () => ({ isActive: false, currentStep: null }) }))
vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({ activeModId: '', mods: [], modsForUi: [], setActiveModId: vi.fn() }),
}))
vi.mock('@/api/chat', () => ({ default: {}, parseChatStreamErrorResponse: vi.fn() }))
vi.mock('@/api/products', () => ({
  default: { searchProducts: vi.fn().mockResolvedValue({ success: true, data: [], total: 0 }) },
}))
vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: vi.fn(),
  isChatStreamEnabled: () => false,
}))
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({
  fetchShipmentRecordsForUnit: vi.fn().mockResolvedValue([]),
  summarizeShipmentRecordsForAudit: vi.fn(() => ({ headline: '审计摘要', detailLines: ['行1'] })),
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({ dispatchCoreWorkflowModRun: vi.fn() }))
vi.mock('@/constants/coreWorkflowMod', () => ({ isCoreWorkflowModInstalled: () => false }))
vi.mock('@/fhd/dbTokenHeaders', () => ({ FHD_DB_WRITE_UNLOCKED_EVENT: 'fhd:db-write-unlocked' }))

import { useChatOrchestration } from './useChatOrchestration'
import { extractLikelyProductQueryKeyword } from './useChatPersistence'
import productsApi from '@/api/products'

function createApi() {
  return useChatOrchestration({
    sessionId: ref('test-session'),
    proIntentExperienceEnabled: ref(false),
  })
}

describe('useChatOrchestration – API surface', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns all expected API methods', () => {
    const api = createApi()
    expect(typeof api.sendMessage).toBe('function')
    expect(typeof api.confirmTask).toBe('function')
    expect(typeof api.cancelTask).toBe('function')
    expect(typeof api.showTaskConfirm).toBe('function')
    expect(typeof api.handleAutoAction).toBe('function')
    expect(typeof api.copyAssistantPushContent).toBe('function')
    expect(typeof api.openAssistantFloatFromTaskPanel).toBe('function')
    expect(typeof api.generateSessionId).toBe('function')
    expect(typeof api.scrollToBottom).toBe('function')
    expect(typeof api.handleShipmentDownloadClick).toBe('function')
    expect(typeof api.startPrintFromTaskCard).toBe('function')
    expect(typeof api.syncSessionMessages).toBe('function')
    expect(typeof api.isStartPrintMessage).toBe('function')
    expect(typeof api.setTtsEnabled).toBe('function')
    expect(typeof api.refetchTaskOrderNumber).toBe('function')
    expect(typeof api.triggerUpload).toBe('function')
    expect(typeof api.onExcelAnalyzeFileChange).toBe('function')
    expect(typeof api.showHistoryPanel).toBe('function')
    expect(typeof api.loadSession).toBe('function')
    expect(typeof api.clearHistorySessions).toBe('function')
    expect(typeof api.newConversation).toBe('function')
  })

  it('returns reactive refs', () => {
    const api = createApi()
    expect(api.isLoading).toBeDefined()
    expect(api.isStreamingReply).toBeDefined()
    expect(api.isExecuting).toBeDefined()
    expect(api.currentTask).toBeDefined()
    expect(api.isProMode).toBeDefined()
    expect(api.ttsEnabled).toBeDefined()
    expect(api.pushCopied).toBeDefined()
    expect(api.messages).toBeDefined()
    expect(api.taskList).toBeDefined()
  })
})

describe('useChatOrchestration – ttsEnabled', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('defaults to enabled when localStorage is not set', () => {
    const api = createApi()
    expect(api.ttsEnabled.value).toBe(true)
  })

  it('reads from localStorage', () => {
    localStorage.setItem('xcagi_chat_tts_enabled', '0')
    const api = createApi()
    expect(api.ttsEnabled.value).toBe(false)
  })

  it('setTtsEnabled persists and updates ref', () => {
    const api = createApi()
    api.setTtsEnabled(false)
    expect(localStorage.getItem('xcagi_chat_tts_enabled')).toBe('0')
    expect(api.ttsEnabled.value).toBe(false)
    api.setTtsEnabled(true)
    expect(localStorage.getItem('xcagi_chat_tts_enabled')).toBe('1')
    expect(api.ttsEnabled.value).toBe(true)
  })
})

describe('useChatOrchestration – generateSessionId', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns non-empty string', () => {
    const api = createApi()
    const id = api.generateSessionId()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(0)
  })

  it('returns unique ids', () => {
    const api = createApi()
    const id1 = api.generateSessionId()
    const id2 = api.generateSessionId()
    expect(id1).not.toBe(id2)
  })
})

describe('useChatOrchestration – scrollToBottom', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('does not throw when chatMessagesRef is null', () => {
    const api = createApi()
    expect(() => api.scrollToBottom()).not.toThrow()
  })
})

describe('useChatOrchestration – cancelTask', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('clears current task', () => {
    const api = createApi()
    api.currentTask.value = { type: 'test' }
    api.cancelTask()
    expect(api.currentTask.value).toBeNull()
  })
})

describe('useChatOrchestration – confirmTask', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('does nothing when no current task', async () => {
    const api = createApi()
    api.currentTask.value = null
    await api.confirmTask()
    // Should not throw
  })

  it('does nothing when isExecuting', async () => {
    const api = createApi()
    api.currentTask.value = { type: 'other', api_url: '/api/test' }
    api.isExecuting.value = true
    await api.confirmTask()
  })

  it('shows error when no api_url', async () => {
    const api = createApi()
    api.currentTask.value = { type: 'other', api_url: '' }
    await api.confirmTask()
    expect(api.currentTask.value).toBeNull()
  })
})

describe('useChatOrchestration – showTaskConfirm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('sets currentTask', () => {
    const api = createApi()
    api.showTaskConfirm({ type: 'shipment_generate', completed: false, api_url: '/api/test' })
    expect(api.currentTask.value).toBeTruthy()
    expect(api.currentTask.value!.type).toBe('shipment_generate')
  })

  it('handles null task', () => {
    const api = createApi()
    api.showTaskConfirm(null)
    expect(api.currentTask.value).toBeTruthy()
  })
})

describe('useChatOrchestration – handleAutoAction', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('dispatches xcagi:open-assistant-float for show_products', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    api.handleAutoAction({ type: 'show_products', query: '5003A' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })

  it('dispatches xcagi:open-assistant-float for show_products_float', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    api.handleAutoAction({ type: 'show_products_float', query: 'test' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })

  it('dispatches xcagi:switch-view for show_orders', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_orders' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('dispatches xcagi:switch-view for show_chat', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_chat' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('dispatches auto-action event', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('auto-action', handler)
    api.handleAutoAction({ type: 'show_orders' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('auto-action', handler)
  })

  it('hydrates product search in float detail', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    api.handleAutoAction({
      type: 'show_products_float',
      query: '5003A',
      hydrateProductSearch: { rows: [{ id: 1, name: '产品A' }], total: 1 },
    })
    expect(handler).toHaveBeenCalled()
    const detail = handler.mock.calls[0][0].detail
    expect(detail.hydrateProductSearch).toBeDefined()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })
})

describe('useChatOrchestration – sendMessage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('triggers remote chat round when debounce disabled', async () => {
    mockRequestChatByModeWithTimeout.mockClear()
    vi.mocked(extractLikelyProductQueryKeyword).mockReturnValue(null)
    const api = createApi()
    await api.sendMessage('查5003产品')
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalled()
  })

  it('uses product fast path when keyword extracted', async () => {
    mockRequestChatByModeWithTimeout.mockClear()
    vi.mocked(extractLikelyProductQueryKeyword).mockReturnValue('5003A')
    vi.mocked(productsApi.searchProducts).mockResolvedValue({
      success: true,
      data: [{ model_number: '5003A', name: '清漆', price: 120 }],
      total: 1,
    } as never)
    const api = createApi()
    await api.sendMessage('查5003A')
    expect(productsApi.searchProducts).toHaveBeenCalledWith('5003A')
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('falls back to chat round when product search fails', async () => {
    mockRequestChatByModeWithTimeout.mockClear()
    vi.mocked(extractLikelyProductQueryKeyword).mockReturnValue('5003A')
    vi.mocked(productsApi.searchProducts).mockRejectedValue(new Error('Network error'))
    const api = createApi()
    await api.sendMessage('查5003A')
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalled()
  })
})

describe('useChatOrchestration – copyAssistantPushContent', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('does nothing when no push content', async () => {
    const api = createApi()
    api.latestAssistantPush.value = null
    await api.copyAssistantPushContent()
    expect(api.pushCopied.value).toBe(false)
  })

  it('sets pushCopied when content exists', async () => {
    const api = createApi()
    api.latestAssistantPush.value = { title: '测试', description: '描述' }
    await api.copyAssistantPushContent()
    expect(api.pushCopied.value).toBe(true)
  })
})

describe('useChatOrchestration – openAssistantFloatFromTaskPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('dispatches xcagi:open-assistant-float event', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    api.openAssistantFloatFromTaskPanel()
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })
})

describe('useChatOrchestration – handleShipmentDownloadClick', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('is callable without error', () => {
    const api = createApi()
    expect(() => api.handleShipmentDownloadClick()).not.toThrow()
  })
})

describe('useChatOrchestration – startPrintFromTaskCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('is callable without error', async () => {
    const api = createApi()
    await expect(api.startPrintFromTaskCard()).resolves.toBeUndefined()
  })
})

describe('useChatOrchestration – isStartPrintMessage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns true for print command', () => {
    const api = createApi()
    expect(api.isStartPrintMessage('开始打印')).toBe(true)
  })

  it('returns false for non-print message', () => {
    const api = createApi()
    expect(api.isStartPrintMessage('普通消息')).toBe(false)
  })
})

describe('useChatOrchestration – syncSessionMessages', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('is callable without error', async () => {
    const api = createApi()
    await expect(api.syncSessionMessages()).resolves.toBeUndefined()
  })
})

describe('useChatOrchestration – lastMessage computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('returns null when no messages', () => {
    const api = createApi()
    expect(api.lastMessage.value).toBeNull()
  })
})

describe('useChatOrchestration – setTaskFilter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('is callable', () => {
    const api = createApi()
    api.setTaskFilter('running')
    expect(api.taskFilter).toBeDefined()
  })
})
