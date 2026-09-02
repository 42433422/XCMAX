<template>
  <div class="im-messenger">
    <div class="im-body">
      <ConversationSidebar
        :is-admin-customer-service-console="isAdminCustomerServiceConsole"
        :busy="busy"
        :im-connection-class="imConnectionClass"
        :im-connection-label="imConnectionLabel"
        :external-channel-entries="externalChannelEntries"
        :active-external-entry="activeExternalEntry"
        :sidebar-list-items="sidebarListItems"
        :sidebar-item-classes="sidebarItemClasses"
        :sidebar-item-avatar-classes="sidebarItemAvatarClasses"
        :sidebar-item-pin-classes="sidebarItemPinClasses"
        :sidebar-item-shows-pin="sidebarItemShowsPin"
        :sidebar-item-title="sidebarItemTitle"
        :sidebar-item-preview="sidebarItemPreview"
        :sidebar-item-avatar-text="sidebarItemAvatarText"
        :sidebar-item-super-avatar-src="sidebarItemSuperAvatarSrc"
        :sidebar-item-unread="sidebarItemUnread"
        @open-contact-picker="openContactPicker"
        @activate-pinned="activatePinnedEntry"
        @select-sidebar-item="selectSidebarItem"
      />

      <main v-if="activeExternalEntry" class="im-chat im-chat--external-inbox">
        <KellaiCustomerInbox />
      </main>
      <main v-else-if="activeGroupChat" class="im-chat im-chat--group-chat">
        <AiGroupChatView />
      </main>
      <SystemEmployeeChat
        v-else-if="activeSystemEntry"
        :active-system-entry="activeSystemEntry"
        :super-cli-tools="superCliTools"
        :super-cli-tool-label="superCliToolLabel"
        :system-entry-status-label="systemEntryStatusLabel"
        :system-entry-identity="systemEntryIdentity"
        :system-entry-dispatch="systemEntryDispatch"
        :system-entry-runtime-status="systemEntryRuntimeStatus"
        :system-entry-last-status="systemEntryLastStatus"
        :super-employee-avatar-key="superEmployeeAvatarKey"
        :super-employee-avatar-src="superEmployeeAvatarSrc"
        :pinned-avatar-text="pinnedAvatarText"
        :is-duty-employee-entry="isDutyEmployeeEntry"
        :is-super-employee-entry="isSuperEmployeeEntry"
        :codex-message-role-label="codexMessageRoleLabel"
        :is-codex-streaming-message="isCodexStreamingMessage"
        :format-time="formatTime"
        :codex-visible-messages="codexVisibleMessages"
        :active-duty-employee-messages="activeDutyEmployeeMessages"
        v-model:codex-draft="codexDraft"
        :codex-busy="codexBusy"
        v-model:duty-employee-draft="dutyEmployeeDraft"
        :duty-employee-busy="dutyEmployeeBusy"
        :codex-scroll-el="imChatDomRefs.codexScrollEl"
        :duty-employee-scroll-el="imChatDomRefs.dutyEmployeeScrollEl"
        :codex-input-el="imChatDomRefs.codexInputEl"
        @activate-pinned="activatePinnedEntry"
        @codex-send="onCodexSend"
        @duty-employee-send="onDutyEmployeeSend"
      />
      <ConversationChat
        v-else-if="activeConversationId"
        :active-title="activeTitle"
        :has-more-history="hasMoreHistory"
        :busy="busy"
        :messages="messages"
        v-model:draft="draft"
        :is-my-message="isMyMessage"
        :format-time="formatTime"
        :scroll-el="imChatDomRefs.scrollEl"
        :cs-automation="activeCsConversation"
        :cs-customer-state="activeCustomerCsConversation"
        :cs-automation-busy="csAutomationBusy"
        @load-older="loadOlderMessages"
        @send="onSend"
        @change-cs-mode="onChangeCsMode"
      />
      <main v-else class="im-chat im-chat--empty">
        <i class="fa fa-comment-o" aria-hidden="true"></i>
        <p>选择左侧会话开始聊天</p>
        <p class="im-empty-hint">这里是同事和客服的一对一会话；找小C办事请用侧栏「智能对话」</p>
      </main>
    </div>

    <MessengerContactPicker
      :open="contactPickerOpen"
      :keyword="contactKeyword"
      :filtered-contacts="filteredContacts"
      :contacts-loading="contactsLoading"
      @close="closeContactPicker"
      @update:keyword="contactKeyword = $event"
      @select="startChatWith"
    />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  createDirectConversation,
  fetchCsInbox,
  fetchCsInboxMessages,
  fetchImConversations,
  fetchImMessages,
  markImRead,
  replyCsInbox,
  sendEnterpriseCsMessage,
  sendImMessage,
  type ImContact,
  type ImConversationSummary,
  type ImMessage,
} from '@/api/im'
import { authApi } from '@/api/auth'
import { useImSounds } from '@/composables/useImSounds'
import { showAppToast } from '@/composables/useAppToast'
import { useXcmaxSync } from '@/composables/useXcmaxSync'
import { isDesktopShell } from '@/utils/desktopShell'
import { useChatSession } from '@/composables/messenger/useChatSession'
import { useContactPicker } from '@/composables/messenger/useContactPicker'
import { useConversationList } from '@/composables/messenger/useConversationList'
import { useCsInboxBridge } from '@/composables/messenger/useCsInboxBridge'
import { useCustomerServiceAutomation } from '@/composables/messenger/useCustomerServiceAutomation'
import { useEnterpriseCsBridge } from '@/composables/messenger/useEnterpriseCsBridge'
import { useSuperEmployeeDispatch } from '@/composables/messenger/useSuperEmployeeDispatch'
import { useImRealtime } from './im-messenger/useImRealtime'
import { useImConversationActions } from './im-messenger/useImConversationActions'
import {
  CODEX_SUPER_EMPLOYEE_ENTRY,
  formatTime,
  isCodexStreamingMessage,
  isDutyEmployeeEntry,
  isSuperEmployeeEntry,
  pinnedAvatarText,
  superEmployeeAvatarKey,
  superEmployeeAvatarSrc,
  systemEntryDispatch,
  systemEntryIdentity,
  systemEntryStatusLabel,
  type DutyEmployeeEntry,
  type ExternalAppEntry,
  type SystemEmployeeEntry,
} from '@/composables/messenger/useMessengerEntries'
import KellaiCustomerInbox from '@/components/im/KellaiCustomerInbox.vue'
import AiGroupChatView from '@/views/AiGroupChatView.vue'
import MessengerContactPicker from '@/views/im/MessengerContactPicker.vue'
import ConversationSidebar from '@/views/im/ConversationSidebar.vue'
import SystemEmployeeChat from '@/views/im/SystemEmployeeChat.vue'
import ConversationChat from '@/views/im/ConversationChat.vue'

