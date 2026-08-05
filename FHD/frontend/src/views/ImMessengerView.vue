<template>
  <div class="im-messenger">
    <div class="im-body">
      <aside :class="['im-sidebar', { 'im-sidebar--employees': isAdminCustomerServiceConsole }]">
        <div class="im-sidebar-head">
          <h2 class="im-title">信息</h2>
          <div class="im-sidebar-actions">
            <router-link
              v-if="isAdminCustomerServiceConsole"
              to="/ai-groups"
              class="im-icon-btn"
              title="我的群聊"
            >
              <i class="fa fa-users" aria-hidden="true"></i>
            </router-link>
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
        </div>

        <div class="im-conn" :class="imConnectionClass">
          <span class="im-conn-dot"></span>
          {{ imConnectionLabel }}
        </div>

        <div v-if="externalChannelEntries.length" class="im-channel-list">
          <button
            v-for="entry in externalChannelEntries"
            :key="entry.id"
            type="button"
            :class="['im-channel-entry', { active: activeExternalEntry?.id === entry.id }]"
            @click="activatePinnedEntry(entry)"
          >
            <span class="im-avatar im-avatar--channel" aria-hidden="true">客</span>
            <span class="im-conv-main">
              <span class="im-conv-title">{{ entry.display_name }}</span>
              <span class="im-conv-preview">{{ entry.subtitle }}</span>
            </span>
            <i class="fa fa-comments-o" aria-hidden="true"></i>
          </button>
        </div>

        <ul v-if="sidebarListItems.length" class="im-conv-list">
          <li
            v-for="item in sidebarListItems"
            :key="item.key"
            :class="sidebarItemClasses(item)"
            @click="selectSidebarItem(item)"
          >
            <span :class="sidebarItemAvatarClasses(item)" aria-hidden="true">
              <img
                v-if="sidebarItemSuperAvatarSrc(item)"
                class="im-super-tool-icon"
                :src="sidebarItemSuperAvatarSrc(item) || undefined"
                alt=""
                decoding="async"
                draggable="false"
              />
              <template v-else>{{ sidebarItemAvatarText(item) }}</template>
            </span>
            <div class="im-conv-main">
              <div class="im-conv-title">{{ sidebarItemTitle(item) }}</div>
              <div class="im-conv-preview">{{ sidebarItemPreview(item) }}</div>
            </div>
            <i
              v-if="sidebarItemShowsPin(item)"
              :class="sidebarItemPinClasses(item)"
              aria-hidden="true"
            ></i>
            <span v-else-if="sidebarItemUnread(item) > 0" class="im-badge">
              {{ sidebarItemUnread(item) }}
            </span>
          </li>
        </ul>
        <div v-else class="im-empty im-empty--list">
          <i class="fa fa-comments-o" aria-hidden="true"></i>
          <p>还没有会话</p>
          <p class="im-empty-hint">这里联系已安装的 AI 同事和专属客服；找小C办事请用侧栏「智能对话」</p>
          <button type="button" class="im-btn im-btn--primary" :disabled="busy" @click="openContactPicker">
            发起会话
          </button>
        </div>
      </aside>

      <main v-if="activeExternalEntry" class="im-chat im-chat--external-inbox">
        <KellaiCustomerInbox />
      </main>
      <main v-else-if="activeGroupChat" class="im-chat im-chat--group-chat">
        <AiGroupChatView />
      </main>
      <main v-else-if="activeSystemEntry" class="im-chat im-chat--system-employee">
        <header class="im-chat-head">
          <span
            :class="[
              'im-avatar',
              'im-avatar--sm',
              {
                'im-avatar--super-tool': superEmployeeAvatarKey(activeSystemEntry),
                [`im-avatar--${superEmployeeAvatarKey(activeSystemEntry)}`]:
                  superEmployeeAvatarKey(activeSystemEntry),
                'im-avatar--employee': isDutyEmployeeEntry(activeSystemEntry),
              },
            ]"
            aria-hidden="true"
          >
            <img
              v-if="superEmployeeAvatarSrc(activeSystemEntry)"
              class="im-super-tool-icon"
              :src="superEmployeeAvatarSrc(activeSystemEntry) || undefined"
              alt=""
              decoding="async"
              draggable="false"
            />
            <template v-else>{{ pinnedAvatarText(activeSystemEntry) }}</template>
          </span>
          <span class="im-chat-title">{{ activeSystemEntry.display_name }}</span>
          <span class="im-system-status">{{ systemEntryStatusLabel(activeSystemEntry) }}</span>
        </header>
        <div class="im-system-employee-body">
          <div class="im-system-employee-profile">
            <section class="im-system-employee-card">
              <div
                :class="[
                  'im-system-employee-avatar',
                  {
                    'im-system-employee-avatar--super-tool': superEmployeeAvatarKey(activeSystemEntry),
                    [`im-system-employee-avatar--${superEmployeeAvatarKey(activeSystemEntry)}`]:
                      superEmployeeAvatarKey(activeSystemEntry),
                    'im-system-employee-avatar--duty': isDutyEmployeeEntry(activeSystemEntry),
                  },
                ]"
                aria-hidden="true"
              >
                <img
                  v-if="superEmployeeAvatarSrc(activeSystemEntry)"
                  class="im-super-tool-icon"
                  :src="superEmployeeAvatarSrc(activeSystemEntry) || undefined"
                  alt=""
                  decoding="async"
                  draggable="false"
                />
                <template v-else>{{ pinnedAvatarText(activeSystemEntry) }}</template>
              </div>
              <h3>{{ activeSystemEntry.display_name }}</h3>
              <p>{{ activeSystemEntry.subtitle }}</p>
            </section>
            <dl class="im-system-status-grid im-system-status-grid--identity">
              <div>
                <dt>身份</dt>
                <dd>{{ systemEntryIdentity(activeSystemEntry) }}</dd>
              </div>
            </dl>
            <details class="im-system-status-details">
              <summary>详情（调度/状态/最近任务）</summary>
              <dl class="im-system-status-grid">
                <div>
                  <dt>{{ isSuperEmployeeEntry(activeSystemEntry) ? '调度' : '联系方式' }}</dt>
                  <dd>{{ systemEntryDispatch(activeSystemEntry) }}</dd>
                </div>
                <div>
                  <dt>状态</dt>
                  <dd>{{ systemEntryRuntimeStatus(activeSystemEntry) }}</dd>
                </div>
                <div>
                  <dt>最近任务</dt>
                  <dd>{{ systemEntryLastStatus(activeSystemEntry) }}</dd>
                </div>
              </dl>
            </details>
            <section
              v-if="isSuperEmployeeEntry(activeSystemEntry)"
              class="im-cli-model-switch"
              aria-label="超级开发组 CLI 切换"
            >
              <div class="im-cli-model-switch__label">超级开发组 · CLI</div>
              <div class="im-cli-model-switch__options" role="tablist">
                <button
                  v-for="tool in superCliTools"
                  :key="tool.id"
                  type="button"
                  role="tab"
                  :class="[
                    'im-cli-model-switch__btn',
                    { active: activeSystemEntry?.id === tool.id },
                  ]"
                  :aria-selected="activeSystemEntry?.id === tool.id"
                  @click="activatePinnedEntry(tool)"
                >
                  {{ superCliToolLabel(tool) }}
                </button>
              </div>
            </section>
          </div>
          <div
            v-if="isSuperEmployeeEntry(activeSystemEntry)"
            ref="codexScrollEl"
            class="im-system-call-log"
          >
            <div v-if="!codexVisibleMessages.length" class="im-system-call-empty">
              <i class="fa fa-terminal" aria-hidden="true"></i>
              <p>等待软件内调用</p>
            </div>
            <div
              v-for="m in codexVisibleMessages"
              :key="m.id"
              :class="[
                'im-system-call-row',
                m.role === 'user' ? 'mine' : 'theirs',
                { 'is-streaming': isCodexStreamingMessage(m) },
              ]"
            >
              <div class="im-system-call-bubble">
                <span class="im-system-call-role">{{ codexMessageRoleLabel(m) }}</span>
                <p>
                  {{ m.body }}
                  <span v-if="isCodexStreamingMessage(m)" class="im-system-call-cursor" aria-hidden="true"></span>
                </p>
                <time>{{ formatTime(m.created_at) }}</time>
              </div>
            </div>
          </div>
          <div v-else ref="dutyEmployeeScrollEl" class="im-system-call-log">
            <div v-if="!activeDutyEmployeeMessages.length" class="im-system-call-empty">
              <i class="fa fa-id-badge" aria-hidden="true"></i>
              <p>向该员工发送任务后，这里会显示执行回复</p>
            </div>
            <div
              v-for="m in activeDutyEmployeeMessages"
              :key="m.id"
              :class="['im-system-call-row', m.role === 'user' ? 'mine' : 'theirs']"
            >
              <div class="im-system-call-bubble">
                <span class="im-system-call-role">
                  {{ m.role === 'user' ? '管理端' : activeSystemEntry.display_name }}
                </span>
                <p>{{ m.body }}</p>
                <time>{{ formatTime(m.created_at) }}</time>
              </div>
            </div>
          </div>
        </div>
        <form
          v-if="isSuperEmployeeEntry(activeSystemEntry)"
          class="im-compose im-compose--codex"
          @submit.prevent="onCodexSend"
        >
          <input
            ref="codexInputEl"
            v-model="codexDraft"
            type="text"
            class="im-compose-input"
            :placeholder="`向${activeSystemEntry.display_name}派工`"
            maxlength="4000"
            :disabled="codexBusy"
            @keydown.enter.prevent="onCodexSend"
          />
          <button
            type="button"
            class="im-btn im-btn--primary"
            :disabled="codexBusy || !codexDraft.trim()"
            @click="onCodexSend"
          >
            调用
          </button>
        </form>
        <form
          v-else
          class="im-compose im-compose--codex"
          @submit.prevent="onDutyEmployeeSend"
        >
          <input
            v-model="dutyEmployeeDraft"
            type="text"
            class="im-compose-input"
            :placeholder="`向${activeSystemEntry.display_name}发送任务`"
            maxlength="4000"
            :disabled="dutyEmployeeBusy"
          />
          <button
            type="submit"
            class="im-btn im-btn--primary"
            :disabled="dutyEmployeeBusy || !dutyEmployeeDraft.trim()"
          >
            {{ dutyEmployeeBusy ? '执行中' : '发送' }}
          </button>
        </form>
      </main>
      <main v-else-if="activeConversationId" class="im-chat">
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
            :class="['im-bubble-row', isMyMessage(m) ? 'mine' : 'theirs']"
          >
            <div class="im-bubble">
              <span v-if="!isMyMessage(m)" class="im-sender">
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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
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
import { productErrorMessage } from '@/utils/productErrorMessage';
import { fetchEmployeeSsot } from '@/utils/platformShellApi';
import {
  dutyEmployeesFromEmployeeSsot,
  type EmployeeSsotPayload,
} from '@/utils/employeeSsotContacts';
import { useXcmaxSync } from '@/composables/useXcmaxSync';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import { isDesktopShell } from '@/utils/desktopShell';
import {
  fetchCodexSuperEmployeeMessages,
  sendCodexSuperEmployeeMessage,
  type CodexSuperEmployeeApiScope,
  type CodexSuperEmployeeDispatch,
  type CodexSuperEmployeeMessage,
} from '@/api/codexSuperEmployee';
import {
  fetchClaudeSuperEmployeeMessages,
  sendClaudeSuperEmployeeMessage,
} from '@/api/claudeSuperEmployee';
import {
  fetchCursorSuperEmployeeMessages,
  sendCursorSuperEmployeeMessage,
} from '@/api/cursorSuperEmployee';
import {
  useChatSession,
} from '@/composables/messenger/useChatSession';
import {
  useContactPicker,
} from '@/composables/messenger/useContactPicker';
import {
  useConversationList,
} from '@/composables/messenger/useConversationList';
import {
  CODEX_POLL_INTERVAL_MS,
  CODEX_POLL_MAX_ROUNDS,
  CODEX_STREAM_PLACEHOLDER_ID,
  CODEX_SUPER_EMPLOYEE_ENTRY,
  avatarText,
  codexReplyFromDispatcher,
  dutyEmployeeReplyFromExecution,
  fallbackDutyEmployees,
  formatTime,
  isAiGroupChatEntry,
  isClaudeSuperEmployeeEntry,
  isCodexDispatcherMessage,
  isCodexDispatchStillOpen,
  isCodexResultMessage,
  isCodexStreamingMessage,
  isCodexSuperEmployeeEntry,
  isCursorSuperEmployeeEntry,
  isDutyEmployeeEntry,
  isExternalAppEntry,
  isSuperEmployeeEntry,
  latestCodexDispatcherMessage,
  latestCodexResultMessage,
  normalizeDutyEmployee,
  pinnedAvatarText,
  sanitizeCodexReplyText,
  superEmployeeAvatarKey,
  superEmployeeAvatarSrc,
  systemEntryDispatch,
  systemEntryIdentity,
  systemEntryStatusLabel,
  uniqueDutyEmployees,
  type ActiveSuperTool,
  type AdminEmployeeApiItem,
  type CodexDisplayMessage,
  type DutyEmployeeChatMessage,
  type DutyEmployeeEntry,
  type EmployeeExecuteResponse,
  type ExternalAppEntry,
  type PinnedImEntry,
  type SystemEmployeeEntry,
} from '@/composables/messenger/useMessengerEntries';
import KellaiCustomerInbox from '@/components/im/KellaiCustomerInbox.vue';
import AiGroupChatView from '@/views/AiGroupChatView.vue';
import MessengerContactPicker from '@/views/im/MessengerContactPicker.vue';

