import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { defineComponent, h, nextTick, ref } from 'vue'
import { writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { resetChatMessageStores, useChatMessages } from '@/composables/useChatMessages'
import { startupPageReadyKey, startupReadyKey, useStartupSplash } from '@/composables/useStartupSplash'

const { getActiveConversation, getConversation } = vi.hoisted(() => ({
  getActiveConversation: vi.fn(async () => {
    throw new Error('offline')
  }),
  getConversation: vi.fn<(id: string) => Promise<unknown>>(),
}))

// ===== Mock pinia 的 storeToRefs，使其直接返回 store 对象 =====
vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return {
    ...actual,
    storeToRefs: (store: any) => store === mockModsStore ? { ...store, activeModId: activeModIdRef } : store,
  }
})

// ===== Mock 模块 =====

const mockChatSendMessage = vi.fn(async () => undefined)
// 使用真实 ref 以保证 computed 响应式
const isLoadingRef = ref(false)
const messagesRef = ref<any[]>([])
const currentTaskRef = ref<any>(null)
const showHistoryRef = ref(false)
const activeModIdRef = ref('')
const mockModsStore = {
  get activeModId() { return activeModIdRef.value },
  mods: ref([]), isLoaded: true, initialize: vi.fn().mockResolvedValue(undefined),
  clientModsUiOff: false, modsForWorkflowUi: [],
}
let realStartup = false

function resetMockRefs() {
  isLoadingRef.value = false
  messagesRef.value = []
  currentTaskRef.value = null
  showHistoryRef.value = false
}

const mockChatViewApi = {
  messages: messagesRef,
  currentTask: currentTaskRef,
  orderNumberFetching: { value: false },
  isLoading: isLoadingRef,
  isRecalling: { value: false },
  isStreamingReply: { value: false },
  isExecuting: { value: false },
  latestAssistantPush: { value: null },
  taskList: { value: [] },
  filteredTaskList: { value: [] },
  activeTaskId: { value: '' },
  expandedTaskIds: { value: [] },
  taskFilter: { value: 'all' },
  showHistory: showHistoryRef,
  historySessions: { value: [] },
  historyLoading: { value: false },
  historyError: { value: '' },
  pushCopied: { value: false },
  loadingProgressText: { value: '' },
  attachmentUploading: { value: false },
  multimodalPendingCount: { value: 0 },
  multimodalStaging: { value: [] },
  artifactStaging: { value: [] },
  unsupportedStaging: { value: [] },
  removeArtifactFile: vi.fn(),
  removeMultimodalFile: vi.fn(),
  dismissUnsupportedFile: vi.fn(),
  taskControlStates: { value: {} },
  taskSyncState: { value: {} },
  historyHasMore: { value: false },
  historyLoadingMore: { value: false },
  loadMoreHistorySessions: vi.fn(),
  retryModelOnly: vi.fn(),
  stopReply: vi.fn(),
  confirmWorkflowFromCard: vi.fn(),
  excelSheetOptions: { value: [] },
  linkedExcelSheet: { value: null },
  linkedExcelAllSheets: { value: false },
  taskTableColumns: { value: [] },
  taskTableItems: { value: [] },
  taskOrderNumber: { value: '' },
  sendMessage: mockChatSendMessage,
  confirmTask: vi.fn(),
  refetchTaskOrderNumber: vi.fn(),
  setCustomOrderNumber: vi.fn(),
  cancelTask: vi.fn(),
  showTaskConfirm: vi.fn(),
  onAttachmentFileChange: vi.fn(),
  bindExcelSheetToChat: vi.fn(),
  bindAllExcelSheetsToChat: vi.fn(),
  toggleTaskExpanded: vi.fn(),
  setTaskFilter: vi.fn(),
  clearTaskHistory: vi.fn(),
  retryTask: vi.fn(),
  cancelTaskById: vi.fn(),
  jumpToTaskMessage: vi.fn(),
  refreshHistorySessions: vi.fn(),
  restoreLatestOwnedSession: vi.fn(),
  showHistoryPanel: vi.fn(),
  loadSession: vi.fn(),
  clearHistorySessions: vi.fn(),
  newConversation: vi.fn(),
  handleShipmentDownloadClick: vi.fn(),
  startPrintFromTaskCard: vi.fn(),
  copyAssistantPushContent: vi.fn(),
  openAssistantFloatFromTaskPanel: vi.fn(),
  syncSessionMessages: vi.fn(async () => undefined),
  handleAutoAction: vi.fn(),
  ttsEnabled: { value: false },
  setTtsEnabled: vi.fn(),
  chatMessagesRef: { value: null },
}

