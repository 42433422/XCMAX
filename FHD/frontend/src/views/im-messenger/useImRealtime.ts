import { nextTick } from 'vue'
import type { Ref } from 'vue'
import { imWebSocketUrl, markImRead, type ImConversationSummary, type ImMessage } from '@/api/im'
import { isCustomerEnterpriseCs } from '@/composables/messenger/useEnterpriseCsBridge'

/** ImMessengerView 实时通道依赖（与拆分前闭包引用一一对应） */
export interface ImRealtimeDeps {
  localUserId: Ref<number | null>
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  messages: Ref<ImMessage[]>
  wsConnected: Ref<boolean>
  wsConnecting: Ref<boolean>
  scrollToBottom: () => void
  loadConversations: () => Promise<void>
  playIncoming: (body: string) => unknown
}

/** ImMessengerView 的 WebSocket / 实时消息处理逻辑（与拆分前逐字一致） */
export function useImRealtime(deps: ImRealtimeDeps) {
  const {
    localUserId,
    conversations,
    activeConversationId,
    messages,
    wsConnected,
    wsConnecting,
    scrollToBottom,
    loadConversations,
    playIncoming,
  } = deps

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempt = 0

  function applyIncomingMessage(msg: ImMessage, cid: number): void {
    // 上游行为守卫（企业客服会话由 enterprise CS bridge 专管，不走通用实时路径）
    if (isCustomerEnterpriseCs(cid)) return
    if (cid === activeConversationId.value) {
      if (!messages.value.some((m) => m.id === msg.id)) {
        messages.value.push(msg)
        void nextTick().then(scrollToBottom)
        void markImRead(cid, msg.id)
      }
    }
    if (msg.sender_user_id !== localUserId.value) {
      void playIncoming(msg.body)
    }
    void loadConversations()
  }

  function applyReadState(conversationId: number, userId: number, lastMessageId: number): void {
    if (userId !== localUserId.value) return
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (conv) {
      conv.unread_count = 0
    }
    if (conversationId === activeConversationId.value && lastMessageId > 0) {
      void markImRead(conversationId, lastMessageId).then(() => loadConversations())
    } else {
      void loadConversations()
    }
  }

  function handleWsPayload(payload: {
    type?: string
    conversation_id?: number
    user_id?: number
    last_message_id?: number
    message?: ImMessage
  }): void {
    if (payload.type === 'pong') return
    if ((payload.type === 'im.message' || payload.type === 'message') && payload.message) {
      const cid = payload.conversation_id ?? payload.message.conversation_id
      applyIncomingMessage(payload.message, cid)
      return
    }
    if (payload.type === 'im.read') {
      const cid = Number(payload.conversation_id)
      const uid = Number(payload.user_id)
      const lastId = Number(payload.last_message_id)
      if (Number.isFinite(cid) && Number.isFinite(uid) && Number.isFinite(lastId)) {
        applyReadState(cid, uid, lastId)
      }
    }
  }

  function scheduleReconnect(): void {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt)
    reconnectTimer = setTimeout(() => {
      reconnectAttempt += 1
      connectWs()
    }, delay)
  }

  function connectWs(): void {
    if (!localUserId.value) return
    disconnectWs(false)
    try {
      wsConnecting.value = true
      ws = new WebSocket(imWebSocketUrl())
      ws.onopen = () => {
        wsConnected.value = true
        wsConnecting.value = false
        reconnectAttempt = 0
      }
      ws.onclose = () => {
        wsConnected.value = false
        wsConnecting.value = false
        scheduleReconnect()
      }
      ws.onerror = () => {
        wsConnected.value = false
        wsConnecting.value = false
      }
      ws.onmessage = (ev) => {
        try {
          handleWsPayload(JSON.parse(String(ev.data)))
        } catch {
          /* ignore */
        }
      }
    } catch {
      wsConnected.value = false
      wsConnecting.value = false
      scheduleReconnect()
    }
  }

  function disconnectWs(clearTimer = true): void {
    if (clearTimer && reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onopen = null
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      ws.close()
      ws = null
    }
    wsConnected.value = false
    wsConnecting.value = false
  }

  return {
    applyIncomingMessage,
    applyReadState,
    handleWsPayload,
    scheduleReconnect,
    connectWs,
    disconnectWs,
  }
}
