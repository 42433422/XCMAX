/**
 * useChatOrchestration.ts 覆盖率补齐测试
 * 针对未覆盖行：errorMessage、normalizeServerContentToHtml、scrollToBottom、
 * useExcelAnalysis 回调、runShipmentMgmtAfterPrintSuccess、applyProRuntimeMode、
 * tryHandleRuntimeModeCommand、refetchTaskOrderNumber、setCustomOrderNumber、
 * shouldAutoRunTask/scheduleAutoConfirmTask、showTaskConfirm、emitAssistantPush、
 * maybeCloseAssistantFloatForShipmentTask、confirmTask 各分支、handleAutoAction 各分支、
 * maybePrefetchProductAssistantFloat、executeRemoteChatRound 快路径/批量/单条、
 * sendMessage 各分支、生命周期钩子等。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, type Ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

// ── vi.hoisted：所有在 vi.mock 工厂中引用的 vi.fn 必须在此定义 ───
const {
  mockAddAndSaveMessage,
  mockExecutePrintTask,
  mockBuildPrintSummaryMessage,
  mockHandleChatRequiresToken,
  mockResolveEffectiveProModeState,
  mockRequestChatByModeWithTimeout,
  mockRequestChatByModeBatchWithTimeout,
  mockEnqueueChatBatchMessage,
  mockGetChatBatchDebounceMs,
  mockIsChatStreamEnabled,
  mockReadPlannerSseResponse,
  mockSendChatStream,
  mockParseChatStreamErrorResponse,
  mockSearchProducts,
  mockFetchShipmentRecordsForUnit,
  mockSummarizeShipmentRecordsForAudit,
  mockDispatchCoreWorkflowModRun,
  mockIsCoreWorkflowModInstalled,
  mockReadWorkflowEmployeeEnabledMap,
  mockUpsertWorkflowEmployeeTask,
  mockGetLastAiMessageRef,
  mockSyncTaskFromChatResponse,
  mockAttachThinkingSteps,
  mockAttachTodoSteps,
  mockAttachWorkflowTrace,
  mockAttachContextSummary,
  mockHydrateTaskOrderNumber,
  mockEnrichShipmentPreviewProducts,
  mockHandleShipmentModify,
  mockResolveExcelAnalysisContextForRequest,
  mockExtractLikelyProductQueryKeyword,
  mockResolveExcelFilePathFromAnalysis,
  mockResolveExcelSheetOptionsFromContext,
  mockReadPersistedExcelAnalysisContext,
  mockPersistExcelAnalysisContext,
  mockApplyPlainTextToMessageIndex,
  mockPushStreamingAiShell,
  mockSaveMessage,
  mockQueueVoice,
  mockClearVoiceQueue,
  mockSyncFromServer,
  mockBuildPlannerChatRequestPayload,
  mockSetLoadingProgress,
  mockStartWaitProgressTimer,
  mockStopLoadingProgress,
  mockResolveChatTimeoutMs,
  state,
} = vi.hoisted(() => ({
  mockAddAndSaveMessage: vi.fn().mockResolvedValue(undefined),
  mockExecutePrintTask: vi.fn(),
  mockBuildPrintSummaryMessage: vi.fn(() => '打印完成'),
  mockHandleChatRequiresToken: vi.fn(),
  mockResolveEffectiveProModeState: vi.fn(() => false),
  mockRequestChatByModeWithTimeout: vi.fn(),
  mockRequestChatByModeBatchWithTimeout: vi.fn(),
  mockEnqueueChatBatchMessage: vi.fn(),
  mockGetChatBatchDebounceMs: vi.fn(() => 0),
  mockIsChatStreamEnabled: vi.fn(() => false),
  mockReadPlannerSseResponse: vi.fn(),
  mockSendChatStream: vi.fn(),
  mockParseChatStreamErrorResponse: vi.fn().mockResolvedValue('流式错误'),
  mockSearchProducts: vi.fn(),
  mockFetchShipmentRecordsForUnit: vi.fn(),
  mockSummarizeShipmentRecordsForAudit: vi.fn(),
  mockDispatchCoreWorkflowModRun: vi.fn(),
  mockIsCoreWorkflowModInstalled: vi.fn(() => false),
  mockReadWorkflowEmployeeEnabledMap: vi.fn(() => ({ shipment_mgmt: false })),
  mockUpsertWorkflowEmployeeTask: vi.fn(),
  mockGetLastAiMessageRef: vi.fn(() => '0'),
  mockSyncTaskFromChatResponse: vi.fn(),
  mockAttachThinkingSteps: vi.fn(),
  mockAttachTodoSteps: vi.fn(),
  mockAttachWorkflowTrace: vi.fn(),
  mockAttachContextSummary: vi.fn(),
  mockHydrateTaskOrderNumber: vi.fn().mockResolvedValue(undefined),
  mockEnrichShipmentPreviewProducts: vi.fn().mockResolvedValue(undefined),
  mockHandleShipmentModify: vi.fn().mockResolvedValue(false),
  mockResolveExcelAnalysisContextForRequest: vi.fn(() => null),
  mockExtractLikelyProductQueryKeyword: vi.fn(() => null),
  mockResolveExcelFilePathFromAnalysis: vi.fn(() => null),
  mockResolveExcelSheetOptionsFromContext: vi.fn(() => []),
  mockReadPersistedExcelAnalysisContext: vi.fn(() => null),
  mockPersistExcelAnalysisContext: vi.fn(),
  mockApplyPlainTextToMessageIndex: vi.fn(),
  mockPushStreamingAiShell: vi.fn(() => 0),
  mockSaveMessage: vi.fn().mockResolvedValue(undefined),
  mockQueueVoice: vi.fn(),
  mockClearVoiceQueue: vi.fn(),
  mockSyncFromServer: vi.fn().mockResolvedValue(undefined),
  mockBuildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hello' } })),
  mockSetLoadingProgress: vi.fn(),
  mockStartWaitProgressTimer: vi.fn(),
  mockStopLoadingProgress: vi.fn(),
  mockResolveChatTimeoutMs: vi.fn(() => 30_000),
  state: {} as {
    taskList?: Ref<unknown[]>
    lastShipmentExecution?: Ref<Record<string, unknown> | null>
    multimodalPendingCount?: Ref<number>
    excelSheetOptions?: Ref<unknown[]>
    linkedExcelSheet?: Ref<unknown>
    lastExcelAnalysisContext?: Ref<unknown>
    linkedExcelAllSheets?: Ref<boolean>
  },
}))

// ── 可控 ref 状态（在 async vi.mock 工厂中赋值到 state） ──────
let capturedExcelCallbacks: {
  onAnalyzed?: (e: unknown) => void
  onAnalyzeStart?: (e: unknown) => void
  onAnalyzeProgress?: (e: unknown) => void
  onAnalyzeDone?: (e: unknown) => void
} = {}
let capturedNormalizeFn: (raw: unknown) => string = () => ''

// ── vi.mock 声明 ───────────────────────────────────────────────
vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: vi.fn(),
      addAndSaveMessage: mockAddAndSaveMessage,
      saveMessage: mockSaveMessage,
      pushStreamingAiShell: mockPushStreamingAiShell,
      applyPlainTextToMessageIndex: mockApplyPlainTextToMessageIndex,
      clearMessages: vi.fn(),
      loadMessages: vi.fn(),
      syncFromServer: mockSyncFromServer,
      queueVoice: mockQueueVoice,
      clearVoiceQueue: mockClearVoiceQueue,
    }),
  }
})

vi.mock('./useChatTaskList', async () => {
  const { ref } = await import('vue')
  state.taskList = ref([])
  return {
    useChatTaskList: () => ({
      taskList: state.taskList!,
      activeTaskId: ref(''),
      expandedTaskIds: ref([]),
      taskFilter: ref('all'),
      activeTask: ref(null),
      filteredTaskList: ref([]),
      createTaskId: (p: string) => `${p}-${Date.now()}`,
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
  }
})

vi.mock('./useChatPersistence', () => ({
  readPersistedExcelAnalysisContext: mockReadPersistedExcelAnalysisContext,
  persistExcelAnalysisContext: mockPersistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis: mockResolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext: mockResolveExcelSheetOptionsFromContext,
  extractLikelyProductQueryKeyword: mockExtractLikelyProductQueryKeyword,
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
    useExcelAnalysis: (_deps: unknown, opts: unknown) => {
      capturedExcelCallbacks = (opts as typeof capturedExcelCallbacks) || {}
      return {
        excelAnalyzeUploading: ref(false),
        excelAnalyzeInputRef: ref(null),
        triggerUpload: vi.fn(),
        onExcelAnalyzeFileChange: vi.fn(),
        setOnMultimodalFileChangeCallback: vi.fn(),
      }
    },
  }
})

vi.mock('./useShipmentTask', async () => {
  const { ref } = await import('vue')
  state.lastShipmentExecution = ref(null)
  return {
    useShipmentTask: () => ({
      lastShipmentExecution: state.lastShipmentExecution!,
      handleModifyCommand: mockHandleShipmentModify,
      hydrateTaskOrderNumber: mockHydrateTaskOrderNumber,
      enrichShipmentPreviewProducts: mockEnrichShipmentPreviewProducts,
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
      executePrintTask: mockExecutePrintTask,
      buildPrintSummaryMessage: mockBuildPrintSummaryMessage,
    }),
  }
})

vi.mock('./useChatWorkflowPanel', () => ({
  useChatWorkflowPanel: () => ({
    registerWorkflowPanelWatchers: vi.fn(),
    mountWorkflowPanel: vi.fn(),
    unmountWorkflowPanel: vi.fn(),
    readWorkflowEmployeeEnabledMap: mockReadWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask: mockUpsertWorkflowEmployeeTask,
  }),
}))

vi.mock('./useChatDbTokenGate', () => ({
  useChatDbTokenGate: () => ({
    handleChatRequiresToken: mockHandleChatRequiresToken,
    resolveEffectiveProModeState: mockResolveEffectiveProModeState,
    syncProModeState: vi.fn(),
    onDbWriteUnlockedForChatRetry: vi.fn(),
    getModeScopedUserId: vi.fn(() => 'u1'),
    resolveChatDbTokensForPayload: vi.fn(() => ({})),
  }),
}))

vi.mock('./useChatExcelContext', async () => {
  const { ref } = await import('vue')
  state.multimodalPendingCount = ref(0)
  state.excelSheetOptions = ref([])
  state.linkedExcelSheet = ref(null)
  state.lastExcelAnalysisContext = ref(null)
  state.linkedExcelAllSheets = ref(false)
  return {
    useChatExcelContext: () => ({
      bindExcelSheetToChat: vi.fn(),
      bindAllExcelSheetsToChat: vi.fn(),
      resolveExcelAnalysisContextForRequest: mockResolveExcelAnalysisContextForRequest,
      lastExcelAnalysisContext: state.lastExcelAnalysisContext!,
      linkedExcelSheet: state.linkedExcelSheet!,
      linkedExcelAllSheets: state.linkedExcelAllSheets!,
      multimodalStaging: ref([]),
      multimodalPendingCount: state.multimodalPendingCount!,
      excelSheetOptions: state.excelSheetOptions!,
      injectExcelContextPayload: vi.fn((p: unknown) => p),
      consumeMultimodalIntoPlannerContext: vi.fn(),
      onMultimodalFileChange: vi.fn(),
    }),
  }
})

vi.mock('./useChatRequest', () => ({
  useChatRequest: () => ({
    loadingProgressText: ref(''),
    chatBatchQueue: ref([]),
    enqueueChatBatchMessage: mockEnqueueChatBatchMessage,
    buildPlannerChatRequestPayload: mockBuildPlannerChatRequestPayload,
    requestChatByMode: vi.fn(),
    requestChatByModeBatch: vi.fn(),
    getChatBatchDebounceMs: mockGetChatBatchDebounceMs,
    setLoadingProgress: mockSetLoadingProgress,
    startWaitProgressTimer: mockStartWaitProgressTimer,
    stopLoadingProgress: mockStopLoadingProgress,
    requestChatByModeWithTimeout: mockRequestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout: mockRequestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs: mockResolveChatTimeoutMs,
  }),
}))

vi.mock('./useChatResponseAttach', () => ({
  useChatResponseAttach: () => ({
    getLastAiMessageRef: mockGetLastAiMessageRef,
    attachThinkingStepsToLastAiMessage: mockAttachThinkingSteps,
    attachTodoStepsToLastAiMessage: mockAttachTodoSteps,
    attachWorkflowTraceToLastAiMessage: mockAttachWorkflowTrace,
    attachContextSummaryToLastAiMessage: mockAttachContextSummary,
    syncTaskFromChatResponse: mockSyncTaskFromChatResponse,
  }),
}))

vi.mock('./useChatSessionHistory', async () => {
  const { ref } = await import('vue')
  return {
    useChatSessionHistory: (deps: { normalizeServerContentToHtml: (raw: unknown) => string }) => {
      capturedNormalizeFn = deps.normalizeServerContentToHtml
      return {
        showHistory: ref(false),
        historySessions: ref([]),
        historyLoading: ref(false),
        historyError: ref(''),
        showHistoryPanel: vi.fn(),
        loadSession: vi.fn(),
        clearHistorySessions: vi.fn(),
        newConversation: vi.fn(),
        registerHistoryModWatch: vi.fn(),
      }
    },
  }
})

vi.mock('@/stores/tutorial', () => ({
  useTutorialStore: () => ({ isActive: false, currentStep: null }),
}))
vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    activeModId: '',
    mods: [],
    modsForUi: [],
    setActiveModId: vi.fn(),
  }),
}))
vi.mock('@/api/chat', () => ({
  default: { sendChatStream: mockSendChatStream },
  parseChatStreamErrorResponse: mockParseChatStreamErrorResponse,
}))
vi.mock('@/api/products', () => ({
  default: { searchProducts: mockSearchProducts },
}))
vi.mock('@/utils/chatSseStream', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/chatSseStream')>()
  return {
    ...actual,
    isChatStreamEnabled: mockIsChatStreamEnabled,
    readPlannerSseResponse: mockReadPlannerSseResponse,
  }
})
vi.mock('@/utils/shipmentMgmtPostPrint', () => ({
  fetchShipmentRecordsForUnit: mockFetchShipmentRecordsForUnit,
  summarizeShipmentRecordsForAudit: mockSummarizeShipmentRecordsForAudit,
}))
vi.mock('@/workflow/coreWorkflowDispatcher', () => ({
  dispatchCoreWorkflowModRun: mockDispatchCoreWorkflowModRun,
}))
vi.mock('@/constants/coreWorkflowMod', () => ({
  isCoreWorkflowModInstalled: mockIsCoreWorkflowModInstalled,
}))
vi.mock('@/fhd/dbTokenHeaders', () => ({
  FHD_DB_WRITE_UNLOCKED_EVENT: 'fhd:db-write-unlocked',
}))

import { useChatOrchestration } from './useChatOrchestration'
import { createApp, defineComponent, h } from 'vue'

// ── 辅助 ───────────────────────────────────────────────────────
function createApi(sessionId = 'test-session') {
  return useChatOrchestration({
    sessionId: ref(sessionId),
    proIntentExperienceEnabled: ref(false),
  })
}

function resetMockState() {
  vi.clearAllMocks()
  state.taskList!.value = []
  state.lastShipmentExecution!.value = null
  state.multimodalPendingCount!.value = 0
  state.excelSheetOptions!.value = []
  state.linkedExcelSheet!.value = null
  state.lastExcelAnalysisContext!.value = null
  state.linkedExcelAllSheets!.value = false
  mockResolveEffectiveProModeState.mockReturnValue(false)
  mockIsChatStreamEnabled.mockReturnValue(false)
  mockGetChatBatchDebounceMs.mockReturnValue(0)
  mockExtractLikelyProductQueryKeyword.mockReturnValue(null)
  mockResolveExcelAnalysisContextForRequest.mockReturnValue(null)
  mockReadWorkflowEmployeeEnabledMap.mockReturnValue({ shipment_mgmt: false })
  mockRequestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '好的' })
  mockAddAndSaveMessage.mockResolvedValue(undefined)
  mockExecutePrintTask.mockResolvedValue({ success: true, message: 'ok' })
  mockBuildPrintSummaryMessage.mockReturnValue('打印完成')
  mockHandleShipmentModify.mockResolvedValue(false)
  mockSearchProducts.mockResolvedValue({ success: true, data: [], total: 0 })
  mockFetchShipmentRecordsForUnit.mockResolvedValue([])
  mockSummarizeShipmentRecordsForAudit.mockReturnValue({ headline: '审计摘要', detailLines: ['行1'] })
  mockSaveMessage.mockResolvedValue(undefined)
  mockPushStreamingAiShell.mockReturnValue(0)
  mockHydrateTaskOrderNumber.mockResolvedValue(undefined)
  mockEnrichShipmentPreviewProducts.mockResolvedValue(undefined)
  mockGetLastAiMessageRef.mockReturnValue('0')
  mockBuildPlannerChatRequestPayload.mockReturnValue({ body: { message: 'hello' } })
  mockResolveChatTimeoutMs.mockReturnValue(30_000)
}

// ═══════════════════════════════════════════════════════════════
// 测试套件
// ═══════════════════════════════════════════════════════════════

describe('useChatOrchestration coverage – normalizeServerContentToHtml', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('HTML 内容直通返回', () => {
    createApi()
    expect(capturedNormalizeFn('<div>hello</div>')).toBe('<div>hello</div>')
  })

  it('纯文本转义并转换换行为 <br>', () => {
    createApi()
    const result = capturedNormalizeFn('line1\nline2')
    expect(result).toContain('<br>')
    expect(result).not.toContain('\n')
  })

  it('空值返回空字符串', () => {
    createApi()
    expect(capturedNormalizeFn(null)).toBe('')
    expect(capturedNormalizeFn('')).toBe('')
    expect(capturedNormalizeFn(undefined)).toBe('')
  })
})

describe('useChatOrchestration coverage – scrollToBottom', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('有 chatMessagesRef 时设置 scrollTop', () => {
    const api = createApi()
    const fakeEl = { scrollTop: 0, scrollHeight: 500 } as HTMLElement
    api.chatMessagesRef.value = fakeEl
    api.scrollToBottom()
    expect(fakeEl.scrollTop).toBe(500)
  })

  it('无 chatMessagesRef 时不抛错', () => {
    const api = createApi()
    api.chatMessagesRef.value = null
    expect(() => api.scrollToBottom()).not.toThrow()
  })
})

describe('useChatOrchestration coverage – ExcelAnalysis 回调', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('onAnalyzeStart 创建 excel_analyze 任务', () => {
    createApi()
    expect(capturedExcelCallbacks.onAnalyzeStart).toBeDefined()
    capturedExcelCallbacks.onAnalyzeStart!({ fileName: 'test.xlsx' })
  })

  it('onAnalyzed 有 persistedPath 时设置 file_path', () => {
    createApi()
    mockResolveExcelFilePathFromAnalysis.mockReturnValue('/tmp/test.xlsx')
    mockResolveExcelSheetOptionsFromContext.mockReturnValue([{ name: 'Sheet1' }])
    capturedExcelCallbacks.onAnalyzed!({
      fileName: 'test.xlsx',
      summary: '摘要',
      result: { fields: [], preview_data: {}, sheets: [] },
    })
    expect(mockPersistExcelAnalysisContext).toHaveBeenCalled()
    expect(state.lastExcelAnalysisContext!.value).toBeTruthy()
  })

  it('onAnalyzed 无 persistedPath 时不设置 file_path', () => {
    createApi()
    mockResolveExcelFilePathFromAnalysis.mockReturnValue(null)
    capturedExcelCallbacks.onAnalyzed!({
      fileName: '',
      summary: '摘要',
      result: { fields: ['f1'], preview_data: { a: 1 }, sheets: [{ name: 'S1' }] },
    })
    expect(state.lastExcelAnalysisContext!.value).toBeTruthy()
    expect(state.lastExcelAnalysisContext!.value).not.toHaveProperty('file_path')
  })

  it('onAnalyzed 有 __VUE_CHAT_FILL__ 时调用它', () => {
    createApi()
    const fillFn = vi.fn(() => true)
    ;(window as unknown as { __VUE_CHAT_FILL__: typeof fillFn }).__VUE_CHAT_FILL__ = fillFn
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    capturedExcelCallbacks.onAnalyzed!({
      fileName: 'test.xlsx',
      summary: '摘要',
      result: { fields: [], preview_data: {}, sheets: [] },
    })
    expect(fillFn).toHaveBeenCalled()
    delete (window as unknown as { __VUE_CHAT_FILL__?: typeof fillFn }).__VUE_CHAT_FILL__
    rafSpy.mockRestore()
  })

  it('onAnalyzed 无 __VUE_CHAT_FILL__ 时兜底写 DOM', () => {
    createApi()
    document.body.innerHTML = '<div id="view-chat"><textarea id="messageInput"></textarea></div>'
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      cb(0)
      return 0
    })
    capturedExcelCallbacks.onAnalyzed!({
      fileName: 'test.xlsx',
      summary: '摘要',
      result: { fields: [], preview_data: {}, sheets: [] },
    })
    const input = document.querySelector('#messageInput') as HTMLTextAreaElement
    expect(input.value).toContain('@uploads/')
    document.body.innerHTML = ''
    rafSpy.mockRestore()
  })

  it('onAnalyzed 有 running excel_analyze 任务时标记成功', () => {
    createApi()
    state.taskList!.value = [
      { id: 'excel-1', type: 'excel_analyze', status: 'running', title: '分析Excel', source: 'excel' },
    ]
    capturedExcelCallbacks.onAnalyzed!({
      fileName: 'test.xlsx',
      summary: '摘要',
      result: { fields: [], preview_data: {}, sheets: [] },
    })
  })

  it('onAnalyzeProgress 有 running 任务时更新进度', () => {
    createApi()
    state.taskList!.value = [
      { id: 'excel-1', type: 'excel_analyze', status: 'running', title: '分析Excel', source: 'excel', progress: 5 },
    ]
    capturedExcelCallbacks.onAnalyzeProgress!({ step: '解析中', progress: 50 })
  })

  it('onAnalyzeProgress 无 running 任务时早返回', () => {
    createApi()
    state.taskList!.value = []
    expect(() => {
      capturedExcelCallbacks.onAnalyzeProgress!({ step: '解析中', progress: 50 })
    }).not.toThrow()
  })

  it('onAnalyzeDone 成功时 finishTask', () => {
    createApi()
    state.taskList!.value = [
      { id: 'excel-1', type: 'excel_analyze', status: 'running', title: '分析Excel', source: 'excel', summary: '摘要' },
    ]
    capturedExcelCallbacks.onAnalyzeDone!({ success: true, message: '完成' })
  })

  it('onAnalyzeDone 失败时 failTask', () => {
    createApi()
    state.taskList!.value = [
      { id: 'excel-1', type: 'excel_analyze', status: 'running', title: '分析Excel', source: 'excel' },
    ]
    capturedExcelCallbacks.onAnalyzeDone!({ success: false, message: '失败原因' })
  })

  it('onAnalyzeDone 无 running 任务时早返回', () => {
    createApi()
    state.taskList!.value = []
    expect(() => {
      capturedExcelCallbacks.onAnalyzeDone!({ success: true, message: '' })
    }).not.toThrow()
  })
})

describe('useChatOrchestration coverage – runShipmentMgmtAfterPrintSuccess', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('shipment_mgmt 禁用时早返回', async () => {
    mockReadWorkflowEmployeeEnabledMap.mockReturnValue({ shipment_mgmt: false })
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
    }
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockFetchShipmentRecordsForUnit).not.toHaveBeenCalled()
  })

  it('purchaseUnit 为空时早返回', async () => {
    mockReadWorkflowEmployeeEnabledMap.mockReturnValue({ shipment_mgmt: true })
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '',
    }
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockFetchShipmentRecordsForUnit).not.toHaveBeenCalled()
  })

  it('正常流程：拉取记录、派发事件、推送消息', async () => {
    mockReadWorkflowEmployeeEnabledMap.mockReturnValue({ shipment_mgmt: true })
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
      orderId: 123,
    }
    mockFetchShipmentRecordsForUnit.mockResolvedValue([{ id: 1 }])
    mockSummarizeShipmentRecordsForAudit.mockReturnValue({
      headline: '审计摘要',
      detailLines: ['行1', '行2'],
    })
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockFetchShipmentRecordsForUnit).toHaveBeenCalledWith('甲公司')
    expect(mockSummarizeShipmentRecordsForAudit).toHaveBeenCalled()
    expect(mockDispatchCoreWorkflowModRun).toHaveBeenCalled()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('出货管理'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('taskList 有 workflow_emp_shipment_mgmt 时 upsertWorkflowEmployeeTask', async () => {
    mockReadWorkflowEmployeeEnabledMap.mockReturnValue({ shipment_mgmt: true })
    state.taskList!.value = [{ id: 'workflow_emp_shipment_mgmt' }]
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
      orderId: 123,
    }
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockUpsertWorkflowEmployeeTask).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – handleStartPrintCommand', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('无 labelPaths 且无 filePath 时提示重新生成', async () => {
    state.lastShipmentExecution!.value = {
      filePath: '',
      labelPaths: [],
      purchaseUnit: '甲公司',
    }
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('未包含可打印文件'),
      'ai',
      undefined,
      expect.any(Object),
    )
    expect(mockExecutePrintTask).not.toHaveBeenCalled()
  })

  it('打印失败时标记 shipment 任务为 failed', async () => {
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
      orderId: 456,
      taskListId: 'shipment-1',
    }
    mockExecutePrintTask.mockResolvedValue({ success: false, message: '打印机离线' })
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('打印完成'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('打印成功且有 taskListId 时标记 shipment 任务为 success', async () => {
    state.lastShipmentExecution!.value = {
      filePath: '/tmp/doc.pdf',
      labelPaths: ['/tmp/label.pdf'],
      purchaseUnit: '甲公司',
      orderId: 789,
      taskListId: 'shipment-1',
    }
    mockExecutePrintTask.mockResolvedValue({ success: true, message: 'ok' })
    const api = createApi()
    await api.sendMessage('开始打印')
    expect(mockExecutePrintTask).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – applyProRuntimeMode / tryHandleRuntimeModeCommand', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  afterEach(() => {
    delete (window as unknown as { setWorkModeFromChat?: unknown }).setWorkModeFromChat
    delete (window as unknown as { setMonitorModeFromChat?: unknown }).setMonitorModeFromChat
    delete (window as unknown as { refreshWorkModeMonitorList?: unknown }).refreshWorkModeMonitorList
  })

  it('pro 模式下发送"工作模式"切换工作模式', async () => {
    const api = createApi()
    api.isProMode.value = true
    const workModeFn = vi.fn()
    ;(window as unknown as { setWorkModeFromChat: typeof workModeFn }).setWorkModeFromChat = workModeFn
    await api.sendMessage('工作模式')
    expect(workModeFn).toHaveBeenCalledWith(true)
  })

  it('pro 模式下发送"监控模式"切换监控模式', async () => {
    const api = createApi()
    api.isProMode.value = true
    const monitorFn = vi.fn()
    ;(window as unknown as { setMonitorModeFromChat: typeof monitorFn }).setMonitorModeFromChat = monitorFn
    await api.sendMessage('监控模式')
    expect(monitorFn).toHaveBeenCalledWith(true)
  })

  it('监控模式入口缺失时提示不可用', async () => {
    const api = createApi()
    api.isProMode.value = true
    await api.sendMessage('监控模式')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('监控模式入口不可用'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('工作模式入口缺失时提示不可用', async () => {
    const api = createApi()
    api.isProMode.value = true
    await api.sendMessage('工作模式')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('工作模式入口不可用'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('非 pro 模式下不处理运行时模式命令', async () => {
    const api = createApi()
    api.isProMode.value = false
    mockExtractLikelyProductQueryKeyword.mockReturnValue(null)
    await api.sendMessage('工作模式')
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalled()
  })

  it('pro 模式下 refreshWorkModeMonitorList 被调用', async () => {
    const api = createApi()
    api.isProMode.value = true
    const workModeFn = vi.fn()
    const refreshFn = vi.fn()
    ;(window as unknown as { setWorkModeFromChat: typeof workModeFn }).setWorkModeFromChat = workModeFn
    ;(window as unknown as { refreshWorkModeMonitorList: typeof refreshFn }).refreshWorkModeMonitorList = refreshFn
    await api.sendMessage('工作模式')
    expect(refreshFn).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – refetchTaskOrderNumber / setCustomOrderNumber', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('refetchTaskOrderNumber 无任务时不调用 hydrate', async () => {
    const api = createApi()
    api.currentTask.value = null
    await api.refetchTaskOrderNumber()
    expect(mockHydrateTaskOrderNumber).not.toHaveBeenCalled()
  })

  it('refetchTaskOrderNumber 非 shipment_generate 类型时不调用', async () => {
    const api = createApi()
    api.currentTask.value = { type: 'other', completed: false } as never
    await api.refetchTaskOrderNumber()
    expect(mockHydrateTaskOrderNumber).not.toHaveBeenCalled()
  })

  it('refetchTaskOrderNumber 已完成任务时不调用', async () => {
    const api = createApi()
    api.currentTask.value = { type: 'shipment_generate', completed: true } as never
    await api.refetchTaskOrderNumber()
    expect(mockHydrateTaskOrderNumber).not.toHaveBeenCalled()
  })

  it('refetchTaskOrderNumber 有效任务时调用 hydrate', async () => {
    const api = createApi()
    api.currentTask.value = { type: 'shipment_generate', completed: false, api_url: '/x' } as never
    await api.refetchTaskOrderNumber()
    expect(mockHydrateTaskOrderNumber).toHaveBeenCalledWith(expect.anything(), { force: true })
    expect(api.orderNumberFetching.value).toBe(false)
  })

  it('setCustomOrderNumber 无任务时不抛错', () => {
    const api = createApi()
    api.currentTask.value = null
    expect(() => api.setCustomOrderNumber('123')).not.toThrow()
  })

  it('setCustomOrderNumber 有任务时设置 customOrderNumber', () => {
    const api = createApi()
    api.currentTask.value = { type: 'shipment_generate', customOrderNumber: '' } as never
    api.setCustomOrderNumber('ORD-001')
    expect((api.currentTask.value as { customOrderNumber: string }).customOrderNumber).toBe('ORD-001')
  })
})

describe('useChatOrchestration coverage – shouldAutoRunTask / scheduleAutoConfirmTask', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('showTaskConfirm excel_import 类型任务自动确认', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'excel_import',
      completed: false,
      api_url: '/api/import',
    })
    expect(api.currentTask.value).toBeTruthy()
    vi.advanceTimersByTime(1)
  })

  it('showTaskConfirm tool_id 为 import_excel_to_database 时自动确认', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      completed: false,
      api_url: '/api/import',
      payload: { tool_id: 'import_excel_to_database' },
    })
    vi.advanceTimersByTime(1)
  })

  it('showTaskConfirm 已完成任务不自动确认', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'excel_import',
      completed: true,
      api_url: '/api/import',
    })
    vi.advanceTimersByTime(1)
  })
})

describe('useChatOrchestration coverage – showTaskConfirm shipment_generate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('有已存在 order_number 时不调用 hydrate', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/test',
      customOrderNumber: 'ORD-001',
    })
    expect(mockHydrateTaskOrderNumber).not.toHaveBeenCalled()
    expect((api.currentTask.value as { customOrderNumber: string }).customOrderNumber).toBe('ORD-001')
  })

  it('无 order_number 时调用 hydrate 和 enrich', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/test',
    })
    expect(mockHydrateTaskOrderNumber).toHaveBeenCalled()
    expect(mockEnrichShipmentPreviewProducts).toHaveBeenCalled()
    expect((api.currentTask.value as { customOrderNumber: string }).customOrderNumber).toBe('')
  })

  it('从 data.order_number 获取已存在单号', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/test',
      data: { order_number: 'ORD-002' },
    })
    expect((api.currentTask.value as { customOrderNumber: string }).customOrderNumber).toBe('ORD-002')
  })
})

describe('useChatOrchestration coverage – maybeCloseAssistantFloatForShipmentTask', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('confirmTask 成功后触发 close-assistant-float 事件', async () => {
    // maybeCloseAssistantFloatForShipmentTask 在 executeRemoteChatRound 中被调用
    // 需通过 sendMessage 触发，响应包含 shipment_generate 任务
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '已生成发货单',
      task: { type: 'shipment_generate', title: '发货任务', api_url: '/api/ship', completed: false },
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:close-assistant-float', handler)
    await api.sendMessage('生成发货单')
    await vi.waitFor(() => {
      expect(handler).toHaveBeenCalled()
    })
    window.removeEventListener('xcagi:close-assistant-float', handler)
  })
})

describe('useChatOrchestration coverage – confirmTask 各分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('GET 方法成功', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, message: 'GET 成功' }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '查询',
      api_url: '/api/get',
      method: 'GET',
      payload: {},
    })
    await api.confirmTask()
    expect(fetch).toHaveBeenCalledWith('/api/get')
    expect(api.currentTask.value?.completed).toBe(true)
    vi.unstubAllGlobals()
  })

  it('POST 返回非 ok 时报告失败', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ message: '服务器错误' }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '测试',
      api_url: '/api/test',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('服务器错误'),
      'ai',
      undefined,
      expect.any(Object),
    )
    expect(api.currentTask.value).toBeNull()
    vi.unstubAllGlobals()
  })

  it('fetch 抛出异常时通过 errorMessage 报告', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('网络断开')))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '测试',
      api_url: '/api/test',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('网络断开'),
      'ai',
      undefined,
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })

  it('fetch 抛出非 Error 类型时使用 fallback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(null))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '测试',
      api_url: '/api/test',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('网络错误'),
      'ai',
      undefined,
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })

  it('requires_token 响应保留任务卡片并弹出令牌输入', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          requires_token: true,
          token_name: 'DB_WRITE_TOKEN',
          token_description: '需要二级写入令牌',
          message: '请输入令牌',
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '写库',
      api_url: '/api/write',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockHandleChatRequiresToken).toHaveBeenCalled()
    expect(api.currentTask.value).toBeTruthy()
    expect(api.currentTask.value?.description).toContain('令牌')
    vi.unstubAllGlobals()
  })

  it('shipment_generate 成功时设置 lastShipmentExecution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '生成成功',
          order_number: 'ORD-1',
          file_path: '/tmp/doc.pdf',
          labels: ['/tmp/label.pdf'],
          purchase_unit: '甲公司',
          order_id: 100,
          doc_name: 'doc.pdf',
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: { params: {} },
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value).toBeTruthy()
    expect(state.lastShipmentExecution!.value?.filePath).toBe('/tmp/doc.pdf')
    vi.unstubAllGlobals()
  })

  it('shipment_generate 成功且有 switch_view 时触发 autoAction', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '成功',
          order_number: 'ORD-1',
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: {},
      switch_view: 'show_products',
    })
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    await api.confirmTask()
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
    vi.unstubAllGlobals()
  })

  it('shipment_generate 无 customOrderNumber 时先 hydrate', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, message: '成功' }),
      }),
    )
    mockHydrateTaskOrderNumber.mockResolvedValue(undefined)
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: { params: { order_number: 'OLD' } },
    })
    await api.confirmTask()
    expect(mockHydrateTaskOrderNumber).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

describe('useChatOrchestration coverage – handleAutoAction 各分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  afterEach(() => {
    delete (window as unknown as { setWorkModeFromChat?: unknown }).setWorkModeFromChat
    delete (window as unknown as { legacyAutoActionHandler?: unknown }).legacyAutoActionHandler
  })

  it('show_materials 派发 switch-view', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_materials' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('show_meeting_minutes_float 派发 open-meeting-minutes 并打开会议纪要面板', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-meeting-minutes', handler)
    api.handleAutoAction({ type: 'show_meeting_minutes_float' })
    expect(handler).toHaveBeenCalled()
    expect(handler.mock.calls[0][0].detail.forceOpen).toBe(true)
    window.removeEventListener('xcagi:open-meeting-minutes', handler)
  })

  it('show_print 派发 switch-view 到 print', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_print' })
    expect(handler).toHaveBeenCalled()
    const detail = handler.mock.calls[0][0].detail
    expect(detail.view).toBe('print')
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('show_customers 派发 switch-view', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_customers' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('show_labels_export 派发 switch-view 到 print', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_labels_export' })
    expect(handler).toHaveBeenCalled()
    expect(handler.mock.calls[0][0].detail.view).toBe('print')
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('show_products 在 pro 模式下额外派发 switch-view 到 products', () => {
    const api = createApi()
    api.isProMode.value = true
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    api.handleAutoAction({ type: 'show_products', query: '5003A' })
    expect(handler).toHaveBeenCalled()
    const views = handler.mock.calls.map((c) => c[0].detail.view)
    expect(views).toContain('products')
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('set_work_mode 在非 pro 模式下早返回不调用 legacyAutoActionHandler', () => {
    const api = createApi()
    api.isProMode.value = false
    const legacyFn = vi.fn()
    ;(window as unknown as { legacyAutoActionHandler: typeof legacyFn }).legacyAutoActionHandler = legacyFn
    api.handleAutoAction({ type: 'set_work_mode' }, 'msg')
    expect(legacyFn).not.toHaveBeenCalled()
  })

  it('有 legacyAutoActionHandler 时调用它', () => {
    const api = createApi()
    const legacyFn = vi.fn()
    ;(window as unknown as { legacyAutoActionHandler: typeof legacyFn }).legacyAutoActionHandler = legacyFn
    api.handleAutoAction({ type: 'show_orders' }, '查询订单')
    expect(legacyFn).toHaveBeenCalled()
  })

  it('show_products 派发 assistant-push 事件', () => {
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:assistant-push', handler)
    api.handleAutoAction({ type: 'show_products', query: '5003A' })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:assistant-push', handler)
  })
})

describe('useChatOrchestration coverage – sendMessage 各分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  afterEach(() => {
    delete (window as unknown as { isProTaskAcquisitionMessage?: unknown }).isProTaskAcquisitionMessage
    delete (window as unknown as { jarvisSendMessage?: unknown }).jarvisSendMessage
  })

  it('handleShipmentModify 返回 true 时跳过后续', async () => {
    mockHandleShipmentModify.mockResolvedValue(true)
    const api = createApi()
    await api.sendMessage('修改发货单')
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('pro 模式下 isProTaskAcquisitionMessage 返回 true 时走 jarvisSendMessage', async () => {
    const api = createApi()
    api.isProMode.value = true
    const isProFn = vi.fn(() => true)
    const jarvisFn = vi.fn()
    ;(window as unknown as { isProTaskAcquisitionMessage: typeof isProFn }).isProTaskAcquisitionMessage = isProFn
    ;(window as unknown as { jarvisSendMessage: typeof jarvisFn }).jarvisSendMessage = jarvisFn
    await api.sendMessage('采集任务')
    expect(jarvisFn).toHaveBeenCalledWith('采集任务')
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('debounce > 0 时走 enqueueChatBatchMessage', async () => {
    mockGetChatBatchDebounceMs.mockReturnValue(300)
    mockEnqueueChatBatchMessage.mockImplementation(
      (_msg: string, _ms: number, cb: (m: string[]) => void) => {
        cb(['batch-msg'])
      },
    )
    mockRequestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '批量回复' })
    const api = createApi()
    await api.sendMessage('普通消息')
    expect(mockEnqueueChatBatchMessage).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – executeRemoteChatRound 快路径', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('产品快路径有结果时打开副窗', async () => {
    mockExtractLikelyProductQueryKeyword.mockReturnValue('5003A')
    mockSearchProducts.mockResolvedValue({
      success: true,
      data: [{ id: 1, model_number: '5003A', name: '清漆', price: 120 }],
      total: 1,
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    await api.sendMessage('查5003A')
    expect(mockSearchProducts).toHaveBeenCalledWith('5003A')
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })

  it('产品快路径无结果时不打开副窗', async () => {
    mockExtractLikelyProductQueryKeyword.mockReturnValue('不存在的产品')
    mockSearchProducts.mockResolvedValue({
      success: true,
      data: [],
      total: 0,
    })
    const api = createApi()
    await api.sendMessage('查不存在的产品')
    expect(mockSearchProducts).toHaveBeenCalled()
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('产品快路径 success:false 时回退到聊天', async () => {
    mockExtractLikelyProductQueryKeyword.mockReturnValue('5003A')
    mockSearchProducts.mockResolvedValue({
      success: false,
      message: '查询失败',
    })
    mockRequestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '回复' })
    const api = createApi()
    await api.sendMessage('查5003A')
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalled()
  })

  it('产品快路径从 products 字段获取数据', async () => {
    mockExtractLikelyProductQueryKeyword.mockReturnValue('5003A')
    mockSearchProducts.mockResolvedValue({
      products: [{ id: 1, model_number: '5003A', name: '清漆', price: 120 }],
      total: 1,
    })
    const api = createApi()
    await api.sendMessage('查5003A')
    expect(mockSearchProducts).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – executeRemoteChatRound 批量', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    mockGetChatBatchDebounceMs.mockReturnValue(300)
    mockEnqueueChatBatchMessage.mockImplementation(
      (_msg: string, _ms: number, cb: (m: string[]) => void) => {
        cb(['first', 'second'])
      },
    )
  })

  it('批量成功且有 requires_token 部分', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1' },
        { success: true, response: 'part-2', requires_token: true, token_name: 'DB_READ_TOKEN', token_description: '读取令牌' },
      ],
    })
    const api = createApi()
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(mockHandleChatRequiresToken).toHaveBeenCalled()
    })
  })

  it('批量成功但有部分失败', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1' },
        { success: false, message: 'part-2 失败' },
      ],
    })
    const api = createApi()
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
        expect.stringContaining('part-2 失败'),
        'ai',
        undefined,
        expect.any(Object),
      )
    })
  })

  it('批量整体失败', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: false,
      batch: true,
      message: '批量请求失败',
      results: [],
    })
    const api = createApi()
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
        expect.stringContaining('批量请求失败'),
        'ai',
        undefined,
        expect.any(Object),
      )
    })
  })

  it('批量成功且有 task', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1', task: { type: 'custom', title: '新任务', api_url: '/x' } },
      ],
    })
    const api = createApi()
    await api.sendMessage('批量')
  })

  it('批量成功且有 autoAction show_products_float', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1', autoAction: { type: 'show_products_float', query: '5003' } },
      ],
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(handler).toHaveBeenCalled()
    })
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })
})

describe('useChatOrchestration coverage – executeRemoteChatRound 单条 JSON', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('单条成功且有 task', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '回复',
      task: { type: 'custom', title: '新任务', api_url: '/x' },
    })
    const api = createApi()
    await api.sendMessage('普通')
  })

  it('单条成功且有 autoAction', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '回复',
      autoAction: { type: 'show_orders' },
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    await api.sendMessage('普通')
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('单条成功且有 requires_token', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '',
      requires_token: true,
      token_name: 'DB_READ_TOKEN',
      token_description: '读取令牌',
    })
    const api = createApi()
    await api.sendMessage('查数据')
    expect(mockHandleChatRequiresToken).toHaveBeenCalled()
  })

  it('单条失败', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: false,
      message: '处理出错',
    })
    const api = createApi()
    await api.sendMessage('普通')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('处理出错'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('单条请求抛出异常', async () => {
    mockRequestChatByModeWithTimeout.mockRejectedValue(new Error('请求超时'))
    const api = createApi()
    await api.sendMessage('普通')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('请求超时'),
      'ai',
      undefined,
      expect.any(Object),
    )
  })

  it('单条请求抛出非 Error 类型', async () => {
    mockRequestChatByModeWithTimeout.mockRejectedValue('字符串错误')
    const api = createApi()
    await api.sendMessage('普通')
    await vi.waitFor(() => {
      expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
        expect.stringContaining('字符串错误'),
        'ai',
        undefined,
        expect.any(Object),
      )
    })
  })

  it('workflow_done action 设置 loadingProgress', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '完成',
      data: { action: 'workflow_done', data: {} },
    })
    const api = createApi()
    await api.sendMessage('执行')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('执行完成，正在整理结果...')
  })

  it('workflow_failed action 设置 loadingProgress', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '失败',
      data: { action: 'workflow_failed', data: {} },
    })
    const api = createApi()
    await api.sendMessage('执行')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('执行失败，正在整理错误信息...')
  })
})

describe('useChatOrchestration coverage – executeRemoteChatRound 流式', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    mockIsChatStreamEnabled.mockReturnValue(true)
    mockSendChatStream.mockResolvedValue({ ok: true, body: {} })
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '你' })
      onEvent({ type: 'token', text: '好' })
      onEvent({ type: 'done', result: { success: true, response: '你好' } })
    })
  })

  it('流式成功并触发 task', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'done', result: { success: true, response: '回复', task: { type: 'custom', title: '任务', api_url: '/x' } } })
    })
    const api = createApi()
    await api.sendMessage('hello')
  })

  it('流式成功并触发 autoAction', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'done', result: { success: true, response: '回复', autoAction: { type: 'show_orders' } } })
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    await api.sendMessage('hello')
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('流式 requires_token 事件且为 WRITE 令牌时保存 resumeDraft', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入令牌' })
      onEvent({ type: 'done', result: { success: true, response: '' } })
    })
    const api = createApi()
    await api.sendMessage('导入数据')
    expect(mockHandleChatRequiresToken).toHaveBeenCalled()
  })

  it('流式 AbortError 时报告超时', async () => {
    const abortErr = new Error('Aborted')
    abortErr.name = 'AbortError'
    mockSendChatStream.mockRejectedValue(abortErr)
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(
      0,
      expect.stringContaining('超时'),
    )
  })

  it('流式非 Abort 错误时报告失败', async () => {
    mockSendChatStream.mockRejectedValue(new Error('连接断开'))
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(
      0,
      expect.stringContaining('连接断开'),
    )
  })

  it('流式 done 无 result 时用 streamPlain 兜底', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '纯文本' })
      onEvent({ type: 'done', result: null })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockSaveMessage).toHaveBeenCalled()
  })

  it('流式 done 有 result 但无 response 时用 streamPlain', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '内容' })
      onEvent({ type: 'done', result: { success: true } })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockSaveMessage).toHaveBeenCalled()
  })

  it('流式 SSE error 事件时报告错误', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'error', message: '模型不可用' })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(
      0,
      expect.stringContaining('模型不可用'),
    )
  })

  it('流式 HTTP 非 ok 时报告错误', async () => {
    mockSendChatStream.mockResolvedValue({ ok: false, status: 502 })
    mockParseChatStreamErrorResponse.mockResolvedValue('服务不可用')
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(
      0,
      expect.stringContaining('处理失败'),
    )
  })
})

describe('useChatOrchestration coverage – maybePrefetchProductAssistantFloat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('非快路径且有 keyword 时 prefetch 副窗', async () => {
    mockExtractLikelyProductQueryKeyword.mockReturnValue('5003A')
    const api = useChatOrchestration({
      sessionId: ref('test'),
      proIntentExperienceEnabled: ref(true),
    })
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    await api.sendMessage('查5003A')
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })
})

describe('useChatOrchestration coverage – copyAssistantPushContent', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('有内容时设置 pushCopied 并定时重置', async () => {
    vi.useFakeTimers()
    const api = createApi()
    api.latestAssistantPush.value = { title: '标题', description: '描述' }
    await api.copyAssistantPushContent()
    expect(api.pushCopied.value).toBe(true)
    vi.advanceTimersByTime(1300)
    expect(api.pushCopied.value).toBe(false)
    vi.useRealTimers()
  })

  it('无内容时不设置 pushCopied', async () => {
    const api = createApi()
    api.latestAssistantPush.value = null
    await api.copyAssistantPushContent()
    expect(api.pushCopied.value).toBe(false)
  })

  it('只有 title 无 description 时也能复制', async () => {
    const api = createApi()
    api.latestAssistantPush.value = { title: '标题', description: '' }
    await api.copyAssistantPushContent()
    expect(api.pushCopied.value).toBe(true)
  })
})

describe('useChatOrchestration coverage – 生命周期钩子', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('onMounted 恢复 excel 上下文并注册事件监听', () => {
    mockReadPersistedExcelAnalysisContext.mockReturnValue({ file_name: 'restored.xlsx' })
    state.excelSheetOptions!.value = [{ name: 'Sheet1' }]

    const TestComp = defineComponent({
      setup() {
        useChatOrchestration({
          sessionId: ref('lifecycle'),
          proIntentExperienceEnabled: ref(false),
        })
        return () => h('div')
      },
    })
    const app = createApp(TestComp)
    const el = document.createElement('div')
    app.mount(el)
    expect(mockReadPersistedExcelAnalysisContext).toHaveBeenCalledWith('lifecycle')
    expect(state.lastExcelAnalysisContext!.value).toBeTruthy()
    expect(state.linkedExcelSheet!.value).toEqual({ name: 'Sheet1' })
    app.unmount()
  })

  it('onMounted 已有 excel 上下文时不恢复', () => {
    state.lastExcelAnalysisContext!.value = { file_name: 'existing.xlsx' }
    mockReadPersistedExcelAnalysisContext.mockReturnValue(null)

    const TestComp = defineComponent({
      setup() {
        useChatOrchestration({
          sessionId: ref('lifecycle2'),
          proIntentExperienceEnabled: ref(false),
        })
        return () => h('div')
      },
    })
    const app = createApp(TestComp)
    const el = document.createElement('div')
    app.mount(el)
    expect(state.lastExcelAnalysisContext!.value).toEqual({ file_name: 'existing.xlsx' })
    app.unmount()
  })

  it('onMounted 已有 linkedExcelSheet 时不覆盖', () => {
    state.linkedExcelSheet!.value = { name: 'Existing' }
    state.excelSheetOptions!.value = [{ name: 'Sheet1' }, { name: 'Sheet2' }]

    const TestComp = defineComponent({
      setup() {
        useChatOrchestration({
          sessionId: ref('lifecycle3'),
          proIntentExperienceEnabled: ref(false),
        })
        return () => h('div')
      },
    })
    const app = createApp(TestComp)
    const el = document.createElement('div')
    app.mount(el)
    expect(state.linkedExcelSheet!.value).toEqual({ name: 'Existing' })
    app.unmount()
  })

  it('onBeforeUnmount 移除事件监听', () => {
    const TestComp = defineComponent({
      setup() {
        useChatOrchestration({
          sessionId: ref('unmount'),
          proIntentExperienceEnabled: ref(false),
        })
        return () => h('div')
      },
    })
    const app = createApp(TestComp)
    const el = document.createElement('div')
    app.mount(el)
    app.unmount()
  })
})

describe('useChatOrchestration coverage – syncSessionMessages', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('调用 syncFromServer 并应用持久化状态', async () => {
    const api = createApi()
    await api.syncSessionMessages()
    expect(mockSyncFromServer).toHaveBeenCalled()
  })
})

describe('useChatOrchestration coverage – errorMessage 间接覆盖', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('confirmTask fetch 异常时 errorMessage 处理 Error 对象', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('连接超时')))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '测试',
      api_url: '/api/test',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('连接超时'),
      'ai',
      undefined,
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })

  it('confirmTask fetch 异常时 errorMessage 处理非 Error 值', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(null))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      title: '测试',
      api_url: '/api/test',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('网络错误'),
      'ai',
      undefined,
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })
})

describe('useChatOrchestration coverage – buildTaskCompletedDescription / extractShipmentExecutionContext', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
  })

  it('confirmTask shipment_generate 成功且数据含 labels 对象数组', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '成功',
          order_number: 'ORD-1',
          file_path: '/tmp/doc.pdf',
          purchase_unit: '甲公司',
          order_id: 200,
          labels: [
            { file_path: '/tmp/label1.pdf' },
            { path: '/tmp/label2.pdf' },
            { filePath: '/tmp/label3.pdf' },
            { filepath: '/tmp/label4.pdf' },
            '  /tmp/label5.pdf  ',
            '',
            null,
          ],
          doc_name: 'doc.pdf',
          record_id: 999,
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value).toBeTruthy()
    expect(state.lastShipmentExecution!.value?.labelPaths.length).toBeGreaterThan(0)
    vi.unstubAllGlobals()
  })

  it('confirmTask shipment_generate 成功且数据嵌套在 data 字段', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '成功',
          data: {
            order_number: 'ORD-2',
            file_path: '/tmp/doc2.pdf',
            purchase_unit: '乙公司',
            order_id: 300,
            labels: ['/tmp/label.pdf'],
            doc_name: 'doc2.pdf',
          },
          document: { filename: 'doc2.pdf', filepath: '/tmp/doc2.pdf' },
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value?.filePath).toBe('/tmp/doc2.pdf')
    vi.unstubAllGlobals()
  })

  it('confirmTask shipment_generate 成功且有 download_url', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '成功',
          order_number: 'ORD-3',
          download_url: '/api/shipment/download/doc.pdf',
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('成功'),
      'ai',
      expect.objectContaining({ shipmentDownloadUrl: '/api/shipment/download/doc.pdf' }),
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })

  it('confirmTask shipment_generate 成功且无 download_url 但有 doc_name', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          message: '成功',
          order_number: 'ORD-4',
          doc_name: 'doc4.pdf',
        }),
      }),
    )
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate',
      completed: false,
      api_url: '/api/shipment',
      method: 'POST',
      payload: {},
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.any(String),
      'ai',
      expect.objectContaining({ shipmentDownloadUrl: '/api/shipment/download/doc4.pdf' }),
      expect.any(Object),
    )
    vi.unstubAllGlobals()
  })
})

describe('useChatOrchestration coverage – proIntentExperienceEnabled 流式 loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    mockIsChatStreamEnabled.mockReturnValue(true)
    mockSendChatStream.mockResolvedValue({ ok: true, body: {} })
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'done', result: { success: true, response: '回复' } })
    })
  })

  it('proIntentExperienceEnabled 且非 pro 模式时 loading 显示专业意图处理中', async () => {
    mockResolveEffectiveProModeState.mockReturnValue(false)
    const api = useChatOrchestration({
      sessionId: ref('hybrid'),
      proIntentExperienceEnabled: ref(true),
    })
    await api.sendMessage('hello')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('专业意图处理中（流式）…')
  })
})

describe('useChatOrchestration coverage – proIntentExperienceEnabled 非流式 loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    mockIsChatStreamEnabled.mockReturnValue(false)
    mockResolveEffectiveProModeState.mockReturnValue(false)
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '回复',
      data: { action: 'workflow_confirmation_required', data: {} },
    })
  })

  it('proIntentExperienceEnabled 且非 pro 模式时 loading 显示专业意图处理中', async () => {
    const api = useChatOrchestration({
      sessionId: ref('hybrid2'),
      proIntentExperienceEnabled: ref(true),
    })
    await api.sendMessage('hello')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('专业意图处理中（普通界面槽位）...')
  })
})