vi.mock('@/composables/useChatView', () => ({
  useChatView: (options: { sessionId: ReturnType<typeof ref<string>> }) => {
    if (!realStartup) return mockChatViewApi
    const chat = useChatMessages(options.sessionId)
    return { ...mockChatViewApi, messages: chat.messages,
      syncSessionMessages: async (syncOptions: Parameters<typeof chat.syncFromServer>[0]) => { await chat.syncFromServer(syncOptions) },
    }
  },
}))

vi.mock('@/api/chat', () => ({
  default: {
    getActiveConversation,
    getConversation,
    saveMessage: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('@/composables/useChatVoiceInput', () => ({
  useChatVoiceInput: () => ({
    voiceButtonDisabled: { value: false },
    voiceButtonClass: { value: '' },
    voiceButtonIcon: { value: 'fa-microphone' },
    voiceButtonText: { value: '语音' },
    voiceButtonTitle: { value: '语音输入' },
    voiceFeedbackText: { value: '' },
    startVoiceRecording: vi.fn(),
    stopVoiceRecording: vi.fn(),
    cleanupVoiceInput: vi.fn(),
  }),
}))

vi.mock('@/composables/useChatMessageUi', () => ({
  useChatMessageUi: () => ({
    messageHeights: { value: [] },
    playingMsgIdx: { value: -1 },
    latestAiMessageIndex: { value: -1 },
    isMessageCollapsed: () => false,
    expandMessage: vi.fn(),
    collapseMessage: vi.fn(),
    canSpeakMessage: () => false,
    toggleMessageTts: vi.fn(),
    batchCalculateHeights: vi.fn(),
    stopMessageTts: vi.fn(),
  }),
}))

vi.mock('@/composables/useChatViewHost', async importOriginal => {
  const actual = await importOriginal<typeof import('@/composables/useChatViewHost')>()
  return { useChatViewHost: (deps: Parameters<typeof actual.useChatViewHost>[0]) => realStartup
    ? actual.useChatViewHost(deps) : { onAutoRefreshToolbarChange: vi.fn() } }
})

vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: () => ({
    paneStyle: { value: {} },
    startResize: vi.fn(),
    resetSize: vi.fn(),
    stopResize: vi.fn(),
  }),
}))

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({
    currentIndustryId: { value: 'default' },
  }),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => mockModsStore,
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryWelcomeMarkdown: () => '您好！我是您的智能助手',
  getIndustryPreset: () => ({
    placeholderNormal: '请输入消息',
  }),
  getIndustryQuickButtons: () => [
    { text: '测试预览', label: '测试' },
    { text: '快捷1', label: '快捷1' },
  ],
}))

vi.mock('@/workflow/coreWorkflowTaskUi', () => ({
  workflowTaskDotStatusClassForTask: () => '',
  workflowTaskDotTitleForTask: () => '',
}))

vi.mock('@/utils/chatTaskLabels', () => ({
  formatTaskTime: () => '',
  formatTaskSourceLabel: () => '',
  formatChatMessageTime: () => '12:00',
}))

vi.mock('@/utils/chatStorageKeys', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/chatStorageKeys')>(),
  readAiSessionIdFromStorage: () => null,
  writeAiSessionIdToStorage: vi.fn(),
}))

