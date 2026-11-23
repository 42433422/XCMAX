import { ref, computed, shallowRef, watch, getCurrentScope, onScopeDispose, type Ref } from 'vue'
import { storeToRefs } from 'pinia'
import chatApi from '../api/chat'
import { boundedChatMessageCache, CHAT_HISTORY_PAGE_SIZE, localMessagePersistence, samePersistedMessage, useChatMessagePersistence } from './useChatMessagePersistence'
import { speakText, stopSpeaking, cleanTextForSpeech } from '../utils/tts'
import { useModsStore } from '@/stores/mods'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useIndustryStore } from '@/stores/industry'
import { getIndustryWelcomeMarkdown } from '@/constants/industryPresets'
import { buildChatMessagesKey, buildChatSessionMetaKey, resolveChatIdentity, resolveChatStorageScope } from '@/utils/chatStorageKeys'
import { readChatModelRoute, recordChatModelRoute } from '@/utils/chatModelRoute'
import { asRecord, asArray, asString, asBoolean } from '@/utils/typeGuards'
import { formatChatMessageTime } from '@/utils/chatTaskLabels'
import { stripModelToolProtocol } from '@/utils/chatModelProtocol'
import { reconcileApprovalCards, restoreApprovalCard } from '@/utils/chatApprovalCard'
import { chatMessageKey } from '@/utils/chatMessageIdentity'
import { captureAuthSession } from '@/utils/authSessionCache'
import { restoreRuntimeContinuation, runtimeContinuationFromPayload } from '@/utils/chatRuntimeContinuation'

const WELCOME_MESSAGE_PREFIX = '您好！我是您的'

/** 本地失败回执（未写入服务端）的识别口径，用于清理被后续对话取代的幽灵行。 */
const TRANSPORT_FAILURE_NOTICE_RE =
  /处理失败|连接中断|请求超时|尚未收到完成回执|没有收到正文|network error|服务暂时不可用/i

function isSupersededTransportFailure(message: ChatMessage): boolean {
  if (message.role !== 'ai' || message.streamingShell) return false
  if (message.persistence?.status === 'saved') return false
  return TRANSPORT_FAILURE_NOTICE_RE.test(String(message.content || '').replace(/<[^>]*>/g, ' '))
}

// TTS 语音队列：按顺序播放，避免多条并发抢扬声器
const voiceQueue: string[] = []
let isPlayingVoice = false
let voiceGeneration = 0
let voiceTimer: ReturnType<typeof setTimeout> | undefined

async function playNextVoice(generation = voiceGeneration) {
  if (generation !== voiceGeneration) return
  const text = voiceQueue.shift()
  if (!text) { isPlayingVoice = false; return }
  isPlayingVoice = true
  try { await speakText(text) } catch { if (generation !== voiceGeneration) return }
  if (generation !== voiceGeneration) return
  voiceTimer = setTimeout(() => { void playNextVoice(generation) }, 350)
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
  voiceGeneration++
  clearTimeout(voiceTimer)
  voiceTimer = undefined
  voiceQueue.length = 0
  isPlayingVoice = false
  stopSpeaking()
}

