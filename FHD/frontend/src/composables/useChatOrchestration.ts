/**
 * useChatOrchestration：聊天编排 Façade。
 * 实现按关注点拆分至 chat-orchestration/ 子模块（自动动作 / 任务执行 / 打印链路 / Excel 分析任务 / 远程对话轮次），
 * 对外入口签名与返回对象字段与拆分前保持完全一致（行为零变更）。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useTutorialStore } from '@/stores/tutorial'
import { useModsStore } from '@/stores/mods'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  clearPersistedTaskPanelState,
  useChatTaskPanelPersistence,
} from './useChatPersistence'
import { useChatTaskList } from './useChatTaskList'
import { useChatMessages } from './useChatMessages'
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
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { isStartPrintMessage } from '../utils/textParser'
import { generateSessionId, normalizeServerContentToHtml, type ChatLocalScope } from './chat-orchestration/chatOrchestrationShared'
import { useChatOrchestrationAutoActions } from './chat-orchestration/useChatOrchestrationAutoActions'
import { useChatOrchestrationTaskExecution } from './chat-orchestration/useChatOrchestrationTaskExecution'
import { useChatOrchestrationPrintFlow } from './chat-orchestration/useChatOrchestrationPrintFlow'
import { useChatOrchestrationExcelTasks } from './chat-orchestration/useChatOrchestrationExcelTasks'
import { useChatOrchestrationRemoteRound } from './chat-orchestration/useChatOrchestrationRemoteRound'
import { useOnboardingFirstOrderRun } from './useOnboardingFirstOrderRun'
import { approveRunWithFreshGrant } from '@/api/agentRunApproval'
import agentRunsApi from '@/api/agentRuns'
import { approvalCardId, parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { asRecord } from '@/utils/typeGuards'

export function useChatOrchestration(options: UseChatViewOptions) {
  const tutorialStore = useTutorialStore()
  const modsStore = useModsStore()
  const { sessionId } = options
  const {
    messages,
    addMessage,
    addAndSaveMessage: addAndSaveMessageRaw,
    saveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    flushMessagesCache,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  } = useChatMessages(sessionId)
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
  const chatSessionActivity = useChatSessionActivity(sessionId)
  const { isLoading, isStreamingReply } = chatSessionActivity
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
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
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
    onIdentityChange: () => {
      pendingDbWriteChatRetryMessages.value = null
      plannerWriteUnlockResumeDraft.value = ''
      chatSessionActivity.cancelAll()
      chatRequest.cancelPendingChatBatch()
      chatSessionActivity.runningIds.value.clear()
      chatSessionActivity.streamingIds.value.clear()
      clearVoiceQueue()
    },
  })
  const {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    refreshHistorySessions,
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

  // Excel 分析任务回调
  const excelTasks = useChatOrchestrationExcelTasks({
    sessionId,
    captureLocalScope,
    addMessage,
    saveMessage,
    lastExcelAnalysisContext,
    linkedExcelAllSheets,
    linkedExcelSheet,
    onMultimodalFileChange,
    taskList,
    createTaskId,
    upsertTask,
    finishTask,
    failTask,
    getLastAiMessageRef,
  })
  const {
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    triggerUpload,
    onExcelAnalyzeFileChange,
  } = excelTasks

  // 远程对话轮次（快路径 / SSE 流式 / JSON 与批量）
  const remoteRound = useChatOrchestrationRemoteRound({
    sessionId,
    messages,
    addMessage,
    saveMessage,
    queueVoice,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
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
    attachAgentRunTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncAgentRunFromPayload,
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
      if (loading || !approvalModeState.enabled || approvalModeState.mode !== 'auto') return
      const card = list.find(msg => msg.role === 'ai' && msg.approvalCard?.status === 'pending'
        && !msg.approvalCard.submitting && !msg.approvalCard.error
        && !msg.approvalCard.approval_path && !msg.approvalCard.approval_request_ids?.length)?.approvalCard
      if (card) void confirmWorkflowFromCard(approvalCardId(card))
    },
    { deep: true },
  )

  function stopReply() {
    localViewRevision++
    const stopped = chatSessionActivity.cancelSession()
    chatRequest.cancelPendingChatBatch()
    chatRequest.stopLoadingProgress()
    clearVoiceQueue()
    pendingDbWriteChatRetryMessages.value = null
    plannerWriteUnlockResumeDraft.value = ''
    if (stopped) {
      for (const msg of messages.value) delete msg.streamingShell
      addMessage('已停止接收本轮回复。已执行的工具不会撤销；后台任务请到任务工作区核对，勿重复提交。', 'ai')
    }
  }

  async function sendMessage(message: string) {
    const taskSessionId = String(sessionId.value || '').trim() || 'default'
    if (isLoading.value) stopReply()
    const generation = chatSessionActivity.beginRound(taskSessionId)
    generation.setLoading(true)
    addMessage(message, 'user')
    const requestScope = {
      identity: resolveChatIdentity(String(modsStore.activeModId || '')),
      signal: generation.signal,
      isCurrent: generation.isCurrent,
      sessionId: taskSessionId,
      messages: [...messages.value],
      turnId: createBusinessHarnessId('turn'),
      taskId: createBusinessHarnessId('task'),
    }
    const localScope = captureLocalScope()
    let queued = false
    try {
      if (await onboardingFirstOrderRun.tryStart(message, localScope)) {
        await refreshHistorySessions()
        return
      }
      const isCurrent = localScope.isCurrent
      if (!isCurrent()) return
      const previewModified = await handleShipmentModify(message, localScope.isCurrent)
      if (!isCurrent()) return
      if (previewModified) {
        await saveMessage('user', message, taskSessionId)
        await refreshHistorySessions()
        return
      }

      const printHandled = await handleStartPrintCommand(message, localScope)
      if (!isCurrent()) return
      if (printHandled) {
        await saveMessage('user', message, taskSessionId)
        await refreshHistorySessions()
        return
      }

      const debounceMs = getChatBatchDebounceMs()
      if (debounceMs <= 0) {
        try {
          await executeRemoteChatRound([message], undefined, requestScope)
        } finally {
          await refreshHistorySessions()
        }
        return
      }
      queued = true
      enqueueChatBatchMessage(message, debounceMs, (msgs) => {
        void executeRemoteChatRound(msgs, undefined, requestScope).finally(() => refreshHistorySessions())
      })
    } finally {
      if (!queued) generation.setLoading(false)
    }
  }

  async function controlWorkflowFromCard(cardId: string, action: 'confirm' | 'cancel') {
    if (!cardId || isLoading.value) return
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
      if (runId) {
        const receipt = action === 'confirm'
          ? await approveRunWithFreshGrant(runId, { isCurrent, runtimeContext: { source: 'chat_approval_card', ...dbGate.resolveChatDbTokensForPayload() } })
          : await agentRunsApi.cancelRun(runId)
        if (!isCurrent() || !receipt) return
        if (!receipt.success || receipt.data?.run_id !== runId) throw new Error(receipt.message || '未收到原任务的操作回执，请核对后重试')
        if (action === 'cancel' && receipt.data.status !== 'cancelled') throw new Error('取消请求已提交，任务尚未确认取消。请在原任务中核对状态。')
        card.status = action === 'confirm' ? 'confirmed' : 'cancelled'
        await addAndSaveMessage(action === 'confirm' ? '已收到确认回执，任务已提交执行，请在任务中查看实际结果。' : '已收到取消回执，任务已取消。', 'ai', undefined, scope.sessionId)
        if (isCurrent()) await syncAgentRunFromPayload({ run_id: runId }, control, isCurrent).catch(() => undefined)
      } else {
        const planId = String(card.plan_id || '').trim()
        if (!planId) throw new Error('确认卡缺少任务标识，请返回原任务核对后重试')
        const payload = await chatRequest.requestChatByModeWithTimeout(control, 90_000, { expectedWorkflowPlanId: planId }, {
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

  async function syncSessionMessages(): Promise<void> {
    if (isLoading.value || isExecuting.value) return
    try {
      await syncFromServer()
    } finally {
      applyPersistedTaskPanelStateForSession(String(sessionId.value || '').trim() || 'default')
      await agentTaskRuntime.refreshTasks()
    }
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
    if (!linkedExcelSheet.value) {
      const first = excelSheetOptions.value[0]
      if (first) linkedExcelSheet.value = first
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
    historySessions,
    historyLoading,
    historyError,
    refreshHistorySessions,
    chatMessagesRef,
    pushCopied,
    loadingProgressText,
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    multimodalPendingCount,
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
    stopReply,
    confirmWorkflowFromCard,
    cancelWorkflowFromCard,
    confirmTask,
    refetchTaskOrderNumber,
    setCustomOrderNumber,
    cancelTask,
    showTaskConfirm,
    triggerUpload,
    onExcelAnalyzeFileChange,
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
