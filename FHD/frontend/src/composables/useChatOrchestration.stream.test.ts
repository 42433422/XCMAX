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
  refreshHistorySessions,
  syncAgentRunFromPayload,
  attachApprovalCardToLastAiMessage,
  attachAgentRunTraceToLastAiMessage,
  queueVoice, addMessage, searchProducts, observeTool, streamMode, modState,
} = vi.hoisted(() => ({
  handleChatRequiresToken: vi.fn(),
  applyPlainTextToMessageIndex: vi.fn(),
  pushStreamingAiShell: vi.fn(() => 0),
  saveMessage: vi.fn().mockResolvedValue(undefined),
  sendChatStream: vi.fn(),
  readPlannerSseResponse: vi.fn(),
  requestChatByModeWithTimeout: vi.fn(),
  refreshHistorySessions: vi.fn().mockResolvedValue(undefined),
  syncAgentRunFromPayload: vi.fn().mockResolvedValue(undefined),
  attachApprovalCardToLastAiMessage: vi.fn(),
  attachAgentRunTraceToLastAiMessage: vi.fn(),
  queueVoice: vi.fn(), addMessage: vi.fn(), searchProducts: vi.fn(), observeTool: vi.fn(),
  streamMode: { enabled: true }, modState: { activeModId: '', mods: [], modsForUi: [], setActiveModId: vi.fn() },
}))

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage,
      addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
      saveMessage,
      pushStreamingAiShell,
      applyPlainTextToMessageIndex,
      clearMessages: vi.fn(),
      loadMessages: vi.fn(),
      syncFromServer: vi.fn().mockResolvedValue(undefined),
      queueVoice,
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
    handleChatRequiresToken,
    onDbWriteUnlockedForChatRetry: vi.fn(),
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
    attachApprovalCardToLastAiMessage,
    attachAgentRunTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage: vi.fn(),
    syncTaskFromChatResponse: vi.fn(),
  }),
}))
vi.mock('./useAgentRunEvents', () => ({
  useAgentRunEventSync: () => ({ syncAgentRunFromPayload }),
}))
vi.mock('./useChatSessionHistory', () => ({
  useChatSessionHistory: () => ({
    showHistory: ref(false),
    historySessions: ref([]),
    historyLoading: ref(false),
    historyError: ref(''),
    refreshHistorySessions,
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
  useModsStore: () => modState,
}))
vi.mock('@/api/chat', () => ({
  default: { sendChatStream },
  parseChatStreamErrorResponse: vi.fn().mockResolvedValue('流式接口错误'),
}))
vi.mock('@/api/products', () => ({ default: { searchProducts } }))
vi.mock('@/api/agentRuns', () => ({ default: { observeTool } }))
vi.mock('@/utils/chatSseStream', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/chatSseStream')>()
  return {
    ...actual,
    isChatStreamEnabled: () => streamMode.enabled,
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
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { extractLikelyProductQueryKeyword } from './useChatPersistence'

describe('useChatOrchestration stream', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    streamMode.enabled = true
    modState.activeModId = ''
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    vi.mocked(extractLikelyProductQueryKeyword).mockReturnValue(null)
    syncAgentRunFromPayload.mockResolvedValue(undefined)
    pushStreamingAiShell.mockReturnValue(0)
    sendChatStream.mockResolvedValue({ ok: true, body: {} })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '你' })
      onEvent({ type: 'done', result: { success: true, response: '你好' } })
    })
  })

  it('sendMessage uses SSE stream when enabled', async () => {
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('hello')
    expect(sendChatStream).toHaveBeenCalled()
    expect(readPlannerSseResponse).toHaveBeenCalled()
    expect(applyPlainTextToMessageIndex).toHaveBeenCalled()
    expect(refreshHistorySessions).toHaveBeenCalledOnce()
    expect(saveMessage).not.toHaveBeenCalled()
    expect(requestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it('sendMessage stream handles requires_token event', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({
        type: 'requires_token',
        token_name: 'PAYMENT_TOKEN',
        token_description: '支付授权',
      })
      onEvent({ type: 'done', result: { success: true, response: '' } })
    })
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('发起支付')
    expect(handleChatRequiresToken).toHaveBeenCalled()
    expect(applyPlainTextToMessageIndex).toHaveBeenCalled()
  })

  it('keeps the stream open while execution progress continues', async () => {
    vi.useFakeTimers()
    try {
      readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
        await vi.advanceTimersByTimeAsync(20_000)
        onEvent({ type: 'tool_progress', label: '正在执行' })
        await vi.advanceTimersByTimeAsync(20_000)
        expect(sendChatStream.mock.calls[0][1].signal.aborted).toBe(false)
        onEvent({ type: 'done', result: { success: true, response: '完成' } })
      })
      await useChatOrchestration({ sessionId: ref('s') }).sendMessage('EXPORT INVENTORY')
    } finally { vi.useRealTimers() }
  })

  it('keeps an accepted task distinguishable from failure after a stream timeout', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'tool_progress', run_id: 'run_export', label: '正在处理任务' })
      throw new DOMException('timeout', 'AbortError')
    })
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('EXPORT INVENTORY')
    expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('请到任务工作区核对结果'))
    expect(requestChatByModeWithTimeout).not.toHaveBeenCalled()
  })

  it.each(['http', 'sse'])('surfaces %s errors as failures', async (kind) => {
    sendChatStream.mockResolvedValue({ ok: kind !== 'http', status: 502, body: {} })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'error', message: '模型不可用' }))
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('hello')
    expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('处理失败'))
  })

  it.each(['pending', 'rejected'])('unlocks a real SSE iteration failure while run tracking is %s', async state => {
    syncAgentRunFromPayload.mockImplementation(() => state === 'pending' ? new Promise<void>(() => {}) : Promise.reject(new Error('tracking unavailable')))
    syncAgentRunFromPayload.mockResolvedValueOnce(undefined)
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'tool_progress', run_id: 'run_iterations' })
      onEvent({ type: 'error', message: '对话达到最大迭代次数，未完成。' })
    })
    const api = useChatOrchestration({ sessionId: ref('s') })
    let sendError: unknown
    const sending = api.sendMessage('先聊聊每日摘要').catch(error => { sendError = error })
    await vi.waitFor(() => {
      expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, '处理失败：对话达到最大迭代次数，未完成。')
      expect(api.isLoading.value).toBe(false)
      expect(api.isStreamingReply.value).toBe(false)
    }, { timeout: 1000 })
    await sending
    expect(sendError).toBeUndefined()
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'run_iterations' }, '先聊聊每日摘要')
  })

  it.each([false, true])('shows approval before tracking resolves and guards a later reply: %s', async laterReply => {
    let finishTracking!: () => void
    syncAgentRunFromPayload.mockImplementation(() => new Promise<void>(resolve => { finishTracking = resolve }))
    const payload = { response: '等待确认', data: { action: 'approval_pending', data: { approval_request_ids: ['approval-1'] } } }
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'done', result: payload }))
    const api = useChatOrchestration({ sessionId: ref('s') })
    const sending = api.sendMessage('读取已登记应用')
    await vi.waitFor(() => {
      expect(attachApprovalCardToLastAiMessage).toHaveBeenCalledWith(payload)
      expect(api.isLoading.value).toBe(false)
    }, { timeout: 1000 })
    await sending
    if (laterReply) api.messages.value.push({ role: 'ai', content: '下一轮回复', time: 'later' })
    finishTracking()
    await Promise.resolve()
    expect(attachAgentRunTraceToLastAiMessage).toHaveBeenCalledTimes(laterReply ? 0 : 1)
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith(payload, '读取已登记应用')
  })

  it('retains the run id carried only by a terminal error', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'error', run_id: 'run_terminal', message: '未完成' }))
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('先聊聊每日摘要')
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'run_terminal' }, '先聊聊每日摘要')
  })

  const switchIdentity = (kind: string) => {
    if (kind === 'owner') setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 2 })
    else modState.activeModId = 'another-mod'
  }

  it.each(['owner', 'mod'])('discards stream callbacks and tail speech after a %s switch', async kind => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      switchIdentity(kind)
      onEvent({ type: 'token', text: 'private answer' })
      onEvent({ type: 'requires_token', token_name: 'DB_WRITE', token_description: '写入' })
      onEvent({ type: 'tool_progress', run_id: 'old-run' })
      onEvent({ type: 'done', result: { success: true, response: 'private answer' } })
    })
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('hello')
    expect(applyPlainTextToMessageIndex).not.toHaveBeenCalled()
    expect(queueVoice).not.toHaveBeenCalled()
    expect(handleChatRequiresToken).not.toHaveBeenCalled()
    expect(syncAgentRunFromPayload).not.toHaveBeenCalled()
    expect(sendChatStream.mock.calls[0][1].signal.aborted).toBe(true)
  })

  it('does not start an old request after its asynchronous prehandlers switch owner', async () => {
    const sending = useChatOrchestration({ sessionId: ref('s') }).sendMessage('hello')
    switchIdentity('owner')
    await sending
    expect(sendChatStream).not.toHaveBeenCalled()
  })

  it.each(['owner', 'mod', 'conversation'])('handles a detached JSON result after a %s switch', async kind => {
    streamMode.enabled = false
    const sid = ref('original')
    requestChatByModeWithTimeout.mockImplementation(async () => {
      if (kind === 'conversation') sid.value = 'new-session'
      else switchIdentity(kind)
      return { success: true, response: 'original private answer' }
    })
    await useChatOrchestration({ sessionId: sid }).sendMessage('hello')
    if (kind === 'conversation') {
      expect(saveMessage).toHaveBeenCalledWith('ai', 'original private answer', 'original')
    } else expect(saveMessage).not.toHaveBeenCalled()
    expect(addMessage).toHaveBeenCalledTimes(1)
    expect(handleChatRequiresToken).not.toHaveBeenCalled()
    expect(syncAgentRunFromPayload).not.toHaveBeenCalled()
  })

  it.each(['owner', 'mod'])('does not record or save an old product query under the next %s', async kind => {
    vi.mocked(extractLikelyProductQueryKeyword).mockReturnValue('synthetic')
    searchProducts.mockImplementation(async () => {
      switchIdentity(kind)
      return { success: true, data: [{ id: 1, name: 'private result' }] }
    })
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('query synthetic')
    expect(observeTool).not.toHaveBeenCalled()
    expect(saveMessage).not.toHaveBeenCalled()
    expect(sendChatStream).not.toHaveBeenCalled()
  })

  it.each(['owner', 'mod'])('does not attach a late JSON task trace after a %s switch', async kind => {
    streamMode.enabled = false
    requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: 'pending' })
    syncAgentRunFromPayload.mockImplementation(async () => switchIdentity(kind))
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('hello')
    expect(attachAgentRunTraceToLastAiMessage).not.toHaveBeenCalled()
  })

})
