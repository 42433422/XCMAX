/** Kitten 对话发送：冻结单轮请求，断流只读回原任务，不重放业务。 */
import { type Ref } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { chatApi, parseChatStreamErrorResponse } from '@/api/chat'
import { agentRunsApi } from '@/api/agentRuns'
import { resolvePlannerChatPath } from '@/utils/plannerChatPaths'
import { readPlannerSseResponse, isChatStreamEnabled } from '@/utils/chatSseStream'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'
import { asRecord, asString } from '@/utils/typeGuards'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import {
  inspectKittenExecution,
  rememberKittenExecution,
  KITTEN_UNCONFIRMED_REASON,
  type KittenExecutionReceipt,
} from './kittenExecutionReceipt'
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

  const sendMessage = async () => {
    if (!inputText.value.trim() || isChatLoading.value || isDatasetParsing.value) return
    const query = inputText.value.trim()
    if (!kittenSessionUserId.value) kittenSessionUserId.value = makeKittenUserId()
    const sessionId = kittenSessionUserId.value
    const receipt: KittenExecutionReceipt = {
      turn_id: createBusinessHarnessId('turn'),
      task_id: createBusinessHarnessId('task'),
      run_id: '',
      approval_id: '',
      token_name: '',
      status: 'running',
      reason: '',
    }
    const ds = datasetSummary.value
    const fields = Array.isArray(ds?.fieldNames) ? ds.fieldNames.map(String) : []
    // Construct once before the assistant placeholder, including a detached dataset/history snapshot.
    const payload = {
      message: query,
      user_id: sessionId,
      source: 'pro',
      mode: 'pro',
      context: {
        kitten_analyzer: true,
        kitten_session_id: sessionId,
        session_id: sessionId,
        conversation_id: sessionId,
        turn_id: receipt.turn_id,
        task_id: receipt.task_id,
        kitten_include_business_db: kittenIncludeBusinessDb.value,
        kitten_web_search: kittenIncludeWebSearch.value,
        has_dataset: Boolean(ds),
        kitten_dataset: ds
          ? {
              file_name: ds.name,
              name: ds.name,
              rows: ds.rows,
              columns: ds.columns,
              fields,
              field_names: [...fields],
              preview_text: ds.previewText || '',
            }
          : null,
        recent_messages: messages.value.slice(-6).map((m) => ({ role: m.role, content: plainTextFromChatHtml(m.content).slice(0, 500) })),
      },
    }
    addMessage('user', query)
    inputText.value = ''
    isChatLoading.value = true
    isKittenStreaming.value = false
    kittenPhase.value = KITTEN_PHASE.analyzing
    const current = () => kittenSessionUserId.value === sessionId
    let streamMessage: KittenChatMessage | null = null
    let streamPlain = ''
    const remember = (row: unknown) => rememberKittenExecution(receipt, row)
    const show = (text: string, envelope: Record<string, unknown>, phase: KittenPhase, title: string) => {
      if (!current()) return
      remember(envelope)
      if (streamMessage) streamMessage.content = textToHtml(text)
      else addMessage('ai', textToHtml(text))
      lastWebSearchHits.value = extractWebSearchHits(envelope.result || envelope)
      const failed = phase === KITTEN_PHASE.error
      currentResult.value = {
        id: Date.now(),
        title,
        summary: buildKittenResultSummary(text),
        chart: false,
        type: failed ? 'error' : phase === KITTEN_PHASE.delivered ? 'analysis' : 'pending',
        kind: failed ? 'chatError' : phase === KITTEN_PHASE.delivered ? 'analysis' : receipt.status,
        execution: { ...receipt },
      }
      kittenPhase.value = phase
      scrollChatToBottom()
    }
    const settle = (envelope: Record<string, unknown>, fallback = '') => {
      const result = inspectKittenExecution(envelope)
      remember(envelope)
      receipt.status = result.status
      receipt.reason = result.reason
      let text = result.text || fallback || result.reason || '服务器未返回有效回复内容。'
      if (result.phase !== KITTEN_PHASE.delivered && streamPlain && !text.includes(streamPlain)) {
        text = `${streamPlain}\n${text}`
      }
      if (result.phase === KITTEN_PHASE.error) text = `请求失败：${text}`
      else if (result.reason && !text.includes(result.reason)) text += `\n${result.reason}`
      show(text, envelope, result.phase, result.title)
    }
    const reconcile = async (): Promise<boolean> => {
      if (!receipt.run_id) return false
      try {
        const result = await agentRunsApi.getRun(receipt.run_id)
        const run = result.data
        if (!current() || !result.success || !run || run.run_id !== receipt.run_id) return false
        const savedTurn = asString(asRecord(run.metadata?.task_context).turn_id)
        if (savedTurn && savedTurn !== receipt.turn_id) return false
        const saved = asRecord(run.final_output?.chat_payload)
        const recovered = { run_id: run.run_id, execution_state: run.status, result: saved }
        if (runHasUncertainReceipt(run) || inspectKittenExecution(recovered).phase === KITTEN_PHASE.unknown) return false
        if (['completed', 'success', 'succeeded'].includes(run.status) && !Object.keys(saved).length) return false
        settle(recovered, streamPlain || run.error || '')
        return true
      } catch {
        return false
      }
    }
    const controller = new AbortController()
    const killTimer = window.setTimeout(() => controller.abort(), KITTEN_CHAT_TIMEOUT_MS)
    try {
      if (isChatStreamEnabled()) {
        isKittenStreaming.value = true
        pushBounded(
          messages,
          { role: 'ai', content: '', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
          MAX_CHAT_MESSAGES,
        )
        streamMessage = messages.value[messages.value.length - 1]
        const res = await chatApi.sendChatStream(payload, { signal: controller.signal })
        if (!res.ok) {
          remember(
            await res
              .clone()
              .json()
              .catch(() => null),
          )
          throw new Error(await parseChatStreamErrorResponse(res))
        }
        let done: Record<string, unknown> | null = null
        let authorization: Record<string, unknown> | null = null
        let streamError = ''
        await readPlannerSseResponse(
          res,
          (ev) => {
            if (!current()) {
              controller.abort()
              return
            }
            remember(asRecord(ev))
            if (ev.type === 'token' && !ev.ephemeral) {
              streamPlain += ev.text || ''
              if (streamMessage) streamMessage.content = textToHtml(streamPlain)
              scrollChatToBottom()
            } else if (ev.type === 'done') {
              done = asRecord(ev.result)
              remember(done)
            } else if (ev.type === 'error') streamError = ev.message || '流式接口错误'
            else if (ev.type === 'requires_token') authorization = { ...ev, requires_token: true }
          },
          controller.signal,
        )
        if (!current()) return
        if (streamError) throw new Error(streamError)
        if (authorization) settle(authorization, streamPlain)
        else if (done) settle(done, streamPlain)
        else throw new Error('连接提前结束，尚未收到完成回执。')
      } else {
        const result = await safeJsonRequest<Record<string, unknown>>(resolvePlannerChatPath(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: controller.signal,
        })
        const envelope = result.data || {}
        remember(envelope)
        if (!result.ok && (result.status >= 500 || !result.data)) throw new Error(result.message || '请求结果未确认')
        settle(
          { ...envelope, ...(!result.ok ? { success: false } : {}) },
          extractChatApiText(envelope) || asString(envelope.message) || result.message || '服务器未返回有效回复内容。',
        )
      }
    } catch (err) {
      if (!current() || (await reconcile())) return
      const reason =
        err instanceof Error && err.name === 'AbortError' ? '请求超时或连接已中断。' : err instanceof Error ? err.message : String(err)
      receipt.status = 'unknown'
      receipt.reason = reason
      show([streamPlain, `${reason}\n${KITTEN_UNCONFIRMED_REASON}`].filter(Boolean).join('\n'), {}, KITTEN_PHASE.unknown, '结果待核对')
    } finally {
      window.clearTimeout(killTimer)
      if (current()) {
        isChatLoading.value = false
        isKittenStreaming.value = false
        scrollChatToBottom()
      }
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
  return { sendMessage, sendQuickAction, handleInputKeydown }
}
