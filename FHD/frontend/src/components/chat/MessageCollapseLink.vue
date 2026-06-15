<template>
  <button type="button" class="msg-fold__action msg-fold__action--collapse" @click="$emit('collapse')">
    <svg class="msg-fold__chevron msg-fold__chevron--up" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M4 10l4-4 4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
    </svg>
    {{ label }}
  </button>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
  }>(),
  {
    label: '收起',
  },
)

defineEmits<{
  collapse: []
}>()
</script>

<style scoped>
.msg-fold__action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin: 6px 0 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--xc-color-primary, #0b72d9);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease;
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