type CurrentUserPayload = {
  user?: { id?: number }
  account_kind?: string
  market_is_admin?: boolean
}

const localUserId = ref<number | null>(null)
const conversations = ref<ImConversationSummary[]>([])
const activeConversationId = ref<number | null>(null)
const activeSystemEntry = ref<SystemEmployeeEntry | null>(null)
const activeExternalEntry = ref<ExternalAppEntry | null>(null)
const activeGroupChat = ref(false)
const dutyEmployees = ref<DutyEmployeeEntry[]>([])
const messages = ref<ImMessage[]>([])
const draft = ref('')
const busy = ref(false)
const hasMoreHistory = ref(false)
const scrollEl = ref<HTMLElement | null>(null)
const isAdminCustomerServiceConsole = ref(false)

const { playIncoming, playOutgoing } = useImSounds()
const {
  activeCustomerCsConversation,
  isCustomerEnterpriseCs,
  refreshEnterpriseCsThread,
  startEnterpriseCsPolling,
  stopEnterpriseCsPolling,
} = useEnterpriseCsBridge({
  enabled: isDesktopShell(),
  conversations,
  activeConversationId,
  messages,
  playIncoming,
  scrollToBottom,
})
const { refreshCsInbox, startCsInboxPolling, stopCsInboxPolling } = useCsInboxBridge({
  enabled: isAdminCustomerServiceConsole,
  conversations,
  activeConversationId,
  messages,
  playIncoming,
  scrollToBottom,
})
const { onImMessage, onImReadState } = useXcmaxSync()