type CurrentUserPayload = {
  user?: { id?: number };
  account_kind?: string;
  market_is_admin?: boolean;
};

type MobileApiResponse<T> = {
  success?: boolean;
  code?: number;
  message?: string;
  data?: T;
};

type AdminEmployeesPayload = {
  items?: AdminEmployeeApiItem[];
  employees?: AdminEmployeeApiItem[];
  count?: number;
};

const localUserId = ref<number | null>(null);
const conversations = ref<ImConversationSummary[]>([]);
const activeConversationId = ref<number | null>(null);
const activeSystemEntry = ref<SystemEmployeeEntry | null>(null);
const activeExternalEntry = ref<ExternalAppEntry | null>(null);
const activeGroupChat = ref(false);
const codexMessages = ref<CodexSuperEmployeeMessage[]>([]);
const codexDraft = ref('');
const codexBusy = ref(false);
const codexDispatch = ref<CodexSuperEmployeeDispatch | null>(null);
const codexStreamBody = ref('');
const codexStreamMessageId = ref('');
const codexStreamRequestId = ref('');
const codexStreamCreatedAt = ref('');
const codexStreamActive = ref(false);
const messages = ref<ImMessage[]>([]);
const draft = ref('');
const dutyEmployees = ref<DutyEmployeeEntry[]>([]);
const dutyEmployeeMessages = ref<Record<string, DutyEmployeeChatMessage[]>>({});
const dutyEmployeeDraft = ref('');
const dutyEmployeeBusy = ref(false);
const busy = ref(false);
const hasMoreHistory = ref(false);
const scrollEl = ref<HTMLElement | null>(null);
const codexScrollEl = ref<HTMLElement | null>(null);
const dutyEmployeeScrollEl = ref<HTMLElement | null>(null);
const codexInputEl = ref<HTMLInputElement | null>(null);
const isAdminCustomerServiceConsole = ref(false);

