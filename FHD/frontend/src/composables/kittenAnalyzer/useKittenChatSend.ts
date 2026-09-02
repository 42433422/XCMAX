/**
 * useKittenAnalyzer 拆分：对话发送（SSE 流式 + JSON 兜底）与请求上下文构建。
 */
import { type Ref } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { chatApi, parseChatStreamErrorResponse } from '@/api/chat'
import { resolvePlannerChatPath } from '@/utils/plannerChatPaths'
import { readPlannerSseResponse, isChatStreamEnabled, type PlannerSseEvent } from '@/utils/chatSseStream'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { KITTEN_PHASE, type KittenPhase } from '@/composables/useKittenWorkflowState'
import {
  KITTEN_CHAT_TIMEOUT_MS,
  MAX_CHAT_MESSAGES,
  buildKittenResultSummary,
  extractChatApiText,
  extractWebSearchHits,
  makeKittenUserId,
  pushBounded,
  textToHtml,
  type KittenAnalysisResult,
  type KittenChatMessage,
  type KittenDatasetSummary,
} from './kittenAnalyzerShared'

export interface KittenChatSendDeps {
  messages: Ref<KittenChatMessage[]>
  inputText: Ref<string>
  isChatLoading: Ref<boolean>
  isKittenStreaming: Ref<boolean>
  isDatasetParsing: Ref<boolean>
  kittenPhase: Ref<KittenPhase>
  currentResult: Ref<KittenAnalysisResult | null>
  kittenSessionUserId: Ref<string>
  kittenIncludeBusinessDb: Ref<boolean>
  kittenIncludeWebSearch: Ref<boolean>
  datasetSummary: Ref<KittenDatasetSummary | null>
  lastWebSearchHits: Ref<Array<{ title: string; url: string; snippet: string }>>
  addMessage: (role: 'user' | 'ai', content: string) => void
  scrollChatToBottom: () => void
}

