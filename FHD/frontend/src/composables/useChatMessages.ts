import { ref, computed, watch, type Ref } from 'vue'
import { storeToRefs } from 'pinia'
import chatApi from '../api/chat'
import { speakText, stopSpeaking, cleanTextForSpeech } from '../utils/tts'
import { useModsStore } from '@/stores/mods'
import { useIndustryStore } from '@/stores/industry'
import { getIndustryWelcomeMarkdown } from '@/constants/industryPresets'
import {
  buildChatMessagesKey,
  buildChatSessionMetaKey,
} from '@/utils/chatStorageKeys'
import { asRecord, asArray, asString, asBoolean } from '@/utils/typeGuards'

const WELCOME_MESSAGE_PREFIX = '您好！我是您的'

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
  if (!text) { playNextVoice(); return }

  try {
    await Promise.race([
      speakText(text),
      new Promise((_, reject) => setTimeout(() => reject(new Error('TTS timeout')), 8000))
    ])
  } catch {
    // swallow，继续播下一条
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
      .trim()
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

import type { UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'

/** UI 聊天消息（与 ApiChatMessage 不同：role 用 ai、时间字段为 time） */
export type ChatMessage = UiChatMessage
export type ChatMessageExtras = UiChatMessageExtras

export function useChatMessages(sessionId: Ref<string>) {
  const modsStore = useModsStore()
  const industryStore = useIndustryStore()
  const { activeModId } = storeToRefs(modsStore)
  const storageKey = computed(() =>
    buildChatMessagesKey(String(sessionId.value || 'default'), String(activeModId.value || ''))
  )
  const sessionMetaKey = computed(() =>
    buildChatSessionMetaKey(String(sessionId.value || 'default'), String(activeModId.value || ''))
  )

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

  function hasMeaningfulContent(raw: unknown): boolean {
    const html = String(raw || '')
    if (!html) return false
    const text = html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]*>/g, '')
      .replace(/&nbsp;/gi, ' ')
      .trim()
    return text.length > 0
  }

  function hasRenderableSidecar(row: Record<string, unknown>): boolean {
    if (asBoolean(row.streamingShell)) return true
    if (asString(row.toolProgressLabel).trim()) return true
    if (asString(row.downloadUrl).trim()) return true
    if (asString(row.shipmentDownloadUrl).trim()) return true
    if (asString(row.thinkingSteps).trim()) return true
    if (asString(row.workflowAction).trim()) return true
    if (asArray(row.todoSteps).length) return true
    if (asArray(row.nodeResults).length) return true
    if (row.contextSummary != null && String(row.contextSummary).trim()) return true
    return false
  }

  function sanitizeMessageExtras(row: Record<string, unknown>): ChatMessageExtras {
    const extras: ChatMessageExtras = {}
    if (asBoolean(row.streamingShell)) extras.streamingShell = true

    const toolProgressLabel = asString(row.toolProgressLabel).trim()
    if (toolProgressLabel) extras.toolProgressLabel = toolProgressLabel

    const downloadUrl = asString(row.downloadUrl).trim()
    if (downloadUrl) extras.downloadUrl = downloadUrl

    const shipmentDownloadUrl = asString(row.shipmentDownloadUrl).trim()
    if (shipmentDownloadUrl) extras.shipmentDownloadUrl = shipmentDownloadUrl

    const thinkingSteps = asString(row.thinkingSteps).trim()
    if (thinkingSteps) extras.thinkingSteps = thinkingSteps

    const workflowAction = asString(row.workflowAction).trim()
    if (workflowAction) extras.workflowAction = workflowAction

    const todoSteps = asArray(row.todoSteps)
      .map((step) => asString(step).trim())
      .filter(Boolean)
    if (todoSteps.length) extras.todoSteps = todoSteps

    const nodeResults = asArray(row.nodeResults)
      .map((raw) => {
        const node = asRecord(raw)
        const nodeId = asString(node.node_id).trim()
        const toolId = asString(node.tool_id).trim()
        const action = asString(node.action).trim()
        if (!nodeId && !toolId && !action) return null
        const result: NonNullable<ChatMessageExtras['nodeResults']>[number] = {
          node_id: nodeId,
          tool_id: toolId,
          action,
          success: asBoolean(node.success),
        }
        const error = asString(node.error).trim()
        if (error) result.error = error
        return result
      })
      .filter((node): node is NonNullable<ChatMessageExtras['nodeResults']>[number] => !!node)
    if (nodeResults.length) extras.nodeResults = nodeResults

    const attachments = asArray(row.attachments)
      .map((item) => asRecord(item))
      .filter((item) => Object.keys(item).length > 0)
    if (attachments.length) extras.attachments = attachments

    if (row.contextSummary != null && String(row.contextSummary).trim()) {
      extras.contextSummary = row.contextSummary
    }

    return extras
  }

  function toPlainText(raw: unknown): string {
    return String(raw || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]*>/g, '')
      .replace(/&nbsp;/gi, ' ')
      .trim()
  }

  function isWelcomeMessage(msg: Pick<ChatMessage, 'role' | 'content'>): boolean {
    if (msg.role !== 'ai') return false
    return toPlainText(msg.content).startsWith(WELCOME_MESSAGE_PREFIX)
  }

  function deriveSessionTitle(list: ChatMessage[]): string {
    const meaningful = list.filter((msg) => hasMeaningfulContent(msg.content) && !isWelcomeMessage(msg))
    const preferred = meaningful.find((msg) => msg.role === 'user') || meaningful[0]
    const plain = toPlainText(preferred?.content || '').replace(/\s+/g, ' ').trim()
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
          updated_at: new Date().toISOString()
        })
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
        const role = (roleRaw === 'user' || roleRaw === 'task') ? roleRaw : 'ai'
        const content = asString(row.content)
        const streamingShell = asBoolean(row.streamingShell)
        const toolProgressLabel = asString(row.toolProgressLabel).trim()
        if (!hasMeaningfulContent(content) && !streamingShell && !toolProgressLabel) return null
        return {
          role,
          content,
          time: asString(row.time).trim()
            || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          ...(streamingShell ? { streamingShell: true } : {}),
          ...(toolProgressLabel ? { toolProgressLabel } : {}),
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

  function addMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: ChatMessageExtras,
    options?: { speak?: boolean }
  ) {
    if (!hasMeaningfulContent(content)) return
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    const safeContent = escapeHtml(content).replace(/\n/g, '<br>')
    messages.value.push({
      role,
      content: safeContent,
      time,
      ...(extras || {})
    })
    persistMessagesCache()

    // TTS 语音播报（仅 AI 消息且非欢迎消息）
    if (options?.speak && role === 'ai' && !isWelcomeMessage({ role, content: safeContent })) {
      queueVoice(safeContent)
    }
  }

  async function saveMessage(role: 'user' | 'ai' | 'task', content: string): Promise<void> {
    if (!hasMeaningfulContent(content)) return
    try {
      await chatApi.saveMessage({
        session_id: sessionId.value,
        user_id: 'default',
        role,
        content
      })
    } catch (e) {
      console.error('保存消息失败:', e)
    }
  }

  async function addAndSaveMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: ChatMessageExtras,
    options?: { speak?: boolean }
  ): Promise<void> {
    if (!hasMeaningfulContent(content)) return
    addMessage(content, role, extras, options)
    await saveMessage(role, content)
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
    const safe = escapeHtml(plain).replace(/\n/g, '<br>')
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
        return {
          role: (roleRaw === 'user' || roleRaw === 'task') ? roleRaw : 'ai',
          content: normalizeServerContentToHtml(row.content),
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
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
    }
  )

  // 切换当前扩展（Mod）时：同一会话 ID 下不同 Mod 的消息缓存相互隔离，
  // 切换后应重新读取当前 Mod 对应的本地消息（若无缓存则展示欢迎语）。
  watch(
    () => String(activeModId.value || ''),
    () => {
      messages.value = readCachedMessages()
    }
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
    clearVoiceQueue
  }
}