const { playIncoming, playOutgoing } = useImSounds();
const { onImMessage, onImReadState } = useXcmaxSync();

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

let ws: WebSocket | null = null;
let offSyncMessage: (() => void) | null = null;
let offSyncRead: (() => void) | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let codexStreamTarget = '';
let codexStreamTimer: ReturnType<typeof setInterval> | null = null;
let codexPollTimer: ReturnType<typeof setTimeout> | null = null;
let codexPollRound = 0;

const codexApiScope = computed<CodexSuperEmployeeApiScope>(() =>
  isAdminConsoleSpa() ? 'admin' : 'mobile',
);

function activeSuperTool(entry: SystemEmployeeEntry | null): ActiveSuperTool | null {
  if (!entry) return null;
  if (isCodexSuperEmployeeEntry(entry)) return 'codex';
  if (isClaudeSuperEmployeeEntry(entry)) return 'claude';
  if (isCursorSuperEmployeeEntry(entry)) return 'cursor';
  return null;
}

function fetchActiveSuperMessages(): Promise<CodexSuperEmployeeMessage[]> {
  const tool = activeSuperTool(activeSystemEntry.value);
  if (tool === 'claude') {
    return fetchClaudeSuperEmployeeMessages({ scope: codexApiScope.value });
  }
  if (tool === 'cursor') {
    return fetchCursorSuperEmployeeMessages({ scope: codexApiScope.value });
  }
  return fetchCodexSuperEmployeeMessages({ scope: codexApiScope.value });
}

