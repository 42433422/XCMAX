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

        <div v-if="pinnedContacts.length" class="im-pinned">
          <div class="im-section-label">{{ pinnedSectionLabel }}</div>
          <ul class="im-conv-list im-conv-list--pinned">
            <li
              v-for="ct in pinnedContacts"
              :key="`pinned-${ct.id}`"
              :class="[
                'im-conv-item',
                'im-conv-item--pinned',
                { active: isPinnedContactActive(ct) },
              ]"
              @click="activatePinnedEntry(ct)"
            >
              <span
                :class="[
                  'im-avatar',
                  {
                    'im-avatar--super-tool': superEmployeeAvatarKey(ct),
                    [`im-avatar--${superEmployeeAvatarKey(ct)}`]: superEmployeeAvatarKey(ct),
                    'im-avatar--employee': isDutyEmployeeEntry(ct),
                  },
                ]"
                aria-hidden="true"
              >
                <img
                  v-if="superEmployeeAvatarSrc(ct)"
                  class="im-super-tool-icon"
                  :src="superEmployeeAvatarSrc(ct) || undefined"
                  alt=""
                  decoding="async"
                  draggable="false"
                />
                <template v-else>{{ pinnedAvatarText(ct) }}</template>
              </span>
              <div class="im-conv-main">
                <div class="im-conv-title">{{ ct.display_name }}</div>
                <div class="im-conv-preview">{{ pinnedEntryPreview(ct) }}</div>
              </div>
              <i
                :class="[
                  'fa',
                  isDutyEmployeeEntry(ct) ? 'fa-id-badge' : 'fa-thumb-tack',
                  'im-pin',
                  { 'im-pin--employee': isDutyEmployeeEntry(ct) },
                ]"
                aria-hidden="true"
              ></i>
            </li>
          </ul>
        </div>

        <ul v-if="visibleConversations.length" class="im-conv-list">
          <li
            v-for="c in visibleConversations"
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

      <main v-if="activeSystemEntry" class="im-chat im-chat--system-employee">
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
            <dl class="im-system-status-grid">
              <div>
                <dt>身份</dt>
                <dd>{{ systemEntryIdentity(activeSystemEntry) }}</dd>
              </div>
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
  fetchCsInbox,
  fetchCsInboxMessages,
  fetchImContacts,
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
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import {
  YUANGON_AREAS,
  YUANGON_PKG_DESCRIPTIONS,
  YUANGON_PKG_ROLE_LABELS,
} from '@/domain/yuangonDutyRoster';
import {
  superEmployeeAvatarSrcForId,
  type SuperEmployeeAvatarKey,
} from '@/constants/superEmployeeAvatars';
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

type CurrentUserPayload = {
  user?: { id?: number };
  account_kind?: string;
  market_is_admin?: boolean;
};

type CodexSuperEmployeeEntry = {
  id: 'codex-super-employee';
  display_name: '超级员工-Codex';
  username: 'codex-super-employee';
  subtitle: '全设备协同调度';
  is_codex_super_employee: true;
};

type ClaudeSuperEmployeeEntry = {
  id: 'claude-super-employee';
  display_name: '超级员工-Claude';
  username: 'claude-super-employee';
  subtitle: '全设备协同 · 排比派工';
  is_claude_super_employee: true;
};

type CursorSuperEmployeeEntry = {
  id: 'cursor-super-employee';
  display_name: '超级员工-Cursor';
  username: 'cursor-super-employee';
  subtitle: '全设备协同 · Agent 派工';
  is_cursor_super_employee: true;
};

type DutyEmployeeEntry = {
  id: string;
  display_name: string;
  username: string;
  subtitle: string;
  description: string;
  area: string;
  status: string;
  api_base_path: string;
  phone_channel: string;
  is_duty_employee_entry: true;
};

type SystemEmployeeEntry = CodexSuperEmployeeEntry | ClaudeSuperEmployeeEntry | CursorSuperEmployeeEntry | DutyEmployeeEntry;
type PinnedImEntry = ImContact | SystemEmployeeEntry;
type CodexDisplayMessage = CodexSuperEmployeeMessage & {
  streaming?: boolean;
  synthetic?: boolean;
};

type MobileApiResponse<T> = {
  success?: boolean;
  code?: number;
  message?: string;
  data?: T;
};

