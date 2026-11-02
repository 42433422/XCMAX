<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ active: boolean; stage?: string; failed?: boolean }>()
defineEmits<{ retry: [] }>()
const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

function clear() {
  clearTimeout(timer)
  timer = undefined
  visible.value = false
}

watch(() => [props.active, props.failed], () => {
  clear()
  // Only defer the feedback: route completion never waits for this timer.
  if (props.failed) visible.value = true
  else if (props.active) timer = setTimeout(() => { visible.value = true }, 280)
}, { immediate: true })
onBeforeUnmount(clear)
</script>

<template>
  <div v-if="visible" class="route-loading-feedback" :class="{ 'is-failed': failed }" :role="failed ? 'alert' : 'status'" :aria-live="failed ? 'assertive' : 'polite'" aria-atomic="true">
    <span v-if="!failed" class="route-loading-feedback__spinner" aria-hidden="true"></span>
    <span v-else class="route-loading-feedback__error" aria-hidden="true">!</span>
    <div class="route-loading-feedback__copy">
      <strong>{{ failed ? '页面加载失败' : '页面加载中…' }}</strong>
      <p>{{ failed ? '请重试，或从导航进入其他页面。' : (stage || '正在准备页面内容') }}</p>
    </div>
    <button v-if="failed" type="button" class="route-loading-feedback__retry" @click="$emit('retry')">重试打开</button>
  </div>
</template>

<style scoped>
.route-loading-feedback {
  display: flex;
  align-items: center;
  gap: var(--xc-space-4);
  flex: 0 0 auto;
  width: calc(100% - 2 * var(--xc-space-6));
  max-width: 680px;
  margin: var(--xc-space-6) auto;
  padding: var(--xc-space-5) var(--xc-space-6);
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-xl);
  background: var(--xc-color-surface);
  color: var(--xc-color-text);
  box-shadow: var(--xc-shadow-sm);
  font-size: var(--xc-font-md);
  line-height: var(--xc-line-height);
  animation: route-feedback-enter 120ms ease-out;
}
.route-loading-feedback__spinner { width: 30px; height: 30px; flex: 0 0 30px; border: 3px solid var(--xc-color-border); border-top-color: var(--xc-color-primary); border-radius: var(--xc-radius-full); animation: route-feedback-spin 800ms linear infinite; }
.route-loading-feedback__copy { min-width: 0; flex: 1; overflow-wrap: anywhere; }
.route-loading-feedback__copy strong { font-weight: var(--xc-font-weight-semibold); font-size: var(--xc-font-lg); }
.route-loading-feedback__copy p { margin: var(--xc-space-1) 0 0; color: var(--xc-color-muted); font-size: var(--xc-font-sm); }
.route-loading-feedback__error { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; flex: 0 0 30px; border: 2px solid currentColor; border-radius: var(--xc-radius-full); color: var(--xc-color-danger); font-size: var(--xc-font-2xl); font-weight: var(--xc-font-weight-semibold); line-height: 1; }
.route-loading-feedback__retry { flex-shrink: 0; padding: var(--xc-space-2) var(--xc-space-3); border: 1px solid var(--xc-color-primary); border-radius: var(--xc-radius-md); background: var(--xc-color-primary); color: var(--xc-color-surface); font: inherit; cursor: pointer; }
.route-loading-feedback__retry:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: 3px; }
.route-loading-feedback.is-failed { border-color: var(--xc-color-danger); }

@keyframes route-feedback-spin { to { transform: rotate(360deg); } }
@keyframes route-feedback-enter {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .route-loading-feedback, .route-loading-feedback__spinner { animation: none; }
}
@media (max-width: 480px) {
  .route-loading-feedback { width: calc(100% - 2 * var(--xc-space-3)); margin: var(--xc-space-3) auto; padding: var(--xc-space-4); gap: var(--xc-space-3); flex-wrap: wrap; }
  .route-loading-feedback__retry { margin-left: auto; }
}
</style>
