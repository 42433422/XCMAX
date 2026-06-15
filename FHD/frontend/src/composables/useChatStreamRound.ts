/**
 * Planner SSE 流式一轮对话（从 useChatOrchestration 拆出）。
 */
import { ref, type Ref } from 'vue'
import chatApi, { parseChatStreamErrorResponse } from '@/api/chat'
import { readPlannerSseResponse, type PlannerSseEvent } from '@/utils/chatSseStream'
import type { ChatPlannerPayload, ChatRequest } from '@/types/chat'
import { asRecord, asString } from '@/utils/typeGuards'
import { stripInternalMarkers } from '@/utils/lightMarkdown'
import { stripPlannerDisplayMarkers } from '@/utils/chatBubbleDisplay'

export type ChatStreamRoundDeps = {
  pushStreamingAiShell: () => number
  applyPlainTextToMessageIndex: (index: number, plain: string) => void
  patchMessageAtIndex: (index: number, patch: Record<string, unknown>) => void
  saveMessage: (role: 'ai', content: string) => Promise<void>
  persistMessagesCache: () => void
  scrollToBottom: () => void
  setLoadingProgress: (text: string) => void
  startWaitProgressTimer: () => void
  stopLoadingProgress: () => void
  queueVoice: (text: string) => void
  clearVoiceQueue: () => void
  ttsEnabled: Ref<boolean>
  buildPlannerChatRequestPayload: (
    message: string,
    opts?: { fromWriteUnlock?: boolean },
  ) => { body: Record<string, unknown> }
  resolveChatTimeoutMs: (text: string) => number
  handleChatRequiresToken: (tokenName: string, tokenDesc: string, remoteMessages: string[]) => void
  onStreamDone: (payload: ChatPlannerPayload, primaryText: string, _msgIndex: number) => Promise<void>
  plannerWriteUnlockResumeDraft: Ref<string>
  isLoading: Ref<boolean>
  isStreamingReply: Ref<boolean>
}

