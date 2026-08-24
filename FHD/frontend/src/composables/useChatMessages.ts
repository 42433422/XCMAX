import { ref, computed, watch, type Ref } from 'vue'
import { storeToRefs } from 'pinia'
import chatApi from '../api/chat'
import { speakText, stopSpeaking, cleanTextForSpeech } from '../utils/tts'
import { useModsStore } from '@/stores/mods'
import { useIndustryStore } from '@/stores/industry'
import { getIndustryWelcomeMarkdown } from '@/constants/industryPresets'
import { buildChatMessagesKey, buildChatSessionMetaKey } from '@/utils/chatStorageKeys'
import { asRecord, asArray, asString, asBoolean } from '@/utils/typeGuards'
import { formatChatMessageTime } from '@/utils/chatTaskLabels'
import { stripModelToolProtocol } from '@/utils/chatModelProtocol'

const WELCOME_MESSAGE_PREFIX = '您好！我是您的'
const VOICE_PLAY_TIMEOUT_MS = 30_000

// TTS 语音队列：按顺序播放，避免多条并发抢扬声器
const voiceQueue: string[] = []
let isPlayingVoice = false

async function playNextVoice() {
  if (voiceQueue.length === 0) {
    isPlayingVoice = false
    return
  }

  isPlayingVoice = true
  const text = voiceQueue.shift()
  if (!text) {
    playNextVoice()
    return
  }

  try {
    let timeoutId: ReturnType<typeof setTimeout> | undefined
    await Promise.race([
      speakText(text),
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('TTS timeout')), VOICE_PLAY_TIMEOUT_MS)
      }),
    ]).finally(() => {
      if (timeoutId) clearTimeout(timeoutId)
    })
  } catch {
    stopSpeaking()
  }
  // 短间隔让句子之间有呼吸
  setTimeout(() => playNextVoice(), 350)
}

export function queueVoice(text: string) {
  // 去除 HTML 标签和标点符号，只保留纯文本用于语音
  const plainText = cleanTextForSpeech(
    String(text || '')
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/<[^>]*>/g, ' ')
      .replace(/&nbsp;/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim(),
  )

  if (!plainText) return

  voiceQueue.push(plainText)
  if (!isPlayingVoice) {
    void playNextVoice()
  }
}

export function clearVoiceQueue() {
  voiceQueue.length = 0
  isPlayingVoice = false
  stopSpeaking()
}

import type { ChatDecisionOption, UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'

/** UI 聊天消息（与 ApiChatMessage 不同：role 用 ai、时间字段为 time） */
export type ChatMessage = UiChatMessage
export type ChatMessageExtras = UiChatMessageExtras

function metadataRecord(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === 'object') return asRecord(raw)
  if (typeof raw !== 'string' || !raw.trim()) return {}
  try {
    return asRecord(JSON.parse(raw))
  } catch {
    return {}
  }
}

/** Restore only the structured UI fields that the chat renderer understands. */
export function chatMessageExtrasFromServerRow(raw: unknown): ChatMessageExtras {
  const row = asRecord(raw)
  const metadata = metadataRecord(row.metadata)
  const ui = asRecord(row.ui_payload || metadata.ui)
  const stringArray = (value: unknown) =>
    asArray(value)
      .map((item) => asString(item).trim())
      .filter(Boolean)
  const objectArray = (value: unknown) =>
    asArray(value)
      .map((item) => asRecord(item))
      .filter((item) => Object.keys(item).length > 0)
  const extras: ChatMessageExtras = {}
  const thinkingSteps = asString(ui.thinkingSteps).trim()
  const workflowAction = asString(ui.workflowAction).trim()
  const contextSummary = asString(ui.contextSummary).trim()
  const downloadUrl = asString(ui.downloadUrl).trim()
  const shipmentDownloadUrl = asString(ui.shipmentDownloadUrl).trim()
  if (thinkingSteps) extras.thinkingSteps = thinkingSteps
  if (workflowAction) extras.workflowAction = workflowAction
  if (contextSummary) extras.contextSummary = contextSummary
  if (downloadUrl) extras.downloadUrl = downloadUrl
  if (shipmentDownloadUrl) extras.shipmentDownloadUrl = shipmentDownloadUrl
  const todoSteps = stringArray(ui.todoSteps)
  if (todoSteps.length) extras.todoSteps = todoSteps
  const nodeResults = objectArray(ui.nodeResults)
  if (nodeResults.length) extras.nodeResults = nodeResults as NonNullable<ChatMessageExtras['nodeResults']>
  const executionProgress = objectArray(ui.executionProgress)
  if (executionProgress.length)
    extras.executionProgress = executionProgress as unknown as NonNullable<ChatMessageExtras['executionProgress']>
  const attachments = objectArray(ui.attachments)
  if (attachments.length) extras.attachments = attachments
  const approvalCard = asRecord(ui.approvalCard)
  if (Object.keys(approvalCard).length) extras.approvalCard = approvalCard
  const agentRunTrace = asRecord(ui.agentRunTrace)
  if (Object.keys(agentRunTrace).length) extras.agentRunTrace = agentRunTrace as unknown as NonNullable<ChatMessageExtras['agentRunTrace']>
  const businessResult = asRecord(ui.businessResult)
  if (Object.keys(businessResult).length) extras.businessResult = businessResult
  const decisionOptions = objectArray(ui.decisionOptions)
    .map((option) => {
      const id = asString(option.id).trim()
      const label = asString(option.label).trim()
      if (!id || !label) return null
      const normalized: ChatDecisionOption = { id, label }
      const description = asString(option.description).trim()
      const message = asString(option.message).trim()
      const composePrefill = asString(option.composePrefill).trim()
      if (description) normalized.description = description
      if (message) normalized.message = message
      if (composePrefill) normalized.composePrefill = composePrefill
      if (asBoolean(option.recommended)) normalized.recommended = true
      return normalized
    })
    .filter((option): option is ChatDecisionOption => !!option)
  if (decisionOptions.length) extras.decisionOptions = decisionOptions
  return extras
}

