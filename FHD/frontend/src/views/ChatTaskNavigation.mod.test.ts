import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { AgentRun, AgentTaskSummary } from '@/api/agentRuns'
import type { TaskItem } from '@/composables/useChatPersistence'
import { useChatTaskRuntimeBridge } from '@/composables/useChatTaskRuntimeBridge'
import { taskSummariesToTaskItems } from '@/utils/agentTaskWorkspaceModel'
import type { UiChatMessage } from '@/types/chat-ui'

const api = vi.hoisted(() => ({
  listTasks: vi.fn(), listRuns: vi.fn(), markTaskRead: vi.fn(), getRun: vi.fn(),
  continueRun: vi.fn(), pauseRun: vi.fn(), resumeRun: vi.fn(), retryRun: vi.fn(), cancelRun: vi.fn(),
}))
vi.mock('@/api/agentRuns', () => ({ default: api }))
vi.mock('pinia', async () => ({
  ...await vi.importActual<typeof import('pinia')>('pinia'),
  storeToRefs: (store: unknown) => store,
}))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ currentIndustryId: ref('generic') }) }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => ({ mods: ref([]) }) }))
vi.mock('@/composables/useChatView', () => ({ useChatView: () => chatApi }))
vi.mock('@/composables/useChatViewHost', () => ({ useChatViewHost: () => ({ onAutoRefreshToolbarChange: vi.fn() }) }))
vi.mock('@/composables/useChatVoiceInput', () => ({ useChatVoiceInput: () => ({
  voiceButtonDisabled: ref(false), voiceButtonClass: ref(''), voiceButtonIcon: ref(''), voiceButtonText: ref('语音'),
  voiceButtonTitle: ref('语音'), voiceFeedbackText: ref(''), startVoiceRecording: vi.fn(), stopVoiceRecording: vi.fn(), cleanupVoiceInput: vi.fn(),
}) }))
vi.mock('@/composables/useChatMessageUi', () => ({ useChatMessageUi: () => ({
  messageHeights: ref(new Map()), playingMsgIdx: ref(-1), latestAiMessageIndex: ref(-1), isMessageCollapsed: () => false,
  expandMessage: vi.fn(), collapseMessage: vi.fn(), getCollapsedPreview: () => '', canSpeakMessage: () => false,
  toggleMessageTts: vi.fn(), batchCalculateHeights: vi.fn(), stopMessageTts: vi.fn(),
}) }))
vi.mock('@/composables/useResizablePane', () => ({ useResizablePane: () => ({
  paneStyle: ref({}), startResize: vi.fn(), resetSize: vi.fn(), stopResize: vi.fn(),
}) }))
vi.mock('@/composables/useChatOfficeDocking', () => ({ useChatOfficeDocking: () => ({
  officeDockingInputRef: ref(null), officeDockingProcessing: ref(false), officeDockingPanelOpen: ref(false), officeDockingReviewItems: ref([]),
  triggerOfficeDocking: vi.fn(), onOfficeDockingFileChange: vi.fn(), toggleOfficeDockingTarget: vi.fn(), confirmOfficeDockingReview: vi.fn(), clearOfficeDockingReview: vi.fn(),
}) }))

// Import the shipped Mod directly. The host ChatView and Vitest Mod alias cannot mask missing desktop wiring.
import ModChatView from '../../../mods/xcagi-planner-bridge/frontend/views/ChatView.vue'

const taskList = ref<TaskItem[]>([])
const activeTaskId = ref('')
const expandedTaskIds = ref<string[]>([])
const loadConversation = vi.fn(async () => { expandedTaskIds.value = [] })
const toggleExpanded = vi.fn((id: string) => {
  expandedTaskIds.value = expandedTaskIds.value.includes(id) ? [] : [id]
})
let chatApi: Record<string, unknown>
let wrapper: VueWrapper | undefined

