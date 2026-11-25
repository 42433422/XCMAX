import { webcrypto } from 'node:crypto'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import { writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'
import { voiceChatBridge } from '@/composables/voiceCallHost'

// ===== 模块级 mock =====

const { getActiveConversation, approveRunWithFreshGrant, showAppToast } = vi.hoisted(() => ({
  getActiveConversation: vi.fn(),
  approveRunWithFreshGrant: vi.fn(async () => ({ status: 'running' })),
  showAppToast: vi.fn(),
}))

vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return { ...actual, storeToRefs: (store: any) => store }
})

vi.mock('@/api/chat', () => ({ default: { getActiveConversation } }))

vi.mock('@/api/agentRunApproval', () => ({
  APPROVAL_GRANT_REJECTED_MESSAGE: '审批凭证已被使用，请刷新后重试',
  APPROVAL_GRANT_MISSING_MESSAGE: '任务当前没有可用的审批凭证',
  approveRunWithFreshGrant,
}))

vi.mock('@/composables/useAppToast', () => ({ showAppToast }))

// ===== useChatView 返回的可控 API =====

const messagesRef = ref<any[]>([])
const cacheErrorRef = ref('')
const currentTaskRef = ref<any>(null)
const isLoadingRef = ref(false)
const showHistoryRef = ref(false)
const historySessionsRef = ref<any[]>([])
const historyErrorRef = ref('')
const artifactStagingRef = ref<any[]>([])
const multimodalStagingRef = ref<any[]>([])
const unsupportedStagingRef = ref<string[]>([])
const excelSheetOptionsRef = ref<any[]>([])
const linkedExcelSheetRef = ref<any>(null)
const linkedExcelAllSheetsRef = ref(false)
const latestAssistantPushRef = ref<any>(null)
const ttsEnabledRef = ref(false)
const taskListRef = ref<any[]>([])

const mockChatViewApi = {
  messages: messagesRef,
  cacheError: cacheErrorRef,
  retryMessagesCache: vi.fn(),
  retryMessageSave: vi.fn(),
  currentTask: currentTaskRef,
  orderNumberFetching: ref(false),
  isLoading: isLoadingRef,
  isRecalling: ref(false),
  isStreamingReply: ref(false),
  isExecuting: ref(false),
  latestAssistantPush: latestAssistantPushRef,
  taskList: taskListRef,
  taskControlStates: ref({}),
  taskSyncState: ref({}),
  refreshTasks: vi.fn(),
  activeTaskId: ref(''),
  filteredTaskList: ref<any[]>([]),
  expandedTaskIds: ref<string[]>([]),
  taskFilter: ref('all'),
  showHistory: showHistoryRef,
  historySessions: historySessionsRef,
  historyLoading: ref(false),
  historyError: historyErrorRef,
  historyHasMore: ref(true),
  historyLoadingMore: ref(false),
  loadMoreHistorySessions: vi.fn(),
  pushCopied: ref(false),
  loadingProgressText: ref(''),
  attachmentUploading: ref(false),
  multimodalPendingCount: ref(0),
  multimodalStaging: multimodalStagingRef,
  artifactStaging: artifactStagingRef,
  unsupportedStaging: unsupportedStagingRef,
  removeArtifactFile: vi.fn(),
  removeMultimodalFile: vi.fn(),
  dismissUnsupportedFile: vi.fn(),
  excelSheetOptions: excelSheetOptionsRef,
  linkedExcelSheet: linkedExcelSheetRef,
  linkedExcelAllSheets: linkedExcelAllSheetsRef,
  taskTableColumns: ref<any[]>([]),
  taskTableItems: ref<any[]>([]),
  taskOrderNumber: ref(''),
  sendMessage: vi.fn(async () => undefined),
  retryModelOnly: vi.fn(),
  confirmDestructive: vi.fn(),
  stopReply: vi.fn(),
  confirmWorkflowFromCard: vi.fn(),
  cancelWorkflowFromCard: vi.fn(),
  confirmTask: vi.fn(),
  refetchTaskOrderNumber: vi.fn(),
  setCustomOrderNumber: vi.fn(),
  cancelTask: vi.fn(),
  onAttachmentFileChange: vi.fn(async () => undefined),
  bindExcelSheetToChat: vi.fn(async () => undefined),
  bindAllExcelSheetsToChat: vi.fn(async () => undefined),
  toggleTaskExpanded: vi.fn(),
  selectTask: vi.fn(),
  setTaskFilter: vi.fn(),
  clearTaskHistory: vi.fn(),
  removeTask: vi.fn(),
  retryTask: vi.fn(),
  pauseTask: vi.fn(),
  resumeTask: vi.fn(),
  approveTask: vi.fn(async () => undefined),
  cancelTaskById: vi.fn(),
  jumpToTaskMessage: vi.fn(),
  refreshHistorySessions: vi.fn(),
  restoreLatestOwnedSession: vi.fn(),
  showHistoryPanel: vi.fn(),
  loadSession: vi.fn(async () => undefined),
  clearHistorySessions: vi.fn(),
  renameSession: vi.fn(),
  deleteSession: vi.fn(),
  newConversation: vi.fn(),
  handleShipmentDownloadClick: vi.fn(),
  startPrintFromTaskCard: vi.fn(),
  copyAssistantPushContent: vi.fn(),
  openAssistantFloatFromTaskPanel: vi.fn(),
  syncSessionMessages: vi.fn(async () => undefined),
  recallUserMessage: vi.fn(async () => ({ ok: true, text: '' })),
  reconcileTurnMessage: vi.fn(async () => ({ ok: true })),
  addAndSaveMessage: vi.fn(async () => undefined),
  stageExcelAnalysisContext: vi.fn(),
  handleAutoAction: vi.fn(),
  ttsEnabled: ttsEnabledRef,
  setTtsEnabled: vi.fn(),
  chatMessagesRef: ref(null),
}

vi.mock('@/composables/useChatView', () => ({ useChatView: () => mockChatViewApi }))

const voiceFeedbackRef = ref('')
const warmVoiceModel = vi.fn(async () => undefined)
const voiceUi = {
  voiceButtonDisabled: ref(false),
  voiceButtonClass: ref(''),
  voiceButtonIcon: ref('fa-microphone'),
  voiceButtonText: ref('语音'),
  voiceButtonTitle: ref('语音输入'),
  voiceFeedbackText: voiceFeedbackRef,
  startVoiceRecording: vi.fn(),
  stopVoiceRecording: vi.fn(),
  cleanupVoiceInput: vi.fn(),
  warmVoiceModel,
}
vi.mock('@/composables/useChatVoiceInput', () => ({ useChatVoiceInput: () => voiceUi }))

