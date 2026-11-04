import { nextTick, watch, type Ref } from 'vue'
import { fetchCsInbox, fetchCsInboxMessages, type ImConversationSummary, type ImMessage } from '@/api/im'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { captureMessageScroll } from './useChatSession'
import { reconcileImSnapshot, useVisiblePolling } from './useVisiblePolling'

type Options = {
  enabled: Ref<boolean>
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  messages: Ref<ImMessage[]>
  playIncoming: (body: string) => void | Promise<void>
  scrollEl: Ref<HTMLElement | null>
}

/** Keep the selected admin CS inbox thread in sync with the production SSOT. */
export function useCsInboxBridge(options: Options) {
  let selection = 0
  let busySelection: number | null = null
  const polling = useVisiblePolling(readInbox)
  watch([options.activeConversationId, options.enabled], () => { selection++; polling.stop() }, { flush: 'sync' })
  watch(productReadAccountEpoch, () => {
    selection++
    polling.stop()
    options.messages.value = []
  }, { flush: 'sync' })

  function isActiveCsInbox(id = options.activeConversationId.value): boolean {
    if (!options.enabled.value || !id) return false
    return Boolean(options.conversations.value.find((item) => item.id === id)?.is_cs_inbox)
  }

  async function readInbox(): Promise<boolean> {
    const activeId = options.activeConversationId.value
    if (!activeId || !isActiveCsInbox(activeId) || busySelection === selection) return false
    const requestSelection = selection
    busySelection = requestSelection
    const current = () => selection === requestSelection && options.activeConversationId.value === activeId && options.enabled.value
    try {
      const oldIds = new Set(options.messages.value.map((item) => item.id))
      const [inbox, remoteMessages] = await Promise.all([fetchCsInbox(), fetchCsInboxMessages(activeId)])
      if (!current()) return false
      const restoreScroll = captureMessageScroll(options.scrollEl)

      const regular = options.conversations.value.filter((item) => !item.is_cs_inbox)
      const regularIds = new Set(regular.map((item) => item.id))
      const active = inbox.find((item) => item.id === activeId)
      const last = remoteMessages[remoteMessages.length - 1]
      if (active) {
        active.unread_count = 0
        active.last_message_at = last?.created_at ?? active.last_message_at
        active.last_message_preview = last?.body ?? ''
      }
      const conversationUpdate = reconcileImSnapshot(options.conversations.value, [...inbox.filter((item) => !regularIds.has(item.id)), ...regular])
      const messageUpdate = reconcileImSnapshot(options.messages.value, remoteMessages)
      options.conversations.value = conversationUpdate.items
      options.messages.value = messageUpdate.items
      const incoming = remoteMessages.find((item) => !oldIds.has(item.id) && (item.origin === 'customer' || item.is_self === false))
      if (incoming) void options.playIncoming(incoming.body)
      if (messageUpdate.changed) {
        await nextTick()
        if (current()) restoreScroll()
      }
      return conversationUpdate.changed || messageUpdate.changed || active?.cs_status === 'ai_processing'
    } catch {
      return false
    } finally {
      if (busySelection === requestSelection) busySelection = null
    }
  }

  function startPolling(): void {
    polling.stop()
    if (!isActiveCsInbox()) return
    polling.start()
  }

  return {
    refreshCsInbox: async (): Promise<void> => { await readInbox() },
    startCsInboxPolling: startPolling,
    stopCsInboxPolling: polling.stop,
  }
}