import type { UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'

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
  const route = readChatModelRoute(metadata.route_metadata || ui.routeMetadata)
  if (route && row.role !== 'user' && ui.role !== 'user') extras.routeMetadata = route
  const turnId = asString(ui.turnId || asRecord(metadata.business_harness).turn_id || asRecord(metadata.summary).turn_id).trim()
  if (turnId) extras.turnId = turnId
  if (row.role !== 'user' && ui.role !== 'user') {
    const continuation = restoreRuntimeContinuation(ui.runtimeContinuation)
      || runtimeContinuationFromPayload(metadata)
    if (continuation) extras.runtimeContinuation = continuation
  }
  const summary = asRecord(metadata.summary)
  const serverStatus = asString(summary.status)
  const observationStatus = ['unknown', 'outcome_unknown'].includes(serverStatus) ? 'unknown'
    : ['running', 'queued', 'waiting_approval', 'paused'].includes(serverStatus) ? serverStatus : ''
  if (row.role !== 'user' && (observationStatus || summary.success === false)) {
    extras.workflowAction = observationStatus || 'failed'
  }
  const savedId = asString(metadata.client_message_id || row.client_message_id).trim()
  const serverMessageId = row.id ?? ui.serverMessageId
  if (typeof serverMessageId === 'number' && Number.isSafeInteger(serverMessageId) && serverMessageId > 0) {
    extras.serverMessageId = serverMessageId
  }
  const persisted = asRecord(ui.persistence)
  const localId = asString(persisted.id).trim()
  if (row.id != null || savedId) {
    extras.persistence = { id: savedId || `server:${row.id}`, status: row.id != null ? 'saved' : 'local',
      ...(row.durable === true ? { durable: true } : {}) }
  } else if (localId && ['local', 'saving', 'saved', 'failed'].includes(asString(persisted.status))) {
    const request = asRecord(persisted.request)
    extras.persistence = {
      id: localId,
      status: persisted.status as NonNullable<ChatMessage['persistence']>['status'],
      ...(persisted.durable === true ? { durable: true } : {}),
      ...(typeof persisted.localSaved === 'boolean' ? { localSaved: persisted.localSaved } : {}),
      ...(persisted.error ? { error: asString(persisted.error) } : {}),
      ...(['user', 'ai', 'task'].includes(asString(request.role)) && typeof request.content === 'string' ? {
        request: { role: request.role as ChatMessage['role'], content: request.content,
          ...(typeof request.expected_revision === 'number' ? { expected_revision: request.expected_revision } : {}),
          ...(typeof request.turn_id === 'string' ? { turn_id: request.turn_id } : {}),
          ...(typeof request.metadata === 'string' ? { metadata: request.metadata } : {}) },
      } : {}),
    }
  }
  const thinkingSteps = asString(ui.thinkingSteps).trim()
  const workflowAction = asString(ui.workflowAction).trim()
  const contextSummary = asString(ui.contextSummary).trim()
  const downloadUrl = asString(ui.downloadUrl).trim()
  const shipmentDownloadUrl = asString(ui.shipmentDownloadUrl).trim()
  if (thinkingSteps) extras.thinkingSteps = thinkingSteps
  if (workflowAction && !observationStatus) extras.workflowAction = workflowAction
  const recoveryTaskId = asString(ui.recoveryTaskId).trim()
  if (recoveryTaskId) extras.recoveryTaskId = recoveryTaskId
  if (contextSummary) extras.contextSummary = contextSummary
  if (downloadUrl) extras.downloadUrl = downloadUrl
  if (shipmentDownloadUrl) extras.shipmentDownloadUrl = shipmentDownloadUrl
  const todoSteps = stringArray(ui.todoSteps)
  if (todoSteps.length) extras.todoSteps = todoSteps
  const nodeResults = objectArray(ui.nodeResults)
  if (nodeResults.length) extras.nodeResults = nodeResults as unknown as NonNullable<ChatMessageExtras['nodeResults']>
  const executionProgress = objectArray(ui.executionProgress)
  if (executionProgress.length)
    extras.executionProgress = executionProgress as unknown as NonNullable<ChatMessageExtras['executionProgress']>
  const attachments = objectArray(ui.attachments)
  if (attachments.length) extras.attachments = attachments
  const approvalCard = asRecord(ui.approvalCard)
  if (Object.keys(approvalCard).length) extras.approvalCard = restoreApprovalCard(approvalCard)
  const agentRunTrace = asRecord(ui.agentRunTrace)
  if (Object.keys(agentRunTrace).length) extras.agentRunTrace = agentRunTrace as unknown as NonNullable<ChatMessageExtras['agentRunTrace']>
  const businessResult = asRecord(ui.businessResult)
  if (Object.keys(businessResult).length) extras.businessResult = businessResult
  const responseData = asRecord(row.data)
  if (asBoolean(ui.sameAsPrevious ?? row.sameAsPrevious ?? row.cached ?? responseData.cached)) {
    extras.sameAsPrevious = true
  }
  return extras
}

