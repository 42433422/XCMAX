<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ active: boolean | string }>()
const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

function clear() {
  clearTimeout(timer)
  timer = undefined
  visible.value = false
}

watch(() => props.active, (active) => {
  clear()
  // Only defer the feedback: route completion never waits for this timer.
  if (active) timer = setTimeout(() => { visible.value = true }, 280)
}, { immediate: true })
onBeforeUnmount(clear)
</script>

<template>
  <div v-if="visible" class="route-loading-feedback" role="status" aria-live="polite">
    页面加载中…
  </div>
</template>

<style scoped>
.route-loading-feedback {
  position: absolute;
  top: 12px;
  right: 16px;
  max-width: calc(100% - 32px);
  padding: 5px 10px;
  border-radius: 14px;
  background: var(--app-bg, #f4f7fb);
  color: var(--app-text-muted, #475467);
  box-shadow: 0 2px 8px rgb(15 23 42 / 8%);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.4;
  pointer-events: none;
  animation: route-feedback-enter 120ms ease-out;
}

@keyframes route-feedback-enter {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .route-loading-feedback { animation: none; }
}
</style>
