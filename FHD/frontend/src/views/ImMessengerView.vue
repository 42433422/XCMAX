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
        @load-older="loadOlderMessages"
        @send="onSend"
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
import { nextTick, onMounted, onUnmounted, ref } from 'vue';
import {
  createDirectConversation,
  fetchCsInbox,
  fetchCsInboxMessages,
  fetchImConversations,
  fetchImMessages,
  imWebSocketUrl,
  markImRead,
  replyCsInbox,
  sendImMessage,
  type ImContact,
  type ImConversationSummary,
  type ImMessage,
} from '@/api/im';
import api from '@/api';
import { authApi } from '@/api/auth';
import { useImSounds } from '@/composables/useImSounds';
import { showAppToast } from '@/composables/useAppToast';
import { useXcmaxSync } from '@/composables/useXcmaxSync';
import { isDesktopShell } from '@/utils/desktopShell';
import { useChatSession } from '@/composables/messenger/useChatSession';
import { useContactPicker } from '@/composables/messenger/useContactPicker';
import { useConversationList } from '@/composables/messenger/useConversationList';
import { useSuperEmployeeDispatch } from '@/composables/messenger/useSuperEmployeeDispatch';
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
} from '@/composables/messenger/useMessengerEntries';
import KellaiCustomerInbox from '@/components/im/KellaiCustomerInbox.vue';
import AiGroupChatView from '@/views/AiGroupChatView.vue';
import MessengerContactPicker from '@/views/im/MessengerContactPicker.vue';
import ConversationSidebar from '@/views/im/ConversationSidebar.vue';
import SystemEmployeeChat from '@/views/im/SystemEmployeeChat.vue';
import ConversationChat from '@/views/im/ConversationChat.vue';

type CurrentUserPayload = {
  user?: { id?: number };
  account_kind?: string;
  market_is_admin?: boolean;
};

const localUserId = ref<number | null>(null);
const conversations = ref<ImConversationSummary[]>([]);
const activeConversationId = ref<number | null>(null);
const activeSystemEntry = ref<SystemEmployeeEntry | null>(null);
const activeExternalEntry = ref<ExternalAppEntry | null>(null);
const activeGroupChat = ref(false);
const dutyEmployees = ref<DutyEmployeeEntry[]>([]);
const messages = ref<ImMessage[]>([]);
const draft = ref('');
const busy = ref(false);
const hasMoreHistory = ref(false);
const scrollEl = ref<HTMLElement | null>(null);
const isAdminCustomerServiceConsole = ref(false);

const { playIncoming, playOutgoing } = useImSounds();
const { onImMessage, onImReadState } = useXcmaxSync();

function closeOverlappingAssistantFloat(): void {
  const emitClose = () => {
    try {
      window.dispatchEvent(new CustomEvent('xcagi:close-assistant-float'));
      window.dispatchEvent(new CustomEvent('xcagi:close-floating-chat'));
      window.dispatchEvent(new CustomEvent('xcagi:suppress-floating-chat'));
    } catch {
      /* ignore non-browser / post-teardown environments */
    }
  };
  try {
    emitClose();
    window.setTimeout(emitClose, 0);
    window.setTimeout(emitClose, 250);
  } catch {
    /* ignore non-browser test environments */
  }
}

function restoreOverlappingAssistantFloat(): void {
  try {
    window.dispatchEvent(new CustomEvent('xcagi:restore-floating-chat'));
  } catch {
    /* ignore non-browser test environments */
  }
}

const {
  wsConnected,
  wsConnecting,
  imApiReachable,
  activeTitle,
  isMyMessage,
  imConnectionClass,
  imConnectionLabel,
} = useChatSession({ conversations, activeConversationId, localUserId });

const {
  contactPickerOpen,
  contacts,
  contactKeyword,
  filteredContacts,
  contactsLoading,
  loadContacts,
  openContactPicker,
  closeContactPicker,
} = useContactPicker({ imApiReachable });

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
});

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
});

// 以普通对象包装传给子组件的 DOM ref，避免模板顶层 ref 自动解包导致 `:scroll-el="scrollEl"`
// 传入的是 scrollEl.value（null）而非 Ref 对象本身。子组件用 `:ref` 回填这些 Ref 对象。
const imChatDomRefs = {
  scrollEl,
  codexScrollEl,
  dutyEmployeeScrollEl,
  codexInputEl,
};

let ws: WebSocket | null = null;
let offSyncMessage: (() => void) | null = null;
let offSyncRead: (() => void) | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;

