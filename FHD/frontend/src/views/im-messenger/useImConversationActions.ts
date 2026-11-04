/** IM 会话选择与发送；客服错误保留到恢复成功。 */
import { nextTick, watch, type Ref } from 'vue'
import {
  fetchCsInboxMessages,
  fetchImMessages,
  markImRead,
  replyCsInbox,
  sendEnterpriseCsMessage,
  sendImMessage,
  type ImConversationSummary,
  type ImMessage,
} from '@/api/im'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { showAppToast } from '@/composables/useAppToast'
import type { ExternalAppEntry, SystemEmployeeEntry } from '@/composables/messenger/useMessengerEntries'

type Options = {
  localUserId: Ref<number | null>
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  activeSystemEntry: Ref<SystemEmployeeEntry | null>
  activeExternalEntry: Ref<ExternalAppEntry | null>
  activeGroupChat: Ref<boolean>
  messages: Ref<ImMessage[]>
  draft: Ref<string>
  enterpriseCsError?: Ref<string>
  enterpriseCsUnconfirmed?: Ref<boolean>
  busy: Ref<boolean>
  hasMoreHistory: Ref<boolean>
  dutyEmployeeDraft: Ref<string>
  isCustomerEnterpriseCs: (id?: number) => boolean
  refreshEnterpriseCsThread: (reset?: boolean) => Promise<void>
  startEnterpriseCsPolling: () => void
  stopEnterpriseCsPolling: () => void
  refreshCsInbox: () => Promise<void>
  startCsInboxPolling: () => void
  stopCsInboxPolling: () => void
  restoreOverlappingAssistantFloat: () => void
  stopCodexPolling: () => void
  stopCodexTypewriter: (immediate?: boolean) => void
  scrollToBottom: () => void
  loadConversations: () => Promise<void>
  playOutgoing: () => void
}

export function useImConversationActions(options: Options) {
  const {
    localUserId,
    conversations,
    activeConversationId,
    activeSystemEntry,
    activeExternalEntry,
    activeGroupChat,
    messages,
    draft,
    busy,
    hasMoreHistory,
    dutyEmployeeDraft,
    isCustomerEnterpriseCs,
    refreshEnterpriseCsThread,
    startEnterpriseCsPolling,
    stopEnterpriseCsPolling,
    refreshCsInbox,
    startCsInboxPolling,
    stopCsInboxPolling,
    restoreOverlappingAssistantFloat,
    stopCodexPolling,
    stopCodexTypewriter,
    scrollToBottom,
    loadConversations,
    playOutgoing,
  } = options

  let operation = 0
  let selectionEpoch = 0
  watch([activeConversationId, productReadAccountEpoch], () => { selectionEpoch++; operation++; busy.value = false }, { flush: 'sync' })

  async function selectConversation(id: number): Promise<void> {
    if (!localUserId.value) return
    stopEnterpriseCsPolling()
    stopCsInboxPolling()
    restoreOverlappingAssistantFloat()
    stopCodexPolling()
    stopCodexTypewriter(true)
    dutyEmployeeDraft.value = ''
    activeExternalEntry.value = null
    activeSystemEntry.value = null
    activeGroupChat.value = false
    activeConversationId.value = id
    const owner = ++operation
    const epoch = productReadAccountEpoch.value
    const selection = selectionEpoch
    const current = () => owner === operation && epoch === productReadAccountEpoch.value && selection === selectionEpoch
    busy.value = true
    try {
      const conv = conversations.value.find((c) => c.id === id)
      const isCs = Boolean(conv?.is_cs_inbox)
      const isCustomerCs = isCustomerEnterpriseCs(id)
      if (isCustomerCs) {
        await refreshEnterpriseCsThread(false)
      } else {
        const loaded = isCs ? await fetchCsInboxMessages(id) : await fetchImMessages(id, { limit: 50 })
        if (!current()) return
        messages.value = loaded
      }
      if (!current()) return
      hasMoreHistory.value = !isCs && !isCustomerCs && messages.value.length >= 50
      await nextTick()
      scrollToBottom()
      if (!isCs && !isCustomerCs) {
        const last = messages.value[messages.value.length - 1]
        if (last) {
          await markImRead(id, last.id)
        }
      }
      if (isCustomerCs) startEnterpriseCsPolling()
      else if (isCs) startCsInboxPolling()
      else await loadConversations()
    } catch (error) {
      if (current()) showAppToast(error instanceof Error ? error.message : '加载消息失败', 'error')
    } finally {
      if (owner === operation) busy.value = false
    }
  }

  async function onSend(): Promise<void> {
    if (busy.value) return
    const epoch = productReadAccountEpoch.value
    const selection = selectionEpoch
    const originalDraft = draft.value
    const id = activeConversationId.value
    const text = draft.value.trim()
    if (!id || !text || !localUserId.value) return
    const conv = conversations.value.find((c) => c.id === id)
    const isCs = Boolean(conv?.is_cs_inbox)
    const isCustomerCs = isCustomerEnterpriseCs(id)
    if (isCustomerCs && options.enterpriseCsUnconfirmed?.value) return
    const owner = ++operation
    busy.value = true
    try {
      let msg: ImMessage
      if (isCustomerCs) {
        // Persist uncertainty before dispatch so navigation cannot lose replay protection.
        if (options.enterpriseCsUnconfirmed) options.enterpriseCsUnconfirmed.value = true
        const sent = await sendEnterpriseCsMessage(text)
        if (activeConversationId.value !== id || productReadAccountEpoch.value !== epoch || selectionEpoch !== selection) return
        msg = sent.message
        if (conv) {
          Object.assign(conv, sent.state, { remote_conversation_id: sent.conversation_id })
        }
      } else {
        msg = isCs ? await replyCsInbox(id, text) : await sendImMessage(id, text)
      }
      if (activeConversationId.value !== id || productReadAccountEpoch.value !== epoch || selectionEpoch !== selection) return
      messages.value.push(msg)
      if (draft.value === originalDraft) draft.value = ''
      if (isCustomerCs && options.enterpriseCsError) options.enterpriseCsError.value = ''
      if (isCustomerCs && options.enterpriseCsUnconfirmed) options.enterpriseCsUnconfirmed.value = false
      playOutgoing()
      await nextTick()
      scrollToBottom()
      if (isCustomerCs) await refreshEnterpriseCsThread()
      else if (isCs) await refreshCsInbox()
      else await loadConversations()
    } catch (error) {
      if (activeConversationId.value !== id || productReadAccountEpoch.value !== epoch || selectionEpoch !== selection) return
      if (isCustomerCs && options.enterpriseCsError) options.enterpriseCsError.value = error instanceof Error ? error.message : '发送失败'
      if (isCustomerCs && options.enterpriseCsUnconfirmed) options.enterpriseCsUnconfirmed.value = !(error instanceof Error && 'reconciliationRequired' in error && error.reconciliationRequired === false)
      showAppToast(error instanceof Error ? error.message : '发送失败', 'error')
    } finally {
      if (owner === operation) busy.value = false
    }
  }

  return { selectConversation, onSend }
}