function closeOverlappingAssistantFloat(): void {
  const emitClose = () => {
    try {
      window.dispatchEvent(new CustomEvent('xcagi:close-assistant-float'))
      window.dispatchEvent(new CustomEvent('xcagi:close-floating-chat'))
      window.dispatchEvent(new CustomEvent('xcagi:suppress-floating-chat'))
    } catch {
      /* ignore non-browser / post-teardown environments */
    }
  }
  try {
    emitClose()
    window.setTimeout(emitClose, 0)
    window.setTimeout(emitClose, 250)
  } catch {
    /* ignore non-browser test environments */
  }
}

function restoreOverlappingAssistantFloat(): void {
  try {
    window.dispatchEvent(new CustomEvent('xcagi:restore-floating-chat'))
  } catch {
    /* ignore non-browser test environments */
  }
}

const { wsConnected, wsConnecting, imApiReachable, activeTitle, isMyMessage, imConnectionClass, imConnectionLabel } = useChatSession({
  conversations,
  activeConversationId,
  localUserId,
})

const {
  contactPickerOpen,
  contacts,
  contactKeyword,
  filteredContacts,
  contactsLoading,
  loadContacts,
  openContactPicker,
  closeContactPicker,
} = useContactPicker({ imApiReachable })

const {
  codexVisibleMessages,
  codexDraft,
  codexBusy,
  activeDutyEmployeeMessages,
  dutyEmployeeDraft,
  dutyEmployeeBusy,
  codexScrollEl,
  dutyEmployeeScrollEl,
  codexInputEl,
  activatePinnedEntry,
  loadCodexConversation,
  loadDutyEmployees,
  onCodexSend,
  onDutyEmployeeSend,
  systemEntryRuntimeStatus,
  systemEntryLastStatus,
  codexMessageRoleLabel,
  stopCodexPolling,
  stopCodexTypewriter,
} = useSuperEmployeeDispatch({
  activeSystemEntry,
  activeExternalEntry,
  activeConversationId,
  activeGroupChat,
  messages,
  hasMoreHistory,
  localUserId,
  isAdminCustomerServiceConsole,
  imApiReachable,
  dutyEmployees,
  closeContactPicker,
  startChatWith,
  closeOverlappingAssistantFloat,
  restoreOverlappingAssistantFloat,
})

// 会话选择与发送动作拆分至 ./im-messenger/useImConversationActions.ts（行为与拆分前一致）
const { selectConversation, onSend } = useImConversationActions({
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
})

const {
  existingDedicatedConversation,
  externalChannelEntries,
  sidebarListItems,
  superCliTools,
  superCliToolLabel,
  sidebarItemClasses,
  sidebarItemAvatarClasses,
  sidebarItemPinClasses,
  sidebarItemShowsPin,
  sidebarItemTitle,
  sidebarItemPreview,
  sidebarItemAvatarText,
  sidebarItemSuperAvatarSrc,
  sidebarItemUnread,
  selectSidebarItem,
} = useConversationList({
  conversations,
  contacts,
  dutyEmployees,
  activeConversationId,
  activeSystemEntry,
  activeExternalEntry,
  activeGroupChat,
  isAdminCustomerServiceConsole,
  selectConversation,
  activatePinnedEntry,
})

// 以普通对象包装传给子组件的 DOM ref，避免模板顶层 ref 自动解包导致 `:scroll-el="scrollEl"`
// 传入的是 scrollEl.value（null）而非 Ref 对象本身。子组件用 `:ref` 回填这些 Ref 对象。
const imChatDomRefs = {
  scrollEl,
  codexScrollEl,
  dutyEmployeeScrollEl,
  codexInputEl,
}

// WebSocket / 实时消息处理拆分至 ./im-messenger/useImRealtime.ts（行为与拆分前一致）
const { applyIncomingMessage, applyReadState, connectWs, disconnectWs } = useImRealtime({
  isCustomerEnterpriseCs,
  localUserId,
  conversations,
  activeConversationId,
  messages,
  wsConnected,
  wsConnecting,
  scrollToBottom,
  loadConversations,
  playIncoming,
  isCustomerEnterpriseCs,
})

