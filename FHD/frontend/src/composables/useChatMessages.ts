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
import { asRecord, asArray, asString, asBoolean, asNumber } from '@/utils/typeGuards'
import { formatChatMessageTime } from '@/utils/chatTaskLabels'
import type { ChatApprovalCard, UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'

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
  if (!text) { playNextVoice(); return }

  try {
    let timeoutId: ReturnType<typeof setTimeout> | undefined
    await Promise.race([
      speakText(text),
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('TTS timeout')), VOICE_PLAY_TIMEOUT_MS)
      })
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

/** UI 聊天消息（与 ApiChatMessage 不同：role 用 ai、时间字段为 time） */
export type ChatMessage = UiChatMessage
export type ChatMessageExtras = UiChatMessageExtras

const CHAT_MESSAGE_SIDECAR_KEYS = [
  'thinkingSteps',
  'todoSteps',
  'workflowAction',
  'nodeResults',
  'contextSummary',
  'streamingShell',
  'toolProgressLabel',
  'downloadUrl',
  'shipmentDownloadUrl',
  'approvalCard',
  'attachments',
] as const

function hasMeaningfulChatContent(raw: unknown): boolean {
  const html = String(raw || '')
  if (!html) return false
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim()
    .length > 0
}

function sanitizeStringList(raw: unknown): string[] {
  return asArray(raw).map((item) => asString(item).trim()).filter(Boolean)
}

function sanitizeApprovalCard(raw: unknown): ChatApprovalCard | undefined {
  const row = asRecord(raw)
  if (!Object.keys(row).length) return undefined

  const statusRaw = asString(row.status).trim()
  const status = statusRaw === 'confirmed' || statusRaw === 'cancelled' ? statusRaw : 'pending'
  const approvalNodes = asArray(row.approval_nodes)
    .map((item) => {
      const node = asRecord(item)
      const nodeId = asString(node.node_id).trim()
      const toolId = asString(node.tool_id).trim()
      const action = asString(node.action).trim()
      if (!nodeId && !toolId && !action) return null
      return {
        ...(nodeId ? { node_id: nodeId } : {}),
        ...(toolId ? { tool_id: toolId } : {}),
        ...(action ? { action } : {}),
      }
    })
    .filter((item): item is NonNullable<typeof item> => !!item)
  const version = asNumber(row.version, 0)
  const card: ChatApprovalCard = {
    ...(version > 0 ? { version } : {}),
    ...(['kind', 'plan_id', 'run_id', 'agent_run_id', 'intent', 'reason', 'confirm_mode'] as const)
      .reduce<Partial<ChatApprovalCard>>((result, key) => {
        const value = asString(row[key]).trim()
        if (value) Object.assign(result, { [key]: value })
        return result
      }, {}),
    ...(sanitizeStringList(row.blocking_nodes).length
      ? { blocking_nodes: sanitizeStringList(row.blocking_nodes) }
      : {}),
    ...(approvalNodes.length ? { approval_nodes: approvalNodes } : {}),
    ...(sanitizeStringList(row.approval_request_ids).length
      ? { approval_request_ids: sanitizeStringList(row.approval_request_ids) }
      : {}),
    ...(sanitizeStringList(row.todo).length ? { todo: sanitizeStringList(row.todo) } : {}),
    ...(Object.prototype.hasOwnProperty.call(row, 'approval_required')
      ? { approval_required: asBoolean(row.approval_required) }
      : {}),
    status,
  }

  const hasIdentity = !!(
    card.kind
    || card.plan_id
    || card.run_id
    || card.agent_run_id
    || card.intent
    || card.reason
    || card.approval_nodes?.length
    || card.approval_request_ids?.length
    || card.todo?.length
  )
  return hasIdentity ? card : undefined
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

  const todoSteps = sanitizeStringList(row.todoSteps)
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
      for (const key of ['error', 'message', 'output_preview', 'recovery_hint'] as const) {
        const value = asString(node[key]).trim()
        if (value) result[key] = value
      }
      for (const key of ['retries', 'duration_ms'] as const) {
        const value = asNumber(node[key], Number.NaN)
        if (Number.isFinite(value)) result[key] = value
      }
      if (Object.prototype.hasOwnProperty.call(node, 'retryable')) {
        result.retryable = asBoolean(node.retryable)
      }
      return result
    })
    .filter((node): node is NonNullable<ChatMessageExtras['nodeResults']>[number] => !!node)
  if (nodeResults.length) extras.nodeResults = nodeResults

  const attachments = asArray(row.attachments)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
  if (attachments.length) extras.attachments = attachments

  const contextSummary = asString(row.contextSummary).trim()
  if (contextSummary) extras.contextSummary = contextSummary

  const approvalCard = sanitizeApprovalCard(row.approvalCard)
  if (approvalCard) extras.approvalCard = approvalCard

  return extras
}