interface ChatMessageStore {
  messages: Ref<ChatMessage[]>
  cacheError: Ref<string>
  /** 同一会话被多个视图（智能对话页 / 悬浮窗）同时使用时共享同一份引用。 */
  refs: number
}

/**
 * 按会话缓存键（会话 + Mod）注册的模块级消息单例。
 * 智能对话页与悬浮窗从同一入口取到同一个 messages 引用，避免两份数组互相覆盖、
 * 同步时把旧消息当成孤儿行追加到末尾。
 */
const chatMessageStores = new Map<string, ChatMessageStore>()

function acquireChatMessageStore(key: string, init: () => ChatMessage[]): ChatMessageStore {
  const existing = chatMessageStores.get(key)
  if (existing) {
    existing.refs += 1
    return existing
  }
  const created: ChatMessageStore = { messages: ref<ChatMessage[]>(init()), cacheError: ref(''), refs: 1 }
  chatMessageStores.set(key, created)
  return created
}

function releaseChatMessageStore(key: string, store: ChatMessageStore): void {
  store.refs -= 1
  if (store.refs <= 0 && chatMessageStores.get(key) === store) chatMessageStores.delete(key)
}

/** 测试用：清空模块级单例，模拟整页刷新。 */
export function resetChatMessageStores(): void {
  chatMessageStores.clear()
}

