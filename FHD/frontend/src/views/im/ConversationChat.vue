<template>
  <main class="im-chat">
    <MatureChat :room-id="activeTitle" :title="activeTitle" :avatar="activeAvatarSrc"
      :rows="rows" :draft="draft" :disabled="busy" busy-label="正在发送…" :has-more="hasMoreHistory"
      @update:draft="emit('update:draft', $event)" @send="send" @load-older="emit('load-older')">
      <template #actions>
      <slot name="ticket-results" />
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
      </template>
    </MatureChat>
  </main>
</template>
<script setup lang="ts">
import { computed, nextTick, type Ref } from 'vue'
import MatureChat from '@/components/im/MatureChat.vue'
import { type ImConversationSummary, type ImMessage } from '@/api/im'

const props = defineProps<{
  activeTitle: string
  activeAvatarSrc?: string | null
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
  if (status === 'ai_retrying') return '系统自动重试中'
  if (status === 'ai_unresolved') return '暂未解决'
  if (status === 'ai_processing') return 'AI处理中'
  if (status === 'human_pending') return '人工已介入'
  if (status === 'human_active') return '人工处理中'
  return 'AI自动接待'
}

function replyOriginLabel(origin?: ImMessage['origin']): string {
  if (origin === 'ai') return 'AI自动回复'
  if (origin === 'manual') return '人工回复'
  if (origin === 'system') return '系统消息'
  return ''
}

const rows = computed(() => props.messages.map(m => ({ id: m.id, body: m.body, mine: props.isMyMessage(m),
  sender: props.isMyMessage(m) ? '我' : m.sender_display_name || `用户${m.sender_user_id}`, at: m.created_at,
  label: replyOriginLabel(m.origin), avatar: props.isMyMessage(m) ? '' : props.activeAvatarSrc,
})))
async function send(value: string) { emit('update:draft', value); await nextTick(); emit('send') }
</script>
<style scoped>
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
  background: #e8f7ee;
  color: #14823d;
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
</style>