type AdminEmployeeApiItem = {
  id?: string;
  name?: string;
  label?: string;
  title?: string;
  description?: string;
  panel_summary?: string;
  yuangon_area?: string;
  industry?: string;
  status?: string;
  api_base_path?: string;
  phone_channel?: string;
};

type AdminEmployeesPayload = {
  items?: AdminEmployeeApiItem[];
  employees?: AdminEmployeeApiItem[];
  count?: number;
};

type DutyEmployeeChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  body: string;
  created_at: string;
  status?: string;
};

type EmployeeExecuteResponse = {
  success?: boolean;
  message?: string;
  source?: string;
  data?: unknown;
};

const CODEX_STREAM_PLACEHOLDER_ID = '__codex_streaming_reply__';
const CODEX_POLL_INTERVAL_MS = 2400;
const CODEX_POLL_MAX_ROUNDS = 60;

const CODEX_SUPER_EMPLOYEE_ENTRY: CodexSuperEmployeeEntry = {
  id: 'codex-super-employee',
  display_name: '超级员工-Codex',
  username: 'codex-super-employee',
  subtitle: '全设备协同调度',
  is_codex_super_employee: true,
};

const CLAUDE_SUPER_EMPLOYEE_ENTRY: ClaudeSuperEmployeeEntry = {
  id: 'claude-super-employee',
  display_name: '超级员工-Claude',
  username: 'claude-super-employee',
  subtitle: '全设备协同 · 排比派工',
  is_claude_super_employee: true,
};

const CURSOR_SUPER_EMPLOYEE_ENTRY: CursorSuperEmployeeEntry = {
  id: 'cursor-super-employee',
  display_name: '超级员工-Cursor',
  username: 'cursor-super-employee',
  subtitle: '全设备协同 · Agent 派工',
  is_cursor_super_employee: true,
};

const SUPER_CLI_TOOLS: SystemEmployeeEntry[] = [
  CODEX_SUPER_EMPLOYEE_ENTRY,
  CURSOR_SUPER_EMPLOYEE_ENTRY,
  CLAUDE_SUPER_EMPLOYEE_ENTRY,
];

const localUserId = ref<number | null>(null);
const conversations = ref<ImConversationSummary[]>([]);
const activeConversationId = ref<number | null>(null);
const activeSystemEntry = ref<SystemEmployeeEntry | null>(null);
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
const wsConnected = ref(false);
const wsConnecting = ref(false);
const imApiReachable = ref(false);
const hasMoreHistory = ref(false);
const scrollEl = ref<HTMLElement | null>(null);
const codexScrollEl = ref<HTMLElement | null>(null);
const dutyEmployeeScrollEl = ref<HTMLElement | null>(null);
const codexInputEl = ref<HTMLInputElement | null>(null);

const contactPickerOpen = ref(false);
const contacts = ref<ImContact[]>([]);
const contactKeyword = ref('');
const contactsLoading = ref(false);
const isAdminCustomerServiceConsole = ref(false);

const { playIncoming, playOutgoing } = useImSounds();
const { onImMessage, onImReadState } = useXcmaxSync();

let ws: WebSocket | null = null;
let offSyncMessage: (() => void) | null = null;
let offSyncRead: (() => void) | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let codexStreamTarget = '';
let codexStreamTimer: ReturnType<typeof setInterval> | null = null;
let codexPollTimer: ReturnType<typeof setTimeout> | null = null;
let codexPollRound = 0;

const activeTitle = computed(() => {
  const conv = conversations.value.find((c) => c.id === activeConversationId.value);
  return conv?.title || '会话';
});

/** 气泡我方/对方判定:CS 收件箱会话里运营者以「企业专属客服」身份,非客户发的即我方。 */
function isMyMessage(m: ImMessage): boolean {
  const conv = conversations.value.find((c) => c.id === activeConversationId.value);
  if (conv?.is_cs_inbox) {
    return m.sender_user_id !== conv.customer_user_id;
  }
  return m.sender_user_id === localUserId.value;
}

const visibleConversations = computed(() =>
  conversations.value.filter(
    (c) => !isAdminCustomerServiceConsole.value || !isEnterpriseDedicatedConversation(c),
  ),
);

