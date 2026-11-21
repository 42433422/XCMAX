import { computed, getCurrentInstance, onActivated, onBeforeUnmount, onDeactivated, ref, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import chatApi from '../api/chat'
import type { ChatPlannerPayload, ChatRequest } from '@/types/chat'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'
import { isOfficeEltToolMessage } from '@/domain/optionalTemplateSelection'
import { isWorkflowControlMessage } from '@/utils/chatSseStream'
import { captureChatArtifacts } from '@/utils/chatArtifactContext'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { pendingRuntimeRunId } from '@/utils/chatRuntimeContinuation'
import { useApprovalMode } from './useApprovalMode'
export type ChatRequestScope = {
  signal?: AbortSignal
  isCurrent?: () => boolean
  identity?: string
  sessionId: string
  messages: ChatMessage[]
  turnId?: string
  taskId?: string
}
export type PlannerChatOptions = {
  expectedWorkflowPlanId?: string
  retryOf?: string
  idempotencyKey?: string
  destructiveConfirmed?: boolean
}

export interface UseChatRequestDeps {
  messages: Ref<ChatMessage[]>
  sessionId?: Ref<string>
  lastRequestContextSummary: Ref<string>
  injectExcelContextPayload: (ctx: Record<string, unknown>, parts: string[]) => boolean
  consumeMultimodalIntoPlannerContext: (ctx: Record<string, unknown>, parts: string[]) => void
  captureArtifacts?: typeof captureChatArtifacts
}

export function useChatRequest(deps: UseChatRequestDeps) {
  const {
    messages,
    sessionId,
    lastRequestContextSummary,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    captureArtifacts = captureChatArtifacts,
  } = deps

  const progressBySession = ref<Record<string, string>>({})
  const waitingSince = new Map<string, number>()
  let waitProgressTicker: number | undefined
  let chatPageActive = true
  const { state: approvalModeState } = useApprovalMode()
  const progressKey = (target?: string) => String(target || sessionId?.value || '').trim() || 'default'
  const loadingProgressText = computed(() => progressBySession.value[progressKey()] || '处理中...')
  const queuedBatches = new Map<string, { messages: string[]; timer: number }>()

  function runtimeContext(session: string, scope?: ChatRequestScope): Record<string, unknown> {
    if (scope?.isCurrent?.() === false || (scope?.identity && scope.identity !== resolveChatIdentity())) return {}
    const history = scope?.messages || (session === String(sessionId?.value || '').trim() ? messages.value : [])
    const runId = pendingRuntimeRunId(history, session)
    return runId ? { agent_runtime_run_id: runId } : {}
  }

  // 一个 turn 的首次提交决定附件；同 turn 重连和显式 retry 均复用快照。
  const artifactBatches = new Map<string, ReturnType<typeof captureChatArtifacts>>()
  function artifactsForTurn(session: string, turn: string, retryOf?: string, scope?: ChatRequestScope) {
    const identity = scope?.identity || ''
    // 按仍在界面历史中的 turn 保留，不能按发给模型的 40 条窗口淘汰可重试消息。
    const history = [...(scope?.messages || []), ...(sessionId?.value === session ? messages.value : [])]
    const visibleTurns = new Set(history.map(message => message.turnId).filter(Boolean))
    if (visibleTurns.size) {
      visibleTurns.add(turn)
      if (retryOf) visibleTurns.add(retryOf)
      for (const key of artifactBatches.keys()) {
        const [owner, sid, previousTurn] = JSON.parse(key) as [string, string, string]
        if (owner === identity && sid === session && !visibleTurns.has(previousTurn)) artifactBatches.delete(key)
      }
    }
    const key = JSON.stringify([identity, session, retryOf || turn])
    let batch = artifactBatches.get(key)
    if (!batch) {
      // 找不到原 turn 时不能误拿输入框中新选择的文件。
      batch = retryOf || progressKey() !== progressKey(session)
        ? { ids: [], complete: () => {} } : captureArtifacts()
      artifactBatches.set(key, batch)
    }
    artifactBatches.set(JSON.stringify([identity, session, turn]), batch)
    return batch
  }

  function buildPlannerChatRequestPayload(
    message: string,
    plannerOpts?: PlannerChatOptions,
    scope?: ChatRequestScope,
  ): {
    body: Record<string, unknown>
    completeArtifacts: () => void
  } {
    const user_id = resolveChatUserId(scope)
    const compactHistory = (scope?.messages || messages.value || []).slice(-40).map((m) => ({
      role: m.role,
      content: plainTextFromChatHtml(m.content).slice(0, 4000),
    }))
    const scopedSessionId = String(scope?.sessionId || sessionId?.value || '').trim()
    const turnId = String(scope?.turnId || '').trim() || createBusinessHarnessId('turn')
    const taskId = String(scope?.taskId || '').trim() || createBusinessHarnessId('task')
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory,
      conversation_id: scopedSessionId,
      session_id: scopedSessionId,
      turn_id: turnId,
      task_id: taskId,
      ...(!plannerOpts?.expectedWorkflowPlanId ? runtimeContext(scopedSessionId, scope) : {}),
      task_title: String(message || '')
        .trim()
        .slice(0, 80),
      ...(approvalModeState.enabled && approvalModeState.mode === 'auto'
        ? { chat_approval_mode: 'auto' }
        : {}),
      ...(plannerOpts?.expectedWorkflowPlanId ? { expected_workflow_plan_id: plannerOpts.expectedWorkflowPlanId } : {}),
      ...(plannerOpts?.retryOf ? { retry_of: plannerOpts.retryOf, idempotency_key: plannerOpts.idempotencyKey || plannerOpts.retryOf } : {}),
      ...(plannerOpts?.destructiveConfirmed ? { destructive_confirmed: true, idempotency_key: plannerOpts.idempotencyKey || turnId } : {}),
    }
    // industry 由后端根据 session account_kind 自动派生（单一真相源），前端不传
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const isActive = progressKey() === progressKey(scopedSessionId)
    const includeDraft = isActive && !plannerOpts?.expectedWorkflowPlanId
    const hasExcelContext = includeDraft && injectExcelContextPayload(contextPayload, contextParts)
    if (includeDraft) consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    // 选文件时登记的附件工件：只认本轮上传，失败重试沿用同一批。
    const artifactBatch = artifactsForTurn(scopedSessionId, turnId, plannerOpts?.retryOf, scope)
    const artifactIds = artifactBatch.ids
    if (artifactIds.length) {
      contextPayload.artifact_ids = artifactIds
      contextParts.push(`后端工件 ${artifactIds.length} 个`)
    }
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    if (isActive) lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    return {
      completeArtifacts: artifactBatch.complete,
      body: {
        message,
        source: 'normal',
        mode: 'basic',
        user_id,
        context: contextPayload,
      },
    }
  }

  function resolveChatUserId(scope?: ChatRequestScope): string {
    const sid = String(scope?.sessionId || sessionId?.value || '').trim() || 'default'
    return `web_normal_${sid}`
  }

  async function requestChatByMode(
    message: string,
    fetchOptions: RequestInit = {},
    plannerOpts?: PlannerChatOptions,
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const { body, completeArtifacts } = buildPlannerChatRequestPayload(message, plannerOpts, scope)
    const reqOpts = { signal: fetchOptions.signal }
    const payload = (await chatApi.sendUnifiedChat(body as unknown as ChatRequest, reqOpts)) as unknown as ChatPlannerPayload
    completeArtifacts()
    return payload
  }

  /** 与单条请求相同的 context / user_id，用于 unified_chat/batch */
  async function requestChatByModeBatch(
    batchTexts: string[],
    fetchOptions: RequestInit = {},
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const user_id = resolveChatUserId(scope)
    const compactHistory = (scope?.messages || messages.value || []).slice(-40).map((m) => ({
      role: m.role,
      content: plainTextFromChatHtml(m.content).slice(0, 4000),
    }))
    const scopedSessionId = String(scope?.sessionId || sessionId?.value || '').trim()
    const turnId = String(scope?.turnId || '').trim() || createBusinessHarnessId('turn')
    const taskId = String(scope?.taskId || '').trim() || createBusinessHarnessId('task')
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory,
      conversation_id: scopedSessionId,
      session_id: scopedSessionId,
      turn_id: turnId,
      task_id: taskId,
      ...runtimeContext(scopedSessionId, scope),
      task_title: String(batchTexts[0] || '')
        .trim()
        .slice(0, 80),
    }
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const hasExcelContext = injectExcelContextPayload(contextPayload, contextParts)
    consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    const artifactBatch = artifactsForTurn(scopedSessionId, turnId, undefined, scope)
    const artifactIds = artifactBatch.ids
    if (artifactIds.length) contextPayload.artifact_ids = artifactIds
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    const reqOpts = { signal: fetchOptions.signal }
    const batchBody = {
      messages: batchTexts,
      user_id,
      context: contextPayload,
      source: 'normal' as const,
      mode: 'basic' as const,
    }
    const payload = (await chatApi.sendUnifiedChatBatch(batchBody as ChatRequest & { messages: string[] }, reqOpts)) as unknown as ChatPlannerPayload
    artifactBatch.complete()
    return payload
  }

  function getChatBatchDebounceMs(): number {
    const v = import.meta.env.VITE_CHAT_BATCH_MS
    // 默认 0：单条消息立即发；需要合并连发时可设 VITE_CHAT_BATCH_MS
    if (v === undefined || v === '') return 0
    const n = Number(v)
    return Number.isFinite(n) && n >= 0 ? n : 0
  }

  function setLoadingProgress(step: string, targetSessionId?: string) {
    const key = progressKey(targetSessionId)
    progressBySession.value = {
      ...progressBySession.value,
      [key]: String(step || '').trim() || '处理中...',
    }
  }

  function updateWaitProgress() {
    const now = Date.now()
    for (const [key, startedAt] of waitingSince) {
      const elapsedSec = Math.floor((now - startedAt) / 1000)
      if (elapsedSec < 1) continue
      const hint = elapsedSec >= 8 ? ' 等待较久，可点击“停止回复”；操作可能仍在执行，请先到任务面板核对，勿重复提交。网络异常时请恢复连接后重试（故障编号：CHAT_WAIT）。' : ''
      setLoadingProgress(`已发送请求，正在等待服务端响应（${elapsedSec}s）...${hint}`, key)
    }
  }

  function syncWaitProgressTicker() {
    if (chatPageActive && waitingSince.size) {
      waitProgressTicker ??= window.setInterval(updateWaitProgress, 1000)
    } else {
      window.clearInterval(waitProgressTicker)
      waitProgressTicker = undefined
    }
  }

  function startWaitProgressTimer(targetSessionId?: string) {
    const startedAt = Date.now()
    waitingSince.set(progressKey(targetSessionId), startedAt)
    syncWaitProgressTicker()
    return startedAt
  }

  function stopLoadingProgress(targetSessionId?: string) {
    const key = progressKey(targetSessionId)
    waitingSince.delete(key)
    syncWaitProgressTicker()
    setLoadingProgress('处理中...', key)
  }

  function pauseWaitProgress(): void {
    chatPageActive = false
    syncWaitProgressTicker()
  }
  if (getCurrentInstance()) {
    onDeactivated(pauseWaitProgress)
    onActivated(() => {
      chatPageActive = true
      updateWaitProgress()
      syncWaitProgressTicker()
    })
    onBeforeUnmount(pauseWaitProgress)
  }

  async function withRequestTimeout<T>(request: (signal: AbortSignal) => Promise<T>, timeoutMs: number, signal?: AbortSignal): Promise<T> {
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    let timeoutId: number | undefined
    const stopped = new Promise<never>((_, reject) => {
      const rejectAbort = () => reject(new DOMException('请求已中断', 'AbortError'))
      controller.signal.addEventListener('abort', rejectAbort, { once: true })
      if (controller.signal.aborted) rejectAbort()
      timeoutId = window.setTimeout(() => {
        reject(new Error(`请求超时（>${Math.floor(timeoutMs / 1000)}s），请检查连接，勿重复提交可能已执行的任务`))
        controller.abort()
      }, timeoutMs)
    })
    try {
      if (controller.signal.aborted) return await stopped
      return await Promise.race([request(controller.signal), stopped])
    } finally {
      window.clearTimeout(timeoutId)
      signal?.removeEventListener('abort', abort)
    }
  }

  function requestChatByModeWithTimeout(
    message: string,
    timeoutMs = 90_000,
    plannerOpts?: PlannerChatOptions,
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    if (isOfficeEltToolMessage(message)) return requestChatByMode(message, {}, plannerOpts, scope)
    return withRequestTimeout(signal => requestChatByMode(message, { signal }, plannerOpts, scope), timeoutMs, scope?.signal)
  }

  function requestChatByModeBatchWithTimeout(batchTexts: string[], timeoutMs = 90_000, scope?: ChatRequestScope): Promise<ChatPlannerPayload> {
    if (batchTexts.some(isOfficeEltToolMessage)) return requestChatByModeBatch(batchTexts, {}, scope)
    return withRequestTimeout(signal => requestChatByModeBatch(batchTexts, { signal }, scope), timeoutMs, scope?.signal)
  }

  function cancelPendingChatBatch(targetSessionId?: string) {
    const keys = targetSessionId ? [progressKey(targetSessionId)] : [...queuedBatches.keys()]
    for (const key of keys) {
      window.clearTimeout(queuedBatches.get(key)?.timer)
      queuedBatches.delete(key)
    }
  }

  function resolveChatTimeoutMs(message: string): number {
    if (isWorkflowControlMessage(message)) return 180_000
    const text = String(message || '').trim()
    const isComplexTask = /(导入|入库|数据库|工作流|执行|创建|新增|批量|excel|上传|加入数据库)/i.test(text)
    return isComplexTask ? 180_000 : 90_000
  }

  function enqueueChatBatchMessage(message: string, debounceMs: number, onFlush: (messages: string[]) => void, targetSessionId?: string): void {
    const key = progressKey(targetSessionId)
    const pending = queuedBatches.get(key)
    if (pending) window.clearTimeout(pending.timer)
    const messages = [...(pending?.messages || []), message]
    const timer = window.setTimeout(() => {
      queuedBatches.delete(key)
      onFlush(messages)
    }, debounceMs)
    queuedBatches.set(key, { messages, timer })
  }

  return {
    loadingProgressText,
    get chatBatchQueue() { return queuedBatches.get(progressKey())?.messages || [] },
    cancelPendingChatBatch,
    enqueueChatBatchMessage,
    buildPlannerChatRequestPayload,
    requestChatByMode,
    requestChatByModeBatch,
    getChatBatchDebounceMs,
    setLoadingProgress,
    startWaitProgressTimer,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  }
}
