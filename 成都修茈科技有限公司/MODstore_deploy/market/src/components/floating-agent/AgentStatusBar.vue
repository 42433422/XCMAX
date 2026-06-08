<template>
  <div v-if="mode !== 'idle'" class="status-bar" :class="`status-bar--${mode}`" aria-live="polite">
    <span class="status-dot" aria-hidden="true" />
    <span>{{ label }}</span>
    <button v-if="canStop" type="button" class="status-stop" @click="$emit('stop')">停止</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ButlerMode } from '../../types/agent'

const props = defineProps<{ mode: ButlerMode }>()
defineEmits<{ (e: 'stop'): void }>()

const label = computed(() => {
  switch (props.mode) {
    case 'listening': return '我在听…说完停顿即可'
    case 'thinking': return 'AI 思考中…'
    case 'operating': return '正在操作页面…'
    case 'awaiting_confirm': return '等待您确认'
    case 'speaking': return 'AI 正在朗读'
    case 'error': return '出现错误'
    default: return ''
  }
})

const canStop = computed(() =>
  props.mode === 'thinking' || props.mode === 'operating' || props.mode === 'listening' || props.mode === 'speaking'
)
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  font-size: 0.75rem;
  font-weight: 500;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.status-bar--listening { color: #5eead4; background: rgba(94, 234, 212, 0.08); }
.status-bar--thinking { color: #fbbf24; background: rgba(251, 191, 36, 0.08); }
.status-bar--operating { color: #60a5fa; background: rgba(96, 165, 250, 0.08); }
.status-bar--awaiting_confirm { color: #f472b6; background: rgba(244, 114, 182, 0.08); }
.status-bar--speaking { color: #c4b5fd; background: rgba(196, 181, 253, 0.08); }
.status-bar--error { color: #f87171; background: rgba(248, 113, 113, 0.08); }

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.2s ease-in-out infinite;
  flex-shrink: 0;
}

.status-stop {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  border: 1px solid currentColor;
  background: transparent;
  color: currentColor;
  cursor: pointer;
  opacity: 0.8;
}

.status-stop:hover { opacity: 1; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