export function useChatStreamRound(deps: ChatStreamRoundDeps) {
  let activeStreamController: AbortController | null = null
  let abortedByUser = false

  function cleanStreamDisplayText(text: string): string {
    return stripInternalMarkers(stripPlannerDisplayMarkers(String(text || ''))).trim()
  }

  function stopStreamingReply() {
    abortedByUser = true
    deps.clearVoiceQueue()
    activeStreamController?.abort()
  }

  async function runPlannerSseStream(
    primaryForStream: string,
    remoteMessages: string[],
    opts?: { fromWriteUnlock?: boolean },
  ): Promise<boolean> {
    deps.isStreamingReply.value = true
    deps.isLoading.value = true
    deps.setLoadingProgress('正在流式生成回复…')
    deps.startWaitProgressTimer()
    abortedByUser = false

    const timeoutMsS = Math.min(120000, deps.resolveChatTimeoutMs(primaryForStream))
    const controller = new AbortController()
    activeStreamController = controller
    const killTimer = window.setTimeout(() => controller.abort(), timeoutMsS)
    const msgIndex = deps.pushStreamingAiShell()
    let streamPlain = ''
    let doneResult: Record<string, unknown> | null = null
    let sseError: string | null = null
    let ttsSpokenOffset = 0
    const ttsShouldSpeak = deps.ttsEnabled.value
    const SPEAK_SENTENCE_BOUNDARY = /[。！？!?；;\n]/g

    const flushTtsFromStream = (text: string, force: boolean) => {
      if (!ttsShouldSpeak || !deps.ttsEnabled.value) return
      const pending = text.slice(ttsSpokenOffset)
      if (!pending) return
      if (force) {
        deps.queueVoice(pending)
        ttsSpokenOffset = text.length
        return
      }
      SPEAK_SENTENCE_BOUNDARY.lastIndex = 0
      let lastBoundary = -1
      let match: RegExpExecArray | null
      while ((match = SPEAK_SENTENCE_BOUNDARY.exec(pending)) !== null) {
        lastBoundary = match.index + match[0].length
      }
      if (lastBoundary < 0) return
      const chunk = pending.slice(0, lastBoundary).trim()
      if (chunk) deps.queueVoice(chunk)
      ttsSpokenOffset += lastBoundary
    }

    try {
      const { body } = deps.buildPlannerChatRequestPayload(primaryForStream, {
        fromWriteUnlock: !!opts?.fromWriteUnlock,
      })
      const res = await chatApi.sendChatStream(
        { ...body, message: String(body.message || primaryForStream) } as ChatRequest &
          Record<string, unknown>,
        { signal: controller.signal },
      )
      if (!res.ok) {
        throw new Error(await parseChatStreamErrorResponse(res))
      }
      await readPlannerSseResponse(res, (ev: PlannerSseEvent) => {
        if (ev.type === 'token') {
          if (ev.ephemeral) return
          streamPlain += ev.text || ''
          deps.applyPlainTextToMessageIndex(msgIndex, streamPlain)
          flushTtsFromStream(streamPlain, false)
          deps.setLoadingProgress('正在生成回复…')
          deps.scrollToBottom()
        } else if (ev.type === 'tool_progress') {
          const label = String(ev.label || ev.text || ev.phase || '工具').trim()
          deps.patchMessageAtIndex(msgIndex, {
            toolProgressLabel: label ? `正在调用 ${label}…` : '正在调用工具…',
          })
          deps.setLoadingProgress(label ? `正在调用 ${label}…` : '正在调用工具…')
          deps.scrollToBottom()
        } else if (ev.type === 'done') {
          doneResult = asRecord(ev.result)
        } else if (ev.type === 'error') {
          sseError = String(ev.message || '流式接口错误')
        } else if (ev.type === 'requires_token') {
          const tokenName = ev.token_name || ''
          const tokenDesc = ev.token_description || ''
          deps.handleChatRequiresToken(tokenName, tokenDesc, remoteMessages)
          const upTok = String(tokenName || '').toUpperCase()
          if (
            upTok.includes('WRITE') ||
            /写入|导入|入库|二级|数据库写入|DB_WRITE/i.test(String(tokenDesc || ''))
          ) {
            deps.plannerWriteUnlockResumeDraft.value = streamPlain
          }
        }
      })

      if (sseError) throw new Error(sseError)

      const finalText =
        cleanStreamDisplayText(String(asString(doneResult?.['response']) || streamPlain)) ||
        streamPlain ||
        '（无内容）'
      deps.patchMessageAtIndex(msgIndex, { toolProgressLabel: undefined })
      deps.applyPlainTextToMessageIndex(msgIndex, finalText)
      if (ttsShouldSpeak && deps.ttsEnabled.value) {
        const tail = finalText.slice(ttsSpokenOffset).trim()
        if (tail) deps.queueVoice(tail)
      }
      await deps.saveMessage('ai', finalText)
      const wrap: ChatPlannerPayload =
        doneResult && typeof doneResult === 'object'
          ? (doneResult as ChatPlannerPayload)
          : { success: true, response: finalText }
      await deps.onStreamDone(wrap, primaryForStream, msgIndex)
      deps.persistMessagesCache()
      return true
    } catch (err: unknown) {
      const errObj = err as { name?: string; message?: string }
      if (errObj?.name === 'AbortError' && abortedByUser) {
        const partial = cleanStreamDisplayText(streamPlain)
        deps.patchMessageAtIndex(msgIndex, { toolProgressLabel: undefined })
        if (partial) {
          deps.applyPlainTextToMessageIndex(msgIndex, partial)
          await deps.saveMessage('ai', partial)
        } else {
          deps.applyPlainTextToMessageIndex(msgIndex, '（已停止生成）')
          await deps.saveMessage('ai', '（已停止生成）')
        }
        return true
      }
      const errText =
        errObj?.name === 'AbortError'
          ? `请求超时（>${Math.floor(timeoutMsS / 1000)}s）或已中断`
          : errObj?.message || '流式对话失败'
      deps.applyPlainTextToMessageIndex(msgIndex, `处理失败：${errText}`)
      await deps.saveMessage('ai', `处理失败：${errText}`)
      return false
    } finally {
      activeStreamController = null
      deps.isStreamingReply.value = false
      window.clearTimeout(killTimer)
      deps.isLoading.value = false
      deps.stopLoadingProgress()
    }
  }

  return {
    runPlannerSseStream,
    stopStreamingReply,
  }
}
