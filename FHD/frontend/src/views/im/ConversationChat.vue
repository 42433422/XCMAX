<template>
  <main class="im-chat">
    <header class="im-chat-head">
      <span class="im-avatar im-avatar--sm" aria-hidden="true">{{ avatarText(activeTitle) }}</span>
      <span class="im-chat-title">{{ activeTitle }}</span>
      <div v-if="csAutomation" class="im-cs-controls">
        <span :class="['im-cs-status', `is-${csAutomation.cs_status || 'ai_active'}`]">
          {{ csStatusLabel(csAutomation.cs_status) }}
        </span>
        <button
          type="button"
          class="im-cs-mode-button"
          :disabled="csAutomationBusy || busy"
          @click="emit('change-cs-mode', csAutomation.cs_mode === 'human' ? 'ai' : 'human')"
        >
          {{ csAutomation.cs_mode === 'human' ? '恢复AI' : '人工接管' }}
        </button>
      </div>
      <span
        v-else-if="csCustomerState"
        :class="['im-cs-status', `is-${csCustomerState.cs_status || 'ai_active'}`]"
      >
        {{ csStatusLabel(csCustomerState.cs_status) }}
      </span>
    </header>
    <div v-if="(csAutomation || csCustomerState)?.cs_status === 'human_pending'" class="im-cs-transfer-banner">
      <strong>AI 已转人工</strong>
      <span>{{ (csAutomation || csCustomerState)?.cs_transfer_reason || '该问题需要人工处理' }}</span>
    </div>
    <button v-if="hasMoreHistory" type="button" class="im-load-more" :disabled="busy" @click="emit('load-older')">加载更早消息</button>
    <div :ref="scrollEl" class="im-messages">
      <template v-for="m in messages" :key="m.id">
        <div :class="['im-bubble-row', isMyMessage(m) ? 'mine' : 'theirs']">
          <div class="im-bubble">
            <span v-if="isMyMessage(m) && replyOriginLabel(m.origin)" class="im-reply-origin">
              {{ replyOriginLabel(m.origin) }}
            </span>
            <span v-if="!isMyMessage(m)" class="im-sender">
              {{ m.sender_display_name || '用户' + m.sender_user_id }}
            </span>
            <p>{{ m.body }}</p>
            <time>{{ formatTime(m.created_at) }}</time>
          </div>
        </div>
      </template>
    </div>
    <form class="im-compose" @submit.prevent="emit('send')">
      <input
        :value="draft"
        type="text"
        class="im-compose-input"
        placeholder="输入消息，回车发送"
        maxlength="4000"
        :disabled="busy"
        @input="onInput"
      />
      <button type="submit" class="im-btn im-btn--primary" :disabled="busy || !draft.trim()">发送</button>
    </form>
  </main>
</template>

<script setup lang="ts">
import type { Ref } from 'vue'
import { type ImConversationSummary, type ImMessage } from '@/api/im'
import { avatarText } from '@/composables/messenger/useMessengerEntries'

defineProps<{
  activeTitle: string
  hasMoreHistory: boolean
  busy: boolean
  messages: ImMessage[]
  draft: string
  isMyMessage: (m: ImMessage) => boolean
  formatTime: (iso: string | null) => string
  scrollEl: Ref<HTMLElement | null>
  csAutomation?: ImConversationSummary
  csCustomerState?: ImConversationSummary
  csAutomationBusy?: boolean
}>()

const emit = defineEmits<{
  (e: 'load-older'): void
  (e: 'update:draft', value: string): void
  (e: 'send'): void
  (e: 'change-cs-mode', mode: 'ai' | 'human'): void
}>()

function csStatusLabel(status?: ImConversationSummary['cs_status']): string {
  if (status === 'ai_processing') return 'AI处理中'
  if (status === 'human_pending') return '待人工'
  if (status === 'human_active') return '人工处理中'
  return 'AI自动接待'
}

function replyOriginLabel(origin?: ImMessage['origin']): string {
  if (origin === 'ai') return 'AI自动回复'
  if (origin === 'manual') return '人工回复'
  if (origin === 'system') return '系统转接'
  return ''
}

function onInput(ev: Event): void {
  emit('update:draft', (ev.target as HTMLInputElement).value)
}
</script>

<style scoped>
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
.im-cs-controls {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.im-cs-status {
  padding: 3px 8px;
  border-radius: 999px;
  background: #e8f3ff;
  color: #1769aa;
  font-size: 12px;
  font-weight: 600;
}
.im-cs-status.is-human_pending {
  background: #fff3e8;
  color: #b54708;
}
.im-cs-status.is-human_active {
  background: #e8f7ee;
  color: #14823d;
}
.im-cs-mode-button {
  padding: 5px 10px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 7px;
  background: #fff;
  color: var(--xc-color-primary, #0052d9);
  cursor: pointer;
}
.im-cs-mode-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.im-cs-transfer-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  background: #fff7e8;
  border-bottom: 1px solid #ffd8a8;
  color: #7a4300;
  font-size: 12px;
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
.im-reply-origin {
  display: block;
  margin-bottom: 3px;
  font-size: 11px;
  opacity: 0.75;
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
.im-avatar--sm {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  font-size: 13px;
}
</style>
