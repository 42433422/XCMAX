<template>
  <div class="msg-fold" :class="{ 'msg-fold--error': isError }">
    <span v-if="isError" class="msg-fold__badge">失败</span>
    <p class="msg-fold__text">{{ preview }}</p>
    <button type="button" class="msg-fold__action" @click="$emit('expand')">
      {{ expandLabel }}
      <svg class="msg-fold__chevron" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    preview: string
    expandLabel?: string
  }>(),
  {
    expandLabel: '展开',
  },
)

defineEmits<{
  expand: []
}>()

const isError = computed(() => isCollapsedPreviewError(props.preview))

function isCollapsedPreviewError(text: string): boolean {
  const raw = String(text || '').trim()
  if (!raw) return false
  return /处理失败|请求失败|对话失败|超时|限流|余额不足|failed to fetch|network error|timeout|429|502|503|504/i.test(
    raw,
  )
}
</script>

<style scoped>
.msg-fold {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  max-width: 100%;
}

.msg-fold--error .msg-fold__text {
  color: #b91c1c;
}

.msg-fold__badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.msg-fold__text {
  margin: 0;
  width: 100%;
  font-size: 13px;
  line-height: 1.55;
  color: #4b5563;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.msg-fold__action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--xc-color-primary, #0b72d9);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, opacity 0.15s ease;
}

.msg-fold__action:hover {
  color: var(--xc-color-primary-dark, #0956a8);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.msg-fold__action:focus-visible {
  outline: 2px solid rgba(11, 114, 217, 0.35);
  outline-offset: 2px;
  border-radius: 2px;
}

.msg-fold__chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
</style>