const pinnedSectionLabel = computed(() =>
  isAdminCustomerServiceConsole.value ? '固定员工' : '固定联系人',
);

const imConnectionClass = computed(() => {
  if (wsConnected.value) return 'is-on';
  if (imApiReachable.value) return 'is-api-on';
  return wsConnecting.value ? 'is-off' : 'is-error';
});

const imConnectionLabel = computed(() => {
  if (wsConnected.value) return '实时已连接';
  if (imApiReachable.value) return '接口已连接';
  return wsConnecting.value ? '正在连接...' : '连接失败';
});

const codexApiScope = computed<CodexSuperEmployeeApiScope>(() =>
  isAdminConsoleSpa() ? 'admin' : 'mobile',
);

type ActiveSuperTool = 'codex' | 'claude' | 'cursor';

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

const filteredContacts = computed(() => {
  const kw = contactKeyword.value.trim().toLowerCase();
  const pool = contacts.value.filter((c) => !isEnterpriseDedicatedContact(c));
  if (!kw) return pool;
  return pool.filter(
    (c) =>
      c.display_name.toLowerCase().includes(kw) || c.username.toLowerCase().includes(kw),
  );
});

const pinnedContacts = computed<PinnedImEntry[]>(() => {
  if (isAdminCustomerServiceConsole.value) {
    return [CODEX_SUPER_EMPLOYEE_ENTRY, CURSOR_SUPER_EMPLOYEE_ENTRY, CLAUDE_SUPER_EMPLOYEE_ENTRY, ...dutyEmployees.value];
  }
  return contacts.value.filter((c) => isEnterpriseDedicatedContact(c));
});

const superCliTools = computed(() =>
  isAdminCustomerServiceConsole.value ? SUPER_CLI_TOOLS : [],
);

function superCliToolLabel(entry: SystemEmployeeEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return 'Codex';
  if (isCursorSuperEmployeeEntry(entry)) return 'Cursor';
  if (isClaudeSuperEmployeeEntry(entry)) return 'Claude';
  return entry.display_name;
}

const activeDutyEmployeeMessages = computed<DutyEmployeeChatMessage[]>(() => {
  const entry = activeSystemEntry.value;
  if (!entry || !isDutyEmployeeEntry(entry)) return [];
  return dutyEmployeeMessages.value[entry.id] || [];
});

function isCodexSuperEmployeeEntry(entry: PinnedImEntry): entry is CodexSuperEmployeeEntry {
  return 'is_codex_super_employee' in entry && entry.is_codex_super_employee;
}

function isClaudeSuperEmployeeEntry(entry: PinnedImEntry): entry is ClaudeSuperEmployeeEntry {
  return 'is_claude_super_employee' in entry && entry.is_claude_super_employee;
}

function isCursorSuperEmployeeEntry(entry: PinnedImEntry): entry is CursorSuperEmployeeEntry {
  return 'is_cursor_super_employee' in entry && entry.is_cursor_super_employee;
}

/** 超级员工（Codex / Claude / Cursor）共用同一套合成器、消息管线与轮询。 */
function isSuperEmployeeEntry(
  entry: PinnedImEntry | null,
): entry is CodexSuperEmployeeEntry | ClaudeSuperEmployeeEntry | CursorSuperEmployeeEntry {
  return Boolean(
    entry
    && (
      isCodexSuperEmployeeEntry(entry)
      || isClaudeSuperEmployeeEntry(entry)
      || isCursorSuperEmployeeEntry(entry)
    ),
  );
}

function isDutyEmployeeEntry(entry: PinnedImEntry | null): entry is DutyEmployeeEntry {
  return Boolean(entry && 'is_duty_employee_entry' in entry && entry.is_duty_employee_entry);
}

function pinnedEntryPreview(entry: PinnedImEntry): string {
  if (isSuperEmployeeEntry(entry)) return entry.subtitle;
  if (isDutyEmployeeEntry(entry)) return entry.subtitle;
  return `@${entry.username}`;
}

function superEmployeeAvatarKey(entry: PinnedImEntry): SuperEmployeeAvatarKey | null {
  if (isCodexSuperEmployeeEntry(entry)) return 'codex';
  if (isClaudeSuperEmployeeEntry(entry)) return 'claude';
  if (isCursorSuperEmployeeEntry(entry)) return 'cursor';
  return null;
}

