import { ref, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import chatApi from '../api/chat'
import type { ChatPlannerPayload, ChatRequest } from '@/types/chat'
import { asRecord, asArray, asString, asBoolean, asDisposable } from '@/utils/typeGuards'

export interface UseChatRequestDeps {
  messages: Ref<ChatMessage[]>
  proIntentExperienceEnabled?: Ref<boolean>
  isProMode: Ref<boolean>
  lastRequestContextSummary: Ref<string>
  plannerWriteUnlockResumeDraft: Ref<string>
  resolveEffectiveProModeState: () => boolean
  getModeScopedUserId: (proEnabled: boolean) => string
  resolveChatDbTokensForPayload: () => { db_read_token?: string; db_write_token?: string }
  injectExcelContextPayload: (ctx: Record<string, unknown>, parts: string[]) => boolean
  consumeMultimodalIntoPlannerContext: (ctx: Record<string, unknown>, parts: string[]) => void
}

export function useChatRequest(deps: UseChatRequestDeps) {
  const {
    messages,
    proIntentExperienceEnabled,
    isProMode,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveEffectiveProModeState,
    getModeScopedUserId,
    resolveChatDbTokensForPayload,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  } = deps

  const loadingProgressText = ref('处理中...')
  let waitProgressTicker: number | null = null
  let chatBatchTimer: number | null = null
  const chatBatchQueue: string[] = []

  function buildPlannerChatRequestPayload(
    message: string,
    plannerOpts?: { fromWriteUnlock?: boolean }
  ): {
    body: Record<string, unknown>
    proIntentEnabled: boolean
  } {
    const runtimeProEnabled = resolveEffectiveProModeState()
    isProMode.value = runtimeProEnabled

    const proIntentEnabled = runtimeProEnabled || !!proIntentExperienceEnabled?.value
    const hybridNormalUiProChannel = proIntentEnabled && !runtimeProEnabled
    const user_id = getModeScopedUserId(proIntentEnabled)
    const compactHistory = (messages.value || [])
      .slice(-6)
      .map((m) => ({
        role: m.role,
        content: String(m.content || '')
          .replace(/<br\s*\/?>/gi, '\n')
          .replace(/<[^>]*>/g, '')
          .slice(0, 500)
      }))
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory
    }
    // industry 由后端根据 session account_kind 自动派生（单一真相源），前端不传
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const hasExcelContext = injectExcelContextPayload(contextPayload, contextParts)
    consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    if (hybridNormalUiProChannel) {
      contextPayload.ui_surface = 'normal'
      contextPayload.intent_channel = 'pro'
      contextPayload.tool_execution_profile = 'normal'
    }
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
    if (proIntentEnabled) {
      return {
        proIntentEnabled,
        body: {
          message,
          source: 'pro',
          mode: 'professional',
          user_id,
          context: contextPayload,
          ...resolveChatDbTokensForPayload()
        }
      }
    }
    return {
      proIntentEnabled,
      body: {
        message,
        source: 'normal',
        mode: 'basic',
        user_id,
        context: contextPayload,
        ...resolveChatDbTokensForPayload()
      }
    }
  }

  async function requestChatByMode(
    message: string,
    fetchOptions: RequestInit = {},
    plannerOpts?: { fromWriteUnlock?: boolean }
  ): Promise<ChatPlannerPayload> {
    const { body, proIntentEnabled } = buildPlannerChatRequestPayload(message, plannerOpts)
    const reqOpts = { signal: fetchOptions.signal }
    if (proIntentEnabled) {
      return (await chatApi.sendChat(body as unknown as ChatRequest, reqOpts)) as unknown as ChatPlannerPayload
    }
    return (await chatApi.sendUnifiedChat(body as unknown as ChatRequest, reqOpts)) as unknown as ChatPlannerPayload
  }

  /** 与单条请求相同的 context / user_id，用于 /api/ai/chat/batch 与 unified_chat/batch */
  async function requestChatByModeBatch(batchTexts: string[], fetchOptions: RequestInit = {}): Promise<ChatPlannerPayload> {
    const runtimeProEnabled = resolveEffectiveProModeState()
    isProMode.value = runtimeProEnabled
    const proIntentEnabled = runtimeProEnabled || !!proIntentExperienceEnabled?.value
    const hybridNormalUiProChannel = proIntentEnabled && !runtimeProEnabled
    const user_id = getModeScopedUserId(proIntentEnabled)
    const compactHistory = (messages.value || [])
      .slice(-6)
      .map((m) => ({
        role: m.role,
        content: String(m.content || '')
          .replace(/<br\s*\/?>/gi, '\n')
          .replace(/<[^>]*>/g, '')
          .slice(0, 500)
      }))
    const contextPayload: Record<string, unknown> = {
      recent_messages: compactHistory
    }
    const contextParts: string[] = []
    contextParts.push(`最近对话 ${compactHistory.length} 条`)
    const hasExcelContext = injectExcelContextPayload(contextPayload, contextParts)
    consumeMultimodalIntoPlannerContext(contextPayload, contextParts)
    const linkedCount = compactHistory.length + (hasExcelContext ? 1 : 0)
    lastRequestContextSummary.value = `已关联上下文：${contextParts.join(' + ')}（共 ${linkedCount}）`
    if (hybridNormalUiProChannel) {
      contextPayload.ui_surface = 'normal'
      contextPayload.intent_channel = 'pro'
      contextPayload.tool_execution_profile = 'normal'
    }
    const reqOpts = { signal: fetchOptions.signal }
    const batchBody = {
      messages: batchTexts,
      user_id,
      context: contextPayload,
      source: proIntentEnabled ? ('pro' as const) : ('normal' as const),
      mode: proIntentEnabled ? ('professional' as const) : ('basic' as const),
      ...resolveChatDbTokensForPayload()
    }
    if (proIntentEnabled) {
      return (await chatApi.sendChatBatch(batchBody as ChatRequest & { messages: string[] }, reqOpts)) as unknown as ChatPlannerPayload
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

  function setLoadingProgress(step: string) {
    loadingProgressText.value = String(step || '').trim() || '处理中...'
  }

  function startWaitProgressTimer() {
    const startedAt = Date.now()
    if (waitProgressTicker) {
      window.clearInterval(waitProgressTicker)
    }
    waitProgressTicker = window.setInterval(() => {
      const elapsedSec = Math.max(1, Math.floor((Date.now() - startedAt) / 1000))
      const hint =
        elapsedSec >= 8
          ? ' 若持续无响应，请确认后端已启动，且 VITE_API_BASE_URL（如有）与浏览器能访问的地址一致。'
          : ''
      loadingProgressText.value = `已发送请求，正在等待服务端响应（${elapsedSec}s）...${hint}`
    }, 1000)
  }

  function stopLoadingProgress() {
    if (waitProgressTicker) {
      window.clearInterval(waitProgressTicker)
      waitProgressTicker = null
    }
    loadingProgressText.value = '处理中...'
  }

  async function requestChatByModeWithTimeout(
    message: string,
    timeoutMs: number = 45000,
    plannerOpts?: { fromWriteUnlock?: boolean }
  ): Promise<ChatPlannerPayload> {
    const controller = new AbortController()
    const timeoutPromise = new Promise<never>((_, reject) => {
      window.setTimeout(() => {
        controller.abort()
        reject(new Error(`请求超时（>${Math.floor(timeoutMs / 1000)}s），请检查后端是否可达或接口是否卡住`))
      }, timeoutMs)
    })
    return Promise.race([
      requestChatByMode(message, { signal: controller.signal }, plannerOpts),
      timeoutPromise
    ])
  }

  async function requestChatByModeBatchWithTimeout(batchTexts: string[], timeoutMs: number = 45000): Promise<ChatPlannerPayload> {
    const controller = new AbortController()
    const timeoutPromise = new Promise<never>((_, reject) => {
      window.setTimeout(() => {
        controller.abort()
        reject(new Error(`批量请求超时（>${Math.floor(timeoutMs / 1000)}s），请检查后端是否可达或接口是否卡住`))
      }, timeoutMs)
    })
    return Promise.race([
      requestChatByModeBatch(batchTexts, { signal: controller.signal }),
      timeoutPromise
    ])
  }

  function resolveChatTimeoutMs(message: string): number {
    const text = String(message || '').trim()
    const isComplexTask = /(导入|入库|数据库|工作流|执行|创建|新增|批量|excel|上传|加入数据库)/i.test(text)
    return isComplexTask ? 90000 : 30000
  }

  function enqueueChatBatchMessage(
    message: string,
    debounceMs: number,
    onFlush: (messages: string[]) => void,
  ): void {
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