export function useChatMessages(sessionId: Ref<string>) {
  const modsStore = useModsStore()
  const industryStore = useIndustryStore()
  const { activeModId } = storeToRefs(modsStore)
  const storageKey = computed(() => buildChatMessagesKey(String(sessionId.value || 'default'), String(activeModId.value || '')))
  const sessionMetaKey = computed(() => buildChatSessionMetaKey(String(sessionId.value || 'default'), String(activeModId.value || '')))

  function getDefaultWelcome(): ChatMessage[] {
    const industryId = String(industryStore.currentIndustryId || '').trim() || '通用'
    return [
      {
        role: 'ai',
        content: getIndustryWelcomeMarkdown(industryId),
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      },
    ]
  }

  function readCachedMessages(): ChatMessage[] {
    try {
      const raw = localStorage.getItem(storageKey.value)
      if (!raw) return getDefaultWelcome()
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || !parsed.length) return getDefaultWelcome()
      const sanitized = sanitizeMessagesList(parsed)
      if (!sanitized.length) return getDefaultWelcome()
      if (isWelcomeMessage(sanitized[0]) && /<[a-z]+[\s>]/i.test(sanitized[0].content)) {
        sanitized[0] = getDefaultWelcome()[0]
      }
      return sanitized
    } catch (_e) {
      return getDefaultWelcome()
    }
  }

  function persistMessagesCache(): void {
    try {
      const sanitized = sanitizeMessagesList(messages.value)
      if (sanitized.length !== messages.value.length) {
        messages.value = sanitized
      }
      localStorage.setItem(storageKey.value, JSON.stringify(messages.value))
      persistSessionMeta(messages.value)
    } catch (_e) {
      // ignore storage errors
    }
  }

  const messages = ref<ChatMessage[]>(readCachedMessages())
  const bootSanitized = sanitizeMessagesList(messages.value)
  if (bootSanitized.length !== messages.value.length) {
    messages.value = bootSanitized.length ? bootSanitized : getDefaultWelcome()
    try {
      localStorage.setItem(storageKey.value, JSON.stringify(messages.value))
      persistSessionMeta(messages.value)
    } catch {
      // ignore storage errors
    }
  }

  const lastMessage = computed(() => messages.value[messages.value.length - 1])

  function escapeHtml(text: string): string {
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
  }

  function extractPlainText(raw: unknown): string {
    const source = String(raw || '')
    const entities: Record<string, string> = {
      amp: '&',
      apos: "'",
      gt: '>',
      lt: '<',
      nbsp: ' ',
      quot: '"',
    }
    let plain = ''
    let index = 0

    while (index < source.length) {
      if (source[index] === '<') {
        const tagEnd = source.indexOf('>', index + 1)
        if (tagEnd < 0) {
          plain += source.slice(index)
          break
        }
        const tagName = source
          .slice(index + 1, tagEnd)
          .trim()
          .toLowerCase()
        if (tagName === 'br' || tagName === 'br/' || tagName.startsWith('br ')) {
          plain += '\n'
        }
        index = tagEnd + 1
        continue
      }

      if (source[index] === '&') {
        const entityEnd = source.indexOf(';', index + 1)
        if (entityEnd > index && entityEnd - index <= 10) {
          const entityName = source.slice(index + 1, entityEnd).toLowerCase()
          const decoded = entities[entityName]
          if (decoded !== undefined) {
            plain += decoded
            index = entityEnd + 1
            continue
          }
        }
      }

      plain += source[index]
      index += 1
    }

    return plain.replace(/\u00a0/g, ' ').trim()
  }

  function hasMeaningfulContent(raw: unknown): boolean {
    return extractPlainText(raw).length > 0
  }

  function toPlainText(raw: unknown): string {
    return extractPlainText(raw)
  }

  function isWelcomeMessage(msg: Pick<ChatMessage, 'role' | 'content'>): boolean {
    if (msg.role !== 'ai') return false
    return toPlainText(msg.content).startsWith(WELCOME_MESSAGE_PREFIX)
  }

  function deriveSessionTitle(list: ChatMessage[]): string {
    const meaningful = list.filter((msg) => hasMeaningfulContent(msg.content) && !isWelcomeMessage(msg))
    const preferred = meaningful.find((msg) => msg.role === 'user') || meaningful[0]
    const plain = toPlainText(preferred?.content || '')
      .replace(/\s+/g, ' ')
      .trim()
    if (!plain) return '新会话'
    return plain.length > 32 ? `${plain.slice(0, 32)}...` : plain
  }

  function persistSessionMeta(list: ChatMessage[]): void {
    try {
      const meaningful = list.filter((msg) => hasMeaningfulContent(msg.content) && !isWelcomeMessage(msg))
      if (!meaningful.length) {
        localStorage.removeItem(sessionMetaKey.value)
        return
      }
      localStorage.setItem(
        sessionMetaKey.value,
        JSON.stringify({
          session_id: String(sessionId.value || 'default'),
          title: deriveSessionTitle(list),
          message_count: meaningful.length,
          updated_at: new Date().toISOString(),
        }),
      )
    } catch {
      // ignore storage errors
    }
  }

  function sanitizeMessagesList(rawList: unknown[]): ChatMessage[] {
    return (Array.isArray(rawList) ? rawList : [])
      .map((msg: unknown) => {
        const row = asRecord(msg)
        const roleRaw = asString(row.role)
        const role = roleRaw === 'user' || roleRaw === 'task' ? roleRaw : 'ai'
        const content = role === 'ai' ? stripModelToolProtocol(row.content) : asString(row.content)
        const streamingShell = asBoolean(row.streamingShell)
        const toolProgressLabel = asString(row.toolProgressLabel).trim()
        if (!hasMeaningfulContent(content) && !streamingShell && !toolProgressLabel) return null
        return {
          role,
          content,
          time: asString(row.time).trim() || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          ...(streamingShell ? { streamingShell: true } : {}),
          ...(toolProgressLabel ? { toolProgressLabel } : {}),
          ...chatMessageExtrasFromServerRow({ ui_payload: row }),
        } as ChatMessage
      })
      .filter((m): m is ChatMessage => !!m)
  }

  function normalizeServerContentToHtml(raw: unknown): string {
    const text = String(raw || '')
    // 如果已经是 HTML（常见：<br>/<div>/<ul>），按原样展示，避免二次转义
    if (/<[a-z][\s\S]*>/i.test(text)) return text
    return escapeHtml(text).replace(/\n/g, '<br>')
  }

  function addMessage(content: string, role: 'user' | 'ai' | 'task' = 'ai', extras?: ChatMessageExtras, options?: { speak?: boolean }) {
    const visibleContent = role === 'ai' ? stripModelToolProtocol(content) : content
    if (!hasMeaningfulContent(visibleContent)) return
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    const safeContent = escapeHtml(visibleContent).replace(/\n/g, '<br>')
    messages.value.push({
      role,
      content: safeContent,
      time,
      ...(extras || {}),
    })
    persistMessagesCache()

    // TTS 语音播报（仅 AI 消息且非欢迎消息）
    if (options?.speak && role === 'ai' && !isWelcomeMessage({ role, content: safeContent })) {
      queueVoice(safeContent)
    }
  }

  async function saveMessage(
    role: 'user' | 'ai' | 'task',
    content: string,
    targetSessionId?: string,
    extras?: ChatMessageExtras,
  ): Promise<void> {
    const visibleContent = role === 'ai' ? stripModelToolProtocol(content) : content
    if (!hasMeaningfulContent(visibleContent)) return
    try {
      await chatApi.saveMessage({
        session_id: targetSessionId || sessionId.value,
        user_id: 'default',
        role,
        content: visibleContent,
        ...(extras && Object.keys(extras).length ? { metadata: JSON.stringify({ ui: extras }) } : {}),
      })
    } catch (e) {
      console.error('保存消息失败:', e)
    }
  }

  async function addAndSaveMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: ChatMessageExtras,
    options?: { speak?: boolean; sessionId?: string },
  ): Promise<void> {
    if (!hasMeaningfulContent(content)) return
    if (!options?.sessionId || options.sessionId === sessionId.value) addMessage(content, role, extras, options)
    await saveMessage(role, content, options?.sessionId, extras)
  }

  /** 流式回复：先占位一条 AI 消息，返回其在 messages 中的下标 */
  function pushStreamingAiShell(): number {
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    messages.value.push({
      role: 'ai',
      content: '',
      time,
      streamingShell: true,
    })
    persistMessagesCache()
    return messages.value.length - 1
  }

  /** 将纯文本安全转为气泡 HTML 并写入指定下标（用于 SSE token 追加） */
  function applyPlainTextToMessageIndex(index: number, plain: string) {
    const safe = escapeHtml(stripModelToolProtocol(plain)).replace(/\n/g, '<br>')
    const row = messages.value[index]
    if (!row) return
    row.content = safe
    if (safe) {
      delete row.streamingShell
    } else {
      row.streamingShell = true
    }
    persistMessagesCache()
  }

  function clearMessages() {
    messages.value = []
    persistMessagesCache()
  }

  function loadMessages(newMessages: ChatMessage[]) {
    messages.value = sanitizeMessagesList(newMessages)
    persistMessagesCache()
  }

  async function syncFromServer(): Promise<boolean> {
    try {
      const sid = String(sessionId.value || '').trim()
      if (!sid) return false
      const data = await chatApi.getConversation(sid)
      const dataRow = asRecord(data)
      const serverMessages = asArray(dataRow.messages)
      if (!serverMessages.length) return false

      const mapped: ChatMessage[] = serverMessages.map((msg: unknown) => {
        const row = asRecord(msg)
        const roleRaw = asString(row.role)
        const role = roleRaw === 'user' || roleRaw === 'task' ? roleRaw : 'ai'
        return {
          role,
          content: normalizeServerContentToHtml(role === 'ai' ? stripModelToolProtocol(row.content) : row.content),
          time: formatChatMessageTime(row.time ?? row.timestamp ?? row.created_at ?? row.createdAt ?? row.updated_at),
          ...chatMessageExtrasFromServerRow(row),
        }
      })
      const sanitized = sanitizeMessagesList(mapped)
      if (!sanitized.length) return false
      loadMessages(sanitized)
      return true
    } catch (_e) {
      return false
    }
  }

  watch(
    () => sessionId.value,
    () => {
      messages.value = readCachedMessages()
    },
  )

  // 切换当前扩展（Mod）时：同一会话 ID 下不同 Mod 的消息缓存相互隔离，
  // 切换后应重新读取当前 Mod 对应的本地消息（若无缓存则展示欢迎语）。
  watch(
    () => String(activeModId.value || ''),
    () => {
      messages.value = readCachedMessages()
    },
  )

  // Cards and traces are mutated after a reply is inserted. Observe only these
  // structured fields so SSE token updates do not cause a localStorage write
  // for every token.
  watch(
    () =>
      messages.value.map((message) => ({
        thinkingSteps: message.thinkingSteps,
        todoSteps: message.todoSteps,
        workflowAction: message.workflowAction,
        nodeResults: message.nodeResults,
        contextSummary: message.contextSummary,
        executionProgress: message.executionProgress,
        downloadUrl: message.downloadUrl,
        shipmentDownloadUrl: message.shipmentDownloadUrl,
        approvalCard: message.approvalCard,
        agentRunTrace: message.agentRunTrace,
        attachments: message.attachments,
        businessResult: message.businessResult,
      })),
    () => persistMessagesCache(),
    { deep: true, flush: 'post' },
  )

  return {
    messages,
    lastMessage,
    addMessage,
    saveMessage,
    addAndSaveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  }
}