function superEmployeeAvatarSrc(entry: PinnedImEntry): string | null {
  return superEmployeeAvatarSrcForId(String(entry.id || '').trim());
}

function pinnedAvatarText(entry: PinnedImEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return 'Codex';
  if (isClaudeSuperEmployeeEntry(entry)) return 'Claude';
  if (isCursorSuperEmployeeEntry(entry)) return 'Cursor';
  if (isDutyEmployeeEntry(entry)) return avatarText(entry.display_name);
  return avatarText(entry.display_name);
}

function dutyContactLabel(channel: string): string {
  const raw = String(channel || '').trim();
  if (raw === 'admin-duty') return '管理端工作台';
  if (raw === 'mobile' || raw === 'mobile-chat') return '手机端会话';
  return raw || '员工通讯录';
}

function systemEntryStatusLabel(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) return '多设备调度';
  return entry.status === 'on_duty' ? '在岗员工' : '编制员工';
}

function systemEntryIdentity(entry: SystemEmployeeEntry): string {
  if (isSuperEmployeeEntry(entry)) return '跨设备协作开发员工';
  return entry.area || '管理端编制员工';
}

function systemEntryDispatch(entry: SystemEmployeeEntry): string {
  if (isCodexSuperEmployeeEntry(entry)) return '全设备 Codex';
  if (isClaudeSuperEmployeeEntry(entry)) return '全设备 Claude';
  if (isCursorSuperEmployeeEntry(entry)) return '全设备 Cursor';
  if (entry.api_base_path) return `${dutyContactLabel(entry.phone_channel)} · ${entry.api_base_path}`;
  return dutyContactLabel(entry.phone_channel);
}

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

function dutyAreaLabelForId(id: string): string {
  for (const area of Object.values(YUANGON_AREAS)) {
    if (area.ids.includes(id)) return area.label;
  }
  return '管理端编制';
}

function normalizeDutyEmployee(raw: AdminEmployeeApiItem): DutyEmployeeEntry | null {
  const id = String(raw.id || '').trim();
  if (!id) return null;
  const name = String(raw.name || raw.label || raw.title || YUANGON_PKG_ROLE_LABELS[id] || id).trim();
  const description = String(
    raw.panel_summary || raw.description || YUANGON_PKG_DESCRIPTIONS[id] || '',
  ).trim();
  const area = String(raw.yuangon_area || raw.industry || dutyAreaLabelForId(id)).trim();
  return {
    id,
    display_name: name || id,
    username: id,
    subtitle: `${dutyContactLabel(raw.phone_channel || 'admin-duty')} · AI号 ${id}`,
    description,
    area,
    status: String(raw.status || 'on_duty').trim(),
    api_base_path: String(raw.api_base_path || `/api/admin/employees/${id}`).trim(),
    phone_channel: String(raw.phone_channel || 'admin-duty').trim(),
    is_duty_employee_entry: true,
  };
}

function fallbackDutyEmployees(): DutyEmployeeEntry[] {
  const rows: AdminEmployeeApiItem[] = [];
  for (const area of Object.values(YUANGON_AREAS)) {
    for (const id of area.ids) {
      rows.push({
        id,
        name: YUANGON_PKG_ROLE_LABELS[id] || id,
        description: YUANGON_PKG_DESCRIPTIONS[id] || '',
        yuangon_area: area.label,
        status: 'on_duty',
        api_base_path: `/api/admin/employees/${id}`,
        phone_channel: 'admin-duty',
      });
    }
  }
  return rows.map(normalizeDutyEmployee).filter((item): item is DutyEmployeeEntry => Boolean(item));
}

function uniqueDutyEmployees(items: DutyEmployeeEntry[]): DutyEmployeeEntry[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function firstTextFromRecord(record: Record<string, unknown> | null, keys: string[]): string {
  if (!record) return '';
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  }
  return '';
}