export function useChatMessages(sessionId: Ref<string>, options: { isBusy?: () => boolean } = {}) {
  const busy = () => options.isBusy?.() === true
  const modsStore = useModsStore()
  const industryStore = useIndustryStore()
  const { activeModId } = storeToRefs(modsStore)
  const storageKey = computed(() => buildChatMessagesKey(String(sessionId.value || 'default'), String(activeModId.value || '')))
  const sessionMetaKey = computed(() => buildChatSessionMetaKey(String(sessionId.value || 'default'), String(activeModId.value || '')))

  const messagesHaveEarlier = ref(false)
  const earlierMessagesLoading = ref(false)
  const earlierMessagesError = ref('')
  let beforeMessageId: number | undefined
  let historyRevision: number | null = null
  let historyMessageCount: number | null = null
  let historyTitle = ''
  let historyEpoch = 0
  const resetHistoryPage = () => {
    historyEpoch++
    beforeMessageId = undefined
    historyRevision = null
    historyMessageCount = null
    historyTitle = ''
    messagesHaveEarlier.value = earlierMessagesLoading.value = false
    earlierMessagesError.value = ''
  }
  function setHistoryPage(page: Record<string, unknown>) {
    const revision = typeof page.revision === 'number' ? page.revision : null
    if (historyRevision !== null && revision !== historyRevision) {
      historyEpoch++
      earlierMessagesLoading.value = false
      earlierMessagesError.value = ''
      historyMessageCount = null
      historyTitle = ''
    }
    if (typeof page.message_count === 'number' && Number.isSafeInteger(page.message_count) && page.message_count >= 0)
      historyMessageCount = page.message_count
    if (typeof page.title === 'string' && page.title.trim()) historyTitle = page.title.trim()
    beforeMessageId = Number(page.next_before_id) || undefined
    messagesHaveEarlier.value = page.has_more === true && beforeMessageId !== undefined
    historyRevision = revision
  }
  function fromServerRows(rows: unknown[], durable: unknown = false): ChatMessage[] {
    return rows.map(raw => {
      const row = asRecord(raw)
      const role = row.role === 'user' || row.role === 'task' ? row.role : 'ai'
      return { role, content: normalizeServerContentToHtml(role === 'ai' ? stripModelToolProtocol(row.content) : row.content),
        time: formatChatMessageTime(row.time ?? row.timestamp ?? row.created_at ?? row.createdAt ?? row.updated_at),
        ...chatMessageExtrasFromServerRow({ ...row, durable: durable === true }) }
    })
  }
  async function loadEarlierMessages(): Promise<void> {
    if (earlierMessagesLoading.value || !messagesHaveEarlier.value || beforeMessageId === undefined) return
    const scope = storageKey.value, sid = sessionId.value, epoch = historyEpoch
    const currentOwner = captureAuthSession(), expectedRevision = historyRevision
    earlierMessagesLoading.value = true
    earlierMessagesError.value = ''
    try {
      const page = asRecord(await chatApi.getConversation(sid, { before_id: beforeMessageId, limit: CHAT_HISTORY_PAGE_SIZE }))
      if (!currentOwner() || scope !== storageKey.value || epoch !== historyEpoch) return
      if (page.success !== true) throw new Error('更早消息未读取成功，请重试')
      if (expectedRevision !== null && page.revision !== expectedRevision) {
        resetHistoryPage()
        await syncFromServer({ required: true })
        return
      }
      const older = fromServerRows(asArray(page.messages), page.durable).filter(row =>
        !messages.value.some(existing => samePersistedMessage(existing, row, toPlainText)))
      setHistoryPage(page)
      messages.value = [...older, ...messages.value]
      reconcileApprovalCards(messages.value)
      restoreModelRoute()
      persistMessagesCache()
    } catch (error) {
      if (currentOwner() && scope === storageKey.value && epoch === historyEpoch)
        earlierMessagesError.value = error instanceof Error ? error.message : '加载更早消息失败'
    } finally {
      if (scope === storageKey.value && epoch === historyEpoch) earlierMessagesLoading.value = false
    }
  }

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

  function readCachedMessages(key = storageKey.value): ChatMessage[] {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return getDefaultWelcome()
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || !parsed.length) return getDefaultWelcome()
      const sanitized = sanitizeMessagesList(parsed)
      for (const message of sanitized) {
        if (message.streamingShell) {
          delete message.streamingShell
          message.content = `${message.content}${hasMeaningfulContent(message.content) ? '<br>' : ''}上次回复未收到完成回执。请核对任务状态，勿重复提交。`
        }
        if (message.persistence?.status === 'saving') {
          message.persistence.status = 'failed'
          message.persistence.error = '上次保存未确认，请仅重试保存。'
        }
      }
      if (!sanitized.length) return getDefaultWelcome()
      if (isWelcomeMessage(sanitized[0]) && /<[a-z]+[\s>]/i.test(sanitized[0].content)) {
        sanitized[0] = getDefaultWelcome()[0]
      }
      const collapsed = withoutRepeatedWelcomes(sanitized)
      return collapsed.length ? collapsed : getDefaultWelcome()
    } catch (_e) {
      return getDefaultWelcome()
    }
  }

  let cacheTimer: ReturnType<typeof setTimeout> | undefined
  let pendingCacheWrite: (() => void) | undefined
  function flushMessagesCache() {
    clearTimeout(cacheTimer)
    cacheTimer = undefined
    const write = pendingCacheWrite
    pendingCacheWrite = undefined
    write?.()
  }
  function scheduleMessagesCache() {
    if (cacheTimer !== undefined) return
    const list = messages.value, key = storageKey.value, metaKey = sessionMetaKey.value, sid = sessionId.value
    pendingCacheWrite = () => persistMessagesCache(list, key, metaKey, sid)
    cacheTimer = setTimeout(flushMessagesCache, 250)
  }
  if (getCurrentScope()) onScopeDispose(flushMessagesCache)

  let activeStoreKey = storageKey.value
  const activeStore = shallowRef(acquireChatMessageStore(activeStoreKey, readCachedMessages))
  const messages = computed({
    get: () => activeStore.value.messages.value,
    set: next => { activeStore.value.messages.value = next },
  })
  const cacheError = computed(() => activeStore.value.cacheError.value)

  if (getCurrentScope()) {
    onScopeDispose(() => {
      flushMessagesCache()
      releaseChatMessageStore(activeStoreKey, activeStore.value)
    })
  }

  /** 切到另一个会话缓存键；已存在的单例沿用其内存态，只有新建时才从本机缓存读取。 */
  function switchActiveStore(): void {
    const nextKey = storageKey.value
    if (nextKey === activeStoreKey) return
    flushMessagesCache()
    releaseChatMessageStore(activeStoreKey, activeStore.value)
    activeStoreKey = nextKey
    activeStore.value = acquireChatMessageStore(activeStoreKey, readCachedMessages)
  }

  function persistMessagesCache(list = messages.value, key = storageKey.value, metaKey = sessionMetaKey.value, sid = sessionId.value): void {
    if (key === activeStoreKey) {
      clearTimeout(cacheTimer)
      cacheTimer = undefined
      pendingCacheWrite = undefined
    }
    try {
      for (const message of list) if (message.persistence) message.persistence.localSaved = true
      const sanitized = sanitizeMessagesList(list)
      if (list === messages.value && sanitized.length !== messages.value.length) {
        messages.value = sanitized
      }
      const live = new Set(list.filter(message => message.streamingShell
        || ['submitted', 'streaming'].includes(message.streamStatus || '')).map(chatMessageKey))
      const cached = boundedChatMessageCache(sanitized.map(message => live.has(chatMessageKey(message))
        ? { ...message, streamingShell: true, ...(message.persistence ? { persistence: { ...message.persistence, durable: undefined } } : {}) }
        : message))
      localStorage.setItem(key, JSON.stringify(cached))
      const retained = new Set(cached.map(chatMessageKey))
      for (const message of list) if (message.persistence && !retained.has(chatMessageKey(message))) delete message.persistence.localSaved
      persistSessionMeta(sanitized, metaKey, sid, cached.length < sanitized.length)
      if (key === activeStoreKey) activeStore.value.cacheError.value = ''
    } catch (_e) {
      for (const message of list) if (message.persistence) message.persistence.localSaved = false
      if (key === activeStoreKey) activeStore.value.cacheError.value = '本机保存失败。服务端未确认的消息请勿关闭页面，可重试本机保存或复制消息。'
    }
  }

  function restoreModelRoute() {
    const latest = [...messages.value].reverse().find(message => message.role === 'ai' && message.routeMetadata)
    recordChatModelRoute(sessionId.value, latest?.routeMetadata || null, resolveChatIdentity(String(activeModId.value || '')))
  }
  restoreModelRoute()
  const bootSanitized = sanitizeMessagesList(messages.value)
  const bootReconciled = reconcileApprovalCards(bootSanitized)
  if (bootSanitized.length !== messages.value.length || bootReconciled) {
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

  function isIndustryGreeting(plain: string): boolean {
    const first = plain.trim().split('\n')[0]?.trim() || ''
    if (first.startsWith('您好！我是您的智能考勤助手')) return true
    return /^你好，(?:我是)?[^。\n]{0,24}助手。$/.test(first)
  }

  function isWelcomeMessage(msg: Pick<ChatMessage, 'role' | 'content'>): boolean {
    if (msg.role !== 'ai') return false
    const plain = toPlainText(msg.content)
    if (plain.includes('未收到完成回执') || plain.includes('上次保存未确认')) return false
    if (plain.startsWith(WELCOME_MESSAGE_PREFIX)) return true
    return isIndustryGreeting(plain)
  }

  function withoutRepeatedWelcomes(list: ChatMessage[]): ChatMessage[] {
    let keptWelcome = false
    const kept: ChatMessage[] = []
    for (const message of list) {
      if (!isWelcomeMessage(message)) {
        kept.push(message)
        continue
      }
      if (keptWelcome || kept.length) continue
      keptWelcome = true
      kept.push(message)
    }
    return kept
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

  function persistSessionMeta(list: ChatMessage[], metaKey = sessionMetaKey.value, sid = sessionId.value, cacheTruncated = false): void {
    try {
      const meaningful = list.filter((msg) => hasMeaningfulContent(msg.content) && !isWelcomeMessage(msg))
      if (!meaningful.length) {
        localStorage.removeItem(metaKey)
        return
      }
      let previous: Record<string, unknown> = {}
      try { previous = asRecord(JSON.parse(localStorage.getItem(metaKey) || '{}')) } catch { /* Rebuild invalid metadata. */ }
      const revision = sid === sessionId.value ? historyRevision : null
      const sameHistory = revision === null || previous.history_revision === revision
      const previousCount = Number(previous.message_count)
      const serverCount = sid === sessionId.value ? historyMessageCount : null
      // A lost save receipt may already be in SQL. Never add pending local rows to this total.
      const count = serverCount ?? (sameHistory && previous.cache_truncated === true && Number.isSafeInteger(previousCount)
        && previousCount >= 0 ? previousCount : meaningful.length)
      localStorage.setItem(
        metaKey,
        JSON.stringify({
          session_id: String(sid || 'default'),
          title: (sid === sessionId.value && historyTitle) || (sameHistory && asString(previous.title).trim()) || deriveSessionTitle(list),
          message_count: count,
          history_revision: revision ?? previous.history_revision ?? null,
          cache_truncated: cacheTruncated || (sameHistory && previous.cache_truncated === true),
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
          uiKey: chatMessageKey(row as unknown as ChatMessage),
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
      persistence: localMessagePersistence(),
      ...(extras || {}),
    })
    persistMessagesCache()

    // TTS 语音播报（仅 AI 消息且非欢迎消息）
    if (options?.speak && role === 'ai' && !isWelcomeMessage({ role, content: safeContent })) {
      queueVoice(safeContent)
    }
  }

  const { saveMessage, retryMessageSave } = useChatMessagePersistence({
    messages, sessionId,
    revision: sid => sid === sessionId.value ? historyRevision ?? 0 : 0,
    scope: () => `${buildChatMessagesKey('scope', String(activeModId.value || ''))}:${productReadAccountEpoch.value}`,
    read: (sid) => {
      if (sid === sessionId.value) return messages.value
      const key = buildChatMessagesKey(sid, String(activeModId.value || ''))
      const store = chatMessageStores.get(key)
      if (store) return store.messages.value
      try { return sanitizeMessagesList(JSON.parse(localStorage.getItem(key) || '[]')) }
      catch { return [] }
    },
    persist: (list, sid) => persistMessagesCache(list, buildChatMessagesKey(sid, String(activeModId.value || '')), buildChatSessionMetaKey(sid, String(activeModId.value || '')), sid),
    plainText: toPlainText,
    html: (text) => escapeHtml(text).replace(/\n/g, '<br>'),
  })

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
  function pushStreamingAiShell(list = messages.value, persist = persistMessagesCache): number {
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    list.push({
      role: 'ai',
      content: '',
      time,
      streamingShell: true,
      persistence: localMessagePersistence(),
    })
    persist()
    return list.length - 1
  }

  /** 将纯文本安全转为气泡 HTML 并写入指定下标（用于 SSE token 追加） */
  function applyPlainTextToMessageIndex(index: number, plain: string, extras?: ChatMessageExtras,
    list = messages.value, schedule = scheduleMessagesCache) {
    const safe = escapeHtml(stripModelToolProtocol(plain)).replace(/\n/g, '<br>')
    const row = list[index]
    if (!row) return
    row.content = safe
    if (extras) Object.assign(row, extras)
    if (safe) {
      delete row.streamingShell
    } else {
      row.streamingShell = true
    }
    schedule()
  }

  // Keep the original store alive while the view is displaying another session.
  function retainConversationMessages(sid = sessionId.value) {
    const modId = String(activeModId.value || '')
    const key = buildChatMessagesKey(sid, modId)
    const metaKey = buildChatSessionMetaKey(sid, modId)
    const store = acquireChatMessageStore(key, () => readCachedMessages(key))
    const persist = () => persistMessagesCache(store.messages.value, key, metaKey, sid)
    return {
      messages: store.messages,
      pushStreamingAiShell: () => pushStreamingAiShell(store.messages.value, persist),
      applyPlainTextToMessageIndex: (index: number, plain: string, extras?: ChatMessageExtras) =>
        applyPlainTextToMessageIndex(index, plain, extras, store.messages.value, () => {
          if (key === activeStoreKey) scheduleMessagesCache()
        }),
      persist,
      release: () => releaseChatMessageStore(key, store),
    }
  }

  function clearMessages() {
    resetHistoryPage()
    messages.value = []
    persistMessagesCache()
  }

  function loadMessages(newMessages: ChatMessage[], page?: Record<string, unknown>) {
    if (page) setHistoryPage(page)
    const sanitized = sanitizeMessagesList(newMessages)
    reconcileApprovalCards(sanitized)
    messages.value = sanitized
    restoreModelRoute()
    persistMessagesCache()
  }

  async function syncFromServer(options: { required?: boolean; isCurrent?: () => boolean; onConversation?: (data: unknown) => void } = {}): Promise<boolean> {
    try {
      const sid = String(sessionId.value || '').trim()
      if (!sid) { if (options.required) throw new Error('当前会话未就绪'); return false }
      const sessionCurrent = captureAuthSession()
      const scope = [sid, activeModId.value, productReadAccountEpoch.value]
      const revision = JSON.stringify(messages.value)
      const data = await chatApi.getConversation(sid)
      if (!sessionCurrent() || options.isCurrent?.() === false ||
        scope.some((value, i) => value !== [sessionId.value, activeModId.value, productReadAccountEpoch.value][i])
        || revision !== JSON.stringify(messages.value)) {
        if (options.required) throw new Error('当前会话已改变，请重试')
        return false
      }
      const dataRow = asRecord(data)
      if (options.required && (dataRow.success !== true || !Array.isArray(dataRow.messages)
        || dataRow.id !== sid)) {
        throw new Error('当前会话内容未确认，请重试')
      }
      const sameRevision = historyRevision !== null && historyRevision === dataRow.revision
      const serverMessages = asArray(dataRow.messages)
      if (!serverMessages.length) {
        setHistoryPage(dataRow)
        if (dataRow.durable === true && dataRow.revision === null) loadMessages([])
        options.onConversation?.(dataRow)
        return options.required === true
      }

      const mapped = fromServerRows(serverMessages, dataRow.durable)
      const sanitized = sanitizeMessagesList(mapped)
      if (!sanitized.length) { if (options.required) throw new Error('当前会话内容无法读取，请重试'); return false }
      const localList = messages.value
      const lastLocal = localList[localList.length - 1]
      const serverTurnIds = new Set(sanitized.map(message => message.turnId).filter(Boolean))
      // 原地复用本地消息对象：对象身份稳定，列表 key 才不会在同步后整列变化。
      const matched = new Set<number>()
      const mergedServer = sanitized.map((server) => {
        const index = localList.findIndex((local, i) => !matched.has(i) && samePersistedMessage(local, server, toPlainText))
        if (index < 0) return server
        matched.add(index)
        return Object.assign(localList[index], server, { uiKey: chatMessageKey(localList[index]) })
      })
      const unsaved = localList.filter((local, index) => {
        if (matched.has(index)) return false
        if (typeof dataRow.revision === 'number' && local.persistence?.request
          && (local.persistence.request.expected_revision ?? 0) !== dataRow.revision) return false
        if (local.persistence?.status === 'saved') return false
        // 服务端已有同一轮次：本地这条只是同一问题的副本（附件证据会改写服务端正文，
        // 按文本匹配不到）。保留它会在每次同步时追加到末尾并再次落库，形成重复提问。
        if (local.role === 'user' && local.turnId && serverTurnIds.has(local.turnId)) return false
        // 没有进行中的轮次、且本轮 turnId 不在服务端：这是从未真正发出的孤儿提问
        // （例如视图已被替换导致请求没发出去），保留它只会在每次同步时被追加到末尾。
        if (local.role === 'user' && local.turnId && !busy() && !serverTurnIds.has(local.turnId)) return false
        // 已被后续对话取代的本地失败回执没有保存价值：它永远匹配不到服务端，
        // 每次同步都会被追加到末尾，把真正的最新回复挤到上面，看起来像“AI 没回”。
        if (isSupersededTransportFailure(local)) {
          const completedOnServer = Boolean(local.turnId) && serverTurnIds.has(local.turnId)
          if (completedOnServer || local !== lastLocal) return false
        }
        return true
      })
      const firstServerId = Number(asRecord(serverMessages[0]).id)
      const older = sameRevision && dataRow.has_more === true ? localList.filter(message => {
        const id = message.serverMessageId ?? Number(message.persistence?.id?.replace(/^server:/, ''))
        return message.persistence?.status === 'saved' && id > 0 && id < firstServerId
      }) : []
      // A latest-page refresh must keep the oldest loaded boundary, including exhaustion.
      setHistoryPage(older.length ? { ...dataRow,
        has_more: messagesHaveEarlier.value, next_before_id: beforeMessageId,
      } : dataRow)
      const next = withoutRepeatedWelcomes([...older, ...mergedServer, ...unsaved.filter(message => !isWelcomeMessage(message))])
      const unchanged = next.length === localList.length && next.every((message, index) => message === localList[index])
      if (!unchanged) loadMessages(next)
      else persistMessagesCache()
      options.onConversation?.(dataRow)
      return true
    } catch (_e) {
      if (options.required) throw _e
      return false
    }
  }

  watch(
    () => sessionId.value,
    () => {
      switchActiveStore()
      resetHistoryPage()
      activeStore.value.cacheError.value = ''
      restoreModelRoute()
    },
    { flush: 'sync' },
  )

  // 切换当前扩展（Mod）时：同一会话 ID 下不同 Mod 的消息缓存相互隔离，
  // 切换后应重新读取当前 Mod 对应的本地消息（若无缓存则展示欢迎语）。
  watch(
    () => [String(activeModId.value || ''), productReadAccountEpoch.value, resolveChatStorageScope()] as const,
    () => {
      // 每个缓存键都是独立单例：身份从临时作用域切到已登录作用域时，
      // 直接切到新键自己的缓存，不把临时欢迎语复制过去。
      switchActiveStore()
      resetHistoryPage()
      activeStore.value.cacheError.value = ''
      restoreModelRoute()
    },
    { flush: 'sync' },
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
        sameAsPrevious: message.sameAsPrevious,
        routeMetadata: message.routeMetadata,
        runtimeContinuation: message.runtimeContinuation,
      })),
    () => persistMessagesCache(),
    { deep: true, flush: 'post' },
  )

  return {
    messages,
    messagesHaveEarlier, earlierMessagesLoading, earlierMessagesError, loadEarlierMessages,
    cacheError,
    retryMessagesCache: () => persistMessagesCache(),
    retryMessageSave,
    lastMessage,
    addMessage,
    saveMessage,
    addAndSaveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    retainConversationMessages,
    flushMessagesCache,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  }
}
