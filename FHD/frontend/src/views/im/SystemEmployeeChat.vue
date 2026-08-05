<template>
  <main class="im-chat im-chat--system-employee">
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
              @click="emit('activate-pinned', tool)"
            >
              {{ superCliToolLabel(tool) }}
            </button>
          </div>
        </section>
      </div>
      <div
        v-if="isSuperEmployeeEntry(activeSystemEntry)"
        :ref="codexScrollEl"
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
      <div v-else :ref="dutyEmployeeScrollEl" class="im-system-call-log">
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
      @submit.prevent="emit('codex-send')"
    >
      <input
        :ref="codexInputEl"
        :value="codexDraft"
        type="text"
        class="im-compose-input"
        :placeholder="`向${activeSystemEntry.display_name}派工`"
        maxlength="4000"
        :disabled="codexBusy"
        @input="onCodexDraftInput"
        @keydown.enter.prevent="emit('codex-send')"
      />
      <button
        type="button"
        class="im-btn im-btn--primary"
        :disabled="codexBusy || !codexDraft.trim()"
        @click="emit('codex-send')"
      >
        调用
      </button>
    </form>
    <form
      v-else
      class="im-compose im-compose--codex"
      @submit.prevent="emit('duty-employee-send')"
    >
      <input
        :value="dutyEmployeeDraft"
        type="text"
        class="im-compose-input"
        :placeholder="`向${activeSystemEntry.display_name}发送任务`"
        maxlength="4000"
        :disabled="dutyEmployeeBusy"
        @input="onDutyEmployeeDraftInput"
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
</template>

<script setup lang="ts">
import type { Ref } from 'vue';
import {
  type CodexDisplayMessage,
  type DutyEmployeeChatMessage,
  type SystemEmployeeEntry,
} from '@/composables/messenger/useMessengerEntries';
import './SystemEmployeeChat.css';

defineProps<{
  activeSystemEntry: SystemEmployeeEntry;
  superCliTools: SystemEmployeeEntry[];
  superCliToolLabel: (entry: SystemEmployeeEntry) => string;
  systemEntryStatusLabel: (entry: SystemEmployeeEntry) => string;
  systemEntryIdentity: (entry: SystemEmployeeEntry) => string;
  systemEntryDispatch: (entry: SystemEmployeeEntry) => string;
  systemEntryRuntimeStatus: (entry: SystemEmployeeEntry) => string;
  systemEntryLastStatus: (entry: SystemEmployeeEntry) => string;
  superEmployeeAvatarKey: (entry: SystemEmployeeEntry) => string | null;
  superEmployeeAvatarSrc: (entry: SystemEmployeeEntry) => string | null;
  pinnedAvatarText: (entry: SystemEmployeeEntry) => string;
  isDutyEmployeeEntry: (entry: SystemEmployeeEntry | null) => boolean;
  isSuperEmployeeEntry: (entry: SystemEmployeeEntry | null) => boolean;
  codexMessageRoleLabel: (m: CodexDisplayMessage) => string;
  isCodexStreamingMessage: (m: CodexDisplayMessage) => boolean;
  formatTime: (iso: string | null) => string;
  codexVisibleMessages: CodexDisplayMessage[];
  activeDutyEmployeeMessages: DutyEmployeeChatMessage[];
  codexDraft: string;
  codexBusy: boolean;
  dutyEmployeeDraft: string;
  dutyEmployeeBusy: boolean;
  codexScrollEl: Ref<HTMLElement | null>;
  dutyEmployeeScrollEl: Ref<HTMLElement | null>;
  codexInputEl: Ref<HTMLInputElement | null>;
}>();

const emit = defineEmits<{
  (e: 'activate-pinned', entry: SystemEmployeeEntry): void;
  (e: 'codex-send'): void;
  (e: 'duty-employee-send'): void;
  (e: 'update:codexDraft', value: string): void;
  (e: 'update:dutyEmployeeDraft', value: string): void;
}>();

function onCodexDraftInput(ev: Event): void {
  emit('update:codexDraft', (ev.target as HTMLInputElement).value);
}

function onDutyEmployeeDraftInput(ev: Event): void {
  emit('update:dutyEmployeeDraft', (ev.target as HTMLInputElement).value);
}
</script>