function sendActiveSuperMessage(message: string, context: Record<string, unknown>) {
  const tool = activeSuperTool(activeSystemEntry.value);
  if (tool === 'claude') {
    return sendClaudeSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
  }
  if (tool === 'cursor') {
    return sendCursorSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
  }
  return sendCodexSuperEmployeeMessage(message, context, { scope: codexApiScope.value });
}

const codexSenderLabel = computed(() =>
  codexApiScope.value === 'mobile' ? '手机端' : '管理端',
);

const codexContextSource = computed(() =>
  codexApiScope.value === 'mobile' ? 'mobile_im' : 'admin_im',
);

const codexLastStatus = computed(() => {
  const status = String(codexDispatch.value?.status || '').trim();
  if (!status) return '等待派工';
  if (status === 'accepted') return '已分发';
  if (status === 'queued') return '已入队';
  if (status === 'dispatch_failed' || status === 'dispatch_error') return '待重试';
  return status;
});

const codexVisibleMessages = computed<CodexDisplayMessage[]>(() => {
  const visible = codexMessages.value
    .filter((m) => !isCodexDispatcherMessage(m))
    .map<CodexDisplayMessage>((m) => {
      const streaming = m.id === codexStreamMessageId.value && Boolean(codexStreamBody.value);
      return {
        ...m,
        body: streaming ? codexStreamBody.value : m.body,
        streaming: streaming && codexStreamActive.value,
      };
    });

  if (
    codexStreamBody.value
    && codexStreamMessageId.value === CODEX_STREAM_PLACEHOLDER_ID
  ) {
    visible.push({
      id: CODEX_STREAM_PLACEHOLDER_ID,
      role: 'assistant',
      body: codexStreamBody.value,
      created_at: codexStreamCreatedAt.value || new Date().toISOString(),
      status: 'running',
      kind: 'codex_stream',
      dispatch_request_id: codexStreamRequestId.value,
      streaming: codexStreamActive.value,
      synthetic: true,
    });
  }
  return visible;
});

const activeDutyEmployeeMessages = computed<DutyEmployeeChatMessage[]>(() => {
  const entry = activeSystemEntry.value;
  if (!entry || !isDutyEmployeeEntry(entry)) return [];
  return dutyEmployeeMessages.value[entry.id] || [];
});

function systemEntryRuntimeStatus(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) {
    return codexBusy.value ? '提交中' : codexStreamActive.value ? '回复中' : '可派工';
  }
  return dutyEmployeeBusy.value && activeSystemEntry.value?.id === entry.id ? '执行中' : '可对话';
}

function systemEntryLastStatus(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) return codexLastStatus.value;
  const last = (dutyEmployeeMessages.value[entry.id] || []).at(-1);
  if (!last) return '等待任务';
  return last.role === 'assistant' ? (last.status || '已回复') : '已发送';
}