const messageUi = {
  messageHeights: ref(new Map()),
  playingMsgIdx: ref(-1),
  latestAiMessageIndex: ref(-1),
  isMessageCollapsed: () => false,
  canCollapseMessage: () => false,
  expandMessage: vi.fn(),
  collapseMessage: vi.fn(),
  canSpeakMessage: () => false,
  toggleMessageTts: vi.fn(),
  batchCalculateHeights: vi.fn(),
  stopMessageTts: vi.fn(),
}
vi.mock('@/composables/useChatMessageUi', () => ({ useChatMessageUi: () => messageUi }))

const officeDocking = {
  panelOpen: ref(false),
  items: ref<any[]>([]),
  processing: ref(false),
  deps: null as any,
  triggerOfficeDocking: vi.fn(),
  onOfficeDockingFileChange: vi.fn(),
  toggleOfficeDockingTarget: vi.fn(),
  pickOfficeWorksheetTemplate: vi.fn(),
  confirmOfficeDockingReview: vi.fn(),
  clearOfficeDockingReview: vi.fn(),
}
vi.mock('@/composables/useChatOfficeDocking', () => ({
  useChatOfficeDocking: (deps: any) => {
    officeDocking.deps = deps
    return {
      officeDockingInputRef: ref(null),
      officeDockingProcessing: officeDocking.processing,
      officeDockingPanelOpen: officeDocking.panelOpen,
      officeDockingReviewItems: officeDocking.items,
      triggerOfficeDocking: officeDocking.triggerOfficeDocking,
      onOfficeDockingFileChange: officeDocking.onOfficeDockingFileChange,
      toggleOfficeDockingTarget: officeDocking.toggleOfficeDockingTarget,
      pickOfficeWorksheetTemplate: officeDocking.pickOfficeWorksheetTemplate,
      confirmOfficeDockingReview: officeDocking.confirmOfficeDockingReview,
      clearOfficeDockingReview: officeDocking.clearOfficeDockingReview,
    }
  },
}))

// ===== store mock =====

let taskCenterError = ''
const taskCenterStoreMock = {
  tasks: ref<any[]>([]),
  actionPending: ref(''),
  get error() { return taskCenterError },
  markTaskRead: vi.fn(async () => undefined),
  controlTask: vi.fn(async () => undefined),
}
vi.mock('@/stores/agentTaskCenter', () => ({ useAgentTaskCenterStore: () => taskCenterStoreMock }))

const modsStoreMock = {
  mods: ref<any[]>([]),
  activeModId: 'mod-a',
  isLoaded: true,
  initialize: vi.fn(async () => undefined),
  clientModsUiOff: false,
  modsForWorkflowUi: [],
}
vi.mock('@/stores/mods', () => ({ useModsStore: () => modsStoreMock }))

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({ currentIndustryId: ref('default') }),
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryPreset: () => ({ placeholderNormal: '请输入消息' }),
  getIndustryQuickButtons: () => [{ text: '测试预览' }, { text: '查库存' }],
}))

vi.mock('@/workflow/coreWorkflowTaskUi', () => ({
  workflowTaskDotStatusClassForTask: () => '',
  workflowTaskDotTitleForTask: () => '',
}))

vi.mock('@/utils/chatTaskLabels', () => ({
  formatTaskTime: () => '',
  formatTaskSourceLabel: () => '',
}))

vi.mock('@/utils/chatStorageKeys', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/chatStorageKeys')>(),
  readAiSessionIdFromStorage: () => null,
  writeAiSessionIdToStorage: vi.fn(),
}))

// ===== 子组件桩：暴露可点击按钮，模拟真实子组件事件 =====

function button(cls: string, label: string, onClick: () => void) {
  return h('button', { class: cls, onClick }, label)
}

const ChatMessageListStub = defineComponent({
  name: 'ChatMessageList',
  props: {
    messages: { type: Array as () => any[], default: () => [] },
    isLoading: { type: Boolean, default: false },
    loadingProgressText: { type: String, default: '' },
    latestAiMessageIndex: { type: Number, default: -1 },
    playingMsgIdx: { type: Number, default: -1 },
    sessionKey: { type: String, default: '' },
    messageHeights: { type: Object, default: () => ({}) },
    proactiveSuggestions: { type: Object, default: () => ({}) },
  },
  emits: [
    'retry-model', 'recall-edit', 'reconcile-turn', 'confirm-destructive', 'retry-save',
    'approval-confirm', 'approval-cancel', 'approve-run', 'expand-message',
    'toggle-message-tts', 'shipment-download-click', 'pick-proactive-suggestion', 'collapse-message',
  ],
  setup(props, { emit }) {
    return () => h('div', { class: 'message-list' }, [
      ...(props.messages as any[]).map((message: any, index: number) =>
        h('div', { class: 'chat-msg', 'data-role': message.role, 'data-idx': index }, String(message.content ?? '')),
      ),
      button('stub-retry-model', '重试模型', () => emit('retry-model', { text: '重发文本', turnId: 'turn-1' })),
      button('stub-recall', '撤回并编辑', () => emit('recall-edit', 0)),
      button('stub-reconcile', '对账', () => emit('reconcile-turn', 3)),
      button('stub-destructive', '清空全部', () => emit('confirm-destructive', { text: '清空全部记录', idempotencyKey: 'idem-1' })),
      button('stub-retry-save', '重试保存', () => emit('retry-save', 'msg-1')),
      button('stub-approval-confirm', '通过审批卡', () => emit('approval-confirm', 'card-1')),
      button('stub-approval-cancel', '取消审批卡', () => emit('approval-cancel', 'card-2')),
      button('stub-approve-run', '通过运行', () => emit('approve-run', 'run-9')),
      button('stub-tts', '播报', () => emit('toggle-message-tts', 1, '播报内容')),
      button('stub-expand', '展开', () => emit('expand-message', 2)),
    ])
  },
})

const ChatSidePanelStub = defineComponent({
  name: 'ChatSidePanel',
  props: {
    currentTask: { type: Object as () => any, default: null },
    taskList: { type: Array as () => any[], default: () => [] },
    historySessions: { type: Array as () => any[], default: () => [] },
    historyError: { type: String, default: '' },
  },
  setup(props, { emit }) {
    return () => h('div', { class: 'side-panel' }, [
      h('span', { class: 'side-panel-task' }, String(props.currentTask?.title || '')),
      button('stub-switch-view', '打开发货记录', () => emit('switch-view', 'products')),
      button('stub-open-shipment', '发货记录视图', () => emit('open-shipment-records')),
      button('stub-approve-task', '通过任务', () => emit('approve-task', 'task-7')),
      button('stub-load-session', '加载历史会话', () => emit('load-session', 'sess-1')),
    ])
  },
})

