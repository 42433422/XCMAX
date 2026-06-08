<template>
  <Teleport to="body">
    <div
      v-if="open && options"
      class="app-confirm-overlay"
      role="presentation"
      @click.self="resolveDangerConfirm(false)"
    >
      <div class="app-confirm-dialog" role="alertdialog" aria-modal="true" :aria-labelledby="'app-confirm-title'">
        <h3 id="app-confirm-title" class="app-confirm-dialog__title">{{ options.title }}</h3>
        <p class="app-confirm-dialog__message">{{ options.message }}</p>
        <div class="app-confirm-dialog__actions">
          <button type="button" class="app-confirm-dialog__cancel" @click="resolveDangerConfirm(false)">
            {{ options.cancelLabel || '取消' }}
          </button>
          <button
            type="button"
            class="app-confirm-dialog__confirm"
            :class="{ 'app-confirm-dialog__confirm--danger': options.destructive !== false }"
            @click="resolveDangerConfirm(true)"
          >
            {{ options.confirmLabel || '确认' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { resolveDangerConfirm, useDangerConfirmState } from '../composables/useDangerConfirm'

const { open, options } = useDangerConfirmState()
</script>

<style scoped>
.app-confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 9800;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.55);
}

.app-confirm-dialog {
  width: min(100%, 400px);
  padding: 20px;
  border-radius: 12px;
  background: var(--wb-sidebar-bg, #111);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
}

.app-confirm-dialog__title {
  margin: 0 0 8px;
  font-size: 1.05rem;
  font-weight: 600;
  color: #f0f0f5;
}

.app-confirm-dialog__message {
  margin: 0 0 16px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.72);
  white-space: pre-wrap;
}

.app-confirm-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.app-confirm-dialog__cancel,
.app-confirm-dialog__confirm {
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.88rem;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.06);
  color: #e5e5e5;
}

.app-confirm-dialog__confirm--danger {
  background: rgba(220, 38, 38, 0.85);
  border-color: rgba(248, 113, 113, 0.5);
  color: #fff;
}
</style>
