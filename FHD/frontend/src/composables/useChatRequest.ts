import { computed, ref, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import chatApi from '../api/chat'
import type { ChatPlannerPayload, ChatRequest } from '@/types/chat'
export type ChatRequestScope = { sessionId: string; messages: ChatMessage[] }
export interface UseChatRequestDeps {
  messages: Ref<ChatMessage[]>
  sessionId?: Ref<string>
  lastRequestContextSummary: Ref<string>
  plannerWriteUnlockResumeDraft: Ref<string>
  resolveChatDbTokensForPayload: () => { db_read_token?: string; db_write_token?: string }
  injectExcelContextPayload: (ctx: Record<string, unknown>, parts: string[]) => boolean
  consumeMultimodalIntoPlannerContext: (ctx: Record<string, unknown>, parts: string[]) => void
}

export function useChatRequest(deps: UseChatRequestDeps) {
  const {
    messages,
    sessionId,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveChatDbTokensForPayload,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  } = deps

  const progressBySession = ref<Record<string, string>>({})
  const waitProgressTickers = new Map<string, number>()
  const progressKey = (target?: string) => String(target || sessionId?.value || '').trim() || 'default'
  const loadingProgressText = computed(() => progressBySession.value[progressKey()] || '处理中...')
  let chatBatchTimer: number | null = null
  const chatBatchQueue: string[] = []

  function buildPlannerChatRequestPayload(
    message: string,
    plannerOpts?: { fromWriteUnlock?: boolean },
    scope?: ChatRequestScope,
  ): {
    body: Record<string, unknown>
  } {
    const user_id = resolveChatUserId(scope)
    const compactHistory = (scope?.messages || messages.value || []).slice(-6).map((m) => ({
      role: m.role,
      content: String(m.content || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<[^>]*>/g, '')
        .slice(0, 500),
    }))
    const scopedSessionId = String(scope?.sessionId || sessionId?.value || '').trim()
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory,
      conversation_id: scopedSessionId,
      session_id: scopedSessionId,
      task_id: scopedSessionId,
      task_title: String(message || '')
        .trim()
        .slice(0, 80),
    }
    // industry 由后端根据 session account_kind 自动派生（单一真相源），前端不传
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const hasExcelContext = injectExcelContextPayload(contextPayload, contextParts)
    consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    if (plannerOpts?.fromWriteUnlock) {
      contextPayload.chat_db_write_authorized = true
      const draftRaw = plannerWriteUnlockResumeDraft.value.trim()
      plannerWriteUnlockResumeDraft.value = ''
      const cap = 9000
      const bodyDraft = draftRaw.length > cap ? `${draftRaw.slice(0, cap)}\n…(已截断)` : draftRaw
      contextPayload.db_write_stream_resume = bodyDraft
        ? `【上一轮流式可见输出节选】\n${bodyDraft}\n\n【续跑要求】用户已在弹窗完成二级写入授权；本请求 JSON 已附带 db_write_token。请直接调用 import_excel_to_database 完成写入（file_path、sheet_name、header_row 与 excel_analysis / 运行时一致）。除非明显缺字段，不要再次整本重跑 excel_analysis 或重复开场白。`
        : '【续跑要求】用户已确认二级写入令牌；本请求已附带 db_write_token。请直接调用 import_excel_to_database，避免重复开场白与无谓的 excel_analysis。'
    }
    return {
      body: {
        message,
        source: 'normal',
        mode: 'basic',
        user_id,
        context: contextPayload,
        ...resolveChatDbTokensForPayload(),
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
    plannerOpts?: { fromWriteUnlock?: boolean },
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const { body } = buildPlannerChatRequestPayload(message, plannerOpts, scope)
    const reqOpts = { signal: fetchOptions.signal }
    return (await chatApi.sendUnifiedChat(body as unknown as ChatRequest, reqOpts)) as unknown as ChatPlannerPayload
  }

  /** 与单条请求相同的 context / user_id，用于 unified_chat/batch */
  async function requestChatByModeBatch(
    batchTexts: string[],
    fetchOptions: RequestInit = {},
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const user_id = resolveChatUserId(scope)
    const compactHistory = (scope?.messages || messages.value || []).slice(-6).map((m) => ({
      role: m.role,
      content: String(m.content || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<[^>]*>/g, '')
        .slice(0, 500),
    }))
    const scopedSessionId = String(scope?.sessionId || sessionId?.value || '').trim()
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory,
      conversation_id: scopedSessionId,
      session_id: scopedSessionId,
      task_id: scopedSessionId,
      task_title: String(batchTexts[0] || '')
        .trim()
        .slice(0, 80),
    }
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const hasExcelContext = injectExcelContextPayload(contextPayload, contextParts)
    consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    const reqOpts = { signal: fetchOptions.signal }
    const batchBody = {
      messages: batchTexts,
      user_id,
      context: contextPayload,
      source: 'normal' as const,
      mode: 'basic' as const,
      ...resolveChatDbTokensForPayload(),
    }
    return (await chatApi.sendUnifiedChatBatch(batchBody as ChatRequest & { messages: string[] }, reqOpts)) as unknown as ChatPlannerPayload
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

  function startWaitProgressTimer(targetSessionId?: string) {
    const key = progressKey(targetSessionId)
    const startedAt = Date.now()
    const existing = waitProgressTickers.get(key)
    if (existing) window.clearInterval(existing)
    waitProgressTickers.set(
      key,
      window.setInterval(() => {
        const elapsedSec = Math.max(1, Math.floor((Date.now() - startedAt) / 1000))
        const hint = elapsedSec >= 8 ? ' 若持续无响应，请确认后端已启动，且 VITE_API_BASE_URL（如有）与浏览器能访问的地址一致。' : ''
        setLoadingProgress(`已发送请求，正在等待服务端响应（${elapsedSec}s）...${hint}`, key)
      }, 1000),
    )
  }

  function stopLoadingProgress(targetSessionId?: string) {
    const key = progressKey(targetSessionId)
    const ticker = waitProgressTickers.get(key)
    if (ticker) window.clearInterval(ticker)
    waitProgressTickers.delete(key)
    setLoadingProgress('处理中...', key)
  }

  async function requestChatByModeWithTimeout(
    message: string,
    timeoutMs: number = 90_000,
    plannerOpts?: { fromWriteUnlock?: boolean },
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const controller = new AbortController()
    let timeoutId: number | null = null
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = window.setTimeout(() => {
        controller.abort()
        reject(new Error(`请求超时（>${Math.floor(timeoutMs / 1000)}s），请检查后端是否可达或接口是否卡住`))
      }, timeoutMs)
    })
    try {
      return await Promise.race([requestChatByMode(message, { signal: controller.signal }, plannerOpts, scope), timeoutPromise])
    } finally {
      if (timeoutId != null) window.clearTimeout(timeoutId)
    }
  }

  async function requestChatByModeBatchWithTimeout(
    batchTexts: string[],
    timeoutMs: number = 90_000,
    scope?: ChatRequestScope,
  ): Promise<ChatPlannerPayload> {
    const controller = new AbortController()
    let timeoutId: number | null = null
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = window.setTimeout(() => {
        controller.abort()
        reject(new Error(`批量请求超时（>${Math.floor(timeoutMs / 1000)}s），请检查后端是否可达或接口是否卡住`))
      }, timeoutMs)
    })
    try {
      return await Promise.race([requestChatByModeBatch(batchTexts, { signal: controller.signal }, scope), timeoutPromise])
    } finally {
      if (timeoutId != null) window.clearTimeout(timeoutId)
    }
  }

  function resolveChatTimeoutMs(message: string): number {
    const text = String(message || '').trim()
    const isComplexTask = /(导入|入库|数据库|工作流|执行|创建|新增|批量|excel|上传|加入数据库)/i.test(text)
    return isComplexTask ? 180_000 : 90_000
  }

  function enqueueChatBatchMessage(message: string, debounceMs: number, onFlush: (messages: string[]) => void): void {
    chatBatchQueue.push(message)
    if (chatBatchTimer != null) {
      window.clearTimeout(chatBatchTimer)
    }
    chatBatchTimer = window.setTimeout(() => {
      chatBatchTimer = null
      const msgs = chatBatchQueue.splice(0)
      onFlush(msgs)
    }, debounceMs)
  }

  return {
    loadingProgressText,
    chatBatchQueue,
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