const ChatHistoryModalStub = defineComponent({
  name: 'ChatHistoryModal',
  props: {
    show: { type: Boolean, default: false },
    historySessions: { type: Array as () => any[], default: () => [] },
    historyLoading: { type: Boolean, default: false },
    historyError: { type: String, default: '' },
    historyHasMore: { type: Boolean, default: false },
    historyLoadingMore: { type: Boolean, default: false },
    currentSessionId: { type: String, default: '' },
  },
  emits: ['close', 'refresh', 'clear', 'load-session', 'load-more'],
  setup(props, { emit }) {
    return () => props.show
      ? h('div', { class: 'history-modal' }, [
        h('span', { class: 'history-count' }, String((props.historySessions as any[]).length)),
        button('stub-history-close', '关闭', () => emit('close')),
        button('stub-history-refresh', '刷新', () => emit('refresh')),
        button('stub-history-clear', '清空', () => emit('clear')),
        button('stub-history-load', '打开会话', () => emit('load-session', 'sess-9')),
      ])
      : h('div', { class: 'history-modal-hidden' })
  },
})

const ChatInputToolbarStub = defineComponent({
  name: 'ChatInputToolbar',
  props: {
    proactiveSuggestionsEnabled: { type: Boolean, default: false },
    ttsEnabled: { type: Boolean, default: false },
    attachmentUploading: { type: Boolean, default: false },
    multimodalPendingCount: { type: Number, default: 0 },
    officeDockingProcessing: { type: Boolean, default: false },
  },
  emits: ['new-conversation', 'trigger-office-docking', 'attachment-file-change', 'proactive-suggestions-change', 'toggle-tts'],
  setup(_props, { emit }) {
    return () => h('div', { class: 'input-toolbar' }, [
      button('stub-new-conversation', '新对话', () => emit('new-conversation')),
      button('stub-office-docking', '办公对接', () => emit('trigger-office-docking')),
      button('stub-excel-change', '上传 Excel', () => emit('attachment-file-change', { target: { files: [] } })),
      button('stub-proactive-toggle', '主动意识', () => emit('proactive-suggestions-change', true)),
      button('stub-tts-toggle', '朗读', () => emit('toggle-tts', true)),
    ])
  },
})

const TaskWorkspaceContextBarStub = defineComponent({
  name: 'TaskWorkspaceContextBar',
  props: {
    title: { type: String, default: '' },
    status: { type: String, default: '' },
    stage: { type: String, default: '' },
    progress: { type: Number, default: undefined },
    unreadCount: { type: Number, default: 0 },
    approvalRequired: { type: Boolean, default: false },
    attempt: { type: Number, default: 1 },
    runCount: { type: Number, default: 1 },
    capabilities: { type: Object, default: () => ({}) },
    actionPending: { type: String, default: '' },
  },
  emits: ['control'],
  setup(props, { emit }) {
    return () => h('div', { class: 'workspace-bar' }, [
      h('span', { class: 'workspace-title' }, props.title),
      h('span', { class: 'workspace-status' }, props.status),
      button('stub-control-approve', '通过', () => emit('control', 'approve')),
      button('stub-control-pause', '暂停', () => emit('control', 'pause')),
    ])
  },
})

const ChatOfficeDockingReviewStub = defineComponent({
  name: 'ChatOfficeDockingReview',
  props: {
    items: { type: Array as () => any[], default: () => [] },
    processing: { type: Boolean, default: false },
  },
  emits: ['toggle-target', 'pick-template', 'confirm', 'close'],
  setup(props, { emit }) {
    return () => h('div', { class: 'office-review' }, [
      h('span', { class: 'office-review-count' }, String((props.items as any[]).length)),
      button('stub-office-toggle', '切换入库', () => emit('toggle-target', 'item-1', 'database', true)),
      button('stub-office-template', '选择模板', () => emit('pick-template', 'item-1', 2)),
      button('stub-office-confirm', '提交入库', () => emit('confirm')),
      button('stub-office-close', '关闭复核', () => emit('close')),
    ])
  },
})

const ChatQuickActionsStub = defineComponent({
  name: 'ChatQuickActions',
  props: { buttons: { type: Array as () => any[], default: () => [] } },
  emits: ['quick'],
  setup(props, { emit }) {
    return () => h('div', { class: 'quick-actions' },
      (props.buttons as any[]).map((btn: any) =>
        h('button', { class: 'stub-quick', onClick: () => emit('quick', btn.text) }, btn.text),
      ))
  },
})

const PaneResizeHandleStub = defineComponent({
  name: 'PaneResizeHandle',
  emits: ['resize-start', 'reset'],
  setup(_props, { emit }) {
    return () => h('div', [
      button('stub-resize-start', '拖动', () => emit('resize-start', new MouseEvent('mousedown', { clientX: 300 }))),
      button('stub-resize-reset', '重置', () => emit('reset')),
    ])
  },
})

vi.mock('@/components/PaneResizeHandle.vue', () => ({ default: PaneResizeHandleStub }))
vi.mock('@/components/chat/ChatQuickActions.vue', () => ({ default: ChatQuickActionsStub }))
vi.mock('@/components/chat/ChatMessageList.vue', () => ({ default: ChatMessageListStub }))
vi.mock('@/components/chat/ChatSidePanel.vue', () => ({ default: ChatSidePanelStub }))
vi.mock('@/components/chat/ChatInputToolbar.vue', () => ({ default: ChatInputToolbarStub }))
vi.mock('@/components/chat/ChatHistoryModal.vue', () => ({ default: ChatHistoryModalStub }))
vi.mock('@/components/chat/ChatOfficeDockingReview.vue', () => ({ default: ChatOfficeDockingReviewStub }))
vi.mock('@/components/chat/TaskWorkspaceContextBar.vue', () => ({ default: TaskWorkspaceContextBarStub }))
vi.mock('@/components/chat/ChatModelRecovery.vue', () => ({
  default: defineComponent({ name: 'ChatModelRecovery', setup: () => () => h('div') }),
}))

// ===== 测试辅助 =====

const mounted: VueWrapper[] = []

function resetRefs() {
  messagesRef.value = []
  cacheErrorRef.value = ''
  currentTaskRef.value = null
  isLoadingRef.value = false
  showHistoryRef.value = false
  historySessionsRef.value = []
  historyErrorRef.value = ''
  artifactStagingRef.value = []
  multimodalStagingRef.value = []
  unsupportedStagingRef.value = []
  excelSheetOptionsRef.value = []
  linkedExcelSheetRef.value = null
  linkedExcelAllSheetsRef.value = false
  latestAssistantPushRef.value = null
  ttsEnabledRef.value = false
  taskListRef.value = []
  voiceFeedbackRef.value = ''
  officeDocking.panelOpen.value = false
  officeDocking.items.value = []
  officeDocking.processing.value = false
  taskCenterStoreMock.tasks.value = []
  taskCenterError = ''
}

async function createTestRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/chat', name: 'chat', component: { template: '<div />' } },
    ],
  })
  await router.push('/chat')
  await router.isReady()
  return router
}

async function mountChatView(props: Record<string, unknown> = {}, options: { flush?: boolean } = {}) {
  const router = await createTestRouter()
  const ChatView = (await import('./ChatView.vue')).default
  const wrapper = mount(ChatView, { props, attachTo: document.body, global: { plugins: [router] } })
  mounted.push(wrapper)
  if (options.flush !== false) await flushPromises()
  return wrapper
}

