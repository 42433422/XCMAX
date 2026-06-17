<template>
  <div class="im-messenger">
    <div class="im-body">
      <aside class="im-sidebar">
        <div class="im-sidebar-head">
          <h2 class="im-title">消息</h2>
          <button
            type="button"
            class="im-icon-btn"
            title="发起会话"
            :disabled="busy"
            @click="openContactPicker"
          >
            <i class="fa fa-pencil-square-o" aria-hidden="true"></i>
          </button>
        </div>

        <div class="im-conn" :class="wsConnected ? 'is-on' : 'is-off'">
          <span class="im-conn-dot"></span>
          {{ wsConnected ? '实时已连接' : '正在连接…' }}
        </div>

        <div v-if="pinnedContacts.length" class="im-pinned">
          <div class="im-section-label">固定联系人</div>
          <ul class="im-conv-list im-conv-list--pinned">
            <li
              v-for="ct in pinnedContacts"
              :key="`pinned-${ct.id}`"
              :class="[
                'im-conv-item',
                'im-conv-item--pinned',
                { active: isPinnedContactActive(ct) },
              ]"
              @click="startChatWith(ct)"
            >
              <span class="im-avatar" aria-hidden="true">{{ avatarText(ct.display_name) }}</span>
              <div class="im-conv-main">
                <div class="im-conv-title">{{ ct.display_name }}</div>
                <div class="im-conv-preview">@{{ ct.username }}</div>
              </div>
              <i class="fa fa-thumb-tack im-pin" aria-hidden="true"></i>
            </li>
          </ul>
        </div>

        <ul v-if="conversations.length" class="im-conv-list">
          <li
            v-for="c in conversations"
            :key="c.id"
            :class="['im-conv-item', { active: c.id === activeConversationId }]"
            @click="selectConversation(c.id)"
          >
            <span class="im-avatar" aria-hidden="true">{{ avatarText(c.title) }}</span>
            <div class="im-conv-main">
              <div class="im-conv-title">{{ c.title }}</div>
              <div class="im-conv-preview">{{ c.last_message_preview || '暂无消息' }}</div>
            </div>
            <span v-if="c.unread_count > 0" class="im-badge">{{ c.unread_count }}</span>
          </li>
        </ul>
        <div v-else-if="!pinnedContacts.length" class="im-empty im-empty--list">
          <i class="fa fa-comments-o" aria-hidden="true"></i>
          <p>还没有会话</p>
          <button type="button" class="im-btn im-btn--primary" :disabled="busy" @click="openContactPicker">
            发起会话
          </button>
        </div>
      </aside>

      <main v-if="activeConversationId" class="im-chat">
        <header class="im-chat-head">
          <span class="im-avatar im-avatar--sm" aria-hidden="true">{{ avatarText(activeTitle) }}</span>
          <span class="im-chat-title">{{ activeTitle }}</span>
        </header>
        <button
          v-if="hasMoreHistory"
          type="button"
          class="im-load-more"
          :disabled="busy"
          @click="loadOlderMessages"
        >
          加载更早消息
        </button>
        <div ref="scrollEl" class="im-messages">
          <div
            v-for="m in messages"
            :key="m.id"
            :class="['im-bubble-row', m.sender_user_id === localUserId ? 'mine' : 'theirs']"
          >
            <div class="im-bubble">
              <span v-if="m.sender_user_id !== localUserId" class="im-sender">
                {{ m.sender_display_name || ('用户' + m.sender_user_id) }}
              </span>
              <p>{{ m.body }}</p>
              <time>{{ formatTime(m.created_at) }}</time>
            </div>
          </div>
        </div>
        <form class="im-compose" @submit.prevent="onSend">
          <input
            v-model="draft"
            type="text"
            class="im-compose-input"
            placeholder="输入消息，回车发送"
            maxlength="4000"
            :disabled="busy"
          />
          <button type="submit" class="im-btn im-btn--primary" :disabled="busy || !draft.trim()">
            发送
          </button>
        </form>
      </main>
      <main v-else class="im-chat im-chat--empty">
        <i class="fa fa-comment-o" aria-hidden="true"></i>
        <p>选择左侧会话开始聊天</p>
      </main>
    </div>

    <div v-if="contactPickerOpen" class="im-modal" @click.self="closeContactPicker">
      <div class="im-modal-card">
        <header class="im-modal-head">
          <span>选择联系人</span>
          <button type="button" class="im-icon-btn" @click="closeContactPicker">
            <i class="fa fa-times" aria-hidden="true"></i>
          </button>
        </header>
        <input
          v-model="contactKeyword"
          type="text"
          class="im-compose-input"
          placeholder="搜索姓名或账号"
          @input="onContactSearch"
        />
        <ul v-if="filteredContacts.length" class="im-contact-list">
          <li
            v-for="ct in filteredContacts"
            :key="ct.id"
            class="im-contact-item"
            @click="startChatWith(ct)"
          >
            <span class="im-avatar im-avatar--sm" aria-hidden="true">{{ avatarText(ct.display_name) }}</span>
            <div class="im-contact-main">
              <div class="im-contact-name">{{ ct.display_name }}</div>
              <div class="im-contact-sub">@{{ ct.username }}</div>
            </div>
          </li>
        </ul>
        <div v-else class="im-empty">
          <p>{{ contactsLoading ? '加载中…' : '未找到联系人' }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import {
  createDirectConversation,
  fetchImContacts,
  fetchImConversations,
  fetchImMessages,
  imWebSocketUrl,
  markImRead,
  sendImMessage,
  type ImContact,
  type ImConversationSummary,
  type ImMessage,
} from '@/api/im';
import { authApi } from '@/api/auth';
import { useImSounds } from '@/composables/useImSounds';
import { showAppToast } from '@/composables/useAppToast';
import { useXcmaxSync } from '@/composables/useXcmaxSync';

const localUserId = ref<number | null>(null);
const conversations = ref<ImConversationSummary[]>([]);
const activeConversationId = ref<number | null>(null);
const messages = ref<ImMessage[]>([]);
const draft = ref('');
const busy = ref(false);
const wsConnected = ref(false);
const hasMoreHistory = ref(false);
const scrollEl = ref<HTMLElement | null>(null);

const contactPickerOpen = ref(false);
const contacts = ref<ImContact[]>([]);
const contactKeyword = ref('');
const contactsLoading = ref(false);

const { playIncoming, playOutgoing } = useImSounds();
const { onImMessage, onImReadState } = useXcmaxSync();

let ws: WebSocket | null = null;
let offSyncMessage: (() => void) | null = null;
let offSyncRead: (() => void) | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;

const activeTitle = computed(() => {
  const conv = conversations.value.find((c) => c.id === activeConversationId.value);
  return conv?.title || '会话';
});

const filteredContacts = computed(() => {
  const kw = contactKeyword.value.trim().toLowerCase();
  const pool = contacts.value.filter((c) => !c.is_enterprise_dedicated_cs);
  if (!kw) return pool;
  return pool.filter(
    (c) =>
      c.display_name.toLowerCase().includes(kw) || c.username.toLowerCase().includes(kw),
  );
});

const pinnedContacts = computed(() =>
  contacts.value.filter((c) => c.is_enterprise_dedicated_cs),
);

function avatarText(name: string): string {
  const s = String(name || '').trim();
  return s ? s.slice(0, 1).toUpperCase() : '?';
}

function formatTime(iso: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function openContactPicker(): Promise<void> {
  contactPickerOpen.value = true;
  contactKeyword.value = '';
  await loadContacts();
}

function closeContactPicker(): void {
  contactPickerOpen.value = false;
}

function onContactSearch(): void {
  /* 本地过滤，filteredContacts 已响应式处理 */
}

function existingDedicatedConversation(contact: ImContact): ImConversationSummary | undefined {
  const username = contact.username.trim().toLowerCase();
  return conversations.value.find((c) => {
    if (c.is_enterprise_dedicated_cs) return true;
    return username && c.title.trim().toLowerCase() === contact.display_name.trim().toLowerCase();
  });
}

function isPinnedContactActive(contact: ImContact): boolean {
  const conv = existingDedicatedConversation(contact);
  return !!conv && conv.id === activeConversationId.value;
}

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
    const user = me?.data?.user as { id?: number } | undefined;
    const id = Number(user?.id);
    return Number.isFinite(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

async function loadContacts(): Promise<void> {
  contactsLoading.value = true;
  try {
    contacts.value = await fetchImContacts();
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载联系人失败', 'error');
  } finally {
    contactsLoading.value = false;
  }
}

async function loadConversations(): Promise<void> {
  if (!localUserId.value) return;
  busy.value = true;
  try {
    conversations.value = await fetchImConversations();
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
  activeConversationId.value = id;
  busy.value = true;
  try {
    messages.value = await fetchImMessages(id, { limit: 50 });
    hasMoreHistory.value = messages.value.length >= 50;
    await nextTick();
    scrollToBottom();
    const last = messages.value[messages.value.length - 1];
    if (last) {
      await markImRead(id, last.id);
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
  busy.value = true;
  try {
    const msg = await sendImMessage(id, text);
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
    ws = new WebSocket(imWebSocketUrl());
    ws.onopen = () => {
      wsConnected.value = true;
      reconnectAttempt = 0;
    };
    ws.onclose = () => {
      wsConnected.value = false;
      scheduleReconnect();
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
    scheduleReconnect();
  }
}

function disconnectWs(clearTimer = true): void {
  if (clearTimer && reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
  wsConnected.value = false;
}

onMounted(async () => {
  localUserId.value = await resolveLocalUserId();
  if (!localUserId.value) {
    showAppToast('请先登录后使用消息功能', 'warning');
    return;
  }
  offSyncMessage = onImMessage(({ conversation_id, message }) => {
    applyIncomingMessage(message, conversation_id);
  });
  offSyncRead = onImReadState(({ conversation_id, user_id, last_message_id }) => {
    applyReadState(conversation_id, user_id, last_message_id);
  });
  connectWs();
  await Promise.all([loadContacts(), loadConversations()]);
});

onUnmounted(() => {
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

/* 左侧会话栏 */
.im-sidebar {
  width: 280px;
  border-right: 1px solid var(--xc-color-border, #e6e9ef);
  display: flex;
  flex-direction: column;
  background: #fafbfc;
}
.im-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
}
.im-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--xc-color-text, #1f2329);
}
.im-icon-btn {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--xc-color-muted, #86909c);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  transition: background 150ms ease, color 150ms ease;
}
.im-icon-btn:hover {
  background: rgba(0, 82, 217, 0.08);
  color: var(--xc-color-primary, #0052d9);
}
.im-conn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px 10px;
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
}
.im-conn-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c9cdd4;
}
.im-conn.is-on .im-conn-dot {
  background: #00b42a;
}
.im-conn.is-off .im-conn-dot {
  background: #ff7d00;
}

.im-pinned {
  border-top: 1px solid rgba(31, 35, 41, 0.04);
  border-bottom: 1px solid rgba(31, 35, 41, 0.06);
  padding: 2px 0 6px;
}
.im-section-label {
  padding: 6px 16px 2px;
  font-size: 12px;
  line-height: 18px;
  color: var(--xc-color-muted, #86909c);
}

.im-conv-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px;
  overflow-y: auto;
  flex: 1;
}
.im-conv-list--pinned {
  overflow: visible;
  flex: none;
  padding-top: 2px;
  padding-bottom: 0;
}
.im-conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
  transition: background 150ms ease;
}
.im-conv-item:hover {
  background: rgba(0, 0, 0, 0.035);
}
.im-conv-item.active {
  background: rgba(0, 82, 217, 0.08);
}
.im-conv-item--pinned {
  background: rgba(0, 82, 217, 0.05);
}
.im-pin {
  flex: none;
  color: var(--xc-color-primary, #0052d9);
  font-size: 12px;
}
.im-conv-main {
  min-width: 0;
  flex: 1;
}
.im-conv-title {
  font-weight: 500;
  font-size: 14px;
  color: var(--xc-color-text, #1f2329);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.im-conv-preview {
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.im-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f53f3f;
  color: #fff;
  font-size: 11px;
  border-radius: 9px;
}

/* 头像 */
.im-avatar {
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #5b8def, #0052d9);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.im-avatar--sm {
  width: 30px;
  height: 30px;
  font-size: 13px;
}

/* 右侧聊天区 */
.im-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.im-chat-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--xc-color-border, #e6e9ef);
  font-weight: 600;
  color: var(--xc-color-text, #1f2329);
}
.im-chat-title {
  font-size: 15px;
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
.im-load-more {
  margin: 10px auto 0;
  padding: 4px 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 999px;
  background: #fff;
  color: var(--xc-color-muted, #86909c);
  font-size: 12px;
  cursor: pointer;
}
.im-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
}
.im-bubble-row {
  display: flex;
  margin-bottom: 12px;
}
.im-bubble-row.mine {
  justify-content: flex-end;
}
.im-bubble {
  max-width: 68%;
  padding: 9px 13px;
  border-radius: 12px;
  background: #f2f3f5;
  border-top-left-radius: 4px;
}
.im-bubble-row.mine .im-bubble {
  background: var(--xc-color-primary, #0052d9);
  color: #fff;
  border-top-left-radius: 12px;
  border-top-right-radius: 4px;
}
.im-sender {
  display: block;
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
  margin-bottom: 2px;
}
.im-bubble p {
  margin: 0;
  word-break: break-word;
  line-height: 1.5;
  font-size: 14px;
}
.im-bubble time {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  opacity: 0.6;
}
.im-compose {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--xc-color-border, #e6e9ef);
}
.im-compose-input {
  flex: 1;
  padding: 9px 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  outline: none;
  transition: border-color 150ms ease;
}
.im-compose-input:focus {
  border-color: var(--xc-color-primary, #0052d9);
}
.im-btn {
  padding: 8px 16px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
}
.im-btn--primary {
  background: var(--xc-color-primary, #0052d9);
  color: #fff;
  border-color: var(--xc-color-primary, #0052d9);
}
.im-btn--primary:hover:not(:disabled) {
  background: var(--xc-color-primary-hover, #003cab);
}
.im-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 空状态 */
.im-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex: 1;
  padding: 24px;
  color: var(--xc-color-muted, #86909c);
  text-align: center;
}
.im-empty .fa {
  font-size: 32px;
  opacity: 0.35;
}
.im-empty p {
  margin: 0;
  font-size: 13px;
}

/* 联系人选择弹窗 */
.im-modal {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.im-modal-card {
  width: min(380px, 92vw);
  max-height: 70vh;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 12px;
}
.im-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 15px;
  font-weight: 600;
  color: var(--xc-color-text, #1f2329);
}
.im-contact-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
}
.im-contact-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 150ms ease;
}
.im-contact-item:hover {
  background: rgba(0, 82, 217, 0.07);
}
.im-contact-main {
  min-width: 0;
}
.im-contact-name {
  font-size: 14px;
  color: var(--xc-color-text, #1f2329);
}
.im-contact-sub {
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
}
</style>
