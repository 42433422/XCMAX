import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import { lastChatModelRoute } from '@/utils/chatModelRoute'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

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
  queueVoice, addMessage, addAndSaveMessage, previewMeta, searchProducts, observeTool, getRun, continueRun, cancelRun, streamMode, modState,
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
  queueVoice: vi.fn(), addMessage: vi.fn(), addAndSaveMessage: vi.fn().mockResolvedValue(undefined), previewMeta: vi.fn(), searchProducts: vi.fn(), observeTool: vi.fn(),
  streamMode: { enabled: true, realShipment: false }, modState: { activeModId: '', mods: [], modsForUi: [], setActiveModId: vi.fn() },
  getRun: vi.fn(), continueRun: vi.fn(), cancelRun: vi.fn(),
}))

vi.mock('./useChatMessages', async () => {
  const { ref } = await import('vue')
  return {
    useChatMessages: () => ({
      messages: ref([]),
      addMessage,
      addAndSaveMessage,
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
vi.mock('./useShipmentTask', async importOriginal => {
  const actual = await importOriginal<typeof import('./useShipmentTask')>()
  const { ref } = await import('vue')
  return {
    useShipmentTask: (...args: Parameters<typeof actual.useShipmentTask>) => streamMode.realShipment ? actual.useShipmentTask(...args) : ({
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
    cancelPendingChatBatch: vi.fn(),
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
vi.mock('./useAgentRunEvents', async importOriginal => ({
  ...await importOriginal<typeof import('./useAgentRunEvents')>(),
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
vi.mock('@/api/shipment', () => ({ shipmentApi: { getProductMetaForPreview: previewMeta, fetchNextOrderNumber: vi.fn() } }))
vi.mock('@/api/products', () => ({ default: { searchProducts } }))
vi.mock('@/api/agentRuns', () => ({ default: { observeTool, getRun, continueRun, cancelRun } }))
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
    productReadAccountEpoch.value++
    streamMode.enabled = true
    streamMode.realShipment = false
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

  it.each(['stream', 'json'])('records only server route receipts for a %s response', async mode => {
    const route = { provider: 'xiaomi', model: 'flash', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'revision-a', route_state: 'completed' }
    streamMode.enabled = mode === 'stream'
    requestChatByModeWithTimeout.mockResolvedValue({ success: true, response: '完成', route_metadata: route })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'route_metadata', route_metadata: { ...route, route_state: 'selected', route_token: 'synthetic-private-token', api_key: 'synthetic-never-render' } })
      onEvent({ type: 'done', result: { success: true, response: '完成', route_metadata: route } })
    })
    await useChatOrchestration({ sessionId: ref('route-receipt') }).sendMessage('hello')
    expect(lastChatModelRoute('route-receipt')).toEqual(route)
  })

  it('keeps selected identity unconfirmed after meta then stop and preserves it in the local interruption message', async () => {
    const selected = { provider: 'xiaomi', model: 'request-model', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'a', route_state: 'selected' }
    let finish!: () => void
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'route_metadata', route_metadata: selected })
      await new Promise<void>(resolve => { finish = resolve })
    })
    const api = useChatOrchestration({ sessionId: ref('selected-stop') })
    const pending = api.sendMessage('hello')
    await vi.waitFor(() => expect(lastChatModelRoute('selected-stop')).toEqual(selected))
    api.stopReply()
    expect(addMessage.mock.calls.find(call => String(call[0]).includes('已停止接收'))?.[2]).toEqual({ routeMetadata: selected })
    finish(); await pending
    expect(lastChatModelRoute('selected-stop')).toEqual(selected)
  })

  it.each(['upstream', 'timeout'])('keeps %s failure distinguishable from an actual model return', async kind => {
    const selected = { provider: 'xiaomi', model: 'request-model', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'a', route_state: 'selected' }
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'route_metadata', route_metadata: selected })
      if (kind === 'upstream') onEvent({ type: 'error', message: '上游401', route_metadata: { ...selected, route_state: 'failed' } })
      else throw new DOMException('timeout', 'AbortError')
    })
    await useChatOrchestration({ sessionId: ref('failed-receipt') }).sendMessage('hello')
    expect(lastChatModelRoute('failed-receipt')?.route_state).toBe(kind === 'upstream' ? 'failed' : 'selected')
  })

  it('retains the failed model identity on a synchronous HTTP error without treating it as a model return', async () => {
    streamMode.enabled = false
    const route = { provider: 'xiaomi', model: 'failed-model', route_source: 'platform_configuration', key_source: 'platform', config_revision: 'a', route_state: 'failed' }
    requestChatByModeWithTimeout.mockRejectedValue({ status: 401, message: '上游授权失败', data: { detail: { route_metadata: route } } })
    await useChatOrchestration({ sessionId: ref('sync-failed-receipt') }).sendMessage('hello')
    expect(lastChatModelRoute('sync-failed-receipt')).toEqual(route)
    expect(addMessage.mock.calls.find(call => String(call[0]).includes('处理失败'))?.[2]).toMatchObject({ workflowAction: 'failed', routeMetadata: route })
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

  it('keeps partial text and marks an abnormal real SSE EOF as incomplete', async () => {
    const actual = await vi.importActual<typeof import('@/utils/chatSseStream')>('@/utils/chatSseStream')
    readPlannerSseResponse.mockImplementation(actual.readPlannerSseResponse)
    sendChatStream.mockResolvedValue(new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"type":"tool_progress","run_id":"unfinished-run"}\n\ndata: {"type":"token","text":"已收到部分内容"}\n\n'))
      controller.close()
    } })))
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('查看任务进度')
    expect(applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, expect.stringContaining('已收到部分内容\n\n[回复未完成]'))
    expect(attachApprovalCardToLastAiMessage).not.toHaveBeenCalled()
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'unfinished-run' }, '查看任务进度', expect.any(Function))
    expect(api.isLoading.value).toBe(false)
    expect(api.isStreamingReply.value).toBe(false)
  })

  it('retains a real authorization pause without reporting success or truncated transport', async () => {
    const actual = await vi.importActual<typeof import('@/utils/chatSseStream')>('@/utils/chatSseStream')
    readPlannerSseResponse.mockImplementation(actual.readPlannerSseResponse)
    sendChatStream.mockResolvedValue(new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"type":"requires_token","token_name":"DB_WRITE","token_description":"写入授权","run_id":"waiting-run"}\n\n'))
      controller.close()
    } })))
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('等待写入授权')
    expect(handleChatRequiresToken).toHaveBeenCalledWith('DB_WRITE', '写入授权', ['等待写入授权'])
    expect(applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '\n[需要授权：写入授权]\n')
    expect(attachApprovalCardToLastAiMessage).not.toHaveBeenCalled()
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'waiting-run' }, '等待写入授权', expect.any(Function))
    expect(api.isLoading.value).toBe(false)
  })

  function approvalHost(run = true) {
    const sessionId = ref('s')
    const api = useChatOrchestration({ sessionId })
    api.messages.value = ['A', 'B'].map(id => ({ role: 'ai', content: `计划 ${id}`, time: '12:00',
      approvalCard: { id: `card-${id}`, plan_id: `plan-${id}`, ...(run ? { run_id: `run-${id}` } : {}), status: 'pending' },
    }))
    const wrapper = mount(ChatMessageList, { props: {
      messages: api.messages.value, isLoading: false, isStreamingReply: false, loadingProgressText: '',
      messageHeights: new Map(), latestAiMessageIndex: 1, playingMsgIdx: -1,
      isMessageCollapsed: () => false, getCollapsedPreview: () => '', canSpeakMessage: () => false,
    } })
    return { api, sessionId, wrapper, first: api.messages.value[0].approvalCard!, second: api.messages.value[1].approvalCard! }
  }

  it('a real earlier approval button targets its own run and waits for the receipt', async () => {
    let resolve!: (value: unknown) => void
    getRun.mockResolvedValue({ success: true, approval: { grant: 'grant-A' } })
    continueRun.mockReturnValue(new Promise(r => { resolve = r }))
    const test = approvalHost()
    try {
      await test.wrapper.findAll('.approval-btn--primary')[0].trigger('click')
      expect(test.wrapper.emitted('approval-confirm')).toEqual([['card-A']])
      const operation = test.api.confirmWorkflowFromCard('card-A')
      await vi.waitFor(() => expect(continueRun).toHaveBeenCalledOnce())
      expect(getRun).toHaveBeenCalledWith('run-A')
      expect(continueRun).toHaveBeenCalledWith('run-A', expect.objectContaining({ approval_grant: 'grant-A' }))
      expect(test.first.status).toBe('pending')
      expect(test.first.submitting).toBe(true)
      await test.api.confirmWorkflowFromCard('card-A')
      expect(continueRun).toHaveBeenCalledOnce()
      resolve({ success: true, data: { run_id: 'run-A', status: 'queued' } })
      await operation
      expect(test.first.status).toBe('confirmed')
      expect(test.second.status).toBe('pending')
      expect(requestChatByModeWithTimeout).not.toHaveBeenCalled()
    } finally { test.wrapper.unmount() }
  })

  it('failed approval remains visible and can be retried with a fresh grant', async () => {
    getRun.mockResolvedValue({ success: true, approval: { grant: 'fresh' } })
    continueRun.mockRejectedValueOnce(new Error('网络失败')).mockResolvedValue({ success: true, data: { run_id: 'run-A', status: 'queued' } })
    const test = approvalHost()
    try {
      await test.api.confirmWorkflowFromCard('card-A')
      expect(test.first.status).toBe('pending')
      expect(test.first.submitting).toBe(false)
      expect(test.wrapper.find('[role="alert"]').text()).toContain('网络失败')
      expect(test.wrapper.findAll('.approval-btn--primary')[0].attributes('disabled')).toBeUndefined()
      await test.api.confirmWorkflowFromCard('card-A')
      expect(getRun).toHaveBeenCalledTimes(2)
      expect(test.first.status).toBe('confirmed')
    } finally { test.wrapper.unmount() }
  })

  it('plan-only approval includes its selected plan and rejects a stale or wrong receipt', async () => {
    requestChatByModeWithTimeout.mockResolvedValueOnce({ success: false, response: '此确认卡对应的计划已失效', data: { action: 'workflow_confirmation_stale', data: { plan_id: 'plan-A' } } })
      .mockResolvedValueOnce({ success: true, response: 'wrong plan', data: { action: 'workflow_done', data: { plan_id: 'plan-B' } } })
      .mockResolvedValue({ success: true, response: '完成', data: { action: 'workflow_done', data: { plan_id: 'plan-A' } } })
    const test = approvalHost(false)
    try {
      await test.api.confirmWorkflowFromCard('card-A')
      expect(requestChatByModeWithTimeout).toHaveBeenCalledWith('确认', 90_000, { expectedWorkflowPlanId: 'plan-A' }, expect.objectContaining({ sessionId: 's' }))
      expect(test.first.status).toBe('pending')
      expect(test.first.error).toContain('失效')
      await test.api.confirmWorkflowFromCard('card-A')
      expect(test.first.status).toBe('pending')
      await test.api.confirmWorkflowFromCard('card-A')
      expect(test.first.status).toBe('confirmed')
      expect(test.second.status).toBe('pending')
    } finally { test.wrapper.unmount() }
  })

  it('cancellation is bound to the clicked card and waits for cancelled status', async () => {
    cancelRun.mockResolvedValueOnce({ success: true, data: { run_id: 'run-A', status: 'running' } })
      .mockResolvedValue({ success: true, data: { run_id: 'run-A', status: 'cancelled' } })
    const test = approvalHost()
    try {
      await test.wrapper.findAll('.approval-btn--ghost')[0].trigger('click')
      expect(test.wrapper.emitted('approval-cancel')).toEqual([['card-A']])
      await test.api.cancelWorkflowFromCard('card-A')
      expect(test.first.status).toBe('pending')
      expect(test.first.error).toContain('尚未确认取消')
      await test.api.cancelWorkflowFromCard('card-A')
      expect(cancelRun).toHaveBeenLastCalledWith('run-A')
      expect(test.first.status).toBe('cancelled')
      expect(test.second.status).toBe('pending')
    } finally { test.wrapper.unmount() }
  })

  it('does not continue after switching conversation while fetching an approval grant', async () => {
    let resolve!: (value: unknown) => void
    getRun.mockReturnValue(new Promise(r => { resolve = r }))
    const test = approvalHost()
    try {
      const operation = test.api.confirmWorkflowFromCard('card-A')
      test.sessionId.value = 'other'
      resolve({ success: true, approval: { grant: 'old-grant' } })
      await operation
      expect(continueRun).not.toHaveBeenCalled()
      expect(test.first.status).toBe('pending')
      expect(test.first.submitting).toBe(false)
    } finally { test.wrapper.unmount() }
  })

  it.each(['http', 'sse'])('surfaces %s errors, unlocks sending and permits retry', async (kind) => {
    sendChatStream.mockResolvedValue({ ok: kind !== 'http', status: 502, body: {} })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'error', message: '模型不可用' }))
    const api = useChatOrchestration({ sessionId: ref('s') })
    await api.sendMessage('hello')
    expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, expect.stringContaining('处理失败'))
    expect(api.isLoading.value).toBe(false)
    expect(api.isStreamingReply.value).toBe(false)
    sendChatStream.mockResolvedValue({ ok: true, body: {} })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'done', result: { success: true, response: '恢复成功' } }))
    await api.sendMessage('hello')
    expect(sendChatStream).toHaveBeenCalledTimes(2)
    expect(applyPlainTextToMessageIndex).toHaveBeenLastCalledWith(0, '恢复成功')
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
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'run_iterations' }, '先聊聊每日摘要', expect.any(Function))
  })

  it.each([false, true])('shows approval before tracking resolves and guards a later reply: %s', async laterReply => {
    let finishTracking!: () => void
    syncAgentRunFromPayload.mockImplementation(() => new Promise<void>(resolve => { finishTracking = resolve }))
    const payload = { run_id: 'approval-run', response: '等待确认', data: { action: 'approval_pending', data: { approval_request_ids: ['approval-1'] } } }
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
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith(payload, '读取已登记应用', expect.any(Function))
  })

  it('retains the run id carried only by a terminal error', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => onEvent({ type: 'error', run_id: 'run_terminal', message: '未完成' }))
    await useChatOrchestration({ sessionId: ref('s') }).sendMessage('先聊聊每日摘要')
    expect(syncAgentRunFromPayload).toHaveBeenCalledWith({ run_id: 'run_terminal' }, '先聊聊每日摘要', expect.any(Function))
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

  it.each(['stop', 'correct'])('fences late tokens, authorization, results and cleanup after %s', async action => {
    const callbacks: Array<(event: unknown) => void> = []
    const finishes: Array<() => void> = []
    readPlannerSseResponse.mockImplementation((_res, onEvent) => {
      callbacks.push(onEvent)
      return new Promise<void>(resolve => finishes.push(resolve))
    })
    const api = useChatOrchestration({ sessionId: ref('same-session') })
    const old = api.sendMessage('old synthetic request')
    await vi.waitFor(() => expect(callbacks).toHaveLength(1))
    const oldSignal = sendChatStream.mock.calls[0][1].signal
    let current: Promise<void> | undefined
    if (action === 'stop') api.stopReply()
    else {
      current = api.sendMessage('corrected synthetic request')
      await vi.waitFor(() => expect(callbacks).toHaveLength(2))
    }
    expect(oldSignal.aborted).toBe(true)
    callbacks[0]({ type: 'route_metadata', route_metadata: { provider: 'old', model: 'stale', route_source: 'preference', key_source: 'user_override', config_revision: 'old' } })
    callbacks[0]({ type: 'token', text: 'late old answer' })
    callbacks[0]({ type: 'requires_token', token_name: 'DB_WRITE' })
    callbacks[0]({ type: 'done', result: { success: true, response: 'late old answer' } })
    finishes[0]()
    await old
    expect(applyPlainTextToMessageIndex).not.toHaveBeenCalled()
    expect(handleChatRequiresToken).not.toHaveBeenCalled()
    expect(queueVoice).not.toHaveBeenCalled()
    expect(api.isLoading.value).toBe(action === 'correct')
    expect(lastChatModelRoute('same-session')).toBeNull()
    if (current) {
      callbacks[1]({ type: 'done', result: { success: true, response: 'correct answer' } })
      finishes[1]()
      await current
      expect(applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, 'correct answer')
    }
    expect(api.isLoading.value).toBe(false)
  })

  it('discards a stopped non-stream response even if transport ignores abort', async () => {
    streamMode.enabled = false
    let finish!: (value: unknown) => void
    requestChatByModeWithTimeout.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const api = useChatOrchestration({ sessionId: ref('s') })
    const sending = api.sendMessage('synthetic request')
    await vi.waitFor(() => expect(requestChatByModeWithTimeout).toHaveBeenCalled())
    api.stopReply()
    finish({ success: true, response: 'late answer', requires_token: true, token_name: 'DB_WRITE' })
    await sending
    expect(addMessage.mock.calls.some(call => call[0] === 'late answer')).toBe(false)
    expect(handleChatRequiresToken).not.toHaveBeenCalled()
    expect(syncAgentRunFromPayload).not.toHaveBeenCalled()
  })

  it.each(['correct', 'stop', 'session', 'return-session', 'owner', 'mod'])('fences the real local shipment helper after %s', async change => {
    streamMode.realShipment = true
    const sid = ref('original')
    const api = useChatOrchestration({ sessionId: sid })
    api.currentTask.value = { type: 'shipment_generate', payload: { params: { products: [] } } }
    const originalTask = api.currentTask.value
    let finish!: (value: unknown) => void
    previewMeta.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    previewMeta.mockResolvedValue({ success: true, data: [{ model_number: 'B002', name: 'B' }] })
    const old = api.sendMessage('再加 1桶 A001 规格10')
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    if (change === 'correct') await api.sendMessage('再加 1桶 B002 规格10')
    else if (change === 'stop') api.stopReply()
    else if (change.includes('session')) { sid.value = 'other'; if (change === 'return-session') sid.value = 'original' }
    else switchIdentity(change)
    finish({ success: true, data: [{ model_number: 'A001', name: 'A' }] })
    await old
    expect(originalTask.payload?.params?.products?.map(product => product.model_number)).toEqual(change === 'correct' ? ['B002'] : [])
    expect(addAndSaveMessage.mock.calls.some(call => String(call[0]).includes('A001'))).toBe(false)
    expect(sendChatStream).not.toHaveBeenCalled()
  })

})
