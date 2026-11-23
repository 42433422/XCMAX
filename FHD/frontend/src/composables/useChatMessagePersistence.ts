import type { Ref } from 'vue'
import chatApi from '@/api/chat'
import type { UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'
import { stripModelToolProtocol } from '@/utils/chatModelProtocol'
import { restoreRuntimeContinuation } from '@/utils/chatRuntimeContinuation'
import { activeChatTurnStatus } from '@/utils/droppedRoundPresentation'
import { chatExecutionOutcome } from '@/components/chat/chatFailureRecovery'
import { asString } from '@/utils/typeGuards'

export const CHAT_HISTORY_PAGE_SIZE = 80
export const CHAT_RESIDENT_MESSAGES = 160
export const CHAT_RESIDENT_BYTES = 512 * 1024
export const CHAT_CACHE_MESSAGES = 40
export const CHAT_CACHE_BYTES = 128 * 1024

export function serverId(message?: UiChatMessage): number | undefined {
  const id = message?.serverMessageId ?? Number(/^server:(\d+)$/.exec(message?.persistence?.id || '')?.[1])
  return Number.isSafeInteger(id) && id > 0 ? id : undefined
}

/** Only acknowledged, settled SQL history may be evicted. Work still needing a decision stays resident. */
export function pinnedMessage(message: UiChatMessage): boolean {
  const active = (status?: string) => !!status && activeChatTurnStatus(status) !== undefined
  const result = message.businessResult
  return message.persistence?.status !== 'saved' || message.persistence.durable !== true || !serverId(message) || !!message.persistence.request
    || !!message.streamingShell || active(message.streamStatus)
    || !!message.approvalCard && (!message.approvalCard.status || message.approvalCard.status === 'pending' || !!message.approvalCard.submitting)
    || active(message.runtimeContinuation?.status) || message.agentRunTrace?.terminal !== true && active(message.agentRunTrace?.status)
    || active(message.workflowAction) || !!message.execution && ['unknown', 'partial'].includes(chatExecutionOutcome(message.execution))
    || message.agentRunTrace?.terminal !== true && active(message.executionProgress?.at(-1)?.status)
    || active(asString(result?.status)) || result?.pending_approval === true || result?.requires_reconciliation === true
    || result?.reconciliation_required === true || result?.outcome_unknown === true
}

export const serializedBytes = (message: UiChatMessage, budget = CHAT_RESIDENT_BYTES) =>
  message.content.length > budget ? budget + 1 : new TextEncoder().encode(JSON.stringify(message)).length

/** A contiguous SQL window, plus separately pinned work. One explicitly read row may exceed the resident budget. */
export function historyWindow(list: UiChatMessage[], newer = true, limit = CHAT_RESIDENT_MESSAGES,
  budget = CHAT_RESIDENT_BYTES, allowOversized = true): UiChatMessage[] {
  let count = 0, bytes = 2, edge = newer ? list.length : 0
  for (let i = newer ? list.length - 1 : 0; newer ? i >= 0 : i < list.length; i += newer ? -1 : 1) {
    const message = list[i]
    if (!pinnedMessage(message)) {
      const size = serializedBytes(message, budget) + 1
      if (count >= limit || bytes + size > budget && !(allowOversized && count === 0)) break
      count++
      bytes += size
    }
    edge = newer ? i : i + 1
  }
  return newer ? list.slice(edge) : list.slice(0, edge)
}

export function withPinned(window: UiChatMessage[], all: UiChatMessage[]): UiChatMessage[] {
  const retained = [...window]
  for (const message of all) if (pinnedMessage(message) && !retained.some(row =>
    row === message || row.uiKey && row.uiKey === message.uiKey
    || row.persistence?.id && row.persistence.id === message.persistence?.id)) retained.push(message)
  return retained.sort((a, b) => (serverId(a) ?? Number.MAX_SAFE_INTEGER) - (serverId(b) ?? Number.MAX_SAFE_INTEGER))
}

/** The single bootstrap-cache policy; durable SQL pages remain the history source of truth. */
export function boundedChatMessageCache(messages: UiChatMessage[]): UiChatMessage[] {
  return withPinned(historyWindow(messages, true, CHAT_CACHE_MESSAGES, CHAT_CACHE_BYTES, false), messages)
}

export function localMessagePersistence(): NonNullable<UiChatMessage['persistence']> {
  return { id: createBusinessHarnessId('message'), status: 'local' }
}

export function samePersistedMessage(local: UiChatMessage, server: UiChatMessage, plainText: (html: string) => string): boolean {
  const localId = local.persistence?.id, serverId = server.persistence?.id
  if (localId && serverId) {
    if (localId === serverId) return true
    // server:<row.id> identifies a legacy row without a client-message binding.
    if (localId.startsWith('server:') === serverId.startsWith('server:')) return false
  }
  if (local.role !== server.role) return false
  const text = (message: UiChatMessage) => plainText(message.content).trim()
  const failureText = (message: UiChatMessage) => text(message).replace(/^处理失败[：:]\s*/, '')
  const failed = (message: UiChatMessage) => ['failed', 'error', 'workflow_failed', 'planner_failed'].includes(message.workflowAction || '')
    || message.agentRunTrace?.status === 'failed' || failureText(message) === '模型未返回可显示的正文，已停止重复请求。请检查模型服务后重试。'
  const sameText = () => local.role === 'ai' && (local.turnId && server.turnId || failed(local) && failed(server))
    ? failureText(local) === failureText(server) : text(local) === text(server)
  if (local.turnId && server.turnId) return local.turnId === server.turnId && sameText()
  if (local.persistence?.request && local.persistence.status !== 'saved') return false
  return local.time === server.time && sameText()
}

export function useChatMessagePersistence(deps: {
  messages: Ref<UiChatMessage[]>
  sessionId: Ref<string>
  scope: () => string
  revision?: (sessionId: string) => number
  read: (sessionId: string) => UiChatMessage[]
  persist: (messages: UiChatMessage[], sessionId: string) => void
  plainText: (html: string) => string
  html: (text: string) => string
}) {
  const inFlight = new Map<string, Promise<void>>()

  async function persistMessage(message: UiChatMessage, list: UiChatMessage[], sessionId: string): Promise<void> {
    const scope = deps.scope()
    const state = message.persistence
    if (!state?.request || state.status === 'saved') return
    const key = JSON.stringify([scope, sessionId, state.id])
    const existing = inFlight.get(key)
    if (existing) return existing
    const request = { ...state.request }
    state.status = 'saving'
    state.error = ''
    deps.persist(list, sessionId)
    const save = (async () => {
      let serverMessageId: number | undefined
      try {
        const response = await (request.turn_id
          ? chatApi.retryTurnPersistence(sessionId, request.turn_id, request.expected_revision ?? 0)
          : chatApi.saveMessage({
          session_id: sessionId,
          user_id: 'default',
          client_message_id: state.id,
          ...request,
        })) as { success?: boolean; saved?: boolean; durable?: boolean; message_id?: number; message_ids?: number[] }
        if (deps.scope() !== scope) return
        if (response?.success !== true || response.saved !== true) throw new Error('save not acknowledged')
        state.status = response.durable === true ? 'saved' : 'local'
        if (response.durable === true) state.durable = true
        else delete state.durable
        state.error = response.durable === true ? '' : '服务端未确认持久保存，当前仅保留本机副本。'
        if (state.status === 'saved') {
          const ids = response.message_ids
          serverMessageId = message.role === 'user' ? ids?.[0] : ids?.at(-1)
          serverMessageId ??= response.message_id
          delete state.request
          if (request.turn_id && ids?.length) {
            for (const row of list) if (row.turnId === request.turn_id && row !== message) {
              row.serverMessageId = row.role === 'user' ? ids[0] : ids[ids.length - 1]
              row.persistence = { id: `server:${row.serverMessageId}`, status: 'saved', durable: true }
            }
          }
        }
      } catch {
        if (deps.scope() !== scope) return
        state.status = 'failed'
        state.error = '消息保存未确认。可仅重试保存，不会重新执行任务。'
      } finally {
        inFlight.delete(key)
        if (deps.scope() === scope) {
          const current = deps.read(sessionId)
          const currentMessage = current.find(item => item.persistence?.id === state.id)
          // A deleted message/session must not be recreated by a late save receipt.
          if (currentMessage) {
            currentMessage.persistence = { ...state }
            if (serverMessageId !== undefined) currentMessage.serverMessageId = serverMessageId
            deps.persist(current, sessionId)
          }
        }
      }
    })()
    inFlight.set(key, save)
    await save
  }

  async function saveMessage(
    role: 'user' | 'ai' | 'task', content: string, targetSessionId?: string, extras?: UiChatMessageExtras,
  ): Promise<void> {
    const visible = role === 'ai' ? stripModelToolProtocol(content) : content
    if (!visible.trim()) return
    const sid = targetSessionId || deps.sessionId.value
    const list = deps.read(sid)
    const matching = list.filter(item => item.role === role && deps.plainText(item.content) === deps.plainText(deps.html(visible))).reverse()
    let message = matching.find(item => !item.persistence?.request && item.persistence?.status !== 'saved')
      || matching.find(item => item.persistence?.status === 'failed' || item.persistence?.status === 'saving')
    if (!message) {
      message = { role, content: deps.html(visible), time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
      list.push(message)
    }
    const continuation = role === 'ai' ? restoreRuntimeContinuation(extras?.runtimeContinuation) : undefined
    if (continuation?.sessionId === sid) message.runtimeContinuation = continuation
    message.persistence ||= localMessagePersistence()
    const ui = { ...(message.turnId ? { turnId: message.turnId } : {}), ...(extras || {}) }
    delete ui.persistence
    message.persistence.request ||= { role, content: visible, expected_revision: deps.revision?.(sid) ?? 0, ...(Object.keys(ui).length ? { metadata: JSON.stringify({ ui }) } : {}) }
    await persistMessage(message, list, sid)
  }

  async function retryMessageSave(id: string): Promise<void> {
    const message = deps.messages.value.find(item => item.persistence?.id === id)
    if (message) await persistMessage(message, deps.messages.value, deps.sessionId.value)
  }

  return { saveMessage, retryMessageSave }
}