function appendDutyEmployeeMessage(employeeId: string, message: DutyEmployeeChatMessage): void {
  dutyEmployeeMessages.value = {
    ...dutyEmployeeMessages.value,
    [employeeId]: [...(dutyEmployeeMessages.value[employeeId] || []), message],
  };
  void nextTick(() => {
    const el = dutyEmployeeScrollEl.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function codexMessageRoleLabel(message: CodexSuperEmployeeMessage): string {
  if (message.role === 'user') return codexSenderLabel.value;
  const tool = activeSuperTool(activeSystemEntry.value);
  if (tool === 'claude') return 'Claude';
  if (tool === 'cursor') return 'Cursor';
  return 'Codex';
}

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

function focusCodexInput(): void {
  const tryFocus = () => {
    if (!isSuperEmployeeEntry(activeSystemEntry.value) || codexBusy.value) return;
    try {
      const active = document.activeElement;
      if (active instanceof HTMLElement && active !== codexInputEl.value) {
        active.blur();
      }
      codexInputEl.value?.focus({ preventScroll: true });
    } catch {
      codexInputEl.value?.focus();
    }
  };
  void nextTick(() => {
    tryFocus();
    window.setTimeout(tryFocus, 80);
    window.setTimeout(tryFocus, 240);
    window.setTimeout(tryFocus, 600);
  });
}

function scrollCodexToBottom(): void {
  const el = codexScrollEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function stopCodexTypewriter(clearBody = false): void {
  if (codexStreamTimer) {
    clearInterval(codexStreamTimer);
    codexStreamTimer = null;
  }
  if (clearBody) {
    codexStreamBody.value = '';
    codexStreamTarget = '';
    codexStreamMessageId.value = '';
    codexStreamRequestId.value = '';
    codexStreamCreatedAt.value = '';
    codexStreamActive.value = false;
  }
}

function stopCodexPolling(): void {
  if (codexPollTimer) {
    clearTimeout(codexPollTimer);
    codexPollTimer = null;
  }
  codexPollRound = 0;
}

function ensureCodexTypewriter(): void {
  if (codexStreamTimer) return;
  codexStreamTimer = setInterval(() => {
    if (!codexStreamTarget) {
      stopCodexTypewriter();
      return;
    }
    const current = codexStreamBody.value;
    if (current.length >= codexStreamTarget.length) {
      stopCodexTypewriter();
      codexStreamActive.value = codexStreamMessageId.value === CODEX_STREAM_PLACEHOLDER_ID
        && Boolean(codexPollTimer);
      return;
    }
    const remaining = codexStreamTarget.length - current.length;
    const step = Math.max(1, Math.min(8, Math.ceil(remaining / 18)));
    codexStreamBody.value = codexStreamTarget.slice(0, current.length + step);
    codexStreamActive.value = true;
    void nextTick().then(scrollCodexToBottom);
  }, 34);
}

function startCodexTypewriter(options: {
  body: string;
  messageId?: string;
  requestId?: string;
  createdAt?: string;
  active?: boolean;
  reset?: boolean;
}): void {
  const target = sanitizeCodexReplyText(options.body);
  if (!target) return;
  const nextMessageId = options.messageId || CODEX_STREAM_PLACEHOLDER_ID;
  const messageChanged = codexStreamMessageId.value !== nextMessageId;
  codexStreamTarget = target;
  codexStreamMessageId.value = nextMessageId;
  codexStreamRequestId.value = options.requestId || codexStreamRequestId.value;
  codexStreamCreatedAt.value = options.createdAt || codexStreamCreatedAt.value || new Date().toISOString();
  if (
    options.reset
    || messageChanged
    || !target.startsWith(codexStreamBody.value)
    || codexStreamBody.value.length > target.length
  ) {
    codexStreamBody.value = target.slice(0, Math.min(target.length, 10));
  }
  codexStreamActive.value = options.active !== false || codexStreamBody.value.length < target.length;
  ensureCodexTypewriter();
  void nextTick().then(scrollCodexToBottom);
}

function syncCodexStreamFromMessages(
  items: CodexSuperEmployeeMessage[],
  requestId = '',
): boolean {
  const effectiveRequestId = requestId || String(
    latestCodexDispatcherMessage(items)?.dispatch_request_id || '',
  );
  const dispatcher = latestCodexDispatcherMessage(items, effectiveRequestId);
  if (!requestId && !isCodexDispatchStillOpen(dispatcher)) {
    return false;
  }
  const result = effectiveRequestId ? latestCodexResultMessage(items, effectiveRequestId) : null;
  if (result) {
    startCodexTypewriter({
      body: result.body,
      messageId: result.id,
      requestId: String(result.dispatch_request_id || effectiveRequestId || ''),
      createdAt: result.created_at,
      active: false,
      reset: codexStreamMessageId.value !== result.id,
    });
    return false;
  }
  if (!dispatcher) return false;
  startCodexTypewriter({
    body: codexReplyFromDispatcher(dispatcher),
    messageId: CODEX_STREAM_PLACEHOLDER_ID,
    requestId: String(dispatcher.dispatch_request_id || effectiveRequestId || ''),
    createdAt: dispatcher.created_at,
    active: isCodexDispatchStillOpen(dispatcher),
    reset: codexStreamMessageId.value !== CODEX_STREAM_PLACEHOLDER_ID,
  });
  return isCodexDispatchStillOpen(dispatcher);
}

function startCodexPolling(requestId = ''): void {
  stopCodexPolling();
  codexPollRound = 0;
  const poll = async () => {
    if (!isSuperEmployeeEntry(activeSystemEntry.value)) return;
    codexPollRound += 1;
    try {
      const next = await fetchActiveSuperMessages();
      codexMessages.value = next;
      const shouldContinue = syncCodexStreamFromMessages(next, requestId);
      if (shouldContinue && codexPollRound < CODEX_POLL_MAX_ROUNDS) {
        codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
      } else {
        codexPollTimer = null;
      }
      await nextTick();
      scrollCodexToBottom();
    } catch {
      if (codexPollRound < CODEX_POLL_MAX_ROUNDS) {
        codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
      } else {
        codexPollTimer = null;
      }
    }
  };
  codexPollTimer = setTimeout(poll, CODEX_POLL_INTERVAL_MS);
}

async function activatePinnedEntry(entry: PinnedImEntry): Promise<void> {
  if (isAiGroupChatEntry(entry)) {
    closeOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeExternalEntry.value = null;
    activeSystemEntry.value = null;
    activeConversationId.value = null;
    activeGroupChat.value = true;
    messages.value = [];
    hasMoreHistory.value = false;
    closeContactPicker();
    return;
  }
  if (isExternalAppEntry(entry)) {
    closeOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeExternalEntry.value = entry;
    activeSystemEntry.value = null;
    activeConversationId.value = null;
    messages.value = [];
    hasMoreHistory.value = false;
    closeContactPicker();
    return;
  }
  if (isSuperEmployeeEntry(entry)) {
    closeOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeExternalEntry.value = null;
    activeSystemEntry.value = entry;
    activeConversationId.value = null;
    activeGroupChat.value = false;
    messages.value = [];
    codexMessages.value = [];
    hasMoreHistory.value = false;
    closeContactPicker();
    await loadCodexConversation();
    focusCodexInput();
    return;
  }
  if (isDutyEmployeeEntry(entry)) {
    closeOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeExternalEntry.value = null;
    activeSystemEntry.value = entry;
    activeConversationId.value = null;
    activeGroupChat.value = false;
    messages.value = [];
    hasMoreHistory.value = false;
    closeContactPicker();
    await nextTick();
    const el = dutyEmployeeScrollEl.value;
    if (el) el.scrollTop = el.scrollHeight;
    return;
  }
  restoreOverlappingAssistantFloat();
  stopCodexPolling();
  stopCodexTypewriter(true);
  activeExternalEntry.value = null;
  activeSystemEntry.value = null;
  activeGroupChat.value = false;
  await startChatWith(entry);
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

async function loadCodexConversation(options: { syncStream?: boolean } = {}): Promise<void> {
  if (!isAdminCustomerServiceConsole.value) return;
  try {
    const next = await fetchActiveSuperMessages();
    codexMessages.value = next;
    if (options.syncStream !== false) {
      const shouldContinue = syncCodexStreamFromMessages(next, codexStreamRequestId.value);
      if (shouldContinue && !codexPollTimer) {
        const dispatcher = latestCodexDispatcherMessage(next, codexStreamRequestId.value);
        startCodexPolling(String(dispatcher?.dispatch_request_id || codexStreamRequestId.value || ''));
      }
    }
    await nextTick();
    scrollCodexToBottom();
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '加载 Codex 对话失败', 'error');
  } finally {
    focusCodexInput();
  }
}

async function loadDutyEmployees(): Promise<void> {
  if (!isAdminCustomerServiceConsole.value) {
    dutyEmployees.value = [];
    return;
  }
  if (!dutyEmployees.value.length) {
    dutyEmployees.value = uniqueDutyEmployees(fallbackDutyEmployees());
  }
  try {
    const ssot = (await fetchEmployeeSsot()) as EmployeeSsotPayload;
    const fromSsot = dutyEmployeesFromEmployeeSsot(ssot);
    if (fromSsot.length) {
      dutyEmployees.value = uniqueDutyEmployees(fromSsot as DutyEmployeeEntry[]);
      imApiReachable.value = true;
      return;
    }
  } catch {
    /* fallback to mobile admin employees */
  }
  try {
    const response = await api.get<MobileApiResponse<AdminEmployeesPayload>>('/api/mobile/v1/admin/employees');
    imApiReachable.value = true;
    const payload = response.data || {};
    const rawItems = payload.items || payload.employees || [];
    const normalized = rawItems
      .map(normalizeDutyEmployee)
      .filter((item): item is DutyEmployeeEntry => Boolean(item));
    if (normalized.length) {
      dutyEmployees.value = uniqueDutyEmployees(normalized);
    }
  } catch (error) {
    showAppToast(
      productErrorMessage(error, '员工通讯录暂时不可用，已使用本地编制兜底'),
      'warning',
    );
  }
}

async function onCodexSend(): Promise<void> {
  if (!isSuperEmployeeEntry(activeSystemEntry.value)) return;
  if (codexBusy.value) return;
  const text = codexDraft.value.trim();
  if (!text) return;
  closeOverlappingAssistantFloat();
  codexBusy.value = true;
  stopCodexPolling();
  const localRequestId = `local-${Date.now()}`;
  const now = new Date().toISOString();
  codexDraft.value = '';
  codexMessages.value = [
    ...codexMessages.value,
    {
      id: `local-user-${localRequestId}`,
      role: 'user',
      body: text,
      created_at: now,
      status: 'sent',
      dispatch_request_id: localRequestId,
    },
  ];
  startCodexTypewriter({
    body: 'Codex 正在接收任务，准备连接全设备执行环境。',
    requestId: localRequestId,
    createdAt: now,
    active: true,
    reset: true,
  });
  await nextTick();
  scrollCodexToBottom();
  try {
    const result = await sendActiveSuperMessage(text, {
      source: codexContextSource.value,
      client_surface: codexApiScope.value === 'mobile' ? 'mobile' : 'admin_console',
      target_devices: ['all'],
    });
    codexDispatch.value = result.dispatch ?? null;
    codexMessages.value = result.messages;
    const requestId = String(
      result.message?.dispatch_request_id
      || result.assistant_message?.dispatch_request_id
      || result.dispatch?.request_id
      || localRequestId,
    );
    const shouldContinue = syncCodexStreamFromMessages(result.messages, requestId);
    if (shouldContinue) startCodexPolling(requestId);
    await nextTick();
    scrollCodexToBottom();
    focusCodexInput();
  } catch (error) {
    stopCodexTypewriter(true);
    showAppToast(error instanceof Error ? error.message : 'Codex 调用失败', 'error');
  } finally {
    codexBusy.value = false;
    focusCodexInput();
  }
}

async function onDutyEmployeeSend(): Promise<void> {
  const entry = activeSystemEntry.value;
  if (!entry || !isDutyEmployeeEntry(entry)) return;
  if (dutyEmployeeBusy.value) return;
  const text = dutyEmployeeDraft.value.trim();
  if (!text) return;
  const localId = `duty-${entry.id}-${Date.now()}`;
  const now = new Date().toISOString();
  dutyEmployeeDraft.value = '';
  dutyEmployeeBusy.value = true;
  appendDutyEmployeeMessage(entry.id, {
    id: `${localId}-user`,
    role: 'user',
    body: text,
    created_at: now,
    status: 'sent',
  });
  try {
    const result = await api.post<EmployeeExecuteResponse>(
      `/api/xcmax/local/employees/${encodeURIComponent(entry.id)}/execute`,
      {
        task: text,
        user_id: localUserId.value || 0,
        input_data: {
          source: 'admin_im',
          client_surface: 'admin_console',
          invoke_mode: 'interactive_chat',
          allow_medium_risk: true,
          employee_id: entry.id,
          employee_name: entry.display_name,
        },
      },
    );
    appendDutyEmployeeMessage(entry.id, {
      id: `${localId}-assistant`,
      role: 'assistant',
      body: dutyEmployeeReplyFromExecution(result, entry),
      created_at: new Date().toISOString(),
      status: result.success === false ? '失败' : '已回复',
    });
  } catch (error) {
    appendDutyEmployeeMessage(entry.id, {
      id: `${localId}-error`,
      role: 'assistant',
      body: error instanceof Error ? `调用失败：${error.message}` : '调用失败：未知错误',
      created_at: new Date().toISOString(),
      status: '失败',
    });
  } finally {
    dutyEmployeeBusy.value = false;
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

/* 左侧会话栏 */
.im-sidebar {
  width: 280px;
  border-right: 1px solid var(--xc-color-border, #e6e9ef);
  display: flex;
  flex-direction: column;
  background: #fafbfc;
  min-height: 0;
}
.im-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
}
.im-sidebar-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.im-sidebar-actions .im-icon-btn {
  text-decoration: none;
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
.im-conn.is-api-on .im-conn-dot {
  background: #2f7cf6;
}
.im-conn.is-off .im-conn-dot {
  background: #ff7d00;
}
.im-conn.is-error .im-conn-dot {
  background: #f53f3f;
}

.im-channel-list {
  padding: 0 8px 6px;
}
.im-channel-entry {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.06);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease;
}
.im-channel-entry:hover,
.im-channel-entry.active {
  border-color: rgba(15, 118, 110, 0.34);
  background: rgba(15, 118, 110, 0.12);
}
.im-channel-entry > .fa {
  color: #0f766e;
}
.im-avatar--channel {
  background: #dff3ee;
  color: #0f766e;
}

.im-conv-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px;
  overflow-y: auto;
  flex: 1;
}
.im-sidebar--employees > .im-conv-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
.im-conv-item--admin-contact {
  background: transparent;
}
.im-conv-item--admin-contact:hover {
  background: rgba(0, 0, 0, 0.035);
}
.im-conv-item--admin-contact.active {
  background: rgba(0, 82, 217, 0.08);
}
.im-pin {
  flex: none;
  color: var(--xc-color-primary, #0052d9);
  font-size: 12px;
}
.im-pin--employee {
  color: #86909c;
}
.im-pin--external {
  color: #0f766e;
}
.im-pin--group {
  color: #7c3aed;
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
  flex-basis: 38px;
  width: 38px;
  height: 38px;
  min-width: 38px;
  min-height: 38px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #5b8def, #0052d9);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.im-avatar--super-tool {
  border-radius: 10px;
  background: transparent;
  font-size: 0;
  letter-spacing: 0;
  text-transform: none;
}
.im-avatar--sm.im-avatar--super-tool {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  border-radius: 8px;
}
.im-avatar--employee {
  border-radius: 10px;
  background: #edf4ff;
  color: #1f6feb;
}
.im-avatar--external {
  border-radius: 10px;
  background: #e6f6f2;
  color: #0f766e;
}
.im-avatar--group {
  border-radius: 10px;
  background: #f3e8ff;
  color: #7c3aed;
}
.im-avatar--sm.im-avatar--employee {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  border-radius: 8px;
}
.im-avatar--sm {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  font-size: 13px;
}
.im-super-tool-icon {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  border-radius: inherit;
  user-select: none;
  -webkit-user-drag: none;
}
.im-codex-icon {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  border-radius: inherit;
  user-select: none;
  -webkit-user-drag: none;
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
.im-system-status {
  margin-left: auto;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(0, 180, 42, 0.1);
  color: #14823d;
  font-size: 12px;
  font-weight: 500;
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
.im-system-employee-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  padding: 16px 18px;
  background: #f7f9fc;
}
.im-system-employee-profile {
  display: grid;
  grid-template-columns: minmax(220px, 300px) minmax(260px, 1fr);
  gap: 12px;
  width: 100%;
}
.im-system-employee-card {
  min-width: 0;
  text-align: center;
  padding: 16px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  background: #fff;
}
.im-system-employee-avatar {
  width: 56px;
  height: 56px;
  min-width: 56px;
  min-height: 56px;
  aspect-ratio: 1;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #1f6feb;
  color: #fff;
  font-size: 22px;
  font-weight: 700;
}
.im-system-employee-avatar--super-tool {
  border-radius: 14px;
  background: transparent;
  font-size: 0;
  letter-spacing: 0;
}
.im-system-employee-avatar--duty {
  border-radius: 16px;
  background: #edf4ff;
  color: #1f6feb;
}
.im-system-employee-card h3 {
  margin: 0;
  color: var(--xc-color-text, #1f2329);
  font-size: 18px;
  font-weight: 650;
}
.im-system-employee-card p {
  margin: 6px 0 0;
  color: var(--xc-color-muted, #86909c);
  font-size: 13px;
}
.im-system-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}
.im-system-status-grid--identity {
  grid-template-columns: 1fr;
  margin-bottom: 10px;
}
.im-system-status-details {
  margin-bottom: 4px;
}
.im-system-status-details summary {
  cursor: pointer;
  color: var(--xc-color-muted, #86909c);
  font-size: 12px;
  margin-bottom: 10px;
  user-select: none;
}
.im-system-status-details summary:hover {
  color: var(--xc-color-text, #1f2329);
}
.im-system-status-grid div {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  background: #fff;
}
.im-system-status-grid dt {
  margin: 0 0 4px;
  color: var(--xc-color-muted, #86909c);
  font-size: 12px;
}
.im-system-status-grid dd {
  margin: 0;
  color: var(--xc-color-text, #1f2329);
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}
.im-cli-model-switch {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 10px;
  background: #fff;
}
.im-cli-model-switch__label {
  margin-bottom: 8px;
  color: var(--xc-color-muted, #86909c);
  font-size: 12px;
  font-weight: 600;
}
.im-cli-model-switch__options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.im-cli-model-switch__btn {
  flex: 1 1 0;
  min-width: 72px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 999px;
  background: #f7f8fa;
  color: var(--xc-color-text, #1f2329);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}
.im-cli-model-switch__btn.active {
  border-color: var(--xc-color-primary, #0052d9);
  background: rgba(0, 82, 217, 0.08);
  color: var(--xc-color-primary, #0052d9);
}
.im-system-call-log {
  flex: 1;
  min-height: 220px;
  width: 100%;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  background: #fff;
}
.im-system-call-empty {
  height: 100%;
  min-height: 190px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--xc-color-muted, #86909c);
}
.im-system-call-empty .fa {
  font-size: 28px;
  opacity: 0.42;
}
.im-system-call-empty p {
  margin: 0;
  font-size: 13px;
}
.im-system-call-row {
  display: flex;
  margin-bottom: 10px;
}
.im-system-call-row.mine {
  justify-content: flex-end;
}
.im-system-call-bubble {
  max-width: min(640px, 72%);
  padding: 9px 12px;
  border-radius: 12px;
  border-top-left-radius: 4px;
  background: #f2f3f5;
}
.im-system-call-row.mine .im-system-call-bubble {
  border-top-left-radius: 12px;
  border-top-right-radius: 4px;
  background: #111827;
  color: #fff;
}
.im-system-call-row.is-streaming .im-system-call-bubble {
  background: #eef6ff;
  border: 1px solid #cfe3ff;
}
.im-system-call-role {
  display: block;
  margin-bottom: 3px;
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
}
.im-system-call-row.mine .im-system-call-role {
  color: rgba(255, 255, 255, 0.68);
}
.im-system-call-bubble p {
  margin: 0;
  word-break: break-word;
  line-height: 1.5;
  font-size: 14px;
}
.im-system-call-cursor {
  display: inline-block;
  width: 6px;
  height: 1.1em;
  margin-left: 2px;
  vertical-align: -2px;
  border-radius: 999px;
  background: #2563eb;
  animation: imCodexCursor 0.9s ease-in-out infinite;
}
@keyframes imCodexCursor {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}
.im-system-call-bubble time {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  opacity: 0.6;
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
.im-compose--codex {
  position: relative;
  z-index: 30;
  background: #fff;
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

.im-empty-hint {
  max-width: 260px;
  margin-top: 4px !important;
  font-size: 12px !important;
  color: var(--xc-color-disabled, #9ca3af);
  line-height: 1.5;
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