function hasRenderableSidecar(row: Record<string, unknown>): boolean {
  return Object.keys(sanitizeMessageExtras(row)).length > 0
}

/** Whitelist and normalize persisted UI messages without discarding structured result cards. */
export function sanitizeChatMessagesList(rawList: unknown[]): ChatMessage[] {
  return (Array.isArray(rawList) ? rawList : [])
    .map((msg: unknown) => {
      const row = asRecord(msg)
      const roleRaw = asString(row.role)
      const role = (roleRaw === 'user' || roleRaw === 'task') ? roleRaw : 'ai'
      const content = asString(row.content)
      if (!hasMeaningfulChatContent(content) && !hasRenderableSidecar(row)) return null
      return {
        role,
        content,
        time: asString(row.time).trim()
          || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        ...sanitizeMessageExtras(row),
      } as ChatMessage
    })
    .filter((message): message is ChatMessage => !!message)
}

export function pickChatMessageSidecars(message: ChatMessage): ChatMessageExtras {
  const result: ChatMessageExtras = {}
  for (const key of CHAT_MESSAGE_SIDECAR_KEYS) {
    const value = message[key]
    if (value !== undefined) Object.assign(result, { [key]: value })
  }
  return result
}

function comparableMessageText(raw: unknown): string {
  return String(raw || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&(nbsp|#160);/gi, ' ')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Overlay local-only UI result cards onto the durable server transcript. */
export function mergeChatMessageSidecars(
  serverMessages: ChatMessage[],
  cachedMessages: ChatMessage[],
): ChatMessage[] {
  const server = sanitizeChatMessagesList(serverMessages)
  const cached = sanitizeChatMessagesList(cachedMessages)
  const consumed = new Set<number>()

  return server.map((message) => {
    const targetText = comparableMessageText(message.content)
    const matchIndex = cached.findIndex((candidate, index) => (
      !consumed.has(index)
      && candidate.role === message.role
      && comparableMessageText(candidate.content) === targetText
      && Object.keys(pickChatMessageSidecars(candidate)).length > 0
    ))
    if (matchIndex < 0) return message
    consumed.add(matchIndex)
    return { ...message, ...pickChatMessageSidecars(cached[matchIndex]) }
  })
}

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
      const sanitized = sanitizeChatMessagesList(parsed)
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
      const sanitized = sanitizeChatMessagesList(messages.value)
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
  const bootSanitized = sanitizeChatMessagesList(messages.value)
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

  const hasMeaningfulContent = hasMeaningfulChatContent

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

  function patchMessageAtIndex(index: number, patch: ChatMessageExtras): void {
    const row = messages.value[index]
    if (!row) return
    Object.assign(row, patch)
    persistMessagesCache()
  }

  function clearMessages() {
    messages.value = []
    persistMessagesCache()
  }

  function loadMessages(newMessages: ChatMessage[]) {
    messages.value = sanitizeChatMessagesList(newMessages)
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
          time: formatChatMessageTime(
            row.time ?? row.timestamp ?? row.created_at ?? row.createdAt ?? row.updated_at,
          ),
        }
      })
      const sanitized = mergeChatMessageSidecars(mapped, messages.value)
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
    patchMessageAtIndex,
    persistMessagesCache,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue
  }
}
