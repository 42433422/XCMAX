<template>
  <div class="action-preview" :class="`action-preview--${action.risk}`" role="alertdialog" :aria-label="`确认操作：${action.label}`">
    <div class="action-preview__header">
      <span class="action-risk-badge" :class="`action-risk-badge--${action.risk}`">
        {{ riskLabel }}
      </span>
      <span class="action-preview__title">即将执行操作</span>
    </div>
    <p class="action-preview__label">{{ action.label }}</p>
    <p v-if="action.risk === 'high'" class="action-preview__warn">
      ⚠️ 此操作无法撤销，请确认后继续
    </p>
    <div class="action-preview__btns">
      <button type="button" class="action-btn action-btn--cancel" @click="$emit('cancel')">
        取消
      </button>
      <button type="button" class="action-btn action-btn--confirm" :class="`action-btn--${action.risk}`" @click="$emit('confirm')">
        {{ action.risk === 'high' ? `确认执行` : '确认' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PendingAction } from '../../types/agent'

const props = defineProps<{ action: PendingAction }>()
defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const riskLabel = computed(() => {
  if (props.action.risk === 'high') return '高风险'
  if (props.action.risk === 'medium') return '中风险'
  return '低风险'
})
</script>

<style scoped>
.action-preview {
  margin: 6px 0;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.action-preview--high { background: rgba(248, 113, 113, 0.08); border-color: rgba(248, 113, 113, 0.3); }
.action-preview--medium { background: rgba(251, 191, 36, 0.07); border-color: rgba(251, 191, 36, 0.25); }
.action-preview--low { background: rgba(74, 222, 128, 0.07); border-color: rgba(74, 222, 128, 0.2); }

.action-preview__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.action-risk-badge {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
}

.action-risk-badge--high { background: rgba(248, 113, 113, 0.2); color: #f87171; }
.action-risk-badge--medium { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
.action-risk-badge--low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }

.action-preview__title {
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.5);
}

.action-preview__label {
  font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.88);
  margin: 0 0 6px;
  font-weight: 500;
}

.action-preview__warn {
  font-size: 0.78rem;
  color: #f87171;
  margin: 0 0 10px;
}

.action-preview__btns {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.action-btn {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}

.action-btn--cancel {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.action-btn--cancel:hover { background: rgba(255, 255, 255, 0.1); }

.action-btn--confirm { background: rgba(96, 165, 250, 0.2); color: #93c5fd; }
.action-btn--confirm.action-btn--high { background: rgba(248, 113, 113, 0.2); color: #f87171; }
.action-btn--confirm.action-btn--medium { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
.action-btn--confirm:hover { filter: brightness(1.15); }
</style>
