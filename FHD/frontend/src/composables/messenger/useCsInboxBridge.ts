import { nextTick, type Ref } from 'vue'
import { fetchCsInbox, fetchCsInboxMessages, type ImConversationSummary, type ImMessage } from '@/api/im'

type Options = {
  enabled: Ref<boolean>
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  messages: Ref<ImMessage[]>
  playIncoming: (body: string) => void | Promise<void>
  scrollToBottom: () => void
}

/** Keep the selected admin CS inbox thread in sync with the production SSOT. */
export function useCsInboxBridge(options: Options) {
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollBusy = false

  function isActiveCsInbox(id = options.activeConversationId.value): boolean {
    if (!options.enabled.value || !id) return false
    return Boolean(options.conversations.value.find((item) => item.id === id)?.is_cs_inbox)
  }

  function stopPolling(): void {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  async function refreshInbox(): Promise<void> {
    const activeId = options.activeConversationId.value
    if (!activeId || !isActiveCsInbox(activeId) || pollBusy) return
    pollBusy = true
    try {
      const oldIds = new Set(options.messages.value.map((item) => item.id))
      const [inbox, remoteMessages] = await Promise.all([fetchCsInbox(), fetchCsInboxMessages(activeId)])
      if (options.activeConversationId.value !== activeId || !options.enabled.value) return

      const regular = options.conversations.value.filter((item) => !item.is_cs_inbox)
      const regularIds = new Set(regular.map((item) => item.id))
      options.conversations.value = [...inbox.filter((item) => !regularIds.has(item.id)), ...regular]
      options.messages.value = remoteMessages

      const active = options.conversations.value.find((item) => item.id === activeId)
      const last = remoteMessages[remoteMessages.length - 1]
      if (active) {
        active.unread_count = 0
        active.last_message_at = last?.created_at ?? active.last_message_at
        active.last_message_preview = last?.body ?? ''
      }
      const incoming = remoteMessages.find((item) => !oldIds.has(item.id) && (item.origin === 'customer' || item.is_self === false))
      if (incoming) void options.playIncoming(incoming.body)
      if (remoteMessages.some((item) => !oldIds.has(item.id))) {
        await nextTick()
        options.scrollToBottom()
      }
    } catch {
      // The regular IM websocket remains usable; retry this production bridge on the next tick.
    } finally {
      pollBusy = false
    }
  }

  function startPolling(): void {
    stopPolling()
    if (!isActiveCsInbox()) return
    pollTimer = setInterval(() => void refreshInbox(), 2500)
  }

  return {
    refreshCsInbox: refreshInbox,
    startCsInboxPolling: startPolling,
    stopCsInboxPolling: stopPolling,
  }
}
