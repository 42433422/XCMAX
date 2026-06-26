import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { defineComponent, h, nextTick, ref } from 'vue'

// ===== Mock pinia 的 storeToRefs，使其直接返回 store 对象 =====
vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return {
    ...actual,
    storeToRefs: (store: any) => store,
  }
})

// ===== Mock 模块 =====

const mockChatSendMessage = vi.fn(async () => undefined)
// 使用真实 ref 以保证 computed 响应式
const isLoadingRef = ref(false)
const isProModeRef = ref(false)
const messagesRef = ref<any[]>([])
const currentTaskRef = ref<any>(null)
const showHistoryRef = ref(false)

function resetMockRefs() {
  isLoadingRef.value = false
  isProModeRef.value = false
  messagesRef.value = []
  currentTaskRef.value = null
  showHistoryRef.value = false
}

const mockChatViewApi = {
  messages: messagesRef,
  currentTask: currentTaskRef,
  orderNumberFetching: { value: false },
  isLoading: isLoadingRef,
  isStreamingReply: { value: false },
  isExecuting: { value: false },
  latestAssistantPush: { value: null },
  proRuntimeTask: { value: null },
  taskList: { value: [] },
  filteredTaskList: { value: [] },
  expandedTaskIds: { value: [] },
  taskFilter: { value: 'all' },
  showHistory: showHistoryRef,
  historySessions: { value: [] },
  historyLoading: { value: false },
  historyError: { value: '' },
  pushCopied: { value: false },
  loadingProgressText: { value: '' },
  excelAnalyzeUploading: { value: false },
  multimodalPendingCount: { value: 0 },
  excelSheetOptions: { value: [] },
  linkedExcelSheet: { value: null },
  linkedExcelAllSheets: { value: false },
  isProMode: isProModeRef,
  taskTableColumns: { value: [] },
  taskTableItems: { value: [] },
  taskOrderNumber: { value: '' },
  sendMessage: mockChatSendMessage,
  confirmTask: vi.fn(),
  refetchTaskOrderNumber: vi.fn(),
  setCustomOrderNumber: vi.fn(),
  cancelTask: vi.fn(),
  showTaskConfirm: vi.fn(),
  triggerUpload: vi.fn(),
  onExcelAnalyzeFileChange: vi.fn(),
  bindExcelSheetToChat: vi.fn(),
  bindAllExcelSheetsToChat: vi.fn(),
  toggleTaskExpanded: vi.fn(),
  setTaskFilter: vi.fn(),
  clearTaskHistory: vi.fn(),
  retryTask: vi.fn(),
  cancelTaskById: vi.fn(),
  jumpToTaskMessage: vi.fn(),
  showHistoryPanel: vi.fn(),
  loadSession: vi.fn(),
  clearHistorySessions: vi.fn(),
  newConversation: vi.fn(),
  handleShipmentDownloadClick: vi.fn(),
  startPrintFromTaskCard: vi.fn(),
  copyAssistantPushContent: vi.fn(),
  openAssistantFloatFromTaskPanel: vi.fn(),
  syncProModeState: vi.fn(),
  syncSessionMessages: vi.fn(),
  handleAutoAction: vi.fn(),
  ttsEnabled: { value: false },
  setTtsEnabled: vi.fn(),
  chatMessagesRef: { value: null },
  excelAnalyzeInputRef: { value: null },
}

vi.mock('@/composables/useChatView', () => ({
  useChatView: () => mockChatViewApi,
}))

vi.mock('@/composables/useChatVoiceInput', () => ({
  useChatVoiceInput: () => ({
    voiceButtonDisabled: { value: false },
    voiceButtonClass: { value: '' },
    voiceButtonIcon: { value: 'fa-microphone' },
    voiceButtonText: { value: '语音' },
    voiceButtonTitle: { value: '语音输入' },
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
    getCollapsedPreview: () => '',
    canSpeakMessage: () => false,
    toggleMessageTts: vi.fn(),
    batchCalculateHeights: vi.fn(),
    stopMessageTts: vi.fn(),
  }),
}))

