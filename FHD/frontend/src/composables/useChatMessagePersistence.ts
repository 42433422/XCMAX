import type { Ref } from 'vue'
import chatApi from '@/api/chat'
import type { UiChatMessage, UiChatMessageExtras } from '@/types/chat-ui'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'
import { stripModelToolProtocol } from '@/utils/chatModelProtocol'
import { restoreRuntimeContinuation } from '@/utils/chatRuntimeContinuation'

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
        state.error = response.durable === true ? '' : '服务端未确认持久保存，当前仅保留本机副本。'
        if (state.status === 'saved') {
          const ids = response.message_ids
          serverMessageId = message.role === 'user' ? ids?.[0] : ids?.at(-1)
          serverMessageId ??= response.message_id
          delete state.request
          if (request.turn_id && ids?.length) {
            for (const row of list) if (row.turnId === request.turn_id && row !== message) {
              row.persistence = { id: `server:${row.role === 'user' ? ids[0] : ids[ids.length - 1]}`, status: 'saved' }
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
