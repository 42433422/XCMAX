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
import { chatMessageExtrasFromServerRow, useChatMessages, type ChatMessage } from './useChatMessages'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'
import { usePrintService } from './usePrintService'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'
import { useChatExcelContext } from './useChatExcelContext'
import { useChatRequest } from './useChatRequest'
import { useDesktopNavigationContext } from './useDesktopNavigationContext'
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
import { useChatOrchestrationRemoteRound, type ChatTurnObservationOptions } from './chat-orchestration/useChatOrchestrationRemoteRound'
import { useOnboardingFirstOrderRun } from './useOnboardingFirstOrderRun'
import { APPROVAL_GRANT_MISSING_MESSAGE, approveRunWithFreshGrant } from '@/api/agentRunApproval'
import agentRunsApi from '@/api/agentRuns'
import type { AgentRunEvent } from '@/api/agentRuns'
import { buildFullApiUrl } from '@/api/core'
import { AuthenticatedEventStream } from '@/utils/authenticatedEventStream'
import { buildAgentRunTraceFromEvents, withAgentRunReceipt } from '@/utils/agentRunTraceModel'
import { runtimeRunChatEvents } from '@/utils/runtimeRunChatEvents'
import { approvalCardId, parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { pendingRuntimeRunId, runtimeContinuationFromPayload } from '@/utils/chatRuntimeContinuation'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { approvalApi } from '@/api/approval'
import chatApi from '@/api/chat'
import { ApiError } from '@/api/core'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { chatExecutionOutcome, readChatExecution } from '@/components/chat/chatFailureRecovery'
import { activeChatTurnMessage, activeChatTurnStatus, droppedRoundFromHistory, readActiveChatTurn, type ActiveChatTurn } from '@/utils/droppedRoundPresentation'
import { useAiSdkChatRound } from './chat-orchestration/useAiSdkChatRound'
import { stepsFromAiParts } from '@/utils/agentStepChain'
import { activeRunIdOfTask } from '@/utils/agentTaskWorkspaceModel'
import { readRuntimeOutputDownloads } from '@/utils/agentArtifactDownloads'
import { plannerExecutionState, requiresTurnReconciliation } from './chat-orchestration/chatOrchestrationShared'

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
  const lastRequestContextSummary = ref('')
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
    captureArtifacts: excelCtx.captureChatArtifacts,
    readDesktopNavigation: useDesktopNavigationContext(),
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
  let observedTurn: { turn: ActiveChatTurn; controller: AbortController; message: ChatMessage; checkingReceipt: boolean;
    sessionId: string; revision?: number; isCurrent: () => boolean; retryAt: number; failures: number;
    stream?: AuthenticatedEventStream; reconnectTimer?: number; lastEventId?: string;
    events: AgentRunEvent[]; seenEvents: Set<string> } | undefined

  function stopTurnObservation() {
    observedTurn?.controller.abort()
    observedTurn?.stream?.close()
    if (observedTurn?.reconnectTimer !== undefined) window.clearTimeout(observedTurn.reconnectTimer)
    observedTurn = undefined
  }

  function observeConversation(data: unknown) {
    const body = asRecord(data), revision = typeof body.revision === 'number' ? body.revision : undefined
    const turn = readActiveChatTurn(body)
    if (turn) return observeActiveTurn(turn, { revision })
    // A terminal run can still have an undelivered queue acknowledgement.
    // Reopening that history must keep following its original bound turn.
    if (body.durable !== true || body.id !== sessionId.value || revision === undefined) return
    for (const raw of [...asArray(body.messages)].reverse()) {
      const row = asRecord(raw)
      if (row.role !== 'assistant') continue
      let metadata = asRecord(row.metadata)
      if (typeof row.metadata === 'string') {
        try { metadata = asRecord(JSON.parse(row.metadata)) } catch { continue }
      }
      if (asRecord(metadata.business_harness).queued_reply !== true) continue
      const pending = readActiveChatTurn({ active_turn: metadata.summary })
      if (pending) return observeActiveTurn(pending, { revision, resume: false })
    }
  }

  function observeActiveTurn(turn: ActiveChatTurn, options: ChatTurnObservationOptions = {}) {
    let message = messages.value.find(row => row.role === 'ai' && row.turnId === turn.turnId)
    if (message && observedTurn?.message === message && observedTurn.turn.runId === turn.runId
      && observedTurn.revision === options.revision && observedTurn.isCurrent()) return
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
    const controller = new AbortController()
    const scope = captureLocalScope()
    const observation = { turn, controller, message, checkingReceipt: false, sessionId: scope.sessionId,
      revision: options.revision, isCurrent: () => scope.isCurrent() && options.isCurrent?.() !== false, retryAt: 0, failures: 0,
      events: [] as AgentRunEvent[], seenEvents: new Set<string>(), stream: undefined as AuthenticatedEventStream | undefined,
      reconnectTimer: undefined as number | undefined, lastEventId: undefined as string | undefined }
    observedTurn = observation
    const isCurrent = () => observedTurn === observation && observation.isCurrent() && messages.value.includes(message)
    const connectRunEvents = () => {
      if (!isCurrent() || typeof agentRunsApi.eventStreamPath !== 'function') return
      const url = buildFullApiUrl(agentRunsApi.eventStreamPath(turn.runId, observation.lastEventId))
      const stream = new AuthenticatedEventStream(url)
      observation.stream = stream
      const reconnect = () => {
        if (!isCurrent() || observation.stream !== stream) return
        stream.close()
        observation.stream = undefined
        void agentTaskRuntime.refreshTasks().catch(() => undefined)
        observation.reconnectTimer = window.setTimeout(() => {
          observation.reconnectTimer = undefined
          connectRunEvents()
        }, 1500)
      }
      const handle = (raw: Event) => {
        if (!isCurrent()) return
        let event: AgentRunEvent
        try { event = JSON.parse((raw as MessageEvent).data) as AgentRunEvent } catch { return }
        if (event.run_id !== turn.runId || !event.event_id || observation.seenEvents.has(event.event_id)) return
        observation.seenEvents.add(event.event_id)
        observation.lastEventId = event.event_id
        observation.events.push(event)
        message.agentRunTrace = buildAgentRunTraceFromEvents(observation.events, turn.runId)
        for (const projected of runtimeRunChatEvents(event)) {
          if (projected.type === 'model_activity') message.waitingHint = '模型正在分析任务…'
          if (projected.type === 'tool_call') {
            message.toolProgressLabel = projected.label
            delete message.waitingHint
          }
          if (projected.type === 'thinking') {
            const steps = String(message.thinkingSteps || '').split('\n').filter(Boolean)
            message.thinkingSteps = [...steps.slice(-14), projected.delta].join('\n')
            message.toolProgressLabel = projected.delta
            delete message.waitingHint
          }
        }
        if (['runtime.xiaox.finished', 'run.state_changed', 'runtime.model.failure'].includes(event.event_type))
          void agentTaskRuntime.refreshTasks().catch(() => undefined)
      }
      for (const name of ['runtime.xiaox.turn.started', 'runtime.xiaox.turn.completed',
        'runtime.xiaox.item.started', 'runtime.xiaox.item.completed', 'runtime.model.started',
        'runtime.model.completed', 'runtime.model.failed', 'runtime.model.failure',
        'runtime.goal.verification.started', 'runtime.goal.verified', 'runtime.xiaox.finished',
        'run.state_changed', 'runtime.progress.stalled', 'runtime.output.quarantined',
        'runtime.recovery.strategy_changed']) stream.addEventListener(name, handle)
      stream.addEventListener('stream.closed', reconnect)
      stream.addEventListener('stream.unauthorized', () => { if (isCurrent()) stopTurnObservation() })
      stream.onerror = reconnect
    }
    connectRunEvents()
    // The task feed supplies terminal status; this read-only run event stream
    // supplies SDK progress without resubmitting the original request.
    void agentTaskRuntime.refreshTasks().catch(() => undefined)
    if (options.resume === false || turn.status === 'blocked') return
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
      if (!isCurrent()) return
      if (result.error) {
        if ([401, 403].includes(Number(asRecord(result.error).status))) {
          finishObservedTurn(observation, 'waiting_auth', '当前授权无法读取原任务回执，请核对授权。')
        }
        return
      }
      if (readActiveChatTurn(receipt)) return
      const payload = asRecord(receipt)
      if (awaitingAuthorization && !requiresTurnReconciliation(receipt)
        && parseApprovalCardFromPayload(payload)?.status !== 'pending') {
        finishObservedTurn(observation, 'waiting_auth', '原任务正在等待授权，请到任务工作区核对。')
        return
      }
      const response = asString(payload.response || payload.message || result.text).trim()
      if (!response || typeof payload.success !== 'boolean') return
      const state = plannerExecutionState(payload)
      if (['queued', 'running', 'planning', 'retrying'].includes(state)) return
      const action = state === 'unknown' ? 'unknown'
        : parseApprovalCardFromPayload(payload)?.status === 'pending' ? 'waiting_approval'
          : state || (payload.success ? 'completed' : 'failed')
      finishObservedTurn(observation, action, response, payload)
    })
  }

  function finishObservedTurn(observation: NonNullable<typeof observedTurn>, action: string, text: string, payload?: Record<string, unknown>, savedMessage?: Record<string, unknown>) {
    const { message } = observation
    const index = messages.value.indexOf(message)
    if (observedTurn !== observation || !observation.isCurrent() || index < 0) return
    const execution = payload ? readChatExecution(payload) : undefined
    const card = payload ? parseApprovalCardFromPayload(payload) : undefined
    const runtimeContinuation = payload ? runtimeContinuationFromPayload(payload) : undefined
    const files = payload ? readRuntimeOutputDownloads(payload) : []
    applyPlainTextToMessageIndex(index, text, { ...(savedMessage ? chatMessageExtrasFromServerRow(savedMessage) : {}),
      workflowAction: action, ...(execution ? { execution } : {}), ...(card ? { approvalCard: card } : {}),
      ...(runtimeContinuation ? { runtimeContinuation } : {}), ...(files.length ? { outputArtifacts: files } : {}) })
    if (!runtimeContinuation && !chatMessageExtrasFromServerRow(savedMessage).runtimeContinuation) delete message.runtimeContinuation
    delete message.toolProgressLabel
    delete message.waitingHint
    if (message.liveSteps?.length) message.liveSteps = message.liveSteps.filter(step => step.state !== 'running')
    if (message.agentRunTrace?.run_id === observation.turn.runId)
      message.agentRunTrace = withAgentRunReceipt(message.agentRunTrace, action)
    chatSessionActivity.forSession(observation.sessionId).setStatus(action === 'completed' ? 'ready'
      : ['failed', 'rejected'].includes(action) ? 'error'
        : ['cancelled', 'interrupted'].includes(action) ? 'stopped'
          : ['waiting_user', 'waiting_approval', 'waiting_auth', 'waiting_input', 'paused'].includes(action) ? 'waiting' : 'review')
    stopTurnObservation()
    flushMessagesCache()
  }

  watch([taskList, () => agentTaskRuntime.taskSyncState.value.checking], async ([tasks, checking]) => {
    const observation = observedTurn
    if (!observation) return
    if (!observation.isCurrent() || !messages.value.includes(observation.message)) return stopTurnObservation()
    if (checking || observation.checkingReceipt) return
    const task = agentTaskRuntime.taskSyncState.value.stale ? undefined : tasks.find(item => activeRunIdOfTask(item) === observation.turn.runId)
    const fields = asRecord(task?.payload)
    const taskId = asString(fields.taskId).trim()
    if (taskId) observation.message.recoveryTaskId = taskId
    const status = activeChatTurnStatus(asString(fields.rawRunStatus))
    if (status) {
      observation.message.toolProgressLabel = task?.stage || activeChatTurnMessage(observation.turn)
      if (observation.message.workflowAction !== status) {
        applyPlainTextToMessageIndex(messages.value.indexOf(observation.message), activeChatTurnMessage({
          ...observation.turn, status, message: '',
        }))
      }
      observation.message.workflowAction = status
      chatSessionActivity.forSession(observation.sessionId).setStatus(['waiting_approval', 'paused'].includes(status) ? 'waiting' : 'review')
      if (status !== 'blocked') return
    }
    if (Date.now() < observation.retryAt) return
    observation.checkingReceipt = true
    try {
      // getConversation has a finite transport timeout; only one read is in flight.
      const data = asRecord(await chatApi.getConversation(observation.sessionId, { turn_id: observation.turn.turnId }))
      if (observedTurn !== observation || !observation.isCurrent()) return
      const binding = asRecord(data.turn_receipt || data.active_turn)
      if ((data.id !== undefined && data.id !== observation.sessionId)
        || (data.durable === true && data.revision === null)
        || (observation.revision !== undefined && data.revision !== observation.revision)
        || (binding.turn_id !== undefined && binding.turn_id !== observation.turn.turnId)
        || (binding.run_id !== undefined && binding.run_id !== observation.turn.runId)) {
        finishObservedTurn(observation, 'unknown', '原会话或任务回执已改变，请重新核对原对话。')
        return
      }
      if (typeof data.revision === 'number') observation.revision = data.revision
      const row = asArray(data.messages).map(asRecord).find(message => typeof binding.message_id === 'number'
        && message.id === binding.message_id && message.role === 'assistant')
      const receipt = droppedRoundFromHistory(row ? { ...data, turn_receipt: { ...binding, message: row.content } } : data, observation.turn.turnId)
      if (receipt.activeTurn) {
        if (receipt.activeTurn.status === 'blocked') observeActiveTurn(receipt.activeTurn, { revision: observation.revision, resume: false })
      } else if (data.success === true && data.durable === true && receipt.savedMessage
        && ['completed', 'failed', 'blocked', 'cancelled', 'rejected', 'interrupted', 'unknown'].includes(asString(binding.status))
        && asString(receipt.savedMessage.content).trim()
        && binding.turn_id === observation.turn.turnId && binding.run_id === observation.turn.runId) {
        const action = ['cancelled', 'rejected'].includes(asString(binding.status)) ? asString(binding.status) : receipt.workflowAction
        finishObservedTurn(observation, action, asString(receipt.savedMessage.content), undefined, receipt.savedMessage)
        return
      } else if (data.success === true && data.durable === true && data.id === observation.sessionId
        && typeof data.revision === 'number' && binding.receipt_kind === 'run' && binding.durable === true
        && binding.turn_id === observation.turn.turnId && binding.run_id === observation.turn.runId
        && requiresTurnReconciliation(binding) && asString(binding.message).trim()) {
        finishObservedTurn(observation, 'unknown', asString(binding.message))
        return
      }
    } catch (error) {
      const status = Number(asRecord(error).status)
      if ([401, 403, 404, 410].includes(status)) {
        finishObservedTurn(observation, [401, 403].includes(status) ? 'waiting_auth' : 'unknown',
          [401, 403].includes(status) ? '当前授权无法读取原任务回执，请核对授权。' : '原对话已不可用，已停止读取交付回执。')
        return
      }
    } finally {
      observation.checkingReceipt = false
    }
    if (observedTurn !== observation || !observation.isCurrent()) return
    observation.retryAt = Date.now() + Math.min(2000 * 2 ** Math.min(observation.failures++, 4), 30_000)
    applyPlainTextToMessageIndex(messages.value.indexOf(observation.message),
      '原任务交付回执正在同步。业务结果请在原任务中核对，无需重复提交。', { workflowAction: 'unknown' })
    delete observation.message.toolProgressLabel
    chatSessionActivity.forSession(observation.sessionId).setStatus('review')
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
    chatRequest,
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
      const card = list.find(msg => msg.role === 'ai' && !msg.runtimeContinuation?.runId && msg.approvalCard?.status === 'pending'
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
    stopTurnObservation()
    localViewRevision++
    const stopped = chatSessionActivity.cancelSession(sessionId.value, { showStopNotice: !options?.supersede })
    chatRequest.cancelPendingChatBatch(sessionId.value)
    chatRequest.stopLoadingProgress()
    clearVoiceQueue()
    if (!stopped) return
    const kept = messages.value.filter((msg) => {
      if (!msg.streamingShell) return true
      const plain = plainTextFromChatHtml(msg.content).trim()
      delete msg.streamingShell
      delete msg.waitingHint
      return plain.length > 0
    })
    if (kept.length !== messages.value.length) messages.value = kept
  }

  async function sendMessage(message: string, turn?: { retryOf?: string; idempotencyKey?: string; destructiveConfirmed?: boolean }) {
    if (isRecalling.value) return
    const taskSessionId = String(sessionId.value || '').trim() || 'default'
    if (isLoading.value) stopReply({ supersede: true })
    const turnId = createBusinessHarnessId('turn')
    const generation = chatSessionActivity.beginRound(taskSessionId, turnId)
    generation.setLoading(true)
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
    const continuingRuntime = Boolean(pendingRuntimeRunId(requestScope.messages, taskSessionId))
    let queued = false
    try {
      if (!continuingRuntime && await onboardingFirstOrderRun.tryStart(message, localScope)) {
        await refreshHistorySessions()
        return
      }
      const isCurrent = localScope.isCurrent
      if (!isCurrent()) { rollbackUnsentUser(); return }
      const previewModified = !continuingRuntime && await handleShipmentModify(message, localScope.isCurrent)
      if (!isCurrent()) { rollbackUnsentUser(); return }
      if (previewModified) {
        await saveMessage('user', message, taskSessionId)
        await refreshHistorySessions()
        return
      }

      const printHandled = !continuingRuntime && await handleStartPrintCommand(message, localScope)
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
    const approvalMessage = messages.value.find(msg => msg.role === 'ai' && msg.approvalCard
      && approvalCardId(msg.approvalCard) === cardId)
    const card = approvalMessage?.approvalCard
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
      const parent = approvalMessage?.runtimeContinuation
      if (parent?.runId && parent.runId === runId) throw new Error('审批卡缺少业务子任务标识，请到原任务核对。')
      let runHandled = false
      if (runId) {
        try {
          const receipt = action === 'confirm'
            ? await approveRunWithFreshGrant(runId, { isCurrent, runtimeContext: { source: 'chat_approval_card' } })
            : await agentRunsApi.cancelRun(runId)
          if (!isCurrent() || !receipt) return
          if (!receipt.success || receipt.data?.run_id !== runId) throw new Error(receipt.message || '未收到原任务的操作回执，请核对后重试')
          if (action === 'cancel' && receipt.data.status !== 'cancelled') throw new Error('取消请求已提交，任务尚未确认取消。请在原任务中核对状态。')
          card.status = action === 'confirm' ? 'confirmed' : 'cancelled'
          await addAndSaveMessage(action === 'confirm' ? '已收到确认回执，任务已提交执行，请在任务中查看实际结果。' : '已收到取消回执，任务已取消。', 'ai',
            parent?.sessionId === scope.sessionId ? { runtimeContinuation: { ...parent } } : undefined, scope.sessionId)
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
    refreshLocalHistorySessions?.()
    applyPersistedTaskPanelStateForSession(scope.sessionId)
    // Tasks have their own stale/error recovery and are not required to read the current conversation.
    // During the startup splash this list (limit 200) occupies the only worker and
    // pushes the page the user is opening past the cold-load budget.
    const shellReady = document.getElementById('app')?.dataset.startupReady === 'true'
    if (options.required) {
      if (!document.getElementById('app') || shellReady) void agentTaskRuntime.refreshTasks().catch(() => {})
    } else await agentTaskRuntime.refreshTasks()
  }

  registerHistoryModWatch(showHistoryPanel)

  workflowPanel.registerWorkflowPanelWatchers(persistTaskPanelStateForSession, currentTask)

  onMounted(() => {
    const sid = String(sessionId.value || '').trim() || 'default'
    if (!lastExcelAnalysisContext.value) {
      const restored = readPersistedExcelAnalysisContext(sid)
      if (restored) lastExcelAnalysisContext.value = restored
    }
    workflowPanel.mountWorkflowPanel()
    agentTaskRuntime.start()
  })

  onBeforeUnmount(() => {
    localViewRevision++
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
    pendingTurnId: chatSessionActivity.pendingTurnId,
    stoppedTurnId: chatSessionActivity.stoppedTurnId,
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
