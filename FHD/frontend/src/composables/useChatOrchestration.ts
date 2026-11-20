/**
 * useChatOrchestration：聊天编排 Façade。
 * 实现按关注点拆分至 chat-orchestration/ 子模块（自动动作 / 任务执行 / 打印链路 / Excel 分析任务 / 远程对话轮次），
 * 对外入口签名与返回对象字段与拆分前保持完全一致（行为零变更）。
 */
import { ref, computed, reactive, watch, onMounted, onBeforeUnmount, onDeactivated } from 'vue'
import { useTutorialStore } from '@/stores/tutorial'
import { useModsStore } from '@/stores/mods'
import { useProductsStore } from '@/stores/products'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  clearPersistedTaskPanelState,
  useChatTaskPanelPersistence,
} from './useChatPersistence'
import { useChatTaskList } from './useChatTaskList'
import { useChatMessages, type ChatMessage } from './useChatMessages'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'
import { usePrintService } from './usePrintService'
import { FHD_DB_WRITE_UNLOCKED_EVENT } from '@/fhd/dbTokenHeaders'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'
import { useChatDbTokenGate } from './useChatDbTokenGate'
import { useChatExcelContext } from './useChatExcelContext'
import { useChatRequest } from './useChatRequest'
import { useChatSessionActivity } from './useChatSessionActivity'
import { useChatResponseAttach } from './useChatResponseAttach'
import { useChatSessionHistory } from './useChatSessionHistory'
import { useAgentRunEventSync } from './useAgentRunEvents'
import { useChatTaskRuntimeBridge } from './useChatTaskRuntimeBridge'
import { useApprovalMode } from './useApprovalMode'
import { useCanonicalChatTaskBridge } from './useCanonicalChatTaskBridge'
import type { UseChatViewOptions } from './useChatView'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { isStartPrintMessage } from '../utils/textParser'
import { generateSessionId, normalizeServerContentToHtml, type ChatLocalScope } from './chat-orchestration/chatOrchestrationShared'
import { useChatOrchestrationAutoActions } from './chat-orchestration/useChatOrchestrationAutoActions'
import { useChatOrchestrationTaskExecution } from './chat-orchestration/useChatOrchestrationTaskExecution'
import { useChatOrchestrationPrintFlow } from './chat-orchestration/useChatOrchestrationPrintFlow'
import { useChatAttachmentPicker } from './useChatAttachmentPicker'
import { useChatOrchestrationRemoteRound } from './chat-orchestration/useChatOrchestrationRemoteRound'
import { useOnboardingFirstOrderRun } from './useOnboardingFirstOrderRun'
import { APPROVAL_GRANT_MISSING_MESSAGE, approveRunWithFreshGrant } from '@/api/agentRunApproval'
import agentRunsApi from '@/api/agentRuns'
import { approvalCardId, parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { approvalApi } from '@/api/approval'
import chatApi from '@/api/chat'
import { ApiError } from '@/api/core'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { lastChatModelRoute } from '@/utils/chatModelRoute'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { chatExecutionOutcome, readChatExecution } from '@/components/chat/chatFailureRecovery'
import { activeChatTurnMessage, activeChatTurnStatus, droppedRoundFromHistory, readActiveChatTurn, type ActiveChatTurn } from '@/utils/droppedRoundPresentation'
import { useAiSdkChatRound } from './chat-orchestration/useAiSdkChatRound'
import { stepsFromAiParts } from '@/utils/agentStepChain'
import { activeRunIdOfTask } from '@/utils/agentTaskWorkspaceModel'
import { requiresTurnReconciliation } from './chat-orchestration/chatOrchestrationShared'

function durableRecallMessageId(message: ChatMessage): number | undefined {
  if (message.persistence?.status !== 'saved') return undefined
  const id = message.serverMessageId ?? Number(/^server:(\d+)$/.exec(message.persistence?.id || '')?.[1])
  return Number.isSafeInteger(id) && id > 0 ? id : undefined
}

export function useChatOrchestration(options: UseChatViewOptions) {
  const tutorialStore = useTutorialStore()
  const modsStore = useModsStore()
  const productsStore = useProductsStore()
  const { sessionId } = options
  const chatIdentity = () =>
    `${getAuthSessionEpoch()}:${productReadAccountEpoch.value}:${resolveChatIdentity(String(modsStore.activeModId || ''))}`
  const chatSessionActivity = useChatSessionActivity(sessionId, chatIdentity)
  const { isLoading, isStreamingReply, isSessionBusy, statuses } = chatSessionActivity
  const recalling = reactive(new Set<string>())
  const recallKey = computed(() => JSON.stringify([chatIdentity(), String(sessionId.value || '').trim() || 'default']))
  const isRecalling = computed(() => recalling.has(recallKey.value))
  const {
    messages,
    messagesHaveEarlier, earlierMessagesLoading, earlierMessagesError, loadEarlierMessages,
    cacheError,
    retryMessagesCache,
    retryMessageSave,
    addMessage,
    addAndSaveMessage: addAndSaveMessageRaw,
    saveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    retainConversationMessages,
    flushMessagesCache,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  } = useChatMessages(sessionId, { isBusy: () => isLoading.value })
  const CHAT_TTS_ENABLED_KEY = 'xcagi_chat_tts_enabled'
  const ttsEnabled = ref(localStorage.getItem(CHAT_TTS_ENABLED_KEY) !== '0')
  function setTtsEnabled(enabled: boolean) {
    ttsEnabled.value = enabled
    localStorage.setItem(CHAT_TTS_ENABLED_KEY, enabled ? '1' : '0')
    if (!enabled) clearVoiceQueue()
  }
  async function addAndSaveMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: Parameters<typeof addAndSaveMessageRaw>[2],
    targetSessionId?: string,
  ): Promise<void> {
    await addAndSaveMessageRaw(content, role, extras, {
      speak: ttsEnabled.value && role === 'ai',
      sessionId: targetSessionId,
    })
  }
  const currentTask = ref<ShipmentTask | null>(null)
  const orderNumberFetching = ref(false)
  let localViewRevision = 0
  watch(sessionId, () => { localViewRevision++ }, { flush: 'sync' })
  function captureLocalScope(): ChatLocalScope {
    const targetSessionId = String(sessionId.value || '').trim() || 'default'
    const identity = resolveChatIdentity(String(modsStore.activeModId || ''))
    const accountEpoch = productReadAccountEpoch.value, revision = localViewRevision
    const isGenerationCurrent = chatSessionActivity.captureGeneration(targetSessionId)
    const isOwnerCurrent = () => accountEpoch === productReadAccountEpoch.value && identity === resolveChatIdentity(String(modsStore.activeModId || ''))
    return { sessionId: targetSessionId, isOwnerCurrent, isCurrent: () => isOwnerCurrent() && revision === localViewRevision && targetSessionId === (String(sessionId.value || '').trim() || 'default') && isGenerationCurrent() }
  }
  const isExecuting = ref(false)
  // 工作流「步骤进度」：消费后方 state.update 事件，维护正在执行/已完成的节点列表
  const stateSteps = ref<
    Array<{
      node_id: string
      status: 'succeeded' | 'failed'
      output_summary: string
    }>
  >([])
  const latestAssistantPush = ref<{ title: string; description: string } | null>(null)
  const chatMessagesRef = ref<HTMLElement | null>(null)
  let persistTaskPanelStateForSession: (targetSessionId?: string) => void = () => {}
  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    activeTask,
    filteredTaskList,
    createTaskId,
    sortTaskList,
    upsertTask,
    removeTask,
    finishTask,
    failTask,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory: clearLocalTaskHistory,
    jumpToTaskMessage,
  } = useChatTaskList({
    chatMessagesRef,
    onPersist: () => persistTaskPanelStateForSession(),
  })
  const panelPersistence = useChatTaskPanelPersistence({
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    sortTaskList,
  })
  persistTaskPanelStateForSession = panelPersistence.persistTaskPanelStateForSession
  const { applyPersistedTaskPanelStateForSession } = panelPersistence
  const pendingDbWriteChatRetryMessages = ref<string[] | null>(null)
  const plannerWriteUnlockResumeDraft = ref('')
  const lastRequestContextSummary = ref('')
  const executeRemoteChatRoundRef: {
    fn: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
  } = { fn: async () => {} }
  const dbGate = useChatDbTokenGate({
    sessionId,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound: (msgs, opts) => executeRemoteChatRoundRef.fn(msgs, opts),
  })
  const { handleChatRequiresToken } = dbGate
  const excelCtx = useChatExcelContext({
    sessionId, addAndSaveMessage,
    getIdentity: () => resolveChatIdentity(String(modsStore.activeModId || '')),
    captureIsCurrent: () => captureLocalScope().isCurrent,
  })
  const {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalPendingCount,
    multimodalStaging,
    artifactStaging,
    unsupportedStaging,
    removeArtifactFile,
    removeMultimodalFile,
    dismissUnsupportedFile,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
  } = excelCtx
  function stageExcelAnalysisContext(payload: Record<string, unknown>): void {
    lastExcelAnalysisContext.value = payload
    const sid = String(sessionId.value || '').trim() || 'default'
    persistExcelAnalysisContext(sid, payload)
  }
  const responseAttach = useChatResponseAttach({
    messages,
    lastRequestContextSummary,
    taskList,
    upsertTask,
    createTaskId,
  })
  const {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachApprovalCardToLastAiMessage,
    attachBusinessResultToLastAiMessage,
    attachAgentRunTraceToLastAiMessage = () => undefined,
    attachContextSummaryToLastAiMessage,
    syncTaskFromChatResponse,
  } = responseAttach

  const { syncAgentRunFromPayload } = useAgentRunEventSync({
    upsertTask,
    removeTask,
    getLastAiMessageRef,
  })

  const chatRequest = useChatRequest({
    messages,
    sessionId,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveChatDbTokensForPayload: dbGate.resolveChatDbTokensForPayload,
    captureArtifacts: excelCtx.captureChatArtifacts,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  })

  const {
    loadingProgressText,
    enqueueChatBatchMessage,
    getChatBatchDebounceMs,
  } = chatRequest

  function scrollToBottom() {
    if (chatMessagesRef.value) {
      chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight
    }
  }

  const sessionHistory = useChatSessionHistory({
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    loadMessages,
    clearMessages,
    persistTaskPanelStateForSession,
    applyPersistedTaskPanelStateForSession,
    clearPersistedTaskPanelState,
    generateSessionId,
    normalizeServerContentToHtml,
    isSessionBusy,
    captureRound: chatSessionActivity.captureGeneration,
    onConversation: observeConversation,
    onIdentityChange: () => {
      pendingDbWriteChatRetryMessages.value = null
      plannerWriteUnlockResumeDraft.value = ''
      chatRequest.cancelPendingChatBatch()
      clearVoiceQueue()
    },
  })
  const {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    historyHasMore,
    historyLoadingMore,
    loadMoreHistorySessions,
    refreshLocalHistorySessions,
    refreshHistorySessions,
    restoreLatestOwnedSession,
    showHistoryPanel,
    loadSession: loadSessionFromHistory,
    clearHistorySessions,
    renameSession,
    deleteSession,
    newConversation: newConversationFromHistory,
    registerHistoryModWatch,
  } = sessionHistory
  const agentTaskRuntime = useChatTaskRuntimeBridge({
    taskList,
    activeTaskId,
    expandedTaskIds,
    sortTaskList,
    persist: () => persistTaskPanelStateForSession(),
    loadConversation: loadSessionFromHistory,
    newConversation: newConversationFromHistory,
    jumpToMessage: jumpToTaskMessage,
    toggleExpanded: toggleTaskExpanded,
    clearLocalHistory: clearLocalTaskHistory,
  })
  let observedTurn: { turn: ActiveChatTurn; controller: AbortController; message: ChatMessage; checkingReceipt: boolean } | undefined

  function stopTurnObservation() {
    observedTurn?.controller.abort()
    observedTurn = undefined
  }

  function observeConversation(data: unknown) {
    const turn = readActiveChatTurn(data)
    if (turn) observeActiveTurn(turn)
  }

  function observeActiveTurn(turn: ActiveChatTurn) {
    let message = messages.value.find(row => row.role === 'ai' && row.turnId === turn.turnId)
    if (message && observedTurn?.message === message && observedTurn.turn.runId === turn.runId
      && message.workflowAction === turn.status) return
    stopTurnObservation()
    const text = activeChatTurnMessage(turn)
    if (!message) {
      addMessage(text, 'ai', { turnId: turn.turnId })
      message = messages.value.find(row => row.role === 'ai' && row.turnId === turn.turnId)
    }
    if (!message) return
    applyPlainTextToMessageIndex(messages.value.indexOf(message), text)
    message.workflowAction = turn.status
    message.toolProgressLabel = text
    if (turn.taskId) message.recoveryTaskId = turn.taskId
    if (turn.status === 'blocked') return
    const controller = new AbortController()
    const observation = { turn, controller, message, checkingReceipt: false }
    observedTurn = observation
    const isCurrent = () => observedTurn === observation && messages.value.includes(message)
    let receipt: unknown
    let awaitingAuthorization = false
    const stream = useAiSdkChatRound({
      onEvent: event => {
        if (!isCurrent()) return
        if (event.type === 'tool_progress' || event.type === 'tool_call') {
          const label = event.type === 'tool_progress' ? event.label || event.text : event.label
          if (label) message.toolProgressLabel = label
        }
        if (event.type === 'done') receipt = event.result
        if (event.type === 'requires_token') awaitingAuthorization = true
      },
      onMessage: reply => {
        if (isCurrent()) message.liveSteps = stepsFromAiParts(reply.parts)
      },
    })
    void stream.resume(turn.turnId, controller.signal).then(result => {
      if (!isCurrent() || result.error || readActiveChatTurn(receipt)) return
      if (awaitingAuthorization) { message.workflowAction = 'waiting_approval'; stopTurnObservation(); return }
      const payload = asRecord(receipt)
      const response = asString(payload.response || payload.message || result.text).trim()
      if (!response || typeof payload.success !== 'boolean') return
      const action = requiresTurnReconciliation(payload) ? 'unknown'
        : parseApprovalCardFromPayload(payload)?.status === 'pending' ? 'waiting_approval'
          : payload.success ? 'completed' : 'failed'
      finishObservedTurn(observation, action, response, payload)
    })
    // The workspace already consumes task updates and polls when its stream is unavailable.
    void agentTaskRuntime.refreshTasks().catch(() => undefined)
  }

  function finishObservedTurn(observation: NonNullable<typeof observedTurn>, action: string, text: string, payload?: Record<string, unknown>) {
    const { message } = observation
    const index = messages.value.indexOf(message)
    if (observedTurn !== observation || index < 0) return
    const execution = payload ? readChatExecution(payload) : undefined
    const card = payload ? parseApprovalCardFromPayload(payload) : undefined
    applyPlainTextToMessageIndex(index, text, { workflowAction: action, ...(execution ? { execution } : {}), ...(card ? { approvalCard: card } : {}) })
    delete message.toolProgressLabel
    stopTurnObservation()
    flushMessagesCache()
  }

  watch(taskList, async tasks => {
    const observation = observedTurn
    if (!observation || observation.checkingReceipt || agentTaskRuntime.taskSyncState.value.stale) return
    const task = tasks.find(item => activeRunIdOfTask(item) === observation.turn.runId)
    if (!task) return
    const fields = asRecord(task.payload)
    const taskId = asString(fields.taskId).trim()
    if (taskId) observation.message.recoveryTaskId = taskId
    const status = activeChatTurnStatus(asString(fields.rawRunStatus))
    if (status) {
      observation.message.toolProgressLabel = task.stage || activeChatTurnMessage(observation.turn)
      if (observation.message.workflowAction !== status) {
        applyPlainTextToMessageIndex(messages.value.indexOf(observation.message), activeChatTurnMessage({
          ...observation.turn, status, message: '',
        }))
      }
      observation.message.workflowAction = status
      if (status === 'blocked') stopTurnObservation()
      return
    }
    const sid = sessionId.value
    observation.checkingReceipt = true
    try {
      const data = await chatApi.getConversation(sid, { turn_id: observation.turn.turnId })
      if (observedTurn !== observation) return
      const receipt = droppedRoundFromHistory(data, observation.turn.turnId)
      if (receipt.activeTurn) {
        if (receipt.activeTurn.status === 'blocked') observeActiveTurn(receipt.activeTurn)
        return
      }
      if (['completed', 'failed', 'interrupted', 'waiting_approval'].includes(receipt.status)) {
        finishObservedTurn(observation, receipt.workflowAction, receipt.text)
        return
      }
    } catch {
      // Keep the most recent task state while the conversation receipt is unavailable.
    } finally {
      observation.checkingReceipt = false
    }
    if (observedTurn !== observation) return
    if (['success', 'failed', 'cancelled'].includes(task.status)) {
      finishObservedTurn(observation, 'unknown', '已读取原任务的结束状态，业务结果请在原任务中核对。')
    }
  }, { flush: 'post' })
  watch([sessionId, chatIdentity], stopTurnObservation, { flush: 'sync' })
  onDeactivated(stopTurnObservation)
  onBeforeUnmount(stopTurnObservation)
  const canonicalTaskBridge = useCanonicalChatTaskBridge({
    sessionId,
    createTaskId,
    refreshTasks: agentTaskRuntime.refreshTasks,
  })
  const onboardingFirstOrderRun = useOnboardingFirstOrderRun({
    saveMessage,
    addAndSaveMessage,
    refreshTasks: agentTaskRuntime.refreshTasks,
  })
  const {
    lastShipmentExecution,
    handleModifyCommand: handleShipmentModify,
    hydrateTaskOrderNumber,
    enrichShipmentPreviewProducts,
    getTaskTableColumns,
    getTaskTableItems,
    getTaskOrderNumber,
  } = useShipmentTask({ addAndSaveMessage }, currentTask, () => captureLocalScope().isCurrent)

  const { isPrinting, executePrintTask, buildPrintSummaryMessage } = usePrintService()

  // ── 拆分模块装配（保持与拆分前相同的创建依赖与调用时序） ──

  // 副窗推送 / AutoAction
  const autoActions = useChatOrchestrationAutoActions({ latestAssistantPush, tutorialStore })
  const {
    pushCopied,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
    handleAutoAction,
    copyAssistantPushContent,
    openAssistantFloatFromTaskPanel,
  } = autoActions

  // 任务确认 / 执行
  const taskExecution = useChatOrchestrationTaskExecution({
    currentTask,
    isExecuting,
    orderNumberFetching,
    canonicalTaskBridge,
    hydrateTaskOrderNumber,
    enrichShipmentPreviewProducts,
    lastShipmentExecution,
    addAndSaveMessage,
    createTaskId,
    upsertTask,
    failTask,
    getLastAiMessageRef,
    handleChatRequiresToken,
    persistTaskPanelStateForSession,
    handleAutoAction,
  })
  const {
    showTaskConfirm,
    setCustomOrderNumber,
    refetchTaskOrderNumber,
    confirmTask,
    cancelTask,
  } = taskExecution

  const workflowPanel = useChatWorkflowPanel({
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    upsertTask,
    sortTaskList,
    createTaskId,
    persistTaskPanelStateForSession,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
  })
  const { readWorkflowEmployeeEnabledMap, upsertWorkflowEmployeeTask } = workflowPanel

  // 打印链路
  const printFlow = useChatOrchestrationPrintFlow({
    modsStore,
    captureLocalScope,
    saveMessage,
    addAndSaveMessage,
    taskList,
    createTaskId,
    upsertTask,
    getLastAiMessageRef,
    emitAssistantPush,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask,
    lastShipmentExecution,
    executePrintTask,
    buildPrintSummaryMessage,
  })
  const {
    handleStartPrintCommand,
    handleShipmentDownloadClick,
    startPrintFromTaskCard,
  } = printFlow

  const { attachmentUploading, onAttachmentFileChange } = useChatAttachmentPicker(
    excelCtx, () => captureLocalScope().isCurrent,
  )

  // 远程对话轮次（快路径 / SSE 流式 / JSON 与批量）
  const remoteRound = useChatOrchestrationRemoteRound({
    sessionId,
    messages,
    addMessage,
    saveMessage,
    queueVoice,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    retainConversationMessages,
    flushMessagesCache,
    ttsEnabled,
    chatSessionActivity,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    chatRequest,
    handleChatRequiresToken,
    resolveExcelAnalysisContextForRequest,
    multimodalPendingCount,
    stateSteps,
    currentTask,
    syncTaskFromChatResponse,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachApprovalCardToLastAiMessage,
    attachBusinessResultToLastAiMessage,
    attachAgentRunTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncAgentRunFromPayload,
    observeActiveTurn,
    showTaskConfirm,
    maybeCloseAssistantFloatForShipmentTask,
    emitAssistantPush,
    handleAutoAction,
  })
  const { executeRemoteChatRound } = remoteRound

  const taskTableColumns = computed(() => (currentTask.value ? getTaskTableColumns(currentTask.value) : []))
  const taskTableItems = computed(() => (currentTask.value ? getTaskTableItems(currentTask.value) : []))
  const taskOrderNumber = computed(() => getTaskOrderNumber(currentTask.value))

  // 审批模式：自动档时，出现待审批卡片即自动确认（审批工作台仍由后端留记录）。
  const { state: approvalModeState } = useApprovalMode()
  watch(
    [messages, isLoading],
    ([list, loading]) => {
      if (loading || isRecalling.value || !approvalModeState.enabled || approvalModeState.mode !== 'auto') return
      const card = list.find(msg => msg.role === 'ai' && msg.approvalCard?.status === 'pending'
        && !msg.approvalCard.submitting && !msg.approvalCard.error
        && !msg.approvalCard.approval_path && !msg.approvalCard.approval_request_ids?.length)?.approvalCard
      if (card) void confirmWorkflowFromCard(approvalCardId(card))
    },
    { deep: true },
  )

  /**
   * Cancel the in-flight round.
   * A newer send supersedes quietly: the previous stream is aborted and an empty
   * thinking shell is removed, without the manual-stop banner.
   */
  function stopReply(options?: { supersede?: boolean }) {
    localViewRevision++
    const stopped = chatSessionActivity.cancelSession()
    chatRequest.cancelPendingChatBatch(sessionId.value)
    chatRequest.stopLoadingProgress()
    clearVoiceQueue()
    pendingDbWriteChatRetryMessages.value = null
    plannerWriteUnlockResumeDraft.value = ''
    if (!stopped) return
    const kept = messages.value.filter((msg) => {
      if (!msg.streamingShell) return true
      const plain = plainTextFromChatHtml(msg.content).trim()
      delete msg.streamingShell
      delete msg.waitingHint
      return plain.length > 0
    })
    if (kept.length !== messages.value.length) messages.value = kept
    if (options?.supersede) return
    const routeMetadata = lastChatModelRoute(sessionId.value, resolveChatIdentity(String(modsStore.activeModId || '')))
    addMessage('已停止接收本轮回复。已执行的工具不会撤销；后台任务请到任务工作区核对，勿重复提交。', 'ai', routeMetadata ? { routeMetadata } : undefined)
  }

  async function sendMessage(message: string, turn?: { retryOf?: string; idempotencyKey?: string; destructiveConfirmed?: boolean }) {
    if (isRecalling.value) return
    const taskSessionId = String(sessionId.value || '').trim() || 'default'
    if (isLoading.value) stopReply({ supersede: true })
    const generation = chatSessionActivity.beginRound(taskSessionId)
    generation.setLoading(true)
    const turnId = createBusinessHarnessId('turn')
    addMessage(message, 'user', { turnId })
    refreshLocalHistorySessions?.()
    const origin = retainConversationMessages?.(taskSessionId)
    const originalMessages = origin?.messages ?? messages
    const localScope = captureLocalScope()
    // 本轮若因视图/身份已过期而没有真正发出请求，要撤回刚插入的用户消息，
    // 否则会留下一条永远没有回复、并在每次同步时被追加到末尾的“幽灵提问”。
    const rollbackUnsentUser = () => {
      if (!localScope.isOwnerCurrent()) return
      const index = originalMessages.value.findIndex(item => item.role === 'user' && item.turnId === turnId)
      if (index < 0) return
      originalMessages.value.splice(index, 1)
      origin?.persist()
      refreshLocalHistorySessions?.()
    }
    const requestScope = {
      identity: resolveChatIdentity(String(modsStore.activeModId || '')),
      signal: generation.signal,
      isCurrent: generation.isCurrent,
      sessionId: taskSessionId,
      messages: [...messages.value],
      turnId,
      taskId: createBusinessHarnessId('task'),
    }
    let queued = false
    try {
      if (await onboardingFirstOrderRun.tryStart(message, localScope)) {
        await refreshHistorySessions()
        return
      }
      const isCurrent = localScope.isCurrent
      if (!isCurrent()) { rollbackUnsentUser(); return }
      const previewModified = await handleShipmentModify(message, localScope.isCurrent)
      if (!isCurrent()) { rollbackUnsentUser(); return }
      if (previewModified) {
        await saveMessage('user', message, taskSessionId)
        await refreshHistorySessions()
        return
      }

      const printHandled = await handleStartPrintCommand(message, localScope)
      if (!isCurrent()) { rollbackUnsentUser(); return }
      if (printHandled) {
        await saveMessage('user', message, taskSessionId)
        await refreshHistorySessions()
        return
      }

      const debounceMs = getChatBatchDebounceMs()
      if (debounceMs <= 0 || multimodalPendingCount.value > 0 || resolveExcelAnalysisContextForRequest()) {
        try {
          await executeRemoteChatRound([message], turn, requestScope)
        } finally {
          await refreshHistorySessions()
        }
        return
      }
      queued = true
      enqueueChatBatchMessage(message, debounceMs, (msgs) => {
        void executeRemoteChatRound(msgs, turn, requestScope).finally(async () => {
          if (localScope.isCurrent()) await syncFromServer()
          await refreshHistorySessions()
        })
      }, taskSessionId)
    } finally {
      origin?.release()
      if (!queued) {
        generation.setLoading(false)
        if (localScope.isCurrent()) await syncFromServer()
      }
    }
  }

  /**
   * 自动审批档：计划确认后若后端生成了审批请求，用同一账号身份提交审批并留痕，
   * 避免「自动」只自动点了确认卡、又把人拦在审批工作台。
   */
  async function approveChatRequestIfAutomatic(payload: Record<string, unknown>, isCurrent: () => boolean) {
    if (!approvalModeState.enabled || approvalModeState.mode !== 'auto') return
    const envelope = asRecord(payload.data)
    if (asString(envelope.action).trim() !== 'approval_pending') return
    const targetNos = new Set(
      asArray(asRecord(envelope.data).approval_request_ids).map((value) => asString(value)).filter(Boolean),
    )
    if (!targetNos.size) return
    const userId = Number(getRuntimeTenantStorageScopeInput()?.localUserId)
    if (!Number.isSafeInteger(userId) || userId <= 0) return
    const listed = await approvalApi.getMyRequests(userId)
    const requests = Array.isArray(listed?.data?.requests) ? listed.data.requests : []
    for (const request of requests) {
      if (!targetNos.has(String(request.request_no || ''))) continue
      if (String(request.status || '') !== 'pending') continue
      if (Number(request.applicant_id) !== userId) continue
      if (String(request.business_type || '') !== 'workflow_tool') continue
      if (!isCurrent()) return
      await approvalApi.approve(Number(request.id), userId, '自动审批模式：确认本轮 AI 工作流写入')
      if (!isCurrent()) return
    }
  }

  async function controlWorkflowFromCard(cardId: string, action: 'confirm' | 'cancel') {
    if (!cardId || isLoading.value || isRecalling.value) return
    const card = messages.value.find(msg => msg.role === 'ai' && msg.approvalCard
      && approvalCardId(msg.approvalCard) === cardId)?.approvalCard
    if (!card || card.status !== 'pending' || card.submitting || card.approval_path || card.approval_request_ids?.length) return
    const round = chatSessionActivity.beginRound()
    const scope = captureLocalScope()
    const isCurrent = () => scope.isCurrent() && messages.value.some(msg => msg.approvalCard === card)
    round.setLoading(true)
    card.submitting = true
    delete card.error
    const control = action === 'confirm' ? '确认' : '取消'
    try {
      const runId = String(card.run_id || card.agent_run_id || '').trim()
      let runHandled = false
      if (runId) {
        try {
          const receipt = action === 'confirm'
            ? await approveRunWithFreshGrant(runId, { isCurrent, runtimeContext: { source: 'chat_approval_card', ...dbGate.resolveChatDbTokensForPayload() } })
            : await agentRunsApi.cancelRun(runId)
          if (!isCurrent() || !receipt) return
          if (!receipt.success || receipt.data?.run_id !== runId) throw new Error(receipt.message || '未收到原任务的操作回执，请核对后重试')
          if (action === 'cancel' && receipt.data.status !== 'cancelled') throw new Error('取消请求已提交，任务尚未确认取消。请在原任务中核对状态。')
          card.status = action === 'confirm' ? 'confirmed' : 'cancelled'
          await addAndSaveMessage(action === 'confirm' ? '已收到确认回执，任务已提交执行，请在任务中查看实际结果。' : '已收到取消回执，任务已取消。', 'ai', undefined, scope.sessionId)
          if (isCurrent()) await syncAgentRunFromPayload({ run_id: runId }, control, isCurrent).catch(() => undefined)
          runHandled = true
        } catch (error) {
          // 计划级审批的 run 没有可续跑的等待步骤，后端不会签发 approval_grant；
          // 这类卡片按 plan_id 走原计划确认，而不是停在「没有可用的审批凭证」。
          if (!(error instanceof Error) || error.message !== APPROVAL_GRANT_MISSING_MESSAGE) throw error
        }
      }
      if (!runHandled) {
        const planId = String(card.plan_id || '').trim()
        if (!planId) throw new Error('确认卡缺少任务标识，请返回原任务核对后重试')
        const payload = await chatRequest.requestChatByModeWithTimeout(control, chatRequest.resolveChatTimeoutMs(control), { expectedWorkflowPlanId: planId }, {
          sessionId: scope.sessionId, messages: [...messages.value], signal: round.signal, isCurrent,
        })
        if (!isCurrent()) return
        const envelope = asRecord(payload.data), inner = asRecord(envelope.data)
        const allowed = action === 'confirm' ? ['workflow_done', 'approval_pending'] : ['workflow_cancelled']
        if (!payload.success || inner.plan_id !== planId || !allowed.includes(String(envelope.action || ''))) {
          throw new Error(String(payload.response || payload.message || '未收到原计划的操作回执，请核对后重试'))
        }
        card.status = action === 'confirm' ? 'confirmed' : 'cancelled'
        const nextCard = parseApprovalCardFromPayload(payload)
        await addAndSaveMessage(payload.response || `原计划已${action === 'confirm' ? '确认' : '取消'}。`, 'ai', nextCard ? { approvalCard: nextCard } : undefined, scope.sessionId)
        if (!isCurrent()) return
        syncTaskFromChatResponse(payload, control)
        remoteRound.consumeStateUpdates(payload)
        attachThinkingStepsToLastAiMessage(payload)
        attachTodoStepsToLastAiMessage(payload)
        attachWorkflowTraceToLastAiMessage(payload)
        if (payload.task) showTaskConfirm(payload.task)
        if (payload.autoAction) handleAutoAction(payload.autoAction, control)
        await syncAgentRunFromPayload(payload, control, isCurrent).catch(() => undefined)
        if (action === 'confirm') await approveChatRequestIfAutomatic(payload, isCurrent)
      }
      if (isCurrent()) await agentTaskRuntime.refreshTasks().catch(() => undefined)
    } catch (error) {
      if (isCurrent()) card.error = error instanceof Error ? error.message : '操作未确认，请核对原任务后重试'
    } finally {
      card.submitting = false
      round.setLoading(false)
    }
  }

  const confirmWorkflowFromCard = (cardId: string) => controlWorkflowFromCard(cardId, 'confirm')
  const cancelWorkflowFromCard = (cardId: string) => controlWorkflowFromCard(cardId, 'cancel')

  /** 撤回一条用户消息及其之后的回复，供「撤回编辑」使用。 */
  async function recallUserMessage(index: number): Promise<{ ok: boolean; text: string; message?: string }> {
    const scope = captureLocalScope()
    const message = messages.value[index]
    if (!message || message.role !== 'user') return { ok: false, text: '', message: '只能撤回自己发送的消息。' }
    if (isLoading.value || isExecuting.value || isRecalling.value) {
      return { ok: false, text: '', message: '当前对话正在处理，请稍后再撤回。' }
    }
    const text = plainTextFromChatHtml(message.content).trim()
    const messageId = durableRecallMessageId(message)
    const suffix = messages.value.slice(index)
    if (suffix.some(row => !durableRecallMessageId(row) && (
      row.turnId || row.persistence?.status === 'saved' || row.persistence?.request ||
      row.businessResult || row.execution || row.agentRunTrace || row.approvalCard || row.workflowAction || row.nodeResults?.length
    )) || (!messageId && suffix.some(durableRecallMessageId))) {
      return { ok: false, text, message: '这段对话含未同步的服务端记录，请先同步会话或核对原任务。' }
    }
    if (!messageId) {
      messages.value = messages.value.slice(0, index)
      return { ok: true, text }
    }
    const key = recallKey.value
    const identity = chatIdentity()
    const isCurrent = () => chatIdentity() === identity && scope.isCurrent()
    const origin = retainConversationMessages?.(scope.sessionId)
    const productScope = productsStore.captureProductsScope()
    recalling.add(key)
    try {
      const result = await chatApi.recallMessage(scope.sessionId, messageId)
      if (!result?.success) return isCurrent()
        ? { ok: false, text, message: result?.message || '撤回服务端消息失败。' }
        : { ok: false, text }
      const target = origin?.messages ?? messages
      if (result.rolled_back && chatIdentity() === identity) productsStore.invalidateProducts(productScope)
      if (chatIdentity() === identity && (origin || isCurrent())) {
        const position = target.value.findIndex(row => durableRecallMessageId(row) === messageId)
        if (position >= 0) {
          target.value = target.value.slice(0, position)
          origin?.persist()
        }
      }
      if (!isCurrent()) return { ok: false, text }
      let notice = result.rolled_back ? '已撤回相关业务操作。' : ''
      try { await syncFromServer({ required: true, isCurrent }) }
      catch { notice = '撤回已完成，历史同步尚未确认，请刷新会话。' }
      return isCurrent() ? { ok: true, text, ...(notice ? { message: notice } : {}) } : { ok: false, text }
    } catch (error) {
      if (!isCurrent()) return { ok: false, text }
      const detail = error instanceof ApiError && error.status > 0
        ? error.message : '撤回结果未确认，请先核对对话和业务记录。'
      return { ok: false, text, message: detail }
    } finally {
      recalling.delete(key)
      origin?.release()
    }
  }

  /** 失败卡片：按本轮幂等键向后端核对，确认这轮到底有没有写入。 */
  async function reconcileTurnMessage(index: number): Promise<{ ok: boolean; message?: string }> {
    const message = messages.value[index]
    const turnId = String(message?.turnId || '').trim()
    if (!message || !turnId) return { ok: false, message: '缺少本轮编号，无法核对。' }
    const scope = captureLocalScope()
    try {
      const result = (await chatApi.reconcileTurn(turnId)) as {
        success?: boolean
        message?: string
        execution?: {
          idempotency_key?: string
          intent?: string
          effect?: string
          committed?: boolean
          records?: number
        }
      } | null
      if (!scope.isCurrent() || messages.value[index] !== message) return { ok: false }
      const execution = result?.execution
      if (!result?.success || !execution) {
        return { ok: false, message: String(result?.message || '核对失败，请稍后重试。') }
      }
      const recordedOutcome = message.execution && chatExecutionOutcome(message.execution)
      if ((execution.records === 0 || execution.effect === 'none')
        && (recordedOutcome === 'partial' || recordedOutcome === 'unknown' || ['unknown', 'blocked'].includes(message.workflowAction || ''))) {
        return { ok: false, message: '本轮幂等记录不足以确认业务结果，请在原任务中核对。' }
      }
      messages.value[index] = {
        ...message,
        execution: {
          idempotencyKey: String(execution.idempotency_key || turnId),
          intent: String(execution.intent || 'chat_turn'),
          committed: execution.committed === true,
          effect: String(execution.effect || 'unknown'),
        },
      }
      return { ok: true }
    } catch {
      return { ok: false, ...(scope.isCurrent() ? { message: '核对失败，请稍后重试。' } : {}) }
    }
  }

  async function syncSessionMessages(options: { required?: boolean; isCurrent?: () => boolean } = {}): Promise<void> {
    if (isLoading.value || isExecuting.value) {
      if (options.required) throw new Error('当前会话正在处理，请稍后重试')
      return
    }
    const scope = captureLocalScope()
    await syncFromServer({ ...options, onConversation: observeConversation })
    if (!scope.isCurrent() || options.isCurrent?.() === false) return
    applyPersistedTaskPanelStateForSession(scope.sessionId)
    // Tasks have their own stale/error recovery and are not required to read the current conversation.
    // During the startup splash this list (limit 200) occupies the only worker and
    // pushes the page the user is opening past the cold-load budget.
    const shellReady = document.getElementById('app')?.dataset.startupReady === 'true'
    if (options.required) {
      if (!document.getElementById('app') || shellReady) void agentTaskRuntime.refreshTasks().catch(() => {})
    } else await agentTaskRuntime.refreshTasks()
  }
  executeRemoteChatRoundRef.fn = executeRemoteChatRound

  registerHistoryModWatch(showHistoryPanel)

  workflowPanel.registerWorkflowPanelWatchers(persistTaskPanelStateForSession, currentTask)

  onMounted(() => {
    const sid = String(sessionId.value || '').trim() || 'default'
    if (!lastExcelAnalysisContext.value) {
      const restored = readPersistedExcelAnalysisContext(sid)
      if (restored) lastExcelAnalysisContext.value = restored
    }
    window.addEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.mountWorkflowPanel()
    agentTaskRuntime.start()
  })

  onBeforeUnmount(() => {
    localViewRevision++
    window.removeEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.unmountWorkflowPanel()
    agentTaskRuntime.stop()
    chatSessionActivity.cancelAll()
    chatRequest.cancelPendingChatBatch()
  })

  return {
    messages,
    messagesHaveEarlier, earlierMessagesLoading, earlierMessagesError, loadEarlierMessages,
    cacheError,
    retryMessagesCache,
    retryMessageSave,
    lastMessage: computed(() => messages.value[messages.value.length - 1] ?? null),
    currentTask,
    orderNumberFetching,
    isLoading,
    isStreamingReply,
    isExecuting,
    stateSteps,
    latestAssistantPush,
    taskList,
    filteredTaskList,
    activeTask,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    showHistory,
    historySessions: computed(() => historySessions.value.map(session => ({
      ...session, activity: statuses.value[session.session_id],
    }))),
    historyLoading,
    historyError,
    historyHasMore,
    historyLoadingMore,
    loadMoreHistorySessions,
    refreshHistorySessions,
    restoreLatestOwnedSession,
    chatMessagesRef,
    pushCopied,
    loadingProgressText,
    attachmentUploading,
    multimodalPendingCount,
    multimodalStaging,
    artifactStaging,
    unsupportedStaging,
    removeArtifactFile,
    removeMultimodalFile,
    dismissUnsupportedFile,
    excelSheetOptions,
    linkedExcelSheet,
    linkedExcelAllSheets,
    isPrinting,
    taskTableColumns,
    taskTableItems,
    taskOrderNumber,
    generateSessionId,
    scrollToBottom,
    sendMessage,
    retryModelOnly: (message: string, turnId: string) => sendMessage(message, { retryOf: turnId, idempotencyKey: turnId }),
    confirmDestructive: (message: string, idempotencyKey: string) => sendMessage(message, { destructiveConfirmed: true, idempotencyKey }),
    stopReply,
    isRecalling,
    recallUserMessage,
    reconcileTurnMessage,
    confirmWorkflowFromCard,
    cancelWorkflowFromCard,
    confirmTask,
    refetchTaskOrderNumber,
    setCustomOrderNumber,
    cancelTask,
    showTaskConfirm,
    onAttachmentFileChange,
    showHistoryPanel,
    clearHistorySessions,
    renameSession,
    deleteSession,
    handleShipmentDownloadClick,
    startPrintFromTaskCard,
    copyAssistantPushContent,
    openAssistantFloatFromTaskPanel,
    syncSessionMessages,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    toggleTaskExpanded,
    setTaskFilter,
    removeTask,
    ...agentTaskRuntime,
    jumpToTaskMessage,
    handleAutoAction,
    isStartPrintMessage,
    ttsEnabled,
    setTtsEnabled,
    addAndSaveMessage,
    stageExcelAnalysisContext,
  }
}