function textFromEmployeeOutputs(record: Record<string, unknown> | null): string {
  const outputs = Array.isArray(record?.outputs) ? record.outputs : [];
  const parts: string[] = [];
  for (const item of outputs) {
    const out = asRecord(item);
    if (!out) continue;
    const directText = firstTextFromRecord(out, ['output', 'message', 'summary', 'error', 'result']);
    if (directText) {
      parts.push(directText);
      continue;
    }
    const nestedOutput = asRecord(out.output);
    const nestedText = firstTextFromRecord(nestedOutput, ['reply', 'response', 'message', 'summary', 'result', 'error']);
    if (nestedText) parts.push(nestedText);
  }
  return parts.join('\n\n').trim();
}

function shortJson(value: unknown): string {
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 1200 ? `${text.slice(0, 1200)}…` : text;
  } catch {
    return '';
  }
}

function dutyEmployeeReplyFromExecution(result: EmployeeExecuteResponse, entry: DutyEmployeeEntry): string {
  const root = asRecord(result);
  const data = asRecord(result.data);
  const nestedResult = asRecord(data?.result);
  const success = result.success !== false && data?.success !== false;
  const text =
    textFromEmployeeOutputs(nestedResult)
    || textFromEmployeeOutputs(data)
    || firstTextFromRecord(data, ['message', 'output', 'reply', 'response', 'stdout'])
    || firstTextFromRecord(nestedResult, ['message', 'output', 'reply', 'response'])
    || firstTextFromRecord(data, ['result', 'summary'])
    || firstTextFromRecord(nestedResult, ['result', 'summary'])
    || firstTextFromRecord(root, ['message']);
  const errorText =
    firstTextFromRecord(data, ['error', 'detail'])
    || firstTextFromRecord(nestedResult, ['error', 'detail'])
    || firstTextFromRecord(root, ['error', 'detail']);
  if (!success) return `执行失败：${errorText || text || '员工运行时未返回详细原因'}`;
  if (text) return text;
  return `${entry.display_name} 已完成执行，但没有返回可读文本。${shortJson(result.data) ? `\n${shortJson(result.data)}` : ''}`;
}

function isEnterpriseDedicatedContact(contact: ImContact): boolean {
  return Boolean(contact.is_enterprise_dedicated_cs)
    || contact.username.trim().toLowerCase() === 'enterprise-cs';
}

function isEnterpriseDedicatedConversation(conversation: ImConversationSummary): boolean {
  return Boolean(conversation.is_enterprise_dedicated_cs)
    || conversation.title.trim() === '企业专属客服';
}

function avatarText(name: string): string {
  const s = String(name || '').trim();
  return s ? s.slice(0, 1).toUpperCase() : '?';
}

function isCodexDispatcherMessage(message: CodexSuperEmployeeMessage): boolean {
  if (message.role === 'system' || message.kind === 'dispatcher') return true;
  if (message.role !== 'assistant') return false;
  const status = String(message.status || '').toLowerCase();
  const body = String(message.body || '');
  return (
    ['accepted', 'queued', 'running', 'dispatch_failed', 'dispatch_error'].includes(status)
    && /调度器|调用队列|已派发|已调用全设备|未发现在线|Para 任务/.test(body)
  );
}

function isCodexResultMessage(message: CodexSuperEmployeeMessage): boolean {
  if (typeof message.kind === 'string' && message.kind.endsWith('_result')) return true;
  return message.role === 'assistant' && !isCodexDispatcherMessage(message);
}

function isCodexStreamingMessage(message: CodexDisplayMessage): boolean {
  return Boolean(message.streaming);
}