async function startChatWith(contact: ImContact): Promise<void> {
  const existing = contact.is_enterprise_dedicated_cs ? existingDedicatedConversation(contact) : undefined;
  if (existing) {
    await selectConversation(existing.id);
    closeContactPicker();
    return;
  }
  busy.value = true;
  try {
    const conv = await createDirectConversation(contact.id);
    closeContactPicker();
    await loadConversations();
    await selectConversation(conv.id);
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '发起会话失败', 'error');
  } finally {
    busy.value = false;
  }
}

async function resolveLocalUserId(): Promise<number | null> {
  try {
    const me = await authApi.getCurrentUser();
    const data = me?.data as CurrentUserPayload | undefined;
    isAdminCustomerServiceConsole.value = Boolean(
      !isDesktopShell()
      && data?.account_kind === 'admin'
      && data?.market_is_admin,
    );
    const id = Number(data?.user?.id);
    return Number.isFinite(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

async function loadConversations(): Promise<void> {
  if (!localUserId.value) return;
  busy.value = true;
  try {
    const regular = await fetchImConversations();
    if (isAdminCustomerServiceConsole.value) {
      // 运营者:把「企业客户→专属客服」收件箱会话并进侧栏(置顶),按 id 去重。
      let inbox: ImConversationSummary[] = [];
      try {
        inbox = await fetchCsInbox();
      } catch (e) {
        console.warn('加载客服收件箱失败', e);
      }
      const seen = new Set(regular.map((c) => c.id));
      conversations.value = [...inbox.filter((c) => !seen.has(c.id)), ...regular];
    } else {
      conversations.value = regular;
    }
    imApiReachable.value = true;
    if (window.xcagiDesktop?.setBadge) {
      const total = conversations.value.reduce((sum, c) => sum + (c.unread_count || 0), 0);
      await window.xcagiDesktop.setBadge(total);
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载会话失败', 'error');
  } finally {
    busy.value = false;
  }
}

async function selectConversation(id: number): Promise<void> {
  if (!localUserId.value) return;
  restoreOverlappingAssistantFloat();
  stopCodexPolling();
  stopCodexTypewriter(true);
  dutyEmployeeDraft.value = '';
  activeExternalEntry.value = null;
  activeSystemEntry.value = null;
  activeGroupChat.value = false;
  activeConversationId.value = id;
  busy.value = true;
  try {
    const conv = conversations.value.find((c) => c.id === id);
    const isCs = Boolean(conv?.is_cs_inbox);
    messages.value = isCs
      ? await fetchCsInboxMessages(id)
      : await fetchImMessages(id, { limit: 50 });
    hasMoreHistory.value = !isCs && messages.value.length >= 50;
    await nextTick();
    scrollToBottom();
    if (!isCs) {
      const last = messages.value[messages.value.length - 1];
      if (last) {
        await markImRead(id, last.id);
      }
    }
    await loadConversations();
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载消息失败', 'error');
  } finally {
    busy.value = false;
  }
}

async function loadOlderMessages(): Promise<void> {
  const id = activeConversationId.value;
  if (!id || !localUserId.value || !messages.value.length) return;
  busy.value = true;
  try {
    const beforeId = messages.value[0]?.id;
    const older = await fetchImMessages(id, { limit: 50, beforeId });
    hasMoreHistory.value = older.length >= 50;
    if (older.length) {
      messages.value = [...older, ...messages.value];
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载历史失败', 'error');
  } finally {
    busy.value = false;
  }
}

function scrollToBottom(): void {
  const el = scrollEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function applyIncomingMessage(msg: ImMessage, cid: number): void {
  if (cid === activeConversationId.value) {
    if (!messages.value.some((m) => m.id === msg.id)) {
      messages.value.push(msg);
      void nextTick().then(scrollToBottom);
      void markImRead(cid, msg.id);
    }
  }
  if (msg.sender_user_id !== localUserId.value) {
    void playIncoming(msg.body);
  }
  void loadConversations();
}

function applyReadState(conversationId: number, userId: number, lastMessageId: number): void {
  if (userId !== localUserId.value) return;
  const conv = conversations.value.find((c) => c.id === conversationId);
  if (conv) {
    conv.unread_count = 0;
  }
  if (conversationId === activeConversationId.value && lastMessageId > 0) {
    void markImRead(conversationId, lastMessageId).then(() => loadConversations());
  } else {
    void loadConversations();
  }
}

function handleWsPayload(payload: {
  type?: string;
  conversation_id?: number;
  user_id?: number;
  last_message_id?: number;
  message?: ImMessage;
}): void {
  if (payload.type === 'pong') return;
  if (
    (payload.type === 'im.message' || payload.type === 'message') &&
    payload.message
  ) {
    const cid = payload.conversation_id ?? payload.message.conversation_id;
    applyIncomingMessage(payload.message, cid);
    return;
  }
  if (payload.type === 'im.read') {
    const cid = Number(payload.conversation_id);
    const uid = Number(payload.user_id);
    const lastId = Number(payload.last_message_id);
    if (Number.isFinite(cid) && Number.isFinite(uid) && Number.isFinite(lastId)) {
      applyReadState(cid, uid, lastId);
    }
  }
}

async function onSend(): Promise<void> {
  const id = activeConversationId.value;
  const text = draft.value.trim();
  if (!id || !text || !localUserId.value) return;
  const conv = conversations.value.find((c) => c.id === id);
  const isCs = Boolean(conv?.is_cs_inbox);
  busy.value = true;
  try {
    const msg = isCs ? await replyCsInbox(id, text) : await sendImMessage(id, text);
    messages.value.push(msg);
    draft.value = '';
    playOutgoing();
    await nextTick();
    scrollToBottom();
    await loadConversations();
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '发送失败', 'error');
  } finally {
    busy.value = false;
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt);
  reconnectTimer = setTimeout(() => {
    reconnectAttempt += 1;
    connectWs();
  }, delay);
}

function connectWs(): void {
  if (!localUserId.value) return;
  disconnectWs(false);
  try {
    wsConnecting.value = true;
    ws = new WebSocket(imWebSocketUrl());
    ws.onopen = () => {
      wsConnected.value = true;
      wsConnecting.value = false;
      reconnectAttempt = 0;
    };
    ws.onclose = () => {
      wsConnected.value = false;
      wsConnecting.value = false;
      scheduleReconnect();
    };
    ws.onerror = () => {
      wsConnected.value = false;
      wsConnecting.value = false;
    };
    ws.onmessage = (ev) => {
      try {
        handleWsPayload(JSON.parse(String(ev.data)));
      } catch {
        /* ignore */
      }
    };
  } catch {
    wsConnected.value = false;
    wsConnecting.value = false;
    scheduleReconnect();
  }
}

function disconnectWs(clearTimer = true): void {
  if (clearTimer && reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.onopen = null;
    ws.onclose = null;
    ws.onerror = null;
    ws.onmessage = null;
    ws.close();
    ws = null;
  }
  wsConnected.value = false;
  wsConnecting.value = false;
}

onMounted(async () => {
  localUserId.value = await resolveLocalUserId();
  if (!localUserId.value) {
    showAppToast('请先登录后使用信息功能', 'warning');
    return;
  }
  offSyncMessage = onImMessage(({ conversation_id, message }) => {
    applyIncomingMessage(message, conversation_id);
  });
  offSyncRead = onImReadState(({ conversation_id, user_id, last_message_id }) => {
    applyReadState(conversation_id, user_id, last_message_id);
  });
  connectWs();
  const initialLoads = [loadContacts(), loadConversations(), loadDutyEmployees()];
  if (isAdminCustomerServiceConsole.value) {
    closeOverlappingAssistantFloat();
    activeSystemEntry.value = CODEX_SUPER_EMPLOYEE_ENTRY;
    initialLoads.push(loadCodexConversation());
  }
  await Promise.all(initialLoads);
});

onUnmounted(() => {
  restoreOverlappingAssistantFloat();
  stopCodexPolling();
  stopCodexTypewriter(true);
  offSyncMessage?.();
  offSyncMessage = null;
  offSyncRead?.();
  offSyncRead = null;
  disconnectWs();
});
</script>

<style scoped>
.im-messenger {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px);
  max-height: 920px;
  padding: 16px;
  box-sizing: border-box;
}
.im-body {
  display: flex;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: var(--xc-radius-md, 8px);
  overflow: hidden;
  background: var(--xc-color-surface, #fff);
}

/* 右侧聊天区（子组件根元素继承此布局） */
.im-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.im-chat--empty {
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--xc-color-muted, #86909c);
}
.im-chat--empty .fa {
  font-size: 42px;
  opacity: 0.35;
}
.im-chat--group-chat {
  overflow: hidden;
}
.im-chat--group-chat > :deep(*) {
  height: 100%;
}

.im-empty-hint {
  max-width: 260px;
  margin-top: 4px !important;
  font-size: 12px !important;
  color: var(--xc-color-disabled, #9ca3af);
  line-height: 1.5;
}
</style>