import { computed, nextTick, ref, type Ref } from 'vue'
import {
  fetchEnterpriseCsThread,
  type ImConversationSummary,
  type ImMessage,
} from '@/api/im'

type Options = {
  enabled: boolean
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  messages: Ref<ImMessage[]>
  playIncoming: (body: string) => void | Promise<void>
  scrollToBottom: () => void
}

/** Poll the canonical production CS thread while the local fixed contact is open. */
export function useEnterpriseCsBridge(options: Options) {
  const enterpriseCsError = ref('')
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollBusy = false

  function customerConversation(id = options.activeConversationId.value) {
    const conv = options.conversations.value.find((item) => item.id === id)
    return conv?.is_enterprise_dedicated_cs && !conv.is_cs_inbox ? conv : undefined
  }
  const activeCustomerCsConversation = computed(() => customerConversation())
  const isCustomerEnterpriseCs = (id = options.activeConversationId.value) => Boolean(options.enabled && customerConversation(id))

  function stopPolling(): void {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  async function refreshThread(notifyIncoming = true): Promise<void> {
    const localId = options.activeConversationId.value
    if (!localId || !isCustomerEnterpriseCs(localId) || pollBusy) return
    pollBusy = true
    try {
      const oldIds = new Set(options.messages.value.map((item) => item.id))
      const thread = await fetchEnterpriseCsThread()
      if (options.activeConversationId.value !== localId) return
      enterpriseCsError.value = ''
      options.messages.value = thread.messages
      const local = options.conversations.value.find((item) => item.id === localId)
      const last = thread.messages[thread.messages.length - 1]
      if (local) {
        const { id: remoteId, ...remoteState } = thread.conversation
        Object.assign(local, remoteState, {
          remote_conversation_id: remoteId,
          last_message_at: last?.created_at ?? null,
          last_message_preview: last?.body ?? '',
        })
      }
      const incoming = thread.messages.find((item) => !oldIds.has(item.id) && !item.is_self)
      if (notifyIncoming && incoming) void options.playIncoming(incoming.body)
      await nextTick()
      options.scrollToBottom()
    } catch (error) {
      if (options.activeConversationId.value === localId) enterpriseCsError.value = error instanceof Error ? error.message : '企业专属客服读取失败'
      if (!notifyIncoming) throw error
    } finally {
      pollBusy = false
    }
  }

  function startPolling(): void {
    stopPolling()
    pollTimer = setInterval(() => void refreshThread(), 2500)
  }

  return {
    enterpriseCsError,
    activeCustomerCsConversation,
    isCustomerEnterpriseCs,
    refreshEnterpriseCsThread: refreshThread,
    startEnterpriseCsPolling: startPolling,
    stopEnterpriseCsPolling: stopPolling,
  }
}