export function useKittenChatSend(deps: KittenChatSendDeps) {
  const {
    messages,
    inputText,
    isChatLoading,
    isKittenStreaming,
    isDatasetParsing,
    kittenPhase,
    currentResult,
    kittenSessionUserId,
    kittenIncludeBusinessDb,
    kittenIncludeWebSearch,
    datasetSummary,
    lastWebSearchHits,
    addMessage,
    scrollChatToBottom,
  } = deps

  const buildKittenRequestContext = () => {
    const ds = datasetSummary.value
    const base = {
      kitten_analyzer: true,
      kitten_include_business_db: kittenIncludeBusinessDb.value,
      kitten_web_search: kittenIncludeWebSearch.value,
      kitten_session_id: kittenSessionUserId.value,
    }
    if (!ds) {
      return {
        ...base,
        has_dataset: false,
        kitten_dataset: null,
      }
    }
    const fields = Array.isArray(ds.fieldNames) ? ds.fieldNames.map((x) => String(x)) : []
    return {
      ...base,
      has_dataset: true,
      kitten_dataset: {
        file_name: ds.name,
        name: ds.name,
        rows: ds.rows,
        columns: ds.columns,
        fields,
        field_names: fields,
        preview_text: ds.previewText || '',
      },
    }
  }

  const buildKittenChatPayload = (query: string) => {
    const compactHistory = (messages.value || []).slice(-6).map((m) => ({
      role: m.role,
      content: plainTextFromChatHtml(m.content).slice(0, 500),
    }))
    return {
      message: query,
      user_id: kittenSessionUserId.value,
      source: 'pro',
      mode: 'pro',
      context: {
        ...buildKittenRequestContext(),
        recent_messages: compactHistory,
      },
    }
  }

  const sendMessage = async () => {
    if (!inputText.value.trim()) return
    if (isChatLoading.value || isDatasetParsing.value) return

    const query = inputText.value.trim()
    addMessage('user', query)
    inputText.value = ''
    isChatLoading.value = true
    isKittenStreaming.value = false
    kittenPhase.value = KITTEN_PHASE.analyzing

    if (!kittenSessionUserId.value) {
      kittenSessionUserId.value = makeKittenUserId()
    }

    const finishWithAiText = (replyText: string, envelope: Record<string, unknown> | null, failed: boolean) => {
      const hits = envelope ? extractWebSearchHits(envelope) : []
      lastWebSearchHits.value = hits
      const rid = Date.now()
      const plain = replyText
      currentResult.value = {
        id: rid,
        title: failed ? '请求失败' : 'AI 分析',
        summary: buildKittenResultSummary(plain),
        chart: false,
        type: failed ? 'error' : 'analysis',
        kind: failed ? 'chatError' : 'analysis',
      }
      kittenPhase.value = failed ? KITTEN_PHASE.error : KITTEN_PHASE.delivered
    }

    try {
      if (isChatStreamEnabled()) {
        isKittenStreaming.value = true
        const streamTime = new Date().toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        })
        pushBounded(messages, { role: 'ai', content: '', time: streamTime }, MAX_CHAT_MESSAGES)
        const aiIdx = messages.value.length - 1
        let streamPlain = ''
        let doneResult: unknown = null
        let sseError: string | null = null
        const controller = new AbortController()
        const killTimer = window.setTimeout(() => controller.abort(), KITTEN_CHAT_TIMEOUT_MS)
        let streamOk = false
        try {
          const res = await chatApi.sendChatStream(buildKittenChatPayload(query), {
            signal: controller.signal,
          })
          if (!res.ok) {
            throw new Error(await parseChatStreamErrorResponse(res))
          }
          await readPlannerSseResponse(res, (ev: PlannerSseEvent) => {
            if (ev.type === 'token') {
              streamPlain += ev.text || ''
              messages.value[aiIdx].content = textToHtml(streamPlain)
              scrollChatToBottom()
            } else if (ev.type === 'done') {
              doneResult = ev.result
            } else if (ev.type === 'error') {
              sseError = String(ev.message || '流式接口错误')
            } else if (ev.type === 'requires_token') {
              const tokenName = ev.token_name || ''
              const tokenRaw = `${String(tokenName || '')} ${String(ev.token_description || '')}`.toUpperCase()
              if (/DB_(READ|WRITE)_TOKEN|数据库.*令牌|一级|二级|写入令牌|查看令牌/.test(tokenRaw)) {
                return
              }
              streamPlain += `\n[需要授权：${ev.token_description || tokenName || '授权信息'}]\n`
              messages.value[aiIdx].content = textToHtml(streamPlain)
              scrollChatToBottom()
            }
          })
          if (sseError) {
            throw new Error(sseError)
          }
          const dr = doneResult as Record<string, unknown> | null
          const finalText = String((dr as { response?: string } | null)?.response ?? streamPlain).trim() || streamPlain || '（无内容）'
          messages.value[aiIdx].content = textToHtml(finalText)
          const failed = dr ? (dr as { success?: boolean }).success === false : false
          finishWithAiText(finalText, dr, failed)
          streamOk = true
        } catch (err) {
          const atIdx = messages.value[aiIdx]
          if (atIdx?.role === 'ai') {
            messages.value.splice(aiIdx, 1)
          }
          if (import.meta.env.DEV) {
            console.warn('kitten stream failed, falling back to JSON chat', err)
          }
        } finally {
          window.clearTimeout(killTimer)
          isKittenStreaming.value = false
        }
        if (streamOk) {
          return
        }
      }

      const jsonAbort = new AbortController()
      const jsonKill = window.setTimeout(() => jsonAbort.abort(), KITTEN_CHAT_TIMEOUT_MS)
      try {
        const result = await safeJsonRequest<Record<string, unknown>>(resolvePlannerChatPath(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildKittenChatPayload(query)),
          signal: jsonAbort.signal,
        })

        let replyText = ''
        if (result.ok && (result.data as { success?: boolean })?.success) {
          replyText = extractChatApiText(result.data as Record<string, unknown>)
        } else {
          const d = result.data as { message?: string } | null
          const errMsg = d?.message || result.message || '请求失败'
          replyText = `请求失败：${errMsg}`
        }

        if (!replyText.trim()) {
          replyText = '服务器未返回有效回复内容。'
        }

        addMessage('ai', textToHtml(replyText))
        const env = result.data as Record<string, unknown> | null
        const failed = !result.ok || !(result.data as { success?: boolean })?.success
        finishWithAiText(replyText, env, failed)
      } finally {
        window.clearTimeout(jsonKill)
      }
    } catch (err) {
      const raw = err instanceof Error ? err.message : String(err)
      const msg =
        err instanceof Error && err.name === 'AbortError' ? `请求超时（>${Math.floor(KITTEN_CHAT_TIMEOUT_MS / 1000)}s）或已中断` : raw
      addMessage('ai', textToHtml(`网络异常：${msg}`))
      currentResult.value = {
        id: Date.now(),
        title: '网络异常',
        summary: msg.slice(0, 220),
        chart: false,
        type: 'error',
        kind: 'networkError',
      }
      kittenPhase.value = KITTEN_PHASE.error
    } finally {
      isChatLoading.value = false
      isKittenStreaming.value = false
      scrollChatToBottom()
    }
  }

  const sendQuickAction = (btn: { text: string }) => {
    inputText.value = btn.text
    void sendMessage()
  }

  const handleInputKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void sendMessage()
    }
  }

  return {
    sendMessage,
    sendQuickAction,
    handleInputKeydown,
  }
}