function codexMessageRoleLabel(message: CodexSuperEmployeeMessage): string {
  if (message.role === 'user') return codexSenderLabel.value;
  const tool = activeSuperTool(activeSystemEntry.value);
  if (tool === 'claude') return 'Claude';
  if (tool === 'cursor') return 'Cursor';
  return 'Codex';
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

function isPinnedContactActive(contact: PinnedImEntry): boolean {
  if (isSuperEmployeeEntry(contact)) {
    return activeSystemEntry.value?.id === contact.id;
  }
  if (isDutyEmployeeEntry(contact)) {
    return activeSystemEntry.value?.id === contact.id;
  }
  const conv = existingDedicatedConversation(contact);
  return !!conv && conv.id === activeConversationId.value;
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

function sanitizeCodexReplyText(text: string): string {
  return String(text || '')
    .replace(/排比\s*Para\/Codex\s*多设备调度器/g, '全设备 Codex')
    .replace(/跨设备调度器/g, '全设备 Codex')
    .replace(/多设备调度器/g, '全设备 Codex')
    .replace(/调度器/g, 'Codex')
    .replace(/Para\/Codex/g, 'Codex')
    .replace(/Para\s*任务/g, 'Codex 任务')
    .replace(/调用队列/g, '任务队列')
    .replace(/任务\s*ID[:：]\s*[0-9a-f-]+/gi, '')
    .replace(/\s+。/g, '。')
    .trim();
}

function codexReplyFromDispatcher(message: CodexSuperEmployeeMessage | null): string {
  if (!message) return 'Codex 已收到任务，正在连接全设备执行环境。';
  const body = String(message.body || '');
  const status = String(message.task_status || message.status || '').toLowerCase();
  if (/未发现在线可用 Codex 设备/.test(body)) {
    return 'Codex 暂未检测到在线工作设备，任务已保留，等待设备上线后继续。';
  }
  if (/任务运行中|进度\s*\d+%/.test(body)) {
    return sanitizeCodexReplyText(body);
  }
  if (status === 'queued') {
    return 'Codex 已收到任务，正在排队等待可用设备。';
  }
  if (status === 'accepted' || status === 'running') {
    return 'Codex 已收到任务，正在连接全设备执行环境。';
  }
  return sanitizeCodexReplyText(body) || 'Codex 已收到任务，正在处理。';
}

function latestCodexDispatcherMessage(
  items: CodexSuperEmployeeMessage[],
  requestId = '',
): CodexSuperEmployeeMessage | null {
  const pool = requestId
    ? items.filter((m) => String(m.dispatch_request_id || '') === requestId)
    : items;
  return [...pool].reverse().find((m) => isCodexDispatcherMessage(m)) ?? null;
}

function latestCodexResultMessage(
  items: CodexSuperEmployeeMessage[],
  requestId = '',
): CodexSuperEmployeeMessage | null {
  const pool = requestId
    ? items.filter((m) => String(m.dispatch_request_id || '') === requestId)
    : items;
  return [...pool].reverse().find((m) => isCodexResultMessage(m)) ?? null;
}

function isCodexDispatchStillOpen(message: CodexSuperEmployeeMessage | null): boolean {
  if (!message) return false;
  const status = String(message.task_status || message.status || '').toLowerCase();
  return !['completed', 'merged', 'failed', 'merge_conflict', 'dispatch_failed', 'dispatch_error'].includes(status);
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
  if (isSuperEmployeeEntry(entry)) {
    closeOverlappingAssistantFloat();
    stopCodexPolling();
    stopCodexTypewriter(true);
    activeSystemEntry.value = entry;
    activeConversationId.value = null;
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
    activeSystemEntry.value = entry;
    activeConversationId.value = null;
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
  activeSystemEntry.value = null;
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
      error instanceof Error ? `员工通讯录使用本地编制兜底：${error.message}` : '员工通讯录使用本地编制兜底',
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
      data?.account_kind === 'admin'
      && data?.market_is_admin,
    );
    const id = Number(data?.user?.id);
    return Number.isFinite(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

async function loadContacts(): Promise<void> {
  contactsLoading.value = true;
  try {
    contacts.value = await fetchImContacts();
    imApiReachable.value = true;
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
  activeSystemEntry.value = null;
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
  await Promise.all([loadContacts(), loadConversations(), loadDutyEmployees()]);
  if (isAdminCustomerServiceConsole.value && !activeConversationId.value) {
    closeOverlappingAssistantFloat();
    activeSystemEntry.value = CODEX_SUPER_EMPLOYEE_ENTRY;
    await loadCodexConversation();
  }
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

.im-pinned {
  border-top: 1px solid rgba(31, 35, 41, 0.04);
  border-bottom: 1px solid rgba(31, 35, 41, 0.06);
  padding: 2px 0 6px;
}
.im-sidebar--employees .im-pinned {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
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
.im-sidebar--employees .im-conv-list--pinned {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.im-sidebar--employees > .im-conv-list:not(.im-conv-list--pinned) {
  flex: 0 0 auto;
  max-height: 150px;
  border-top: 1px solid rgba(31, 35, 41, 0.06);
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
.im-pin--employee {
  color: #86909c;
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