vi.mock('@/components/PaneResizeHandle.vue', () => ({
  default: defineComponent({ name: 'PaneResizeHandle', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatQuickActions.vue', () => ({
  default: defineComponent({ name: 'ChatQuickActions', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatMessageList.vue', () => ({
  default: defineComponent({ name: 'ChatMessageList', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatTaskPanel.vue', () => ({
  default: defineComponent({ name: 'ChatTaskPanel', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatConversationPanel.vue', () => ({
  default: defineComponent({ name: 'ChatConversationPanel', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatSidePanel.vue', () => ({
  default: defineComponent({ name: 'ChatSidePanel', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatInputToolbar.vue', () => ({
  default: defineComponent({ name: 'ChatInputToolbar', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatHistoryModal.vue', () => ({
  default: defineComponent({ name: 'ChatHistoryModal', setup: () => () => h('div') }),
}))

// ===== 测试辅助 =====

async function mountChatView(props: { workspaceConversationId?: string } = {}, provide: Record<symbol, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
    ],
  })
  await router.push('/chat')
  await router.isReady()

  const ChatView = (await import('./ChatView.vue')).default
  const wrapper = mount(ChatView, {
    props,
    global: {
      plugins: [router],
      provide,
    },
  })
  await flushPromises()
  return { wrapper, router }
}

// ===== 测试 =====

describe('ChatView functions – generateSessionId', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
  })
  afterEach(() => {
    setRuntimeTenantStorageScopeInput(null)
    localStorage.clear()
  })

  it('空白首页会拉回本账号最近一条会话', async () => {
    const { wrapper } = await mountChatView()
    expect(mockChatViewApi.restoreLatestOwnedSession).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('只有欢迎语时仍拉回最近会话', async () => {
    messagesRef.value = [{ role: 'ai', content: '你好，我是业务助手。', time: '14:56' }]
    const { wrapper } = await mountChatView()
    expect(mockChatViewApi.restoreLatestOwnedSession).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not mistake invisible or malformed HTML for an existing reply', async () => {
    messagesRef.value = [{ role: 'ai', content: '<script>alert(1)</script><script', time: '14:56' }]
    const { wrapper } = await mountChatView()
    expect(mockChatViewApi.restoreLatestOwnedSession).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('已有用户消息时不覆盖当前会话', async () => {
    messagesRef.value = [{ role: 'user', content: '员工图谱无法显示', time: '14:56' }]
    const { wrapper } = await mountChatView()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('生成非空字符串 session ID', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    const id = vm.generateSessionId()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('每次调用生成不同的 ID', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    const id1 = vm.generateSessionId()
    const id2 = vm.generateSessionId()
    expect(id1).not.toBe(id2)
    wrapper.unmount()
  })
})

describe('ChatView functions – sendMessage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('空消息不发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = ''
    await vm.sendMessage()
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    expect(wrapper.get('#sendMessageBtn').attributes('disabled')).toBeDefined()
    expect(wrapper.get('#chat-composer-status').text()).toContain('请输入内容')
    wrapper.unmount()
  })

  it('空白消息不发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '   '
    await vm.sendMessage()
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('有效消息发送并清空输入', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '测试消息'
    await vm.sendMessage()
    expect(mockChatSendMessage).toHaveBeenCalledWith('测试消息')
    expect(vm.messageInput).toBe('')
    wrapper.unmount()
  })

  it('有内容时发送按钮可用并提供可访问状态', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '准备发送'
    await nextTick()
    const button = wrapper.get('#sendMessageBtn')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.attributes('aria-disabled')).toBe('false')
    expect(button.attributes('title')).toBe('发送消息')
    wrapper.unmount()
  })

  it('isLoading 时允许发送纠正', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isLoading.value = true
    vm.messageInput = '测试消息'
    await vm.sendMessage()
    expect(mockChatSendMessage).toHaveBeenCalledWith('测试消息')
    mockChatViewApi.isLoading.value = false
    wrapper.unmount()
  })

  it('从 DOM 获取消息内容', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = ''
    // 模拟 DOM 中有内容
    const textarea = document.createElement('textarea')
    textarea.id = 'messageInput'
    textarea.value = 'DOM消息'
    document.body.appendChild(textarea)
    await vm.sendMessage()
    expect(mockChatSendMessage).toHaveBeenCalledWith('DOM消息')
    document.body.removeChild(textarea)
    wrapper.unmount()
  })
})

describe('ChatView functions – sendQuick', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('只填入输入框，不自动发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.sendQuick('快捷消息')
    await flushPromises()
    expect(vm.messageInput).toBe('快捷消息')
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('空字符串只填入输入框，不发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.sendQuick('')
    await flushPromises()
    expect(vm.messageInput).toBe('')
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('ChatView functions – handleKeyDown', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('Enter 键触发发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '测试'
    const event = { key: 'Enter', shiftKey: false, preventDefault: vi.fn() } as any
    vm.handleKeyDown(event)
    await flushPromises()
    expect(event.preventDefault).toHaveBeenCalled()
    expect(mockChatSendMessage).toHaveBeenCalledWith('测试')
    wrapper.unmount()
  })

  it('Shift+Enter 不触发发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '测试'
    const event = { key: 'Enter', shiftKey: true, preventDefault: vi.fn() } as any
    vm.handleKeyDown(event)
    await flushPromises()
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('非 Enter 键不触发发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.messageInput = '测试'
    const event = { key: 'Escape', shiftKey: false, preventDefault: vi.fn() } as any
    vm.handleKeyDown(event)
    await flushPromises()
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(mockChatSendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('ChatView functions – openShipmentRecordsFromAuditTask', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('派发 xcagi:switch-view 事件', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    const spy = vi.fn()
    window.addEventListener('xcagi:switch-view', spy)
    vm.openShipmentRecordsFromAuditTask()
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { view: 'shipment-records' },
      }),
    )
    window.removeEventListener('xcagi:switch-view', spy)
    wrapper.unmount()
  })
})

describe('ChatView functions – emitSwitchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('派发 xcagi:switch-view 事件带指定 view', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    const spy = vi.fn()
    window.addEventListener('xcagi:switch-view', spy)
    vm.emitSwitchView('products')
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { view: 'products' },
      }),
    )
    window.removeEventListener('xcagi:switch-view', spy)
    wrapper.unmount()
  })

  it('空 view 字符串也能派发事件', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    const spy = vi.fn()
    window.addEventListener('xcagi:switch-view', spy)
    vm.emitSwitchView('')
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { view: '' },
      }),
    )
    window.removeEventListener('xcagi:switch-view', spy)
    wrapper.unmount()
  })
})

