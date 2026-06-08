<template>
  <div class="app-toast-host" aria-live="polite" aria-relevant="additions">
    <div
      v-for="t in toasts"
      :key="t.id"
      class="app-toast"
      :class="`app-toast--${t.variant}`"
      role="status"
    >
      {{ t.message }}
      <button type="button" class="app-toast__close" aria-label="关闭" @click="dismissAppToast(t.id)">×</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { dismissAppToast, useAppToastState } from '../composables/useAppToast'

const { toasts } = useAppToastState()
</script>

<style scoped>
.app-toast-host {
  position: fixed;
  left: 50%;
  bottom: calc(72px + env(safe-area-inset-bottom, 0px));
  transform: translateX(-50%);
  z-index: 9700;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(92vw, 420px);
  pointer-events: none;
}

.app-toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.88rem;
  line-height: 1.4;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  background: rgba(24, 24, 28, 0.96);
  color: #f0f0f5;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.app-toast--error {
  border-color: rgba(248, 113, 113, 0.45);
  color: #fecaca;
}

.app-toast--success {
  border-color: rgba(52, 211, 153, 0.4);
}

.app-toast__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.7;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0 2px;
}
</style>
