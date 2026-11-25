<template>
  <!-- Element Plus owns the modal stack, Escape, focus trap and restoration. -->
  <ElDialog
    :model-value="open && options !== null"
    class="app-confirm-dialog"
    :title="options?.title ?? ''"
    width="400px"
    align-center
    append-to-body
    destroy-on-close
    :show-close="false"
    :lock-scroll="true"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    :before-close="dismiss"
    @opened="focusCancel"
  >
    <template v-if="options">
      <p class="app-confirm-dialog__message">{{ options.message }}</p>
      <div class="app-confirm-dialog__actions">
        <button
          ref="cancelButton"
          type="button"
          class="app-confirm-dialog__cancel"
          v-bind="{ 'data-dialog-initial-focus': '' }"
          @click="resolveDangerConfirm(false)"
        >{{ options.cancelLabel || '取消' }}</button>
        <button
          type="button"
          class="app-confirm-dialog__confirm"
          :class="{ 'app-confirm-dialog__confirm--danger': options.destructive !== false }"
          @click="resolveDangerConfirm(true)"
        >{{ options.confirmLabel || '确认' }}</button>
      </div>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { resolveDangerConfirm, useDangerConfirmState } from '../composables/useDangerConfirm'

const { open, options } = useDangerConfirmState()
const cancelButton = ref<HTMLButtonElement | null>(null)

// A destructive confirmation must never gain default keyboard focus.
function focusCancel() {
  cancelButton.value?.focus({ preventScroll: true })
}

// Called only by Element Plus on overlay click / Escape / close requests.
// Confirm and cancel buttons settle the existing promise directly.
function dismiss(done: () => void) {
  resolveDangerConfirm(false)
  done()
}
</script>

<style scoped>
.app-confirm-dialog__message {
  margin: 0 0 16px;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.app-confirm-dialog__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--xc-token-spacing-sm);
}
.app-confirm-dialog__cancel,
.app-confirm-dialog__confirm {
  min-height: 40px;
  padding: 8px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--xc-token-radius-small);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  font: inherit;
  cursor: pointer;
  transition: background-color var(--xc-token-motion-feedback-ms) ease;
}
.app-confirm-dialog__confirm:not(.app-confirm-dialog__confirm--danger) {
  background: var(--xc-token-market-light-wb-accent-primary, #0071e3);
  color: white;
  border-color: var(--xc-token-market-light-wb-accent-primary, #0071e3);
}
.app-confirm-dialog__confirm--danger {
  background: var(--xc-token-market-light-wb-status-danger, #d70015);
  color: white;
  border-color: var(--xc-token-market-light-wb-status-danger, #d70015);
}
.app-confirm-dialog__cancel:hover { background: var(--el-fill-color); }
.app-confirm-dialog__confirm:hover { filter: brightness(0.96); }
.app-confirm-dialog__cancel:focus-visible,
.app-confirm-dialog__confirm:focus-visible {
  outline: 3px solid var(--xc-token-market-light-wb-accent-primary, #0071e3);
  outline-offset: 2px;
}
@media (pointer: coarse) {
  .app-confirm-dialog__cancel,
  .app-confirm-dialog__confirm { min-height: 44px; }
}
@media (prefers-reduced-motion: reduce) {
  .app-confirm-dialog__cancel,
  .app-confirm-dialog__confirm { transition: none; }
}
</style>
