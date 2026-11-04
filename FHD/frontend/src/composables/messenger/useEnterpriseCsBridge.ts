import { computed, nextTick, ref, watch, type Ref } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { captureMessageScroll } from './useChatSession'
import { reconcileImSnapshot, useVisiblePolling } from './useVisiblePolling'
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
  scrollEl: Ref<HTMLElement | null>
}

/** Poll the canonical production CS thread while the local fixed contact is open. */
export function useEnterpriseCsBridge(options: Options) {
  const enterpriseCsReadError = ref('')
  const enterpriseCsSendError = ref('')
  const enterpriseCsUnconfirmed = ref(false)
  const enterpriseCsError = computed(() => enterpriseCsSendError.value || enterpriseCsReadError.value)
  let busySelection: number | null = null
  let selectionEpoch = 0
  const polling = useVisiblePolling(() => readThread())
  watch(options.activeConversationId, () => { selectionEpoch++; polling.stop() }, { flush: 'sync' })
  watch(productReadAccountEpoch, () => {
    selectionEpoch++
    polling.stop()
    options.messages.value = []
    enterpriseCsReadError.value = ''
  }, { flush: 'sync' })

  function customerConversation(id = options.activeConversationId.value) {
    const conv = options.conversations.value.find((item) => item.id === id)
    return conv?.is_enterprise_dedicated_cs && !conv.is_cs_inbox ? conv : undefined
  }
  const activeCustomerCsConversation = computed(() => customerConversation())
  const isCustomerEnterpriseCs = (id = options.activeConversationId.value) => Boolean(options.enabled && customerConversation(id))

  async function readThread(notifyIncoming = true): Promise<boolean> {
    const localId = options.activeConversationId.value
    if (!localId || !isCustomerEnterpriseCs(localId) || busySelection === selectionEpoch) return false
    const accountEpoch = productReadAccountEpoch.value
    const selection = selectionEpoch
    busySelection = selection
    const current = () => options.activeConversationId.value === localId && selection === selectionEpoch && accountEpoch === productReadAccountEpoch.value
    try {
      const oldIds = new Set(options.messages.value.map((item) => item.id))
      const thread = await fetchEnterpriseCsThread()
      if (!current()) return false
      const restoreScroll = captureMessageScroll(options.scrollEl)
      enterpriseCsReadError.value = ''
      const update = reconcileImSnapshot(options.messages.value, thread.messages)
      options.messages.value = update.items
      const local = options.conversations.value.find((item) => item.id === localId)
      const last = thread.messages[thread.messages.length - 1]
      let conversationChanged = false
      if (local) {
        const { id: remoteId, ...remoteState } = thread.conversation
        const next = { ...local, ...remoteState,
          remote_conversation_id: remoteId,
          last_message_at: last?.created_at ?? null,
          last_message_preview: last?.body ?? '',
        }
        conversationChanged = reconcileImSnapshot([local], [next]).changed
        if (conversationChanged) Object.assign(local, next)
      }
      const incoming = thread.messages.find((item) => !oldIds.has(item.id) && !item.is_self)
      if (notifyIncoming && incoming) void options.playIncoming(incoming.body)
      if (update.changed) {
        await nextTick()
        if (current()) restoreScroll()
      }
      return update.changed || conversationChanged || local?.cs_status === 'ai_processing' || enterpriseCsUnconfirmed.value
    } catch (error) {
      if (current()) enterpriseCsReadError.value = error instanceof Error ? error.message : '企业专属客服读取失败'
      if (!notifyIncoming) throw error
      return false
    } finally {
      if (busySelection === selection) busySelection = null
    }
  }

  function startPolling(): void {
    polling.stop()
    if (isCustomerEnterpriseCs()) polling.start()
  }

  return {
    enterpriseCsError,
    enterpriseCsSendError,
    enterpriseCsUnconfirmed,
    activeCustomerCsConversation,
    isCustomerEnterpriseCs,
    refreshEnterpriseCsThread: async (notifyIncoming = true): Promise<void> => { await readThread(notifyIncoming) },
    startEnterpriseCsPolling: startPolling,
    stopEnterpriseCsPolling: polling.stop,
  }
}