let offSyncMessage: (() => void) | null = null
let offSyncRead: (() => void) | null = null

async function startChatWith(contact: ImContact): Promise<void> {
  const existing = contact.is_enterprise_dedicated_cs ? existingDedicatedConversation(contact) : undefined
  if (existing) {
    await selectConversation(existing.id)
    closeContactPicker()
    return
  }
  busy.value = true
  try {
    const conv = await createDirectConversation(contact.id)
    closeContactPicker()
    await loadConversations()
    await selectConversation(conv.id)
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '发起会话失败', 'error')
  } finally {
    busy.value = false
  }
}

async function resolveLocalUserId(): Promise<number | null> {
  try {
    const me = await authApi.getCurrentUser()
    const data = me?.data as CurrentUserPayload | undefined
    isAdminCustomerServiceConsole.value = Boolean(!isDesktopShell() && data?.account_kind === 'admin' && data?.market_is_admin)
    const id = Number(data?.user?.id)
    return Number.isFinite(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

async function loadConversations(): Promise<void> {
  if (!localUserId.value) return
  busy.value = true
  try {
    const regular = await fetchImConversations()
    if (isAdminCustomerServiceConsole.value) {
      // 运营者:把「企业客户→专属客服」收件箱会话并进侧栏(置顶),按 id 去重。
      let inbox: ImConversationSummary[] = []
      try {
        inbox = await fetchCsInbox()
      } catch (e) {
        console.warn('加载客服收件箱失败', e)
      }
      const seen = new Set(regular.map((c) => c.id))
      conversations.value = [...inbox.filter((c) => !seen.has(c.id)), ...regular]
    } else {
      conversations.value = regular
    }
    imApiReachable.value = true
    if (window.xcagiDesktop?.setBadge) {
      const total = conversations.value.reduce((sum, c) => sum + (c.unread_count || 0), 0)
      await window.xcagiDesktop.setBadge(total)
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载会话失败', 'error')
  } finally {
    busy.value = false
  }
}

const { activeCsConversation, csAutomationBusy, onChangeCsMode } = useCustomerServiceAutomation({
  conversations,
  activeConversationId,
  reloadConversations: loadConversations,
})


async function loadOlderMessages(): Promise<void> {
  const id = activeConversationId.value
  if (!id || !localUserId.value || !messages.value.length || isCustomerEnterpriseCs(id)) return
  busy.value = true
  try {
    const beforeId = messages.value[0]?.id
    const older = await fetchImMessages(id, { limit: 50, beforeId })
    hasMoreHistory.value = older.length >= 50
    if (older.length) {
      messages.value = [...older, ...messages.value]
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载历史失败', 'error')
  } finally {
    busy.value = false
  }
}

function scrollToBottom(): void {
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

onMounted(async () => {
  localUserId.value = await resolveLocalUserId()
  if (!localUserId.value) {
    showAppToast('请先登录后使用信息功能', 'warning')
    return
  }
  offSyncMessage = onImMessage(({ conversation_id, message }) => {
    applyIncomingMessage(message, conversation_id)
  })
  offSyncRead = onImReadState(({ conversation_id, user_id, last_message_id }) => {
    applyReadState(conversation_id, user_id, last_message_id)
  })
  connectWs()
  const initialLoads = [loadContacts(), loadConversations(), loadDutyEmployees()]
  if (isAdminCustomerServiceConsole.value) {
    closeOverlappingAssistantFloat()
    activeSystemEntry.value = CODEX_SUPER_EMPLOYEE_ENTRY
    initialLoads.push(loadCodexConversation())
  }
  await Promise.all(initialLoads)
})

onUnmounted(() => {
  restoreOverlappingAssistantFloat()
  stopCodexPolling()
  stopCodexTypewriter(true)
  stopEnterpriseCsPolling()
  stopCsInboxPolling()
  offSyncMessage?.()
  offSyncMessage = null
  offSyncRead?.()
  offSyncRead = null
  disconnectWs()
})
</script>

<style scoped src="./im-messenger/im-messenger.css"></style>
<style scoped src="./ImMessengerResponsive.css"></style>
