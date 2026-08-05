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

<style scoped>
.im-chat--system-employee {
  font: inherit;
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
</style>