vi.mock('@/composables/useChatViewHost', () => ({
  useChatViewHost: () => ({
    onProIntentToolbarChange: vi.fn(),
    onAutoRefreshToolbarChange: vi.fn(),
  }),
}))

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
  useModsStore: () => ({
    mods: { value: [] },
    clientModsUiOff: false,
    modsForWorkflowUi: [],
  }),
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryPreset: () => ({
    placeholderPro: '请输入专业模式消息',
    placeholderNormal: '请输入消息',
  }),
  getIndustryQuickButtons: () => [
    { text: '测试预览', label: '测试' },
    { text: '快捷1', label: '快捷1' },
  ],
}))

vi.mock('@/constants/clientModeTiers', () => ({
  isClientModeTiersUiEnabled: () => false,
  PRO_INTENT_EXPERIENCE_KEY: 'xcagi_pro_intent_experience',
}))

vi.mock('@/workflow/coreWorkflowTaskUi', () => ({
  workflowTaskDotStatusClassForTask: () => '',
  workflowTaskDotTitleForTask: () => '',
}))

vi.mock('@/utils/chatTaskLabels', () => ({
  formatTaskTime: () => '',
  formatTaskSourceLabel: () => '',
}))

vi.mock('@/utils/xcagiStorageKeys', () => ({
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

vi.mock('@/components/chat/ChatInputToolbar.vue', () => ({
  default: defineComponent({ name: 'ChatInputToolbar', setup: () => () => h('div') }),
}))

vi.mock('@/components/chat/ChatHistoryModal.vue', () => ({
  default: defineComponent({ name: 'ChatHistoryModal', setup: () => () => h('div') }),
}))

// ===== 测试辅助 =====

async function mountChatView() {
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
    global: {
      plugins: [router],
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
  })
  afterEach(() => {
    localStorage.clear()
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

  it('isLoading 时不发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isLoading.value = true
    vm.messageInput = '测试消息'
    await vm.sendMessage()
    expect(mockChatSendMessage).not.toHaveBeenCalled()
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

  it('设置 messageInput 并触发发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.sendQuick('快捷消息')
    await flushPromises()
    expect(mockChatSendMessage).toHaveBeenCalledWith('快捷消息')
    wrapper.unmount()
  })

  it('空字符串也能触发发送', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    vm.sendQuick('')
    await flushPromises()
    // 空字符串 trim 后为空，不发送
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
      })
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
      })
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
      })
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

  it('非 pro 模式过滤掉测试预览按钮', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isProMode.value = false
    await nextTick()
    const buttons = vm.visibleQuickButtons
    expect(buttons.length).toBe(1)
    expect(buttons[0].text).not.toBe('测试预览')
    wrapper.unmount()
  })

  it('pro 模式显示所有按钮', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isProMode.value = true
    await nextTick()
    const buttons = vm.visibleQuickButtons
    expect(buttons.length).toBe(2)
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

  it('非 pro 模式返回普通占位符', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isProMode.value = false
    await nextTick()
    expect(vm.inputPlaceholder).toBe('请输入消息')
    wrapper.unmount()
  })

  it('pro 模式返回专业占位符', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    mockChatViewApi.isProMode.value = true
    await nextTick()
    expect(vm.inputPlaceholder).toBe('请输入专业模式消息')
    wrapper.unmount()
  })
})

describe('ChatView functions – currentSessionId', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetMockRefs()
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('初始化时生成 session ID', async () => {
    const { wrapper } = await mountChatView()
    const vm = wrapper.vm as any
    expect(typeof vm.currentSessionId).toBe('string')
    expect(vm.currentSessionId.length).toBeGreaterThan(0)
    wrapper.unmount()
  })
})