function fakeFileEntry(name: string, type = '') {
  return {
    isFile: true,
    isDirectory: false,
    file: (onOk: (file: File) => void) => onOk(new File(['data'], name, { type })),
  }
}

function fakeBrokenFileEntry() {
  return {
    isFile: true,
    isDirectory: false,
    file: (_onOk: (file: File) => void, onError: () => void) => onError(),
  }
}

function fakeBrokenDirectoryEntry() {
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (_onOk: (items: any[]) => void, onError: () => void) => onError(),
    }),
  }
}

function fakeOpaqueEntry() {
  return { isFile: false, isDirectory: false }
}

function fakeDirectoryEntry(children: any[]) {
  let served = false
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (onOk: (items: any[]) => void) => {
        onOk(served ? [] : children)
        served = true
      },
    }),
  }
}

async function dropFiles(wrapper: VueWrapper, dataTransfer: unknown) {
  const event = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: dataTransfer })
  wrapper.get('.input-area').element.dispatchEvent(event)
  await flushPromises()
}

async function dragEvent(wrapper: VueWrapper, type: 'dragenter' | 'dragover' | 'dragleave', dataTransfer: unknown) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: dataTransfer })
  wrapper.get('.input-area').element.dispatchEvent(event)
  await nextTick()
}

describe('ChatView interactions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    resetRefs()
    setRuntimeTenantStorageScopeInput(null)
    invalidateTenantStorageScopeCache()
    getActiveConversation.mockReset()
    getActiveConversation.mockRejectedValue(new Error('offline'))
    mockChatViewApi.syncSessionMessages.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmount()
    vi.unstubAllGlobals()
    document.body.replaceChildren()
    setRuntimeTenantStorageScopeInput(null)
    invalidateTenantStorageScopeCache()
    localStorage.clear()
  })

  it('桌面快捷命令复用当前对话的新建和历史会话控制器，忙碌时不打断', async () => {
    const wrapper = await mountChatView()
    window.dispatchEvent(new Event('xcagi:workspace-open-sessions'))
    expect(mockChatViewApi.showHistoryPanel).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('xcagi:workspace-new-conversation'))
    await flushPromises()
    expect(mockChatViewApi.newConversation).toHaveBeenCalledTimes(1)
    isLoadingRef.value = true
    window.dispatchEvent(new Event('xcagi:workspace-new-conversation'))
    await flushPromises()
    expect(mockChatViewApi.newConversation).toHaveBeenCalledTimes(1)
    expect(showAppToast).toHaveBeenCalledWith(expect.stringContaining('当前对话'), 'warning')
    wrapper.unmount()
    window.dispatchEvent(new Event('xcagi:workspace-new-conversation'))
    expect(mockChatViewApi.newConversation).toHaveBeenCalledTimes(1)
  })

  it('独立任务工作区不响应主对话的新建及历史会话快捷命令', async () => {
    await mountChatView({ workspaceTaskId: 'task-1', workspaceConversationId: 'conv-1' })
    window.dispatchEvent(new Event('xcagi:workspace-open-sessions'))
    window.dispatchEvent(new Event('xcagi:workspace-new-conversation'))
    await flushPromises()
    expect(mockChatViewApi.newConversation).not.toHaveBeenCalled()
    expect(mockChatViewApi.showHistoryPanel).not.toHaveBeenCalled()
  })

  it('语音通话入口只发起点话且不展开悬浮面板', async () => {
    const wrapper = await mountChatView()
    const listener = vi.fn()
    window.addEventListener('xcagi:start-voice-call', listener)
    await wrapper.get('.voice-call-entry-btn').trigger('click')
    expect(listener).toHaveBeenCalledTimes(1)
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ expandPanel: false })
    window.removeEventListener('xcagi:start-voice-call', listener)
  })

  it('通话轮复用当前消息与发送通道，卸载后清空登记', async () => {
    const wrapper = await mountChatView()
    expect(voiceChatBridge.value?.messages).toBe(messagesRef)
    await voiceChatBridge.value?.send?.('帮我查一下库存')
    expect(mockChatViewApi.sendMessage).toHaveBeenCalledWith('帮我查一下库存')
    wrapper.unmount()
    mounted.length = 0
    expect(voiceChatBridge.value?.messages).toBeNull()
  })

  it('任务工作区显示任务标题并登记已读', async () => {
    taskCenterStoreMock.tasks.value = [{ task_id: 'task-42', title: '发货任务', status: 'running' }]
    const wrapper = await mountChatView({ workspaceTaskId: 'task-42' })
    expect(wrapper.get('.workspace-title').text()).toBe('发货任务')
    expect(taskCenterStoreMock.markTaskRead).toHaveBeenCalledWith('task-42')
  })

  it('工作区控制条把动作透传给任务中心', async () => {
    taskCenterStoreMock.tasks.value = [{ task_id: 'task-42', title: '发货任务', status: 'waiting_user' }]
    const wrapper = await mountChatView({ workspaceTaskId: 'task-42' })
    await wrapper.get('.stub-control-approve').trigger('click')
    await flushPromises()
    expect(taskCenterStoreMock.controlTask).toHaveBeenCalledWith('task-42', 'approve')
    await wrapper.get('.stub-control-pause').trigger('click')
    await flushPromises()
    expect(taskCenterStoreMock.controlTask).toHaveBeenCalledWith('task-42', 'pause')
  })

  it('任务中心报错时弹出错误提示', async () => {
    taskCenterStoreMock.tasks.value = [{ task_id: 'task-42', title: '发货任务', status: 'running' }]
    const wrapper = await mountChatView({ workspaceTaskId: 'task-42' })
    taskCenterError = '任务已被其他账号接管'
    await wrapper.get('.stub-control-approve').trigger('click')
    await flushPromises()
    expect(showAppToast).toHaveBeenCalledWith('任务已被其他账号接管', 'error', { duration: 8000 })
  })

  it('本机保存失败时显示告警并可重试', async () => {
    cacheErrorRef.value = '本机会话保存失败'
    const wrapper = await mountChatView()
    const warning = wrapper.get('.chat-cache-warning')
    expect(warning.attributes('role')).toBe('alert')
    expect(warning.text()).toContain('本机会话保存失败')
    await wrapper.get('.chat-cache-warning button').trigger('click')
    expect(mockChatViewApi.retryMessagesCache).toHaveBeenCalledTimes(1)
  })

  it('渲染消息列表角色与内容', async () => {
    messagesRef.value = [
      { role: 'user', content: '导出九月销售单' },
      { role: 'ai', content: '已生成发货单报表' },
    ]
    const wrapper = await mountChatView()
    const rows = wrapper.findAll('.chat-msg')
    expect(rows).toHaveLength(2)
    expect(rows[0].attributes('data-role')).toBe('user')
    expect(rows[0].text()).toBe('导出九月销售单')
    expect(rows[1].text()).toBe('已生成发货单报表')
  })

  it('工具卡审批按钮把卡片 id 交给审批流程', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-approval-confirm').trigger('click')
    await wrapper.get('.stub-approval-cancel').trigger('click')
    expect(mockChatViewApi.confirmWorkflowFromCard).toHaveBeenCalledWith('card-1')
    expect(mockChatViewApi.cancelWorkflowFromCard).toHaveBeenCalledWith('card-2')
  })

  it('审批运行卡携带运行时来源并刷新会话消息', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-approve-run').trigger('click')
    await flushPromises()
    expect(approveRunWithFreshGrant).toHaveBeenCalledTimes(1)
    const [runId, options] = approveRunWithFreshGrant.mock.calls[0] as unknown as [string, any]
    expect(runId).toBe('run-9')
    expect(options.runtimeContext).toEqual({ source: 'chat_run_trace_approval' })
    expect(options.isCurrent()).toBe(true)
    expect(mockChatViewApi.syncSessionMessages).toHaveBeenCalled()
  })

  it('重试模型会带上失败轮次并清空输入草稿', async () => {
    const wrapper = await mountChatView()
    ;(wrapper.vm as any).messageInput = '半截草稿'
    await wrapper.get('.stub-retry-model').trigger('click')
    await flushPromises()
    expect((wrapper.vm as any).messageInput).toBe('')
    expect(mockChatViewApi.retryModelOnly).toHaveBeenCalledWith('重发文本', 'turn-1')
  })

  it('确认撤回后把原文本回填输入框并聚焦', async () => {
    mockChatViewApi.recallUserMessage.mockResolvedValueOnce({ ok: true, text: '重新整理发货单' })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = await mountChatView()
    await wrapper.get('.stub-recall').trigger('click')
    await flushPromises()
    expect(mockChatViewApi.recallUserMessage).toHaveBeenCalledWith(0)
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('撤销可核实的业务操作'))
    expect((wrapper.vm as any).messageInput).toBe('重新整理发货单')
    expect(document.activeElement?.id).toBe('messageInput')
    confirmSpy.mockRestore()
  })

  it('撤回被拒绝时提示原因且不回填', async () => {
    mockChatViewApi.recallUserMessage.mockResolvedValueOnce({ ok: false, message: '该轮次已进入执行，无法撤回' })
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    const wrapper = await mountChatView()
    await wrapper.get('.stub-recall').trigger('click')
    await flushPromises()
    expect(alertSpy).toHaveBeenCalledWith('该轮次已进入执行，无法撤回')
    expect((wrapper.vm as any).messageInput).toBe('')
    confirmSpy.mockRestore()
    alertSpy.mockRestore()
  })

  it('撤回前取消确认不会调用撤回接口', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = await mountChatView()
    await wrapper.get('.stub-recall').trigger('click')
    await flushPromises()
    expect(mockChatViewApi.recallUserMessage).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('轮次对账失败时提示用户', async () => {
    mockChatViewApi.reconcileTurnMessage.mockResolvedValueOnce({ ok: false, message: '本轮已结束，无法对账' })
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    const wrapper = await mountChatView()
    await wrapper.get('.stub-reconcile').trigger('click')
    await flushPromises()
    expect(mockChatViewApi.reconcileTurnMessage).toHaveBeenCalledWith(3)
    expect(alertSpy).toHaveBeenCalledWith('本轮已结束，无法对账')
    alertSpy.mockRestore()
  })

  it('轮次对账成功时不打扰用户', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    const wrapper = await mountChatView()
    await wrapper.get('.stub-reconcile').trigger('click')
    await flushPromises()
    expect(alertSpy).not.toHaveBeenCalled()
    alertSpy.mockRestore()
  })

  it('破坏性操作确认透传文本与幂等键', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-destructive').trigger('click')
    await flushPromises()
    expect(mockChatViewApi.confirmDestructive).toHaveBeenCalledWith('清空全部记录', 'idem-1')
  })

  it('重试保存消息透传消息 id', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-retry-save').trigger('click')
    expect(mockChatViewApi.retryMessageSave).toHaveBeenCalledWith('msg-1')
  })

  it('消息折叠与播报事件透传索引', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-tts').trigger('click')
    await wrapper.get('.stub-expand').trigger('click')
    expect(messageUi.toggleMessageTts).toHaveBeenCalledWith(1, '播报内容')
    expect(messageUi.expandMessage).toHaveBeenCalledWith(2)
  })

  it('窗口重试事件找回最近失败轮次并重发', async () => {
    messagesRef.value = [
      { role: 'user', content: '<p>导出九月销售单</p>', turnId: 'turn-7' },
      { role: 'ai', content: '处理失败：模型超时', turnId: 'turn-7', workflowAction: 'failed' },
    ]
    const wrapper = await mountChatView()
    ;(wrapper.vm as any).messageInput = '残留草稿'
    window.dispatchEvent(new CustomEvent('xcagi:retry-last-failed-turn'))
    await flushPromises()
    expect(mockChatViewApi.retryModelOnly).toHaveBeenCalledWith('导出九月销售单', 'turn-7')
    expect((wrapper.vm as any).messageInput).toBe('')
  })

  it('没有失败轮次时提示用户重新输入', async () => {
    messagesRef.value = [{ role: 'ai', content: '报表已生成' }]
    await mountChatView()
    window.dispatchEvent(new CustomEvent('xcagi:retry-last-failed-turn'))
    await flushPromises()
    expect(mockChatViewApi.retryModelOnly).not.toHaveBeenCalled()
    expect(showAppToast).toHaveBeenCalledWith('没有可重试的失败轮次，请重新输入。', 'info')
  })

  it('失败轮次缺少对应提问时跳过并提示', async () => {
    messagesRef.value = [
      { role: 'ai', content: '模型未返回可显示内容', turnId: 'turn-x', workflowAction: 'failed' },
      { role: 'ai', content: '处理失败', turnId: '', workflowAction: 'failed' },
    ]
    await mountChatView()
    window.dispatchEvent(new CustomEvent('xcagi:retry-last-failed-turn'))
    await flushPromises()
    expect(mockChatViewApi.retryModelOnly).not.toHaveBeenCalled()
    expect(showAppToast).toHaveBeenCalledWith('没有可重试的失败轮次，请重新输入。', 'info')
  })

  it('按住语音按钮收音，松开或移出后结束', async () => {
    const wrapper = await mountChatView()
    const button = wrapper.get('.voice-input-btn')
    await button.trigger('mousedown')
    expect(voiceUi.startVoiceRecording).toHaveBeenCalled()
    await button.trigger('mouseup')
    expect(voiceUi.stopVoiceRecording).toHaveBeenCalledWith(false)
    await button.trigger('mouseleave')
    expect(voiceUi.stopVoiceRecording).toHaveBeenCalledWith(true)
    await button.trigger('touchstart')
    expect(voiceUi.startVoiceRecording).toHaveBeenCalledTimes(2)
    await button.trigger('touchend')
    expect(voiceUi.stopVoiceRecording).toHaveBeenCalledWith(false)
    await button.trigger('touchcancel')
    expect(voiceUi.stopVoiceRecording).toHaveBeenCalledWith(true)
    expect(wrapper.get('.voice-input-btn').text()).toContain('语音')
  })

  it('侧边栏切换视图与打开发货记录派发全局事件', async () => {
    const wrapper = await mountChatView()
    const listener = vi.fn()
    window.addEventListener('xcagi:switch-view', listener)
    await wrapper.get('.stub-switch-view').trigger('click')
    await wrapper.get('.stub-open-shipment').trigger('click')
    expect(listener.mock.calls.map(call => (call[0] as CustomEvent).detail.view))
      .toEqual(['products', 'shipment-records'])
    window.removeEventListener('xcagi:switch-view', listener)
  })

  it('侧边栏显示当前任务并透传任务操作', async () => {
    currentTaskRef.value = { id: 'task-7', title: '补发订单' }
    const wrapper = await mountChatView()
    expect(wrapper.get('.side-panel-task').text()).toBe('补发订单')
    await wrapper.get('.stub-approve-task').trigger('click')
    await wrapper.get('.stub-load-session').trigger('click')
    await flushPromises()
    expect(mockChatViewApi.approveTask).toHaveBeenCalledWith('task-7')
    expect(mockChatViewApi.loadSession).toHaveBeenCalledWith('sess-1')
  })

  it('历史会话弹窗的刷新、清空、打开与关闭都可用', async () => {
    showHistoryRef.value = true
    historySessionsRef.value = [{ id: 'sess-9', title: '昨天' }]
    const wrapper = await mountChatView()
    expect(wrapper.get('.history-count').text()).toBe('1')
    await wrapper.get('.stub-history-refresh').trigger('click')
    await wrapper.get('.stub-history-clear').trigger('click')
    await wrapper.get('.stub-history-load').trigger('click')
    await wrapper.get('.stub-history-close').trigger('click')
    expect(mockChatViewApi.showHistoryPanel).toHaveBeenCalled()
    expect(mockChatViewApi.clearHistorySessions).toHaveBeenCalled()
    expect(mockChatViewApi.loadSession).toHaveBeenCalledWith('sess-9')
    expect(showHistoryRef.value).toBe(false)
  })

  it('拖入支持的表格文件进入统一上传入口', async () => {
    const wrapper = await mountChatView()
    const file = new File(['a'], '发货明细.xlsx')
    await dropFiles(wrapper, { items: [], files: [file] })
    expect(mockChatViewApi.onAttachmentFileChange).toHaveBeenCalledTimes(1)
    const event = mockChatViewApi.onAttachmentFileChange.mock.calls[0][0] as any
    expect(event.target.files.map((item: File) => item.name)).toEqual(['发货明细.xlsx'])
    expect(event.target.value).toBe('')
  })

  it('拖入不支持的文件时给出提示而不上传', async () => {
    const wrapper = await mountChatView()
    await dropFiles(wrapper, { items: [], files: [new File(['a'], 'setup.exe')] })
    expect(mockChatViewApi.onAttachmentFileChange).not.toHaveBeenCalled()
    expect(mockChatViewApi.addAndSaveMessage).toHaveBeenCalledWith(
      '[附件] 不支持的文件类型，请拖入 Excel、图片、PDF 或包含它们的文件夹', 'ai')
  })

  it('拖入文件夹时递归收集受支持文件', async () => {
    const wrapper = await mountChatView()
    const root = fakeDirectoryEntry([
      fakeFileEntry('发货明细.xlsx'),
      fakeDirectoryEntry([fakeFileEntry('现场照片.png', 'image/png')]),
    ])
    await dropFiles(wrapper, {
      items: [{ kind: 'file', webkitGetAsEntry: () => root }],
      files: [new File(['a'], 'ignored.txt')],
    })
    const event = mockChatViewApi.onAttachmentFileChange.mock.calls[0][0] as any
    expect(event.target.files.map((item: File) => item.name)).toEqual(['发货明细.xlsx', '现场照片.png'])
  })

  it('按 MIME 接受无扩展名的图片文件', async () => {
    const wrapper = await mountChatView()
    await dropFiles(wrapper, { items: [], files: [new File(['a'], 'paste', { type: 'image/png' })] })
    expect(mockChatViewApi.onAttachmentFileChange).toHaveBeenCalledTimes(1)
  })

  it('文件夹扫描失败时回退到普通文件列表', async () => {
    const wrapper = await mountChatView()
    await dropFiles(wrapper, {
      items: [
        { kind: 'file', webkitGetAsEntry: () => fakeBrokenFileEntry() },
        { kind: 'file', webkitGetAsEntry: () => fakeBrokenDirectoryEntry() },
        { kind: 'file', webkitGetAsEntry: () => fakeOpaqueEntry() },
      ],
      files: [new File(['a'], '发货明细.xlsx')],
    })
    const event = mockChatViewApi.onAttachmentFileChange.mock.calls[0][0] as any
    expect(event.target.files.map((item: File) => item.name)).toEqual(['发货明细.xlsx'])
  })

  it('空拖拽不触发上传', async () => {
    const wrapper = await mountChatView()
    await dropFiles(wrapper, { items: [], files: [] })
    await dropFiles(wrapper, null)
    expect(mockChatViewApi.onAttachmentFileChange).not.toHaveBeenCalled()
    expect(mockChatViewApi.addAndSaveMessage).not.toHaveBeenCalled()
  })

  it('回复进行中忽略拖入文件', async () => {
    isLoadingRef.value = true
    const wrapper = await mountChatView()
    await dropFiles(wrapper, { items: [], files: [new File(['a'], '发货明细.xlsx')] })
    expect(mockChatViewApi.onAttachmentFileChange).not.toHaveBeenCalled()
  })

  it('拖拽进入时显示覆盖层，离开后移除', async () => {
    const wrapper = await mountChatView()
    await dragEvent(wrapper, 'dragenter', { types: ['Files'], dropEffect: '' })
    expect(wrapper.get('.composer-drop-overlay').text()).toBe('松开以上传附件')
    expect(wrapper.get('.input-area').classes()).toContain('input-area--dragover')
    await dragEvent(wrapper, 'dragenter', { types: ['Files'], dropEffect: '' })
    await dragEvent(wrapper, 'dragover', { types: ['Files'], dropEffect: '' })
    await dragEvent(wrapper, 'dragleave', null)
    expect(wrapper.find('.composer-drop-overlay').exists()).toBe(true)
    await dragEvent(wrapper, 'dragleave', null)
    expect(wrapper.find('.composer-drop-overlay').exists()).toBe(false)
  })

  it('非文件拖拽不显示覆盖层', async () => {
    const wrapper = await mountChatView()
    await dragEvent(wrapper, 'dragenter', { types: ['text/plain'] })
    await dragEvent(wrapper, 'dragover', { types: ['text/plain'], dropEffect: '' })
    expect(wrapper.find('.composer-drop-overlay').exists()).toBe(false)
  })

  it('拖入完成后清除拖拽态', async () => {
    const wrapper = await mountChatView()
    await dragEvent(wrapper, 'dragenter', { types: ['Files'] })
    await dropFiles(wrapper, { items: [], files: [] })
    expect(wrapper.find('.composer-drop-overlay').exists()).toBe(false)
  })

  it('待发送附件可逐项移除并标注跳过原因', async () => {
    artifactStagingRef.value = [{ artifact_id: 'art-1', filename: '发货明细.xlsx' }]
    multimodalStagingRef.value = [{ kind: 'image', filename: '现场照片.png' }]
    unsupportedStagingRef.value = ['现场.zip']
    const wrapper = await mountChatView()
    expect(wrapper.get('[aria-label="移除 发货明细.xlsx"]')).toBeTruthy()
    expect(wrapper.get('[aria-label="移除 现场照片.png"]')).toBeTruthy()
    expect(wrapper.get('.composer-attachment--skipped').text()).toContain('已跳过')
    await wrapper.get('[aria-label="移除 发货明细.xlsx"]').trigger('click')
    await wrapper.get('[aria-label="移除 现场照片.png"]').trigger('click')
    await wrapper.get('[aria-label="忽略 现场.zip"]').trigger('click')
    expect(mockChatViewApi.removeArtifactFile).toHaveBeenCalledWith('art-1')
    expect(mockChatViewApi.removeMultimodalFile).toHaveBeenCalledWith(
      expect.objectContaining({ filename: '现场照片.png' }))
    expect(mockChatViewApi.dismissUnsupportedFile).toHaveBeenCalledWith('现场.zip')
  })

  it('选择工作表模板会绑定到当前对话', async () => {
    excelSheetOptionsRef.value = [
      { sheet_name: '发货明细', sheet_index: 1 },
      { sheet_name: '汇总', sheet_index: 2 },
    ]
    const wrapper = await mountChatView()
    const labelButton = wrapper.get('.sheet-link-bar .sheet-link-btn')
    expect(labelButton.text()).toBe('选择工作表模板')
    await labelButton.trigger('click')
    const picker = wrapper.get('.sheet-link-picker')
    const sheetButton = picker.findAll('.sheet-link-btn').find(btn => btn.text() === '发货明细')
    await sheetButton!.trigger('click')
    expect(mockChatViewApi.bindExcelSheetToChat).toHaveBeenCalledWith({ sheet_name: '发货明细', sheet_index: 1 })
    expect(wrapper.find('.sheet-link-picker').exists()).toBe(false)
  })

  it('全部工作表模板与不使用模板互斥切换', async () => {
    excelSheetOptionsRef.value = [{ sheet_name: '发货明细', sheet_index: 1 }]
    const wrapper = await mountChatView()
    await wrapper.get('.sheet-link-bar .sheet-link-btn').trigger('click')
    const allButton = wrapper.findAll('.sheet-link-picker .sheet-link-btn').find(btn => btn.text() === '全部工作表')
    await allButton!.trigger('click')
    expect(mockChatViewApi.bindAllExcelSheetsToChat).toHaveBeenCalled()
    linkedExcelAllSheetsRef.value = true
    await nextTick()
    expect(wrapper.get('.sheet-link-bar .sheet-link-btn').text()).toBe('全部工作表')
    await wrapper.get('.sheet-link-bar .sheet-link-btn').trigger('click')
    const noneButton = wrapper.findAll('.sheet-link-picker .sheet-link-btn').find(btn => btn.text() === '不使用模板')
    await noneButton!.trigger('click')
    expect(linkedExcelSheetRef.value).toBeNull()
    expect(linkedExcelAllSheetsRef.value).toBe(false)
  })

  it('已绑定工作表时按钮显示工作表名', async () => {
    excelSheetOptionsRef.value = [{ sheet_name: '发货明细', sheet_index: 1 }]
    linkedExcelSheetRef.value = { sheet_name: '发货明细', sheet_index: 1 }
    const wrapper = await mountChatView()
    expect(wrapper.get('.sheet-link-bar .sheet-link-btn').text()).toBe('发货明细')
    expect(wrapper.get('.sheet-link-bar .sheet-link-btn').classes()).toContain('active')
  })

  it('工具栏按钮触发新对话、办公对接、上传与朗读开关', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-new-conversation').trigger('click')
    await wrapper.get('.stub-office-docking').trigger('click')
    await wrapper.get('.stub-excel-change').trigger('click')
    await wrapper.get('.stub-tts-toggle').trigger('click')
    expect(mockChatViewApi.newConversation).toHaveBeenCalled()
    expect(officeDocking.triggerOfficeDocking).toHaveBeenCalled()
    expect(mockChatViewApi.onAttachmentFileChange).toHaveBeenCalledWith({ target: { files: [] } })
    expect(mockChatViewApi.setTtsEnabled).toHaveBeenCalledWith(true)
  })

  it('主动意识开关写入本地偏好', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('.stub-proactive-toggle').trigger('click')
    expect(localStorage.getItem('xcagi_proactive_suggestions')).toBe('1')
    const toolbar = wrapper.findComponent({ name: 'ChatInputToolbar' })
    expect(toolbar.props('proactiveSuggestionsEnabled')).toBe(true)
  })

  it('办公文件复核面板可切换入库目标、选择模板、提交与关闭', async () => {
    officeDocking.panelOpen.value = true
    officeDocking.items.value = [{ id: 'item-1', fileName: '发货明细.xlsx', status: 'ready' }]
    const wrapper = await mountChatView()
    expect(wrapper.get('.office-review-count').text()).toBe('1')
    await wrapper.get('.stub-office-toggle').trigger('click')
    await wrapper.get('.stub-office-template').trigger('click')
    await wrapper.get('.stub-office-confirm').trigger('click')
    await wrapper.get('.stub-office-close').trigger('click')
    expect(officeDocking.toggleOfficeDockingTarget).toHaveBeenCalledWith('item-1', 'database', true)
    expect(officeDocking.pickOfficeWorksheetTemplate).toHaveBeenCalledWith('item-1', 2)
    expect(officeDocking.confirmOfficeDockingReview).toHaveBeenCalled()
    expect(officeDocking.clearOfficeDockingReview).toHaveBeenCalled()
  })

  it('入库确认消息会填入输入框并发送', async () => {
    await mountChatView()
    expect(officeDocking.deps?.sendDatabaseImportMessage).toBeTypeOf('function')
    await officeDocking.deps.sendDatabaseImportMessage('把这张表导入数据库')
    expect(mockChatViewApi.sendMessage).toHaveBeenCalledWith('把这张表导入数据库')
  })

  it('选择办公文件后交给复核流程处理', async () => {
    const wrapper = await mountChatView()
    const input = wrapper.get('input[type="file"]')
    const file = new File(['a'], '发货明细.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    expect(officeDocking.onOfficeDockingFileChange).toHaveBeenCalledTimes(1)
    expect(wrapper.get('input[type="file"]').attributes('accept')).toContain('.xlsx')
  })

  it('缓存后的对话页重新激活会恢复本账号会话', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    const ChatView = (await import('./ChatView.vue')).default
    const Host = defineComponent({
      props: { show: { type: Boolean, default: true } },
      setup(hostProps) {
        return () => h(KeepAlive, null, [hostProps.show ? h(ChatView) : h('div', { class: 'hidden' })])
      },
    })
    const router = await createTestRouter()
    const wrapper = mount(Host, { attachTo: document.body, global: { plugins: [router] } })
    mounted.push(wrapper)
    await flushPromises()
    await wrapper.setProps({ show: false })
    await flushPromises()
    await wrapper.setProps({ show: true })
    await flushPromises()
    expect(mockChatViewApi.restoreLatestOwnedSession).toHaveBeenCalled()
  })

  it('快捷按钮只填充输入框并聚焦到末尾', async () => {
    const wrapper = await mountChatView()
    const quick = wrapper.findAll('.stub-quick').find(btn => btn.text() === '查库存')
    await quick!.trigger('click')
    await flushPromises()
    expect((wrapper.vm as any).messageInput).toBe('查库存')
    expect(mockChatViewApi.sendMessage).not.toHaveBeenCalled()
    const textarea = document.getElementById('messageInput') as HTMLTextAreaElement
    expect(document.activeElement).toBe(textarea)
    expect(textarea.selectionStart).toBe('查库存'.length)
  })

  it('语音反馈文本覆盖编辑状态并标记错误', async () => {
    voiceFeedbackRef.value = '麦克风权限被拒绝'
    const wrapper = await mountChatView()
    const status = wrapper.get('#chat-composer-status')
    expect(status.text()).toBe('麦克风权限被拒绝')
    expect(status.classes()).toContain('chat-composer-status--error')
  })

  it('回复进行中提供停止按钮并显示纠正文案', async () => {
    isLoadingRef.value = true
    const wrapper = await mountChatView()
    expect(wrapper.get('#chat-composer-status').text()).toContain('可停止回复或发送纠正')
    expect(wrapper.get('#sendMessageBtn').text()).toBe('发送纠正')
    await wrapper.get('[data-testid="stop-reply"]').trigger('click')
    expect(mockChatViewApi.stopReply).toHaveBeenCalled()
  })

  it('拖动任务面板分隔条与重置会走布局逻辑', async () => {
    const wrapper = await mountChatView()
    expect(wrapper.get('.chat-container').attributes('style')).toContain('--chat-right-pane-width')
    await wrapper.get('.stub-resize-start').trigger('click')
    await wrapper.get('.stub-resize-reset').trigger('click')
    expect(wrapper.get('.chat-pane-handle-slot').exists()).toBe(true)
  })

  it('挂载后定时预热语音模型', async () => {
    const captured: Array<() => void> = []
    const realSetTimeout = window.setTimeout
    const timerSpy = vi.spyOn(window, 'setTimeout').mockImplementation(((fn: any) => {
      captured.push(fn)
      return 0
    }) as any)
    try {
      await mountChatView({}, { flush: false })
    } finally {
      timerSpy.mockRestore()
    }
    expect(captured.length).toBeGreaterThan(0)
    captured.forEach(fn => fn())
    await flushPromises()
    expect(warmVoiceModel).toHaveBeenCalled()
    expect(realSetTimeout).toBeTypeOf('function')
  })

  it('登录态就绪后采用服务端最近会话并同步消息', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    getActiveConversation.mockResolvedValue({ conversation_id: 'server-55' })
    const wrapper = await mountChatView()
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('server-55')
    expect(writeAiSessionIdToStorage).toHaveBeenCalledWith('server-55')
    expect(mockChatViewApi.syncSessionMessages).toHaveBeenCalled()
    expect(mockChatViewApi.restoreLatestOwnedSession).not.toHaveBeenCalled()
  })

  it('账号作用域变化时保留工作区会话并同步消息', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    const wrapper = await mountChatView({ workspaceConversationId: 'ws-conv-1' })
    await flushPromises()
    mockChatViewApi.syncSessionMessages.mockRejectedValue(new Error('offline'))
    setRuntimeTenantStorageScopeInput({ tenantId: 2, localUserId: 2 })
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('ws-conv-1')
    expect(mockChatViewApi.syncSessionMessages).toHaveBeenCalled()
    expect(wrapper.get('#view-chat').exists()).toBe(true)
  })

  it('活动会话同步失败时页面仍然可用', async () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    getActiveConversation.mockResolvedValue({ conversation_id: 'server-99' })
    mockChatViewApi.syncSessionMessages.mockRejectedValue(new Error('network down'))
    const wrapper = await mountChatView()
    await flushPromises()
    expect((wrapper.vm as any).currentSessionId).toBe('server-99')
    expect(wrapper.get('#messageInput').exists()).toBe(true)
  })

  it('宿主挂载后暴露全局发送与填充入口', async () => {
    await mountChatView()
    const host = window as any
    expect(host.__VUE_CHAT_SEND__).toBeTypeOf('function')
    await host.__VUE_CHAT_SEND__('通过宿主发送')
    expect(mockChatViewApi.sendMessage).toHaveBeenCalledWith('通过宿主发送')
    expect(host.__VUE_CHAT_FILL__('填充到输入框')).toBe(true)
    expect((document.getElementById('messageInput') as HTMLTextAreaElement).value).toBe('填充到输入框')
    expect(await host.__VUE_CHAT_SEND__('   ')).toBe(false)
  })

  it('助手推送事件更新侧栏最新推送内容', async () => {
    await mountChatView()
    window.dispatchEvent(new CustomEvent('xcagi:assistant-push', { detail: { title: '任务完成', description: '发货单已生成' } }))
    await nextTick()
    expect(latestAssistantPushRef.value).toEqual({ title: '任务完成', description: '发货单已生成' })
  })

  it('输入法确认与 Shift+Enter 不触发发送或阻止默认行为', async () => {
    const wrapper = await mountChatView()
    const input = wrapper.get('#messageInput')
    await input.setValue('正在输入中文')
    for (const init of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
      const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init })
      input.element.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    await flushPromises()
    expect(mockChatViewApi.sendMessage).not.toHaveBeenCalled()
    expect((wrapper.vm as any).messageInput).toBe('正在输入中文')
  })

  it('回车发送与输入内容联动', async () => {
    const wrapper = await mountChatView()
    await wrapper.get('#messageInput').setValue('补发这批订单')
    expect(wrapper.get('#sendMessageBtn').attributes('disabled')).toBeUndefined()
    await wrapper.get('#messageInput').trigger('keydown', { key: 'Enter', shiftKey: false })
    await flushPromises()
    expect(mockChatViewApi.sendMessage).toHaveBeenCalledWith('补发这批订单')
    expect((wrapper.vm as any).messageInput).toBe('')
  })
})
