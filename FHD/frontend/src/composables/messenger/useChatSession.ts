/**
 * IM 信息页「会话连接状态」与活跃会话派生的纯视图逻辑。
 *
 * 收敛 WebSocket / API 可达性标记（wsConnected / wsConnecting / imApiReachable）
 * 及由其派生的连接文案/样式，以及活跃会话标题与气泡我方/对方判定。
 * WebSocket 的建立/重连/销毁仍由父组件负责，这里只暴露状态 ref 供其读写。
 */
import { computed, ref, type Ref } from 'vue'
import { type ImConversationSummary, type ImMessage } from '@/api/im'

export type UseChatSessionParams = {
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  localUserId: Ref<number | null>
}

export function useChatSession(params: UseChatSessionParams) {
  const { conversations, activeConversationId, localUserId } = params

  const wsConnected = ref(false)
  const wsConnecting = ref(false)
  const imApiReachable = ref(false)

  const activeTitle = computed(() => {
    const conv = conversations.value.find((c) => c.id === activeConversationId.value)
    return conv?.title || '会话'
  })

  /** 气泡我方/对方判定:CS 收件箱会话里运营者以「企业专属客服」身份,非客户发的即我方。 */
  function isMyMessage(m: ImMessage): boolean {
    const conv = conversations.value.find((c) => c.id === activeConversationId.value)
    if (conv?.is_cs_inbox) {
      return m.sender_user_id !== conv.customer_user_id
    }
    return m.sender_user_id === localUserId.value
  }

  const imConnectionClass = computed(() => {
    if (wsConnected.value) return 'is-on'
    if (imApiReachable.value) return 'is-api-on'
    return wsConnecting.value ? 'is-off' : 'is-error'
  })

  const imConnectionLabel = computed(() => {
    if (wsConnected.value) return '实时已连接'
    if (imApiReachable.value) return '接口已连接'
    return wsConnecting.value ? '正在连接...' : '连接失败'
  })

  return {
    wsConnected,
    wsConnecting,
    imApiReachable,
    activeTitle,
    isMyMessage,
    imConnectionClass,
    imConnectionLabel,
  }
}
