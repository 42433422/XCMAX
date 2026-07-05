<script setup lang="ts">
import type { ChatApprovalCard } from '@/types/chat-ui'

defineProps<{
  card: ChatApprovalCard
  busy?: boolean
}>()

defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <div class="chat-approval-card" data-testid="chat-approval-inline-card">
    <div class="chat-approval-card__title">
      {{ card.approval_required ? '需要审批确认' : '执行前确认' }}
    </div>
    <p v-if="card.reason" class="chat-approval-card__reason">{{ card.reason }}</p>
    <p v-if="card.intent" class="chat-approval-card__intent">{{ card.intent }}</p>
    <ul v-if="card.blocking_nodes?.length" class="chat-approval-card__nodes">
      <li v-for="node in card.blocking_nodes" :key="node">{{ node }}</li>
    </ul>
    <ul v-if="card.todo?.length" class="chat-approval-card__todo">
      <li v-for="(step, idx) in card.todo" :key="idx">{{ step }}</li>
    </ul>
    <div class="chat-approval-card__actions">
      <button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="$emit('confirm')">
        {{ card.approval_required ? '提交审批' : '确认执行' }}
      </button>
      <button type="button" class="btn btn-ghost btn-sm" :disabled="busy" @click="$emit('cancel')">
        取消
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-approval-card {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle, rgba(127, 127, 127, 0.35));
  border-radius: 10px;
  background: var(--surface-elevated, rgba(127, 127, 127, 0.08));
}
.chat-approval-card__title {
  font-weight: 600;
  margin-bottom: 6px;
}
.chat-approval-card__reason,
.chat-approval-card__intent {
  margin: 0 0 6px;
  font-size: 0.92rem;
  opacity: 0.9;
}
.chat-approval-card__nodes,
.chat-approval-card__todo {
  margin: 6px 0 10px;
  padding-left: 1.2rem;
  font-size: 0.88rem;
}
.chat-approval-card__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
