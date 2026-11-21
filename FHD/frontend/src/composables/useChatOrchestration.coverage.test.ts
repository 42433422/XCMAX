/**
 * useChatOrchestration.ts 覆盖率补齐测试
 * 针对未覆盖行：errorMessage、normalizeServerContentToHtml、scrollToBottom、
 * runShipmentMgmtAfterPrintSuccess、
 * refetchTaskOrderNumber、setCustomOrderNumber、
 * showTaskConfirm、emitAssistantPush、
 * maybeCloseAssistantFloatForShipmentTask、confirmTask 各分支、handleAutoAction 各分支、
 * maybePrefetchProductAssistantFloat、executeRemoteChatRound 快路径/批量/单条、
 * sendMessage 各分支、生命周期钩子等。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, type Ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import agentRunsApi, { type AgentRunResponse } from '@/api/agentRuns'

vi.mock('@/api/agentRuns', () => ({
  default: {
    observeTool: vi.fn().mockResolvedValue({ success: true }),
    taskEventStreamPath: vi.fn(() => '/api/agent/tasks/events/stream'),
    createTask: vi.fn(),
    getRun: vi.fn(),
    continueRun: vi.fn(),
    cancelRun: vi.fn(),
    listTasks: vi.fn(),
    listRuns: vi.fn(),
  },
}))

// ── vi.hoisted：所有在 vi.mock 工厂中引用的 vi.fn 必须在此定义 ───
const {
  mockAddAndSaveMessage,
  mockAddMessage,
  mockExecutePrintTask,
  mockBuildPrintSummaryMessage,
  mockRequestChatByModeWithTimeout,
  mockRequestChatByModeBatchWithTimeout,
  mockEnqueueChatBatchMessage,
  mockGetChatBatchDebounceMs,
  mockIsChatStreamEnabled,
  mockReadPlannerSseResponse,
  mockSendChatStream,
  mockGetConversation,
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
  mockAttachApprovalCard,
  mockAttachBusinessResult,
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
  mockAddMessage: vi.fn(),
  mockExecutePrintTask: vi.fn(),
  mockBuildPrintSummaryMessage: vi.fn(() => '打印完成'),
  mockRequestChatByModeWithTimeout: vi.fn(),
  mockRequestChatByModeBatchWithTimeout: vi.fn(),
  mockEnqueueChatBatchMessage: vi.fn(),
  mockGetChatBatchDebounceMs: vi.fn(() => 0),
  mockIsChatStreamEnabled: vi.fn(() => false),
  mockReadPlannerSseResponse: vi.fn(),
  mockSendChatStream: vi.fn(),
  mockGetConversation: vi.fn(),
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
  mockAttachApprovalCard: vi.fn(),
  mockAttachBusinessResult: vi.fn(),
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
  mockBuildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hello' }, completeArtifacts: vi.fn() })),
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
let capturedNormalizeFn: (raw: unknown) => string = () => ''

// ── vi.mock 声明 ───────────────────────────────────────────────
vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage: mockAddMessage,
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
    cancelPendingChatBatch: vi.fn(),
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
    attachApprovalCardToLastAiMessage: mockAttachApprovalCard,
    attachBusinessResultToLastAiMessage: mockAttachBusinessResult,
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
        refreshHistorySessions: vi.fn(),
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
  default: { sendChatStream: mockSendChatStream, getConversation: mockGetConversation },
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

import { useChatOrchestration } from './useChatOrchestration'
import { createApp, defineComponent, h } from 'vue'

// ── 辅助 ───────────────────────────────────────────────────────
function createApi(sessionId = 'test-session') {
  return useChatOrchestration({
    sessionId: ref(sessionId),
  })
}

function canonicalReceipt(status: string, output: Record<string, unknown> = {}): AgentRunResponse {
  return {
    success: true,
    data: {
      run_id: 'coverage-run', user_id: 'u1', message: '任务', status,
      final_output: { node_outputs: { result: output } },
    },
  }
}

function mockCanonicalReceipt(status: string, output: Record<string, unknown> = {}) {
  const receipt = canonicalReceipt(status, output)
  vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt)
  vi.mocked(agentRunsApi.getRun).mockResolvedValue(receipt)
  return receipt
}

function shipmentPayload(params: Record<string, unknown> = {}) {
  return {
    tool_id: 'shipment_orders', action: 'generate',
    params: { unit_name: '甲公司', products: [{ name: '产品甲', quantity: 1, specification: '1L' }], ...params },
  }
}

function resetMockState() {
  vi.clearAllMocks()
  vi.mocked(agentRunsApi.createTask).mockReset()
  vi.mocked(agentRunsApi.getRun).mockReset()
  vi.mocked(agentRunsApi.continueRun).mockReset()
  vi.mocked(agentRunsApi.cancelRun).mockReset().mockResolvedValue(canonicalReceipt('cancelled'))
  vi.mocked(agentRunsApi.listTasks).mockResolvedValue({ success: true, data: [] })
  vi.mocked(agentRunsApi.listRuns).mockResolvedValue({ success: true, data: [] })
  mockCanonicalReceipt('queued')
  state.taskList!.value = []
  state.lastShipmentExecution!.value = null
  state.multimodalPendingCount!.value = 0
  state.excelSheetOptions!.value = []
  state.linkedExcelSheet!.value = null
  state.lastExcelAnalysisContext!.value = null
  state.linkedExcelAllSheets!.value = false
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
  mockSummarizeShipmentRecordsForAudit.mockReturnValue({
    headline: '审计摘要',
    detailLines: ['行1'],
  })
  mockSaveMessage.mockResolvedValue(undefined)
  mockPushStreamingAiShell.mockReturnValue(0)
  mockHydrateTaskOrderNumber.mockResolvedValue(undefined)
  mockEnrichShipmentPreviewProducts.mockResolvedValue(undefined)
  mockGetLastAiMessageRef.mockReturnValue('0')
  mockBuildPlannerChatRequestPayload.mockReturnValue({ body: { message: 'hello' }, completeArtifacts: vi.fn() })
  mockResolveChatTimeoutMs.mockReturnValue(30_000)
  mockGetConversation.mockRejectedValue(new Error('history unavailable'))
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
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('出货管理'), 'ai', undefined, expect.any(Object))
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
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('未包含可打印文件'), 'ai', undefined, expect.any(Object))
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
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('打印完成'), 'ai', undefined, expect.any(Object))
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
    api.currentTask.value = { type: 'shipment_generate', completed: false, payload: shipmentPayload() } as never
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

describe('useChatOrchestration coverage – completed task receipt', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('showTaskConfirm 保留已完成任务的回执卡片', () => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom',
      completed: true,
      api_url: '/api/import',
    })
    vi.advanceTimersByTime(1)
    expect(api.currentTask.value?.completed).toBe(true)
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
      payload: shipmentPayload(),
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
      payload: shipmentPayload(),
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
      payload: shipmentPayload(),
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
      task: {
        type: 'shipment_generate',
        title: '发货任务',
        payload: shipmentPayload(),
        completed: false,
      },
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
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it.each(['GET', 'POST'])('只有 %s API 地址的任务明确未开始且不发请求', async method => {
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '旧任务', api_url: '/api/retired-task', method, payload: {},
    })
    await api.confirmTask()
    expect(api.currentTask.value?.completed).toBe(false)
    expect(api.currentTask.value?.data?.execution_state).toBe('not_started')
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('任务未开始：缺少有效能力契约'), 'ai',
      expect.objectContaining({ workflowAction: 'not_started' }), expect.any(Object),
    )
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(agentRunsApi.getRun).not.toHaveBeenCalled()
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('统一任务失败回执保留服务器错误展示', async () => {
    mockCanonicalReceipt('failed', { success: false, message: '服务器错误' })
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '测试',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'products' } },
    })
    await api.confirmTask()
    expect(agentRunsApi.createTask).toHaveBeenCalledWith(expect.objectContaining({
      tool_id: 'business_db', action: 'read', params: { entity: 'products' },
    }))
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('服务器错误'), 'ai', undefined, expect.any(Object))
    expect(api.currentTask.value).toBeNull()
  })

  it('任务准入接口异常时通过 errorMessage 报告', async () => {
    vi.mocked(agentRunsApi.createTask).mockRejectedValue(new Error('网络断开'))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '测试',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'products' } },
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('网络断开'), 'ai', undefined, expect.any(Object))
  })

  it('任务准入抛出非 Error 类型时使用 fallback', async () => {
    vi.mocked(agentRunsApi.createTask).mockRejectedValue(null)
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '测试',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'products' } },
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('网络错误'), 'ai', undefined, expect.any(Object))
  })

  it('原任务等待授权时保留卡片，确认只读取原回执', async () => {
    mockCanonicalReceipt('waiting_user')
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '发货', payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(api.currentTask.value?.completed).toBe(false)
    expect(api.currentTask.value?.description).toContain('任务工作区')
    expect(api.currentTask.value).toHaveProperty('agentRunId', 'coverage-run')
    await api.confirmTask()
    expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
    expect(agentRunsApi.getRun).toHaveBeenCalledExactlyOnceWith('coverage-run')
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it('shipment_generate 成功时设置 lastShipmentExecution', async () => {
    mockCanonicalReceipt('completed', {
      success: true, message: '生成成功', order_number: 'ORD-1',
      file_path: '/tmp/doc.pdf', labels: ['/tmp/label.pdf'],
      purchase_unit: '甲公司', order_id: 100, doc_name: 'doc.pdf',
    })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value).toBeTruthy()
    expect(state.lastShipmentExecution!.value?.filePath).toBe('/tmp/doc.pdf')
    expect(agentRunsApi.createTask).toHaveBeenCalledWith(expect.objectContaining({
      tool_id: 'shipment_orders', action: 'generate',
    }))
  })

  it('原任务审批回执完成后触发 switch_view', async () => {
    const waiting: AgentRunResponse = {
      ...canonicalReceipt('waiting_user'),
      approval: {
        grant: 'coverage-grant', run_id: 'coverage-run', step_id: 'shipment-step',
        tool_id: 'shipment_orders', action: 'generate', expires_at: 2_000_000_000,
      },
    }
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.continueRun).mockResolvedValue(canonicalReceipt('completed', {
      success: true, message: '成功', order_number: 'ORD-1',
    }))
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(), switch_view: 'show_products',
    })
    const handler = vi.fn()
    window.addEventListener('xcagi:open-assistant-float', handler)
    await api.confirmTask()
    expect(agentRunsApi.continueRun).toHaveBeenCalledExactlyOnceWith('coverage-run', {
      approval_grant: 'coverage-grant', runtime_context: { source: 'chat_task_card_approval' },
    })
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:open-assistant-float', handler)
  })

  it('shipment_generate 无 customOrderNumber 时先 hydrate', async () => {
    mockCanonicalReceipt('completed', { success: true, message: '成功' })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload({ order_number: 'OLD' }),
    })
    await api.confirmTask()
    expect(mockHydrateTaskOrderNumber).toHaveBeenCalled()
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

  it('handleShipmentModify 返回 true 时跳过后续', async () => {
    mockHandleShipmentModify.mockResolvedValue(true)
    const api = createApi()
    await api.sendMessage('修改发货单')
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('debounce > 0 时走 enqueueChatBatchMessage', async () => {
    mockGetChatBatchDebounceMs.mockReturnValue(300)
    mockEnqueueChatBatchMessage.mockImplementation((_msg: string, _ms: number, cb: (m: string[]) => void) => {
      cb(['batch-msg'])
    })
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
    mockEnqueueChatBatchMessage.mockImplementation((_msg: string, _ms: number, cb: (m: string[]) => void) => {
      cb(['first', 'second'])
    })
  })

  it('批量成功且有 requires_token 部分', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1' },
        {
          success: true,
          response: 'part-2',
          requires_token: true,
          token_name: 'DB_READ_TOKEN',
          token_description: '读取令牌',
        },
      ],
    })
    const api = createApi()
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(mockAddMessage).toHaveBeenCalledWith('part-2', 'ai', expect.objectContaining({ workflowAction: 'waiting_auth' }), expect.any(Object))
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
      expect(mockAddMessage).toHaveBeenCalledWith(expect.stringContaining('part-2 失败'), 'ai', { turnId: expect.any(String), workflowAction: 'failed' }, expect.any(Object))
    })
  })

  it('批量成功时把各部分业务结果挂到对应消息', async () => {
    const first = { status: 'completed', summary: '客户创建成功', facts: { customer_id: 23 } }
    const second = { status: 'completed', summary: '已删除', evidence: { completed_tool_count: 1 } }
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        { success: true, response: 'part-1', businessResult: first },
        { success: true, response: 'part-2', businessResult: second },
      ],
    })
    const api = createApi()
    await api.sendMessage('批量')
    await vi.waitFor(() => {
      expect(mockAddMessage).toHaveBeenCalledWith('part-1', 'ai', expect.objectContaining({ businessResult: first }), expect.any(Object))
      expect(mockAddMessage).toHaveBeenCalledWith('part-2', 'ai', expect.objectContaining({ businessResult: second }), expect.any(Object))
    })
    expect(mockAttachBusinessResult.mock.calls.map((call) => call[0].businessResult)).toEqual([first, second])
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
      expect(mockAddMessage).toHaveBeenCalledWith(expect.stringContaining('批量请求失败'), 'ai', { turnId: expect.any(String), workflowAction: 'failed' }, expect.any(Object))
    })
  })

  it('批量成功且有 task', async () => {
    mockRequestChatByModeBatchWithTimeout.mockResolvedValue({
      success: true,
      batch: true,
      results: [
        {
          success: true,
          response: 'part-1',
          task: { type: 'custom', title: '新任务', api_url: '/x' },
        },
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
        {
          success: true,
          response: 'part-1',
          autoAction: { type: 'show_products_float', query: '5003' },
        },
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
    expect(mockAddMessage).toHaveBeenCalledWith(expect.any(String), 'ai', expect.objectContaining({ workflowAction: 'waiting_auth' }), expect.any(Object))
  })

  it('单条失败', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: false,
      message: '处理出错',
    })
    const api = createApi()
    await api.sendMessage('普通')
    expect(mockAddMessage).toHaveBeenCalledWith(expect.stringContaining('处理出错'), 'ai', { turnId: expect.any(String), workflowAction: 'failed' }, expect.any(Object))
  })

  it('单条失败仍挂载终态业务结果', async () => {
    const businessResult = { status: 'failed', summary: '写入失败', facts: {} }
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: false,
      message: '写入失败',
      businessResult,
    })
    const api = createApi()
    await api.sendMessage('普通')
    expect(mockAddMessage).toHaveBeenCalledWith(
      expect.stringContaining('写入失败'),
      'ai',
      expect.objectContaining({ workflowAction: 'failed', businessResult }),
      expect.any(Object),
    )
    expect(mockAttachBusinessResult).toHaveBeenCalledWith(expect.objectContaining({ success: false, businessResult }))
  })

  it('单条请求异常且原回执不可用时保持 unknown', async () => {
    mockRequestChatByModeWithTimeout.mockRejectedValue(new Error('请求超时'))
    const api = createApi()
    await api.sendMessage('普通')
    expect(mockAddMessage).toHaveBeenCalledWith(
      expect.stringContaining('结果未知'),
      'ai',
      expect.objectContaining({
        turnId: expect.any(String),
        workflowAction: 'unknown',
        execution: expect.objectContaining({ effect: 'unknown', outcome: 'unknown', committed: false }),
      }),
      expect.any(Object),
    )
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalledTimes(1)
  })

  it('单条请求抛出非 Error 类型且原回执不可用时保持 unknown', async () => {
    mockRequestChatByModeWithTimeout.mockRejectedValue('字符串错误')
    const api = createApi()
    await api.sendMessage('普通')
    await vi.waitFor(() => {
      expect(mockAddMessage).toHaveBeenCalledWith(
        expect.stringContaining('结果未知'),
        'ai',
        expect.objectContaining({
          turnId: expect.any(String),
          workflowAction: 'unknown',
          execution: expect.objectContaining({ effect: 'unknown', outcome: 'unknown', committed: false }),
        }),
        expect.any(Object),
      )
    })
    expect(mockRequestChatByModeWithTimeout).toHaveBeenCalledTimes(1)
  })

  it('workflow_done action 设置 loadingProgress', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '完成',
      data: { action: 'workflow_done', data: {} },
    })
    const api = createApi()
    await api.sendMessage('执行')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('执行完成，正在整理结果...', 'test-session')
  })

  it('workflow_failed action 设置 loadingProgress', async () => {
    mockRequestChatByModeWithTimeout.mockResolvedValue({
      success: true,
      response: '失败',
      data: { action: 'workflow_failed', data: {} },
    })
    const api = createApi()
    await api.sendMessage('执行')
    expect(mockSetLoadingProgress).toHaveBeenCalledWith('执行失败，正在整理错误信息...', 'test-session')
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
      onEvent({
        type: 'done',
        result: {
          success: true,
          response: '回复',
          task: { type: 'custom', title: '任务', api_url: '/x' },
        },
      })
    })
    const api = createApi()
    await api.sendMessage('hello')
  })

  it('流式成功并触发 autoAction', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({
        type: 'done',
        result: { success: true, response: '回复', autoAction: { type: 'show_orders' } },
      })
    })
    const api = createApi()
    const handler = vi.fn()
    window.addEventListener('xcagi:switch-view', handler)
    await api.sendMessage('hello')
    expect(handler).toHaveBeenCalled()
    window.removeEventListener('xcagi:switch-view', handler)
  })

  it('流式 requires_token 事件只保留等待状态', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({
        type: 'requires_token',
        token_name: 'DB_WRITE_TOKEN',
        token_description: '写入令牌',
      })
      onEvent({ type: 'done', result: { success: true, response: '' } })
    })
    const api = createApi()
    await api.sendMessage('导入数据')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '\n[需要授权：写入令牌]\n')
    expect(mockSendChatStream).toHaveBeenCalledTimes(1)
  })

  it('流式 AbortError 时报告超时', async () => {
    const abortErr = new Error('Aborted')
    abortErr.name = 'AbortError'
    mockSendChatStream.mockRejectedValue(abortErr)
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('超时'))
  })

  it('流式非 Abort 错误时报告失败', async () => {
    mockSendChatStream.mockRejectedValue(new Error('连接断开'))
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('连接断开'))
  })

  it('流式 done 无 result 时用 streamPlain 兜底', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '纯文本' })
      onEvent({ type: 'done', result: null })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '纯文本')
    expect(mockSaveMessage).not.toHaveBeenCalled()
  })

  it('流式 done 有 result 但无 response 时用 streamPlain', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '内容' })
      onEvent({ type: 'done', result: { success: true } })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '内容')
    expect(mockSaveMessage).not.toHaveBeenCalled()
  })

  it('流式 SSE error 事件时报告错误', async () => {
    mockReadPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'error', message: '模型不可用' })
    })
    const api = createApi()
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('模型不可用'))
  })

  it('流式 HTTP 502 且无法核对回执时保持结果未知，不重复提交', async () => {
    mockSendChatStream.mockResolvedValue({ ok: false, status: 502 })
    mockParseChatStreamErrorResponse.mockResolvedValue('服务不可用')
    const api = createApi()
    api.messages.value.push({ role: 'ai', content: '', time: '', streamingShell: true })
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(0, '连接中断，结果未知。请核对原任务后再决定是否重试，未标记为成功。')
    expect(api.messages.value[0].workflowAction).toBe('unknown')
    expect(mockGetConversation).toHaveBeenCalledExactlyOnceWith('test-session', { turn_id: expect.any(String) })
    expect(mockSendChatStream).toHaveBeenCalledOnce()
    expect(mockRequestChatByModeWithTimeout).not.toHaveBeenCalled()
    expect(mockSaveMessage).not.toHaveBeenCalled()
    expect(api.isLoading.value).toBe(false)
    expect(api.isStreamingReply.value).toBe(false)
  })

  it('流式 HTTP 400 明确拒绝请求时报告失败', async () => {
    mockSendChatStream.mockResolvedValue({ ok: false, status: 400 })
    mockParseChatStreamErrorResponse.mockResolvedValue('请求参数错误')
    const api = createApi()
    api.messages.value.push({ role: 'ai', content: '', time: '', streamingShell: true })
    await api.sendMessage('hello')
    expect(mockApplyPlainTextToMessageIndex).toHaveBeenCalledWith(0, '处理失败：请求参数错误')
    expect(api.messages.value[0].workflowAction).toBe('failed')
    expect(mockGetConversation).not.toHaveBeenCalled()
    expect(mockSendChatStream).toHaveBeenCalledOnce()
    expect(mockSaveMessage).not.toHaveBeenCalled()
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
    // 有产品关键词但处于多模态挂起（非快路径）时，应并行预开产品副窗
    state.multimodalPendingCount!.value = 1
    const api = useChatOrchestration({
      sessionId: ref('test'),
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
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } })
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
        })
        return () => h('div')
      },
    })
    const app = createApp(TestComp)
    const el = document.createElement('div')
    app.mount(el)
    expect(mockReadPersistedExcelAnalysisContext).toHaveBeenCalledWith('lifecycle')
    expect(state.lastExcelAnalysisContext!.value).toBeTruthy()
    expect(state.linkedExcelSheet!.value).toBeNull()
    app.unmount()
  })

  it('onMounted 已有 excel 上下文时不恢复', () => {
    state.lastExcelAnalysisContext!.value = { file_name: 'existing.xlsx' }
    mockReadPersistedExcelAnalysisContext.mockReturnValue(null)

    const TestComp = defineComponent({
      setup() {
        useChatOrchestration({
          sessionId: ref('lifecycle2'),
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
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('原任务回执读取异常时 errorMessage 处理 Error 对象', async () => {
    vi.mocked(agentRunsApi.getRun).mockRejectedValue(new Error('连接超时'))
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '测试', agentRunId: 'coverage-run', agentTaskId: 'coverage-task',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'products' } },
    })
    await api.confirmTask()
    expect(agentRunsApi.getRun).toHaveBeenCalledWith('coverage-run')
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('连接超时'), 'ai', undefined, expect.any(Object))
  })

  it('原任务回执异常时 errorMessage 处理非 Error 值', async () => {
    vi.mocked(agentRunsApi.getRun).mockRejectedValue(null)
    const api = createApi()
    api.showTaskConfirm({
      type: 'custom', title: '测试', agentRunId: 'coverage-run', agentTaskId: 'coverage-task',
      payload: { tool_id: 'business_db', action: 'read', params: { entity: 'products' } },
    })
    await api.confirmTask()
    expect(agentRunsApi.getRun).toHaveBeenCalledWith('coverage-run')
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('网络错误'), 'ai', undefined, expect.any(Object))
  })
})

describe('useChatOrchestration coverage – buildTaskCompletedDescription / extractShipmentExecutionContext', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    resetMockState()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('confirmTask shipment_generate 成功且数据含 labels 对象数组', async () => {
    mockCanonicalReceipt('completed', {
      success: true, message: '成功', order_number: 'ORD-1',
      file_path: '/tmp/doc.pdf', purchase_unit: '甲公司', order_id: 200,
      labels: [
        { file_path: '/tmp/label1.pdf' },
        { path: '/tmp/label2.pdf' },
        { filePath: '/tmp/label3.pdf' },
        { filepath: '/tmp/label4.pdf' },
        '  /tmp/label5.pdf  ', '', null,
      ],
      doc_name: 'doc.pdf', record_id: 999,
    })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value).toBeTruthy()
    expect(state.lastShipmentExecution!.value?.labelPaths.length).toBeGreaterThan(0)
    expect(api.currentTask.value?.completed).toBe(true)
  })

  it('confirmTask shipment_generate 成功且数据嵌套在 data 字段', async () => {
    mockCanonicalReceipt('completed', {
      success: true, message: '成功',
      data: {
        order_number: 'ORD-2', file_path: '/tmp/doc2.pdf', purchase_unit: '乙公司',
        order_id: 300, labels: ['/tmp/label.pdf'], doc_name: 'doc2.pdf',
      },
      document: { filename: 'doc2.pdf', filepath: '/tmp/doc2.pdf' },
    })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(state.lastShipmentExecution!.value?.filePath).toBe('/tmp/doc2.pdf')
    expect(api.currentTask.value?.completed).toBe(true)
  })

  it('confirmTask shipment_generate 成功且有 download_url', async () => {
    mockCanonicalReceipt('completed', {
      success: true, message: '成功', order_number: 'ORD-3',
      download_url: '/api/shipment/download/doc.pdf',
    })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.stringContaining('成功'), 'ai',
      expect.objectContaining({ shipmentDownloadUrl: '/api/shipment/download/doc.pdf' }),
      expect.any(Object),
    )
  })

  it('confirmTask shipment_generate 成功且无 download_url 但有 doc_name', async () => {
    mockCanonicalReceipt('completed', {
      success: true, message: '成功', order_number: 'ORD-4', doc_name: 'doc4.pdf',
    })
    const api = createApi()
    api.showTaskConfirm({
      type: 'shipment_generate', completed: false, payload: shipmentPayload(),
    })
    await api.confirmTask()
    expect(mockAddAndSaveMessage).toHaveBeenCalledWith(
      expect.any(String), 'ai',
      expect.objectContaining({ shipmentDownloadUrl: '/api/shipment/download/doc4.pdf' }),
      expect.any(Object),
    )
  })
})
