import type { Ref } from 'vue'
import { extractAgentRunId, type useAgentRunEventSync } from '../useAgentRunEvents'
import type { useChatExcelContext } from '../useChatExcelContext'
import type { useChatMessages } from '../useChatMessages'
import type { useChatRequest, ChatRequestScope } from '../useChatRequest'
import type { useChatResponseAttach } from '../useChatResponseAttach'
import { readPlannerBusinessResult } from '@/utils/readPlannerBusinessResult'
import { stepsFromAiParts, isDocumentTemplateChange } from '@/utils/agentStepChain'
import type { ChatConversationStatus, useChatSessionActivity } from '../useChatSessionActivity'
import type { ShipmentTask } from '../useShipmentTask'
import type { ChatPlannerPayload } from '@/types/chat'
import chatApi from '@/api/chat'
import { useAiSdkChatRound } from './useAiSdkChatRound'
import productsApi from '@/api/products'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { useModsStore } from '@/stores/mods'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { isChatStreamEnabled, isWorkflowControlMessage, IncompletePlannerSseError, type PlannerSseEvent } from '@/utils/chatSseStream'
import { collapseExactDuplicateReply } from '@/utils/chatReplyNormalization'
import { stripPlannerDisplayMarkers } from '@/utils/chatBubbleDisplay'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { extractLikelyProductQueryKeyword } from '../useChatPersistence'
import { persistDetachedPlannerResult, recordProductFastPathTask } from '../useChatSessionActivity'
import { asPlannerPayload, errorMessage, requiresTurnReconciliation, plannerExecutionState, isUnfinishedPlannerResponse } from './chatOrchestrationShared'
import { classifyRawError } from '@/utils/networkStability'
import { activeChatTurnMessage, droppedRoundFromHistory, readActiveChatTurn, readDroppedRoundOutcome, type ActiveChatTurn } from '@/utils/droppedRoundPresentation'
import { aiModBriefFromChat, generateAndInstallAiMod } from '@/utils/aiModDeliveryApi'
import type { UiChatMessageExtras } from '@/types/chat-ui'
import { readChatModelRoute, recordChatModelRoute } from '@/utils/chatModelRoute'
import { captureAuthSession, probeEnterpriseSession } from '@/utils/authSessionCache'
import { noteModelPath } from '@/components/sidebar/modelPathHealth'
import { modelOutcomeFromText, readChatExecution } from '@/components/chat/chatFailureRecovery'
import type { PlannerChatOptions } from '../useChatRequest'
import { isOfficeEltToolMessage } from '@/domain/optionalTemplateSelection'
import { parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { isRuntimeWaiting, pendingRuntimeRunId, runtimeContinuationFromPayload } from '@/utils/chatRuntimeContinuation'

/** Bound the initial model wait; once content or a tool marker arrives, use the reply budget. */
export const CHAT_STREAM_STALL_MS = 40_000

type ChatMessagesApi = ReturnType<typeof useChatMessages>

export interface ChatOrchestrationRemoteRoundDeps {
  sessionId: Ref<string>
  messages: ChatMessagesApi['messages']
  addMessage: ChatMessagesApi['addMessage']
  saveMessage: ChatMessagesApi['saveMessage']
  queueVoice: ChatMessagesApi['queueVoice']
  pushStreamingAiShell: ChatMessagesApi['pushStreamingAiShell']
  applyPlainTextToMessageIndex: ChatMessagesApi['applyPlainTextToMessageIndex']
  flushMessagesCache: ChatMessagesApi['flushMessagesCache']
  retainConversationMessages?: ChatMessagesApi['retainConversationMessages']
  ttsEnabled: Ref<boolean>
  chatSessionActivity: ReturnType<typeof useChatSessionActivity>
  chatRequest: ReturnType<typeof useChatRequest>
  resolveExcelAnalysisContextForRequest: ReturnType<typeof useChatExcelContext>['resolveExcelAnalysisContextForRequest']
  multimodalPendingCount: ReturnType<typeof useChatExcelContext>['multimodalPendingCount']
  stateSteps: Ref<Array<{ node_id: string; status: 'succeeded' | 'failed'; output_summary: string }>>
  currentTask: Ref<ShipmentTask | null>
  syncTaskFromChatResponse: ReturnType<typeof useChatResponseAttach>['syncTaskFromChatResponse']
  attachThinkingStepsToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachThinkingStepsToLastAiMessage']
  attachTodoStepsToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachTodoStepsToLastAiMessage']
  attachWorkflowTraceToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachWorkflowTraceToLastAiMessage']
  attachApprovalCardToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachApprovalCardToLastAiMessage']
  attachBusinessResultToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachBusinessResultToLastAiMessage']
  attachAgentRunTraceToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachAgentRunTraceToLastAiMessage']
  attachContextSummaryToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachContextSummaryToLastAiMessage']
  syncAgentRunFromPayload: ReturnType<typeof useAgentRunEventSync>['syncAgentRunFromPayload']
  observeActiveTurn?: (turn: ActiveChatTurn) => void
  showTaskConfirm: (task: unknown) => void
  maybeCloseAssistantFloatForShipmentTask: (task: unknown, autoAction: unknown) => void
  emitAssistantPush: (payload?: unknown) => void
  handleAutoAction: (action: unknown, userMessage?: string) => void
}

export function useChatOrchestrationRemoteRound(deps: ChatOrchestrationRemoteRoundDeps) {
  const modsStore = useModsStore()
  const {
    sessionId,
    messages,
    addMessage,
    queueVoice,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
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
    showTaskConfirm,
    maybeCloseAssistantFloatForShipmentTask,
    emitAssistantPush,
    handleAutoAction,
  } = deps
  const {
    setLoadingProgress,
    startWaitProgressTimer,
    buildPlannerChatRequestPayload,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  } = chatRequest

  function responseCameFromCache(payload: unknown): boolean {
    const row = asRecord(payload)
    const data = asRecord(row.data)
    const inner = asRecord(data.data)
    return row.cached === true || data.cached === true || inner.cached === true
  }
  function responseExtras(payload: ChatPlannerPayload, failed = false, list = messages.value): UiChatMessageExtras | undefined {
    const routeMetadata = readChatModelRoute(payload.route_metadata)
    const execution = readChatExecution(payload)
    const businessResult = readPlannerBusinessResult(payload)
    const runtimeContinuation = runtimeContinuationFromPayload(payload)
    const approvalCard = runtimeContinuation ? parseApprovalCardFromPayload(payload) : null
    const receipt = asRecord(payload.history_persistence)
    const receiptIds = asArray(receipt.message_ids)
    const extras: UiChatMessageExtras = {
      ...(routeMetadata ? { routeMetadata } : {}),
      ...(plannerExecutionState(payload) ? { workflowAction: plannerExecutionState(payload) } : failed ? { workflowAction: 'failed' } : {}),
      ...(responseCameFromCache(payload) ? { sameAsPrevious: true } : {}),
      ...(execution ? { execution } : {}),
      ...(businessResult ? { businessResult } : {}),
      ...(runtimeContinuation ? { runtimeContinuation } : {}),
      ...(approvalCard ? { approvalCard } : {}),
    }
    if (receipt.status === 'saved' && receiptIds.length) {
      const turnId = String(receipt.turn_id || payload.turn_id || '')
      for (const message of list) {
        if (turnId && message.turnId === turnId) {
          const id = message.role === 'user' ? receiptIds[0] : receiptIds[receiptIds.length - 1]
          message.persistence = { id: `server:${id}`, status: 'saved' }
        }
      }
      extras.persistence = { id: `server:${receiptIds[receiptIds.length - 1]}`, status: 'saved' }
    } else if (receipt.status === 'failed') {
      extras.persistence = {
        id: `receipt:${String(payload.turn_id || receipt.conversation_id || '')}`,
        status: 'failed', error: String(receipt.message || '历史尚未保存，请仅重试保存。'),
        request: { role: 'ai', content: String(payload.response || payload.message || ''),
          expected_revision: Number(receipt.revision || 0), turn_id: String(receipt.turn_id || payload.turn_id || ''), metadata: JSON.stringify({ ui: extras, business_harness: { turn_id: payload.turn_id } }) },
      }
    }
    return Object.keys(extras).length ? extras : undefined
  }

  function isUnfinishedResponse(value: unknown): boolean {
    const payload = asPlannerPayload(value)
    const isRuntime = payload.runtime === 'codex' || asRecord(payload.data).runtime === 'codex'
    // A rejected runtime admission is terminal for this round, even when its parent is retained.
    // Canonical state keeps reconciliation and authorization waits ahead of the runtime envelope.
    if (isRuntime && ['blocked', 'reply_completed'].includes(plannerExecutionState(payload))) return false
    return isUnfinishedPlannerResponse(payload)
  }

  function conversationStatus(payload: ChatPlannerPayload): ChatConversationStatus {
    const activeTurn = readActiveChatTurn(payload)
    if (activeTurn) return ['waiting_approval', 'paused'].includes(activeTurn.status) ? 'waiting' : 'review'
    if (requiresTurnReconciliation(payload)) return 'review'
    if (payload.requires_token || parseApprovalCardFromPayload(payload)?.status === 'pending') return 'waiting'
    if (['waiting_user', 'waiting_approval', 'waiting_input', 'waiting_auth', 'paused'].includes(plannerExecutionState(payload))) return 'waiting'
    if (isUnfinishedResponse(payload)) return 'review'
    if (['cancelled', 'interrupted'].includes(plannerExecutionState(payload))) return 'stopped'
    return payload.success === false ? 'error' : 'ready'
  }

  function observeModelOutcome(text: string, payload?: ChatPlannerPayload) {
    if (isUnfinishedResponse(payload)) return
    const execution = readChatExecution(payload)
    if (execution?.effect === 'preview') return
    const outcome = modelOutcomeFromText(text)
    if (outcome === 'degraded' || payload?.success === false) noteModelPath('degraded')
    else if (outcome === 'healthy') noteModelPath('healthy')
  }

  /** 消费后端 state.update 事件（payload.data.data.state_updates），维护「步骤进度」UI 状态 */
  function consumeStateUpdates(payload: ChatPlannerPayload): void {
    const row = asRecord(payload)
    const data = asRecord(row.data)
    const inner = asRecord(data.data ?? data)
    const updates = asArray<Record<string, unknown>>(inner.state_updates ?? row.state_updates)
    if (!updates.length) return
    for (const u of updates) {
      if (String(u.type || '') !== 'state.update') continue
      const nodeId = String(u.node_id || '')
      if (!nodeId) continue
      const entry = {
        node_id: nodeId,
        status: String(u.status || 'succeeded') === 'failed' ? ('failed' as const) : ('succeeded' as const),
        output_summary: String(u.output_summary || ''),
      }
      const idx = stateSteps.value.findIndex((s) => s.node_id === nodeId)
      if (idx >= 0) {
        stateSteps.value[idx] = entry
      } else {
        stateSteps.value.push(entry)
      }
    }
  }

  function maybePrefetchProductAssistantFloat(userText: string) {
    // 教程进行中也需要与聊天请求并行预开产品副窗；否则会出现「不开教程立刻出副窗、走了教程反而要等 AI」的体验差。
    // 副窗切到「协助/产品查询」若与某步高亮冲突，用户仍可用教程卡片「下一步」或退出教程。
    const kw = extractLikelyProductQueryKeyword(userText)
    if (!kw) return
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: { feature: 'products', query: kw, forceOpen: true },
      }),
    )
  }

  async function executeRemoteChatRound(remoteMessages: string[], opts?: PlannerChatOptions, scope?: ChatRequestScope) {
    if (!remoteMessages.length) return
    const requestScope = scope || { sessionId: sessionId.value, messages: [...messages.value] }
    if (!requestScope.isCurrent) Object.assign(requestScope, chatSessionActivity.beginRound(requestScope.sessionId))
    const identity = requestScope.identity ?? resolveChatIdentity(String(modsStore.activeModId || ''))
    const isAuthCurrent = captureAuthSession()
    const isOwnerCurrent = () => isAuthCurrent() && requestScope.isCurrent?.() !== false && identity === resolveChatIdentity(String(modsStore.activeModId || ''))
    if (!isOwnerCurrent()) return
    const activity = chatSessionActivity.forSession(requestScope.sessionId)
    const round = {
      isActive: () => isOwnerCurrent() && activity.isActive(),
      setLoading: (value: boolean) => { if (isOwnerCurrent()) activity.setLoading(value) },
      setStreaming: (value: boolean) => { if (isOwnerCurrent()) activity.setStreaming(value) },
      setStatus: (status: ChatConversationStatus) => { if (isOwnerCurrent()) activity.setStatus(status) },
    }
    const saveMessage: ChatMessagesApi['saveMessage'] = async (...args) => {
      if (isOwnerCurrent()) await deps.saveMessage(...args)
    }
    const addRoundMessage = async (text: string, extras?: UiChatMessageExtras) => {
      if (round.isActive()) addMessage(text, 'ai', { turnId: requestScope.turnId, ...extras }, { speak: ttsEnabled.value })
    }
    const primaryText = remoteMessages[0] || ''
    const continuingRuntime = Boolean(pendingRuntimeRunId(requestScope.messages, requestScope.sessionId))
    const aiModBrief = !continuingRuntime && remoteMessages.length === 1 && !isAdminConsoleSpa() ? aiModBriefFromChat(primaryText) : ''

    if (aiModBrief) {
      round.setLoading(true)
      setLoadingProgress('正在创建自用 MOD…', requestScope.sessionId)
      startWaitProgressTimer(requestScope.sessionId)
      try {
        const result = await generateAndInstallAiMod(aiModBrief, {
          isCurrent: isOwnerCurrent,
          onProgress: (progress) => { if (isOwnerCurrent()) setLoadingProgress(progress.label, requestScope.sessionId) },
        })
        if (!isOwnerCurrent()) return
        const responseText = `已生成并安装自用 MOD「${result.modId}」。${result.installMessage}`
        const extras: UiChatMessageExtras = {
          workflowAction: 'mod_generated_and_installed',
          nodeResults: [
            { node_id: 'generate', tool_id: 'workbench', action: 'generate_mod', success: true },
            { node_id: 'validate', tool_id: 'workbench', action: 'validate_mod', success: true },
            { node_id: 'install', tool_id: 'mod_store', action: 'install_self_use', success: true },
          ],
        }
        await addRoundMessage(responseText, extras)
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', responseText, requestScope.sessionId, extras),
        ])
      } catch (err) {
        const responseText = `MOD 生成或安装失败：${errorMessage(err, '未知错误')}`
        await addRoundMessage(responseText)
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', responseText, requestScope.sessionId),
        ])
      } finally {
        round.setLoading(false)
        if (isOwnerCurrent()) stopLoadingProgress(requestScope.sessionId)
      }
      return
    }

    /** 查产品类话术可不必等 /ai/chat 或连通性探测，直接走产品列表接口 */
    /** 管理端（admin-console）无产品库业务，不走产品快路径，避免「查询…」话术被误判为产品检索 */
    const kwFast =
      !continuingRuntime && remoteMessages.length === 1 && !isAdminConsoleSpa() && !resolveExcelAnalysisContextForRequest() && multimodalPendingCount.value === 0
        ? extractLikelyProductQueryKeyword(primaryText)
        : null

    // 快路径会自己拉产品列表并注水副窗；再 prefetch 会多打一遍相同接口，徒增等待
    if (!continuingRuntime && !kwFast && round.isActive()) {
      maybePrefetchProductAssistantFloat(primaryText)
    }

    if (kwFast) {
      round.setLoading(true)
      setLoadingProgress('正在查询产品库…', requestScope.sessionId)
      startWaitProgressTimer(requestScope.sessionId)
      try {
        const resp = await productsApi.searchProducts(kwFast)
        if (!isOwnerCurrent()) return
        const respRow = asRecord(resp)
        if (resp && resp.success === false) {
          throw new Error(String(resp.message || '产品库查询失败'))
        }
        const raw = resp.data ?? respRow.products ?? respRow.items
        const rows = asArray<Record<string, unknown>>(raw)
        const lines = rows.slice(0, 3).map((row) => {
          const m = String(row.model_number || '').trim()
          const n = String(row.name || row.product_name || '-').trim()
          const p = Number(row.price || 0)
          const pf = Number.isFinite(p) ? p.toFixed(2) : '0.00'
          return `- ${m || '-'} / ${n} / ￥${pf}`
        })
        const previewSuffix = lines.length ? `\n预览命中 ${rows.length} 条：\n${lines.join('\n')}` : ''
        const hasResults = lines.length > 0
        const responseText = hasResults
          ? `已帮你打开产品副窗并带入「${kwFast}」。可在卡片中查看与修改。${previewSuffix}`
          : `未在产品库中找到「${kwFast}」，请确认型号或关键词后重试。`
        const payload: ChatPlannerPayload = {
          success: true,
          response: responseText,
          ...(hasResults ? { autoAction: { type: 'show_products_float', query: kwFast } } : {}),
        }
        const mappedRows = rows.slice(0, 20).map((r) => ({
          id: r.id,
          model_number: r.model_number || '',
          name: r.name || r.product_name || '',
          price: Number(r.price || 0),
          unit: r.unit || '',
        }))
        const totalFromApi = typeof respRow.total === 'number' ? respRow.total : rows.length
        await recordProductFastPathTask(requestScope.sessionId, primaryText, kwFast, mappedRows, totalFromApi, responseText)
        await addRoundMessage(payload.response || '')
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', payload.response || '', requestScope.sessionId),
        ])
        if (!round.isActive()) return
        syncTaskFromChatResponse(payload, primaryText)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(payload)
        attachTodoStepsToLastAiMessage(payload)
        attachWorkflowTraceToLastAiMessage(payload)
        attachApprovalCardToLastAiMessage(payload)
        attachBusinessResultToLastAiMessage(payload)
        if (!payload.task && (payload.autoAction?.type === 'show_products_float' || payload.autoAction?.type === 'show_products')) {
          currentTask.value = null
        }
        if (payload.autoAction) {
          handleAutoAction(
            {
              ...payload.autoAction,
              hydrateProductSearch: { rows: mappedRows, total: totalFromApi },
            },
            primaryText,
          )
        }
        return
      } catch {
        /* 回退到下方 unified / chat 全链路 */
      } finally {
        round.setLoading(false)
        if (isOwnerCurrent()) stopLoadingProgress(requestScope.sessionId)
      }
    }

    if (!isOwnerCurrent()) return
    recordChatModelRoute(requestScope.sessionId, null, identity)
    if (remoteMessages.length === 1 && isChatStreamEnabled()) {
      const primaryForStream = remoteMessages[0] || ''
      round.setStreaming(true)
      round.setLoading(true)
      setLoadingProgress('正在流式生成回复…', requestScope.sessionId)
      const streamStartedAt = startWaitProgressTimer(requestScope.sessionId)
      const baseS = resolveChatTimeoutMs(primaryForStream)
      const timeoutMsS = Math.min(120000, baseS)
      const controller = new AbortController()
      const streamState = { stalled: false }
      const officeToolRun = isOfficeEltToolMessage(primaryForStream)
      const workflowControl = isWorkflowControlMessage(primaryForStream)
      const abort = () => controller.abort()
      if (!officeToolRun) {
        requestScope.signal?.addEventListener('abort', abort, { once: true })
        if (requestScope.signal?.aborted) abort()
      }
      let killTimer = 0
      const stallTimer = officeToolRun || workflowControl ? 0 : window.setTimeout(() => {
        streamState.stalled = true
        controller.abort()
      }, CHAT_STREAM_STALL_MS)
      const armDeadline = () => {
        if (officeToolRun) return
        window.clearTimeout(killTimer)
        killTimer = window.setTimeout(() => {
          controller.abort()
        }, timeoutMsS)
      }
      armDeadline()
      const conversation = deps.retainConversationMessages?.(requestScope.sessionId)
      const streamMessages = conversation?.messages ?? messages
      const msgIndex = (conversation?.pushStreamingAiShell ?? pushStreamingAiShell)()
      const streamMessage = streamMessages.value[msgIndex]
      const canUpdateStream = () => isOwnerCurrent() && (conversation !== undefined || round.isActive())
      const applyStreamText = (plain: string, extras?: UiChatMessageExtras) => {
        const index = conversation ? streamMessages.value.indexOf(streamMessage) : msgIndex
        const apply = conversation?.applyPlainTextToMessageIndex ?? applyPlainTextToMessageIndex
        if (extras) apply(index, plain, extras)
        else apply(index, plain)
      }
      if (streamMessage) {
        streamMessage.turnId = requestScope.turnId
        streamMessage.streamStartedAt = streamStartedAt
        streamMessage.streamStatus = 'submitted'
      }
      // token 逐条到达时合并到一帧渲染：长回复下把 O(tokens) 次重渲染压成 O(帧)。
      let streamFrame = 0
      const flushStreamFrame = () => {
        streamFrame = 0
        if (canUpdateStream()) applyStreamText(streamPlain)
      }
      const scheduleStreamFrame = () => {
        if (streamFrame) return
        streamFrame = window.requestAnimationFrame(flushStreamFrame)
      }
      const cancelStreamFrame = () => {
        if (streamFrame) window.cancelAnimationFrame(streamFrame)
        streamFrame = 0
      }
      const consumeRoute = (value: unknown) => {
        if (!canUpdateStream()) return
        const route = readChatModelRoute(value)
        if (!route) return
        recordChatModelRoute(requestScope.sessionId, route, identity)
        if (streamMessage) streamMessage.routeMetadata = route
      }
      const syncStreamRun = (payload: unknown, attachTrace = false) => {
        const runId = extractAgentRunId(payload) || streamRunId
        if (!round.isActive() || !runId) return
        void syncAgentRunFromPayload({ ...asRecord(payload), run_id: runId }, primaryText, round.isActive).then(() => {
          const index = conversation ? messages.value.indexOf(streamMessage) : msgIndex
          if (attachTrace && round.isActive() && index >= 0
            && messages.value[index] === streamMessage
            && !messages.value.slice(index + 1).some(message => message?.role === 'ai')) {
            attachAgentRunTraceToLastAiMessage(runId)
          }
        }).catch(() => undefined)
      }
      let streamPlain = ''
      let streamTextFromAi = false
      let replaying = false
      let plannerEventHandler: ((event: PlannerSseEvent) => void) | null = null
      let handlePlannerEventRef: ((event: PlannerSseEvent) => void) | null = null
      const aiChatRound = useAiSdkChatRound({
        onEvent: (event) => plannerEventHandler?.(event),
        onMessage: (message) => {
          if (!canUpdateStream() || !streamMessage) return
          streamMessage.streamStatus = 'streaming'
          streamMessage.liveSteps = stepsFromAiParts(message.parts)
        },
        // 附件工件取数轨迹：累积到当前 assistant 消息，气泡「附件读取」按需展开。
        onTrace: (items) => {
          if (replaying || !canUpdateStream() || !streamMessage || !items.length) return
          streamMessage.trace = [...(streamMessage.trace || []), ...items]
        },
        onText: (value) => {
          if (!streamTextFromAi) return
          streamPlain = value
          if (!canUpdateStream()) return
          scheduleStreamFrame()
          if (streamMessage) delete streamMessage.waitingHint
          setLoadingProgress('正在生成回复…', requestScope.sessionId)
        },
      })
      let doneResult: unknown = null
      let awaitingAuthorization = false
      let sseError: string | null = null
      let failureExecution: ReturnType<typeof readChatExecution> = undefined
      let sseOutcomeUnknown = false
      let observationInterrupted = false
      let streamRunId = ''
      // 新一轮开始：清掉上一轮残留的执行链步骤，避免多轮累积。
      if (streamMessage) delete streamMessage.liveSteps
      const ttsShouldSpeakThisMessage = ttsEnabled.value
      let receivedDone = false
      let completeArtifacts = () => {}
      let doneApplied = false
      const applyDonePayload = () => {
        if (doneApplied || !isOwnerCurrent()) return
        doneApplied = true
        completeArtifacts()
        const donePayload = asPlannerPayload(doneResult)
        round.setStatus(conversationStatus(donePayload))
        consumeRoute(donePayload.route_metadata)
        const activeTurn = readActiveChatTurn(donePayload)
        if (activeTurn) {
          if (canUpdateStream() && streamMessage) {
            const extras = responseExtras(donePayload, false, streamMessages.value)
            applyStreamText(String(donePayload.response || activeChatTurnMessage(activeTurn)), extras)
            streamMessage.workflowAction = activeTurn.status
            if (activeTurn.taskId) streamMessage.recoveryTaskId = activeTurn.taskId
            delete streamMessage.streamingShell
          }
          if (round.isActive()) deps.observeActiveTurn?.(activeTurn)
          return
        }
        const finalText = collapseExactDuplicateReply(String(donePayload.response ?? streamPlain).trim() || streamPlain || '（无内容）')
        if (canUpdateStream()) {
          cancelStreamFrame()
          const extras = responseExtras(donePayload, donePayload.success === false, streamMessages.value) || {}
          if (!round.isActive()) {
            const card = parseApprovalCardFromPayload(donePayload)
            if (card) extras.approvalCard = card
          }
          applyStreamText(finalText, Object.keys(extras).length ? extras : undefined)
          observeModelOutcome(finalText, donePayload)
        }
        if (round.isActive() && ttsShouldSpeakThisMessage && ttsEnabled.value && donePayload.success !== false) {
          const clean = stripPlannerDisplayMarkers(finalText.replace(/（正在(?:将 Excel 导入数据库|生成 Word 文档|生成 Excel 工作簿|生成可下载文件)(?:[^（）]|（[^（）]*）)*）/g, '\n')).trim()
          if (clean && clean !== '（无内容）') queueVoice(clean)
        }
        if (!round.isActive()) return
        const wrap: ChatPlannerPayload = doneResult && typeof doneResult === 'object' ? donePayload : { success: true, response: finalText }
        syncTaskFromChatResponse(wrap, primaryText)
        syncStreamRun(wrap, true)
        consumeStateUpdates(wrap)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(wrap)
        attachTodoStepsToLastAiMessage(wrap)
        attachWorkflowTraceToLastAiMessage(wrap)
        attachApprovalCardToLastAiMessage(wrap)
        attachBusinessResultToLastAiMessage(wrap)
        if (streamMessage && !streamMessage.workflowAction) {
          const data = asRecord(wrap.data)
          streamMessage.workflowAction = String(wrap.execution_state || asRecord(data.data).status || data.status
            || data.action || (wrap.success === false ? 'failed' : 'completed'))
        }
        if (isUnfinishedResponse(wrap)) return
        if (wrap.task) {
          showTaskConfirm(wrap.task)
          emitAssistantPush({
            title: asString(asRecord(wrap.task).title || '新任务'),
            description: asString(asRecord(wrap.task).description || '收到一条任务，请处理'),
          })
        }
        if (!wrap.task && (wrap?.autoAction?.type === 'show_products_float' || wrap?.autoAction?.type === 'show_products')) {
          currentTask.value = null
        }
        if (wrap.autoAction) {
          handleAutoAction(wrap.autoAction, primaryText)
        }
        if (wrap.task) {
          maybeCloseAssistantFloatForShipmentTask(wrap.task, wrap.autoAction)
        }
      }
      try {
        const request = buildPlannerChatRequestPayload(primaryForStream, opts, requestScope)
        const body = request.body
        const submittedBody = { ...body, message: String(body.message || primaryForStream) }
        completeArtifacts = request.completeArtifacts
        streamTextFromAi = true
        handlePlannerEventRef = (ev: PlannerSseEvent) => {
          if (replaying) {
            // 续传只补齐正文与终态，不重放副作用。
            if (ev.type === 'done') {
              doneResult = ev.result
              receivedDone = true
            } else if (ev.type === 'error') {
              sseError = String(ev.message || '流式接口错误')
              sseOutcomeUnknown = Boolean(ev.requires_reconciliation || ev.execution_outcome === 'unknown')
            } else if (ev.type === 'requires_token') {
              awaitingAuthorization = true
            }
            return
          }
          if (!isOwnerCurrent()) { controller.abort(); return }
          const heartbeat = (ev.type === 'token' && ev.ephemeral === true)
            || (ev.type === 'tool_progress' && ev.phase === 'accepted')
          if ((ev.type === 'token' || ev.type === 'tool_progress' || ev.type === 'tool_call' || ev.type === 'model_activity' || ev.type === 'thinking') && !heartbeat) {
            // Legacy tools send a visible call marker, then can execute silently
            // for minutes. Run creation alone is not evidence of model progress.
            if (ev.type === 'model_activity' || ev.type === 'thinking' || ev.type === 'tool_call' || (ev.type === 'token' && ev.text.trim())
              || (ev.type === 'tool_progress' && ev.phase !== 'started')) {
              window.clearTimeout(stallTimer)
            }
            armDeadline()
          }
          if (ev.type === 'route_metadata') {
            consumeRoute(ev.route_metadata)
          } else if (ev.type === 'tool_progress') {
            streamRunId = ev.run_id || streamRunId
            const hint = String(ev.text || ev.label || '').trim()
            const hasLiveTool = streamMessage?.liveSteps?.some(step => step.state === 'running')
            if (canUpdateStream() && streamMessage && hint && !hasLiveTool) {
              streamMessage.waitingHint = hint
              // 执行链的流式占位步骤：轮到哪个动作就显示哪个，不等整轮结束。
              streamMessage.toolProgressLabel = hint
            }
            if (!hasLiveTool) setLoadingProgress(hint || '正在执行任务…', requestScope.sessionId)
            if (streamRunId) syncStreamRun({ run_id: streamRunId })
          } else if (ev.type === 'thinking') {
            const delta = String(ev.delta || '').trim()
            if (canUpdateStream() && streamMessage && delta) {
              const prev = String(streamMessage.thinkingSteps || '')
              streamMessage.thinkingSteps = prev ? `${prev}\n${delta}` : delta
              delete streamMessage.waitingHint
            }
          } else if (ev.type === 'tool_call') {
            // 工具 parts 由 AI SDK 组装；旁路只处理控制面与既有业务刷新。
            if (canUpdateStream() && streamMessage) {
              if (ev.phase !== 'finished') delete streamMessage.waitingHint
              if (ev.label) {
                streamMessage.toolProgressLabel = ev.label
                setLoadingProgress(ev.label, requestScope.sessionId)
              }
            }
            // 模板库已在页面上时不重新挂载，用窗口事件让它按服务端真实状态刷新。
            if (isDocumentTemplateChange(ev)) {
              window.dispatchEvent(
                new CustomEvent('xcagi:templates-updated', {
                  detail: { source: 'chat', action: String(ev.action || '') },
                }),
              )
            }
          } else if (ev.type === 'token') {
            if (ev.ephemeral) {
              const hint = String(ev.text || '').replace(/\s+/g, ' ').trim()
              if (canUpdateStream() && streamMessage && hint) streamMessage.waitingHint = hint
              setLoadingProgress(hint || '仍在等待模型响应…', requestScope.sessionId)
            } else if (canUpdateStream() && streamMessage) {
              delete streamMessage.waitingHint
            }
          } else if (ev.type === 'done') {
            doneResult = ev.result
            receivedDone = true
          } else if (ev.type === 'error') {
            consumeRoute(ev.route_metadata)
            streamRunId = ev.run_id || streamRunId
            if (streamRunId) syncStreamRun({ run_id: streamRunId })
            sseOutcomeUnknown = Boolean(ev.requires_reconciliation || ev.execution_outcome === 'unknown')
            observationInterrupted = ['REPLAY_UNAVAILABLE', 'STREAM_INTERRUPTED'].includes(ev.code || '')
            sseError = String(ev.message || '流式接口错误')
            failureExecution = readChatExecution(ev.result || ev) || failureExecution
          } else if (ev.type === 'requires_token') {
            awaitingAuthorization = true
            streamRunId = ev.run_id || streamRunId
            const tokenName = ev.token_name || ''
            const tokenDesc = ev.token_description || ''
            streamTextFromAi = false
            streamPlain += `\n[需要授权：${tokenDesc || tokenName || '授权信息'}]\n`
            if (canUpdateStream()) {
              cancelStreamFrame()
              applyStreamText(streamPlain)
            }
          }
        }
        plannerEventHandler = handlePlannerEventRef
        const roundResult = await aiChatRound.send(submittedBody, controller.signal)
        plannerEventHandler = null
        streamTextFromAi = false
        if (!isOwnerCurrent()) return
        if (!awaitingAuthorization && roundResult.text) streamPlain = roundResult.text
        if (sseError) throw new Error(sseError)
        if (roundResult.error && !receivedDone) throw roundResult.error
        // 请求已成功送出并拿到流：本轮工件 id 用毕即清，避免串到下一轮。
        completeArtifacts()
        if (awaitingAuthorization && plannerExecutionState(doneResult) !== 'unknown') {
          round.setStatus('waiting')
          if (canUpdateStream() && streamMessage) {
            streamMessage.workflowAction = 'waiting_auth'
            delete streamMessage.streamingShell
          }
          if (streamRunId) syncStreamRun({ run_id: streamRunId })
          return
        }
        if (!receivedDone) throw new IncompletePlannerSseError()
        applyDonePayload()
      } catch (err: unknown) {
        plannerEventHandler = null
        streamTextFromAi = false
        cancelStreamFrame()
        if (Number(asRecord(err).status) === 401 && round.isActive()) void probeEnterpriseSession()
        const timedOut = asRecord(err).name === 'AbortError'
        const stallText = `请求超时（>${Math.floor(CHAT_STREAM_STALL_MS / 1000)}s）。本轮尚未收到完成回执。`
        const errText =
          timedOut
            ? streamRunId
              ? '对话连接已超时，任务可能仍在执行。请到任务工作区核对结果，勿重复提交。'
              : streamState.stalled
                ? stallText
                : `请求超时（>${Math.floor(timeoutMsS / 1000)}s）或已中断`
            : errorMessage(err, '流式对话失败')
        const dropped = observationInterrupted || !sseError && (timedOut || err instanceof IncompletePlannerSseError
          || [408, 502, 503, 504].includes(Number(asRecord(err).status))
          || /failed to fetch|network\s*error|econnrefused|econnreset|err_connection|socket hang up|load failed|网络中断|连接中断/i.test(errText))
        if (dropped && canUpdateStream() && requestScope.turnId && !requestScope.signal?.aborted && handlePlannerEventRef) {
          // 只读回放按原 turn 取事件，提交端点不会再次收到原指令。
          let resumed = false
          replaying = true
          sseError = null
          plannerEventHandler = handlePlannerEventRef
          streamTextFromAi = true
          const replayController = new AbortController()
          const abortReplay = () => replayController.abort()
          requestScope.signal?.addEventListener('abort', abortReplay, { once: true })
          const replayTimer = window.setTimeout(() => replayController.abort(), 20000)
          try {
            const result = await aiChatRound.resume(requestScope.turnId, replayController.signal)
            if (result.text) streamPlain = result.text
            // The replayed terminal receipt is authoritative even if the socket closes afterward.
            resumed = !sseError && receivedDone
              && (!awaitingAuthorization || plannerExecutionState(doneResult) === 'unknown') && isOwnerCurrent()
          } catch {
            resumed = false
          } finally {
            window.clearTimeout(replayTimer)
            requestScope.signal?.removeEventListener('abort', abortReplay)
            replaying = false
            streamTextFromAi = false
            plannerEventHandler = null
          }
          if (resumed) {
            applyDonePayload()
            return
          }
        }

        if (dropped && canUpdateStream()) {
          const presentation = await readDroppedRoundOutcome(
            String(requestScope.sessionId || ''), requestScope.turnId, streamRunId, canUpdateStream,
          )
          if (!canUpdateStream()) return
          round.setStatus(presentation.status === 'completed' ? 'ready' : presentation.status === 'failed' ? 'error'
            : presentation.status === 'interrupted' ? 'stopped' : presentation.status === 'waiting_approval' ? 'waiting' : 'review')
          const pendingText = err instanceof IncompletePlannerSseError
            ? `${streamPlain.trim()}${streamPlain.trim() ? '\n\n' : ''}[回复未完成] `
            : timedOut ? `${errText}\n` : ''
          const shown = `${presentation.status === 'unknown' && !presentation.activeTurn ? pendingText : ''}${presentation.text}`
          applyStreamText(shown, failureExecution ? { execution: failureExecution } : undefined)
          if (presentation.status === 'completed' || presentation.status === 'failed') {
            observeModelOutcome(shown, failureExecution ? { execution: failureExecution } : undefined)
          }
          if (streamMessage) {
            streamMessage.workflowAction = presentation.workflowAction
            delete streamMessage.streamingShell
            delete streamMessage.waitingHint
          }
          if (presentation.activeTurn && round.isActive()) deps.observeActiveTurn?.(presentation.activeTurn)
          // 本地流被重置时后端往往仍在完成并落库：稍后回读一次会话，
          // 若能拿到本轮回执就把失败气泡替换成真实回复。
          if (presentation.status === 'unknown' && !presentation.activeTurn) {
            window.setTimeout(() => {
              void (async () => {
                try {
                  const convo = await chatApi.getConversation(String(requestScope.sessionId || ''), { turn_id: requestScope.turnId })
                  const late = droppedRoundFromHistory(convo, String(requestScope.turnId || ''))
                  if (late.activeTurn && round.isActive()) deps.observeActiveTurn?.(late.activeTurn)
                  if (late.status !== 'completed' || !late.text || !round.isActive()) return
                  const row = messages.value.find(message => message === streamMessage || (
                    message.role === 'ai' && message.turnId && message.turnId === requestScope.turnId))
                  if (!row || row.role !== 'ai' || row.workflowAction === 'completed') return
                  applyPlainTextToMessageIndex(messages.value.indexOf(row), late.text)
                  row.workflowAction = 'completed'
                  round.setStatus('ready')
                } catch {
                  /* 保留已展示的失败回执 */
                }
              })()
            }, 1500)
          }
        } else if (canUpdateStream()) {
          round.setStatus(sseOutcomeUnknown ? 'review' : 'error')
          const transport = /failed to fetch|networkerror|econnrefused|offline/i.test(errText) ? classifyRawError(errText) : null
          const visibleError = err instanceof IncompletePlannerSseError
            ? `${streamPlain.trim()}${streamPlain.trim() ? '\n\n' : ''}[回复未完成] ${errText}`
            : transport || (timedOut && streamRunId ? errText : `处理失败：${errText}`)
          applyStreamText(visibleError, failureExecution ? { execution: failureExecution } : undefined)
          observeModelOutcome(visibleError, failureExecution ? { execution: failureExecution } : undefined)
          if (streamMessage) {
            streamMessage.workflowAction = sseOutcomeUnknown ? 'unknown' : 'failed'
            delete streamMessage.streamingShell
            delete streamMessage.waitingHint
          }
        }
        if (streamRunId) syncStreamRun({ run_id: streamRunId })
      } finally {
        plannerEventHandler = null
        streamTextFromAi = false
        cancelStreamFrame()
        if (streamMessage) streamMessage.streamStatus = streamMessage.workflowAction === 'failed' ? 'error' : 'ready'
        if (canUpdateStream() && streamMessage) delete streamMessage.waitingHint
        if (!doneApplied && canUpdateStream() && streamMessage?.streamingShell) {
          const leftover = streamPlain.trim()
          const unfinished = leftover
            ? `${leftover}\n\n[回复未完成] 本轮回复已结束，但没有完成回执。请重试。`
            : '处理失败：本轮回复已结束，但没有收到正文。请重试。'
          applyStreamText(unfinished, failureExecution ? { execution: failureExecution } : undefined)
          observeModelOutcome(unfinished, failureExecution ? { execution: failureExecution } : undefined)
          streamMessage.workflowAction = 'failed'
          round.setStatus('error')
          delete streamMessage.streamingShell
          delete streamMessage.waitingHint
        }
        if (canUpdateStream()) {
          if (conversation) conversation.persist()
          else deps.flushMessagesCache?.()
        }
        conversation?.release()
        round.setStreaming(false)
        window.clearTimeout(stallTimer)
        window.clearTimeout(killTimer)
        requestScope.signal?.removeEventListener('abort', abort)
        round.setLoading(false)
        if (isOwnerCurrent()) stopLoadingProgress(requestScope.sessionId)
      }
      return
    }

    round.setLoading(true)
    round.setStreaming(false)
    setLoadingProgress('正在理解你的问题...', requestScope.sessionId)
    let data: ChatPlannerPayload = {}
    try {
      // 不再在发聊天前阻塞等待 /api/ai/test（最多 3s），否则「慢」往往来自这里而非 AI
      setLoadingProgress(
        remoteMessages.length > 1 ? `正在批量处理 ${remoteMessages.length} 条消息...` : '正在整理上下文...',
        requestScope.sessionId,
      )
      startWaitProgressTimer(requestScope.sessionId)
      const base = resolveChatTimeoutMs(primaryText)
      const timeoutMs = Math.min(120000, remoteMessages.length <= 1 ? base : base * remoteMessages.length)
      let rawData: unknown
      if (remoteMessages.length === 1) {
        rawData = await requestChatByModeWithTimeout(remoteMessages[0], timeoutMs, opts, requestScope)
      } else {
        rawData = await requestChatByModeBatchWithTimeout(remoteMessages, timeoutMs, requestScope)
      }
      if (!isOwnerCurrent()) return
      data = asPlannerPayload(rawData)
      const head = remoteMessages.length === 1 ? data : asPlannerPayload(data.results?.[0])
      const headData = asRecord(head.data)
      setLoadingProgress('已收到响应，正在解析执行计划...', requestScope.sessionId)
      if (headData.action === 'workflow_confirmation_required') {
        setLoadingProgress('已生成计划，等待你确认执行...', requestScope.sessionId)
      } else if (headData.action === 'workflow_done') {
        setLoadingProgress('执行完成，正在整理结果...', requestScope.sessionId)
      } else if (headData.action === 'workflow_failed') {
        setLoadingProgress('执行失败，正在整理错误信息...', requestScope.sessionId)
      }
    } catch (err: unknown) {
      const errorData = asRecord(asRecord(err).data)
      const route = readChatModelRoute(errorData.route_metadata || asRecord(errorData.detail).route_metadata)
      data = {
        success: false,
        message: errorMessage(err, '请求失败'),
        ...(route ? { route_metadata: route } : {}),
      }
      const status = Number(asRecord(err).status)
      if (requestScope.turnId && isOwnerCurrent() && (!Number.isFinite(status) || status === 0 || status === 408 || status >= 500)) {
        const original = await readDroppedRoundOutcome(String(requestScope.sessionId || ''), requestScope.turnId, '', isOwnerCurrent)
        if (!isOwnerCurrent()) return
        data = { ...data, success: original.status === 'completed', execution_state: original.status,
          response: original.text, message: original.text,
          ...(original.activeTurn ? { active_turn: {
            turn_id: original.activeTurn.turnId, run_id: original.activeTurn.runId,
            task_id: original.activeTurn.taskId, status: original.activeTurn.status, message: original.activeTurn.message,
          } } : {}) }
      }
    } finally {
      round.setStreaming(false)
      round.setLoading(false)
      if (isOwnerCurrent()) stopLoadingProgress(requestScope.sessionId)
    }

    if (!isOwnerCurrent()) return
    const results = data.batch && Array.isArray(data.results) ? data.results.map(asPlannerPayload) : [data]
    const statuses = results.map(conversationStatus)
    round.setStatus(statuses.includes('review') ? 'review' : statuses.includes('error') ? 'error'
      : statuses.includes('waiting') ? 'waiting' : statuses.includes('stopped') ? 'stopped' : data.success === false ? 'error' : 'ready')
    if (!round.isActive()) return persistDetachedPlannerResult(data, requestScope.sessionId, saveMessage)
    const receipt = data.batch && Array.isArray(data.results) ? data.results[data.results.length - 1] : data
    recordChatModelRoute(requestScope.sessionId, receipt?.route_metadata, identity)
    const showUnfinished = async (part: ChatPlannerPayload) => {
      await addRoundMessage(String(part.response || part.message || '原任务尚未完成，请在任务工作区核对进度。'), responseExtras(part))
      if (!round.isActive()) return
      syncTaskFromChatResponse(part, primaryText)
      await syncAgentRunFromPayload(part, primaryText, isOwnerCurrent)
      if (!round.isActive()) return
      attachAgentRunTraceToLastAiMessage(extractAgentRunId(part))
      attachApprovalCardToLastAiMessage(part)
      attachBusinessResultToLastAiMessage(part)
      const activeTurn = readActiveChatTurn(part)
      if (activeTurn) deps.observeActiveTurn?.(activeTurn)
    }
    if (data.batch && Array.isArray(data.results)) {
      if (data.success || results.some(isUnfinishedResponse) || results.some(part => runtimeContinuationFromPayload(part))) {
        for (const part of results) {
          if (isUnfinishedResponse(part)) {
            await showUnfinished(part)
          } else if (part && part.success) {
            await addRoundMessage(part.response || '', responseExtras(part))
            attachBusinessResultToLastAiMessage(part)
            if (!round.isActive()) return
            syncTaskFromChatResponse(part, primaryText)
            await syncAgentRunFromPayload(part, primaryText, isOwnerCurrent)
            if (!round.isActive()) return
            attachAgentRunTraceToLastAiMessage(extractAgentRunId(part))
          } else {
            await addRoundMessage('处理失败: ' + (part.message || '未知错误'), responseExtras(part, true))
            attachBusinessResultToLastAiMessage(part)
            if (requiresTurnReconciliation(part)) {
              await syncAgentRunFromPayload(part, primaryText, isOwnerCurrent)
              if (!round.isActive()) return
              attachAgentRunTraceToLastAiMessage(extractAgentRunId(part))
            }
          }
        }
        attachContextSummaryToLastAiMessage()
        const lastOk = [...results].reverse().find((p) => p && (p.success || isRuntimeWaiting(p)))
        if (lastOk) {
          consumeStateUpdates(lastOk)
          attachThinkingStepsToLastAiMessage(lastOk)
          attachTodoStepsToLastAiMessage(lastOk)
          attachWorkflowTraceToLastAiMessage(lastOk)
          attachApprovalCardToLastAiMessage(lastOk)
        }
        if (results.some(isUnfinishedResponse)) return
        const lastTask = [...results].reverse().find((p) => p.task)
        if (lastTask?.task) {
          showTaskConfirm(lastTask.task)
          const taskRow = asRecord(lastTask.task)
          emitAssistantPush({
            title: taskRow.title || '新任务',
            description: taskRow.description || '收到一条任务，请处理',
          })
        }
        const lastFloat = [...results]
          .reverse()
          .find((p) => p.autoAction?.type === 'show_products_float' || p.autoAction?.type === 'show_products')
        if (!lastTask?.task && lastFloat?.autoAction) {
          currentTask.value = null
        }
        const lastAction = [...results].reverse().find((p) => p.autoAction)
        if (lastAction?.autoAction) {
          handleAutoAction(lastAction.autoAction, remoteMessages[remoteMessages.length - 1] || '')
        }
        if (lastTask?.task) {
          maybeCloseAssistantFloatForShipmentTask(lastTask.task, lastAction?.autoAction)
        }
      } else {
        await addRoundMessage('处理失败: ' + (data.message || '批量请求失败'), responseExtras(data, true))
        attachBusinessResultToLastAiMessage(data)
      }
      return
    }

    if (isUnfinishedResponse(data)) {
      await showUnfinished(data)
      return
    }

    if (data.success) {
      await addRoundMessage(data.response || '', responseExtras(data))
      observeModelOutcome(String(data.response || data.message || ''), data)
      if (!round.isActive()) return
      syncTaskFromChatResponse(data, primaryText)
      await syncAgentRunFromPayload(data, primaryText, isOwnerCurrent)
      if (!round.isActive()) return
      attachAgentRunTraceToLastAiMessage(extractAgentRunId(data))
      consumeStateUpdates(data)
      attachContextSummaryToLastAiMessage()
      attachThinkingStepsToLastAiMessage(data)
      attachTodoStepsToLastAiMessage(data)
      attachWorkflowTraceToLastAiMessage(data)
      attachApprovalCardToLastAiMessage(data)
      attachBusinessResultToLastAiMessage(data)
      if (requiresTurnReconciliation(data)) return

      if (data.task) {
        showTaskConfirm(data.task)
        const taskRow = asRecord(data.task)
        emitAssistantPush({
          title: taskRow.title || '新任务',
          description: taskRow.description || '收到一条任务，请处理',
        })
      }
      if (!data.task && (data?.autoAction?.type === 'show_products_float' || data?.autoAction?.type === 'show_products')) {
        currentTask.value = null
      }

      if (data.autoAction) {
        handleAutoAction(data.autoAction, primaryText)
      }
      if (data.task) {
        maybeCloseAssistantFloatForShipmentTask(data.task, data.autoAction)
      }
    } else {
      const failedText = '处理失败: ' + (data.message || '未知错误')
      await addRoundMessage(failedText, responseExtras(data, true))
      attachBusinessResultToLastAiMessage(data)
      observeModelOutcome(failedText, data)
      if (requiresTurnReconciliation(data)) {
        await syncAgentRunFromPayload(data, primaryText, isOwnerCurrent)
        if (!round.isActive()) return
        attachAgentRunTraceToLastAiMessage(extractAgentRunId(data))
      }
    }
  }

  return {
    consumeStateUpdates,
    maybePrefetchProductAssistantFloat,
    executeRemoteChatRound,
  }
}