function summary(status = 'waiting_user'): AgentTaskSummary {
  const run: AgentRun = {
    run_id: 'run-current-attempt', user_id: 'test-user', message: '创建首单', status,
    created_at: '2026-09-05T08:00:00Z', updated_at: '2026-09-05T08:01:00Z',
    metadata: { task_context: { task_id: 'task-durable-order', conversation_id: 'conversation-order' } },
    steps: [], events: [],
  }
  return {
    task_id: 'task-durable-order', user_id: 'test-user', title: '首单出货', source: 'agent', task_type: 'agent', status,
    conversation_id: 'conversation-order', active_run_id: run.run_id, active_run: run, runs: [run], attempt: 1, run_count: 2,
  }
}
function inertApi(): Record<string, unknown> {
  return {
    messages: ref([]), currentTask: ref(null), orderNumberFetching: ref(false), isLoading: ref(false), isStreamingReply: ref(false),
    cacheError: ref(''), retryMessagesCache: vi.fn(), retryMessageSave: vi.fn(),
    historyHasMore: ref(false), historyLoadingMore: ref(false), loadMoreHistorySessions: vi.fn(),
    isExecuting: ref(false), latestAssistantPush: ref(null), taskList, filteredTaskList: taskList, activeTaskId, expandedTaskIds,
    taskFilter: ref('all'), showHistory: ref(false), historySessions: ref([]), historyLoading: ref(false), historyError: ref(''),
    pushCopied: ref(false), loadingProgressText: ref(''), excelAnalyzeUploading: ref(false), multimodalPendingCount: ref(0),
    excelSheetOptions: ref([]), linkedExcelSheet: ref(null), linkedExcelAllSheets: ref(false), taskTableColumns: ref([]),
    taskTableItems: ref([]), taskOrderNumber: ref(''), ttsEnabled: ref(false), chatMessagesRef: ref(null), excelAnalyzeInputRef: ref(null),
    ...Object.fromEntries(['sendMessage', 'confirmWorkflowFromCard', 'cancelWorkflowFromCard', 'confirmTask', 'refetchTaskOrderNumber',
      'setCustomOrderNumber', 'cancelTask', 'showTaskConfirm', 'onExcelAnalyzeFileChange', 'bindExcelSheetToChat', 'bindAllExcelSheetsToChat',
      'setTaskFilter', 'jumpToTaskMessage', 'showHistoryPanel', 'clearHistorySessions', 'handleShipmentDownloadClick', 'startPrintFromTaskCard',
      'copyAssistantPushContent', 'openAssistantFloatFromTaskPanel', 'syncSessionMessages', 'handleAutoAction', 'setTtsEnabled',
      'addAndSaveMessage', 'stageExcelAnalysisContext'].map(name => [name, vi.fn()])),
  }
}
async function mountView(task = summary(), feedback = false) {
  taskList.value = taskSummariesToTaskItems([task])
  api.listTasks.mockResolvedValue({ success: true, data: [task] })
  api.getRun.mockResolvedValue({ success: true, data: task.active_run, approval: { grant: 'fresh-action-bound-grant' } })
  const bridge = useChatTaskRuntimeBridge({
    taskList, activeTaskId, expandedTaskIds, sortTaskList: vi.fn(), persist: vi.fn(), loadConversation,
    newConversation: vi.fn(), jumpToMessage: vi.fn(), toggleExpanded, clearLocalHistory: vi.fn(),
  })
  chatApi = { ...inertApi(), ...bridge }
  if (feedback) {
    chatApi.messages = ref<UiChatMessage[]>([{ role: 'user', content: '待保存记录', time: '12:00', persistence: {
      id: 'message-retry', status: 'failed', localSaved: false, error: '消息保存未确认，不会重新执行任务。',
      request: { role: 'user', content: '待保存记录' },
    } }])
    chatApi.cacheError = ref('本机保存失败，请重试')
    chatApi.showHistory = ref(true)
    chatApi.historySessions = ref([{ session_id: 'first-page', title: '第一批历史' }])
    chatApi.historyHasMore = ref(true)
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/chat', component: { template: '<div />' } },
    { path: '/workspaces/:taskId', name: 'task-workspace', component: { template: '<div />' } },
  ] })
  await router.push('/chat')
  await router.isReady()
  wrapper = mount(ModChatView, { global: { plugins: [router], stubs: {
    PaneResizeHandle: true, ChatQuickActions: true, ChatMessageList: !feedback, ChatInputToolbar: true,
    ChatHistoryModal: !feedback, ChatOfficeDockingReview: true,
  } } })
  return { router, bridge }
}
const controls = () => [api.continueRun, api.pauseRun, api.resumeRun, api.retryRun, api.cancelRun]
const button = (label: string) => wrapper!.findAll('button').find(item => item.text() === label)!
beforeEach(() => {
  Object.values(api).forEach(mock => mock.mockReset().mockResolvedValue({ success: true }))
  activeTaskId.value = ''; expandedTaskIds.value = []
  loadConversation.mockClear(); toggleExpanded.mockClear()
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('shipped chat Mod task navigation', () => {
  it('shows a confirmation link on the collapsed card and navigates by durable task and conversation without submitting', async () => {
    const { router } = await mountView()
    expect(wrapper!.find('.task-list-detail').exists()).toBe(false)
    const link = wrapper!.get('.task-workspace-action a')
    expect(link.text()).toBe('前往确认')
    expect(link.attributes('href')).toBe('/workspaces/task-durable-order?conversation=conversation-order')
    await link.trigger('click'); await flushPromises()
    expect(router.currentRoute.value.name).toBe('task-workspace')
    expect(router.currentRoute.value.params.taskId).toBe('task-durable-order')
    expect(router.currentRoute.value.query.conversation).toBe('conversation-order')
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
    expect(api.getRun).not.toHaveBeenCalled()
  })

  it('actually selects and expands the desktop card after conversation hydration, then opens its workspace', async () => {
    const { router } = await mountView()
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    expect(loadConversation).toHaveBeenCalledExactlyOnceWith('conversation-order')
    expect(api.markTaskRead).toHaveBeenCalledExactlyOnceWith('task-durable-order')
    expect(wrapper!.get('.task-list-main').attributes('aria-expanded')).toBe('true')
    expect(wrapper!.get('.task-list-item').classes()).toContain('task-list-item-active')
    expect(wrapper!.get('.task-list-detail').text()).toContain('审批并执行')
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
    await wrapper!.get('.agent-task-runtime .task-actions button').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.params.taskId).toBe('task-durable-order')
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it('keeps approval a separate explicit action and submits once with a fresh bound grant', async () => {
    await mountView()
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    await button('审批并执行').trigger('click'); await flushPromises()
    expect(api.getRun).toHaveBeenCalledExactlyOnceWith('run-current-attempt')
    expect(api.continueRun).toHaveBeenCalledExactlyOnceWith('run-current-attempt', { approval_grant: 'fresh-action-bound-grant' })
    controls().slice(1).forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it('preserves denied approval capabilities while keeping workspace access available', async () => {
    const task = summary()
    task.capabilities = { approve: false, pause: false, resume: false, retry: false, cancel: false }
    await mountView(task)
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    expect(button('审批并执行')).toBeUndefined()
    expect(wrapper!.get('.task-workspace-action a').text()).toBe('前往确认')
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it('keeps a server-reported permission failure visible after selection and refresh', async () => {
    const task = summary('failed')
    task.active_run!.error = '当前账号无权执行此任务，请联系负责人'
    await mountView(task)
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    expect(wrapper!.get('.task-error').text()).toContain('当前账号无权执行此任务')
    expect(wrapper!.get('.task-workspace-action a').text()).toBe('查看任务')
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it.each([{ taskId: '' }, { serverBacked: false }])('does not invent workspace links for an incomplete/local snapshot (%j)', async (payload) => {
    await mountView()
    Object.assign(taskList.value[0].payload!, payload)
    await flushPromises()
    expect(wrapper!.find('.task-workspace-action').exists()).toBe(false)
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it('retains the fresh-grant refusal at the real task bridge', async () => {
    const { bridge } = await mountView()
    api.getRun.mockResolvedValue({ success: true, data: summary().active_run, approval: {} })
    await bridge.approveTask(taskList.value[0].id)
    expect(bridge.taskControlStates.value[taskList.value[0].id]).toMatchObject({ needsVerification: true, error: expect.stringContaining('审批未确认成功') })
    expect(api.continueRun).not.toHaveBeenCalled()
  })

  it('wires save retry, cache recovery, history paging and stale-state verification in the shipped desktop view', async () => {
    const { bridge } = await mountView(summary(), true)
    expect(wrapper!.get('.chat-cache-warning').text()).toContain('本机保存失败')
    await button('仅重试保存').trigger('click')
    await button('重试本机保存').trigger('click')
    await button('加载更早的会话').trigger('click')
    expect(chatApi.retryMessageSave).toHaveBeenCalledExactlyOnceWith('message-retry')
    expect(chatApi.retryMessagesCache).toHaveBeenCalledTimes(1)
    expect(chatApi.loadMoreHistorySessions).toHaveBeenCalledTimes(1)
    bridge.taskSyncState.value = { stale: true, checking: false, lastVerifiedAt: 1, error: '无法核实任务状态' }
    await flushPromises()
    expect(wrapper!.get('.task-sync-status').text()).toContain('无法核实任务状态')
    await wrapper!.get('.task-sync-status button').trigger('click')
    await flushPromises()
    expect(bridge.taskSyncState.value.stale).toBe(false)
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })

  it.each([
    ['running', '暂停', 'pauseRun'], ['paused', '继续', 'resumeRun'],
    ['failed', '重试', 'retryRun'], ['running', '取消', 'cancelRun'],
  ] as const)('wires the existing %s task control to its exact active run (%s)', async (status, label, method) => {
    await mountView(summary(status))
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    expect(wrapper!.get('.task-workspace-action a').text()).toBe('查看任务')
    await button(label).trigger('click'); await flushPromises()
    expect(api[method]).toHaveBeenCalledExactlyOnceWith('run-current-attempt')
    expect(api.continueRun).not.toHaveBeenCalled()
  })

  it('preserves local-task expansion without inventing a workspace or approving anything', async () => {
    await mountView()
    taskList.value = [{ id: 'local-task', title: '本地任务', source: 'workflow', type: 'workflow', status: 'success', startedAt: 1, updatedAt: 1 }]
    await flushPromises()
    await wrapper!.get('.task-list-main').trigger('click'); await flushPromises()
    expect(toggleExpanded).toHaveBeenCalledExactlyOnceWith('local-task')
    expect(wrapper!.get('.task-list-main').attributes('aria-expanded')).toBe('true')
    expect(wrapper!.find('.task-workspace-action').exists()).toBe(false)
    controls().forEach(control => expect(control).not.toHaveBeenCalled())
  })
})