describe('ChatView functions – visibleQuickButtons computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('过滤掉测试预览按钮', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    await nextTick()
    const buttons = vm.visibleQuickButtons
    expect(buttons.length).toBe(1)
    expect(buttons[0].text).not.toBe('测试预览')
    wrapper.unmount()
  })
})

describe('ChatView functions – inputPlaceholder computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('返回普通占位符', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    await nextTick()
    expect(vm.inputPlaceholder).toBe('请输入消息')
    wrapper.unmount()
  })
})

describe('ChatView task panel layout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })

  it('always reserves the side panel for the task/conversation switcher', async () => {
    const { wrapper } = await mountChatView()
    expect(wrapper.findComponent({ name: 'ChatSidePanel' }).exists()).toBe(true)
    expect(wrapper.find('.chat-pane-handle-slot').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('ChatView functions – currentSessionId', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
    getActiveConversation.mockReset()
    getActiveConversation.mockRejectedValue(new Error('offline'))
  })
  afterEach(() => {
    setRuntimeTenantStorageScopeInput(null)
    invalidateTenantStorageScopeCache()
    localStorage.clear()
  })

  it('初始化时生成 session ID', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    expect(typeof vm.currentSessionId).toBe('string')
    expect(vm.currentSessionId.length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('waits for an owned scope, then adopts the server conversation before trying latest history', async () => {
    getActiveConversation.mockResolvedValueOnce({ conversation_id: 'server-last' })
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    expect(getActiveConversation).not.toHaveBeenCalled()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()

    setRuntimeTenantStorageScopeInput({ tenantId: 1, marketUserId: '2' })
    await nextTick()
    await flushPromises()
    expect(vm.currentSessionId).toBe('server-last')
    expect(writeAiSessionIdToStorage).toHaveBeenCalledWith('server-last')
    expect(mockChatViewApi.syncSessionMessages).toHaveBeenCalled()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('discards an old active pointer when the owner changes while it is pending', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    let finish!: (value: any) => void
    getActiveConversation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await mountChatView()
    getActiveConversation.mockResolvedValueOnce({ conversation_id: 'owner-b' })
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 2 })
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('owner-b')
    finish({ conversation_id: 'owner-a-secret' })
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('owner-b')
    expect(writeAiSessionIdToStorage).not.toHaveBeenCalledWith('owner-a-secret')
    wrapper.unmount()
  })

  it.each(['send', 'background send', 'new conversation', 'unmount'])('retires active-pointer restoration after %s', async action => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    let finish!: (value: any) => void
    getActiveConversation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await mountChatView()
    if (action === 'send') { (wrapper.vm as any).messageInput = 'local command'; await (wrapper.vm as any).sendMessage() }
    else if (action === 'background send') { isLoadingRef.value = true; isLoadingRef.value = false }
    else if (action === 'new conversation') (wrapper.vm as any).currentSessionId = 'new-conversation'
    else wrapper.unmount()
    finish({ conversation_id: 'stale-active' })
    await flushPromises()
    expect(writeAiSessionIdToStorage).not.toHaveBeenCalledWith('stale-active')
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
    if (action !== 'unmount') wrapper.unmount()
  })

  it('preserves an explicit workspace conversation across scope arrival', async () => {
    const { wrapper } = await mountChatView({ workspaceConversationId: 'task-conversation' })
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('task-conversation')
    expect(getActiveConversation).not.toHaveBeenCalled()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('only starts the latest-history fallback after the active lookup finishes', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    let finish!: (value: any) => void
    getActiveConversation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await mountChatView()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
    finish({ conversation_id: '' })
    await flushPromises()
    expect(mockChatViewApi.restoreLatestOwnedSession).toHaveBeenCalledOnce()
    const canApply = mockChatViewApi.restoreLatestOwnedSession.mock.calls[0][0] as unknown as () => boolean
    expect(canApply()).toBe(true)
    isLoadingRef.value = true
    expect(canApply()).toBe(false)
    wrapper.unmount()
  })

  it.each([false, true])('mounted startup keeps its required conversation current until an empty=%s response', async empty => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    resetChatMessageStores()
    realStartup = true
    const splash = useStartupSplash()
    let prepare!: (signal: AbortSignal) => Promise<void>
    let finishActive: ((value: unknown) => void) | undefined
    const reads: Array<{ id: string; finish: (value: unknown) => void }> = []
    getActiveConversation.mockImplementation(() => new Promise(resolve => { finishActive = resolve }))
    getConversation.mockImplementation(id => new Promise(resolve => { reads.push({ id, finish: resolve }) }))
    const response = (id: string) => ({ success: true, id,
      messages: empty ? [] : [{ role: 'user', content: 'verified current conversation', time: '12:00' }],
    })
    const { wrapper } = await mountChatView({}, {
      [startupReadyKey as symbol]: splash.appReady,
      [startupPageReadyKey as symbol]: (load: typeof prepare) => { prepare = load; return () => {} },
    })
    try {
      const startup = splash.runStartup(async (_current, _stage, signal) => { await prepare(signal) })
      await flushPromises()
      expect(reads).toHaveLength(1)
      expect(splash.appReady.value).toBe(false)
      // If restoration started in parallel, let its real session change win first.
      finishActive?.({ conversation_id: 'owned-active-session' })
      await flushPromises()
      for (const read of reads.splice(1)) read.finish(response(read.id))
      await flushPromises()
      reads[0].finish(response(reads[0].id))
      await startup
      expect(splash.startupError.value).toBe('')
      expect(splash.appReady.value).toBe(true)
      expect((wrapper.vm as any).messages.some((row: { role: string }) => row.role === 'user')).toBe(!empty)
      // The same owned restoration remains available after the required read succeeds.
      finishActive?.({ conversation_id: 'owned-active-session' })
      await flushPromises()
      for (const read of reads.splice(1)) read.finish(response(read.id))
      await flushPromises()
      expect((wrapper.vm as any).currentSessionId).toBe('owned-active-session')
    } finally {
      wrapper.unmount(); splash.teardownOnUnmount(); realStartup = false
      resetChatMessageStores()
    }
  })

  it('keeps a new account masked and retires the old pointer across startup cancellation', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    const ready = ref(true)
    const pointers: Array<(value: unknown) => void> = []
    getActiveConversation.mockImplementation(() => new Promise(resolve => { pointers.push(resolve) }))
    const { wrapper } = await mountChatView({}, { [startupReadyKey as symbol]: ready })
    try {
      expect(pointers).toHaveLength(1)
      ready.value = false
      setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 2 })
      await flushPromises()
      expect(pointers).toHaveLength(1)
      pointers[0]({ conversation_id: 'old-account-private-session' })
      await flushPromises()
      expect(writeAiSessionIdToStorage).not.toHaveBeenCalledWith('old-account-private-session')
      ready.value = true
      await flushPromises()
      expect(pointers).toHaveLength(2)
      pointers[1]({ conversation_id: 'new-account-session' })
      await flushPromises()
      expect((wrapper.vm as any).currentSessionId).toBe('new-account-session')
    } finally { wrapper.unmount() }
  })
})
