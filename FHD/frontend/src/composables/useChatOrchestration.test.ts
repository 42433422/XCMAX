import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const { syncFromServer, resumeChatStream } = vi.hoisted(() => ({ syncFromServer: vi.fn(), resumeChatStream: vi.fn() }))

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
      syncFromServer,
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
  useModsStore: () => ({
    activeModId: '',
    mods: [],
    modsForUi: [],
    setActiveModId: vi.fn(),
  }),
}))
const { recallMessage } = vi.hoisted(() => ({ recallMessage: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { recallMessage, resumeChatStream }, parseChatStreamErrorResponse: vi.fn() }))
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
import { ApiError } from '@/api/core'
import { useProductsStore } from '@/stores/products'

describe('useChatOrchestration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    recallMessage.mockReset()
    syncFromServer.mockReset().mockResolvedValue(undefined)
    resumeChatStream.mockReset()
  })

  it('reopens a blocked original turn in place without replaying the later continuation turn', async () => {
    const api = useChatOrchestration({ sessionId: ref('session-1') } as Parameters<typeof useChatOrchestration>[0])
    api.messages.value = [
      { role: 'ai', turnId: 'original-turn', content: '旧观察超时', time: '10:00', workflowAction: 'failed' },
      { role: 'ai', turnId: 'later-turn', content: '继续', time: '10:01' },
    ]
    syncFromServer.mockImplementationOnce(async options => options.onConversation({
      active_turn: { turn_id: 'original-turn', run_id: 'original-run', task_id: 'original-task', status: 'blocked' },
    }))

    await api.syncSessionMessages({ required: true })

    expect(api.messages.value).toHaveLength(2)
    expect(api.messages.value[0]).toMatchObject({ workflowAction: 'blocked', recoveryTaskId: 'original-task' })
    expect(api.messages.value[1].workflowAction).toBeUndefined()
    expect(resumeChatStream).not.toHaveBeenCalled()
  })

  it('returns core chat API surface', () => {
    const sessionId = ref('orch-session')
    const api = useChatOrchestration({
      sessionId,
    })
    expect(typeof api.sendMessage).toBe('function')
    expect(typeof api.confirmTask).toBe('function')
    expect(api.ttsEnabled).toBeDefined()
  })

  it('setTtsEnabled persists preference and clears voice queue', () => {
    const sessionId = ref('tts-session')
    const api = useChatOrchestration({
      sessionId,
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
    })
    api.setTaskFilter('running')
    expect(api.taskFilter).toBeDefined()
  })

  it('keeps a saved turn until the server acknowledges its rollback and blocks sends during recall', async () => {
    const api = useChatOrchestration({ sessionId: ref('recall-session') })
    const products = useProductsStore()
    const previousVersion = products.invalidationVersion
    api.messages.value = [
      { role: 'user', time: '', content: '导入数据', turnId: 'original', serverMessageId: 15, persistence: { id: 'client-id', status: 'saved' } },
      { role: 'ai', time: '', content: '导入完成', persistence: { id: 'server:16', status: 'saved' } },
    ]
    let acknowledge!: (value: unknown) => void
    recallMessage.mockReturnValueOnce(new Promise(resolve => { acknowledge = resolve }))
    const pending = api.recallUserMessage(0)
    expect(recallMessage).toHaveBeenCalledWith('recall-session', 15)
    expect(api.isRecalling.value).toBe(true)
    await api.sendMessage('并发追加')
    expect(api.messages.value).toHaveLength(2)
    expect(products.invalidationVersion).toBe(previousVersion)
    acknowledge({ success: true, rolled_back: 1 })
    await expect(pending).resolves.toEqual({ ok: true, text: '导入数据', message: '已撤回相关业务操作。' })
    expect(api.messages.value).toHaveLength(0)
    expect(products.invalidationVersion).toBe(previousVersion + 1)
    expect(api.isRecalling.value).toBe(false)
  })

  it('keeps the transcript and exposes the server rollback conflict', async () => {
    const api = useChatOrchestration({ sessionId: ref('conflict-session') })
    api.messages.value = [{ role: 'user', time: '', content: '导入数据', persistence: { id: 'server:15', status: 'saved' } }]
    recallMessage.mockRejectedValueOnce(new ApiError('导入后有新操作，需先核对', 409, null))
    await expect(api.recallUserMessage(0)).resolves.toMatchObject({ ok: false, message: '导入后有新操作，需先核对' })
    expect(api.messages.value).toHaveLength(1)
  })

  it('prevents recall over unsynced turns and allows an unsent local message', async () => {
    const api = useChatOrchestration({ sessionId: ref('local-session') })
    api.messages.value = [
      { role: 'user', time: '', content: '原消息', persistence: { id: 'server:15', status: 'saved' } },
      { role: 'user', time: '', content: '后续消息', turnId: 'unverified' },
    ]
    await expect(api.recallUserMessage(0)).resolves.toMatchObject({ ok: false })
    await expect(api.recallUserMessage(1)).resolves.toMatchObject({ ok: false })
    expect(api.messages.value).toHaveLength(2)
    api.messages.value = [{ role: 'user', time: '', content: '本机草稿' }]
    await expect(api.recallUserMessage(0)).resolves.toEqual({ ok: true, text: '本机草稿' })
    expect(recallMessage).not.toHaveBeenCalled()
  })
})
