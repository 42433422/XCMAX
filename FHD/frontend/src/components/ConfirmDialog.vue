<template>
  <Teleport to="body">
    <div v-if="modelValue" class="confirm-dialog-overlay" @click.self="handleCancel">
      <div ref="panel" class="confirm-dialog" :style="{ maxWidth: maxWidth }" role="dialog" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="messageId" tabindex="-1">
        <div class="confirm-dialog-header">
          <h3 :id="titleId">{{ title }}</h3>
        </div>
        <div :id="messageId" class="confirm-dialog-body">
          <slot>
            <p>{{ message }}</p>
          </slot>
        </div>
        <div class="confirm-dialog-footer">
          <button v-if="showCancel" type="button" class="btn btn-secondary" data-dialog-initial-focus @click="handleCancel">
            {{ cancelText }}
          </button>
          <button type="button" :class="['btn', confirmClass]" @click="handleConfirm">
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, useId } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'
const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: '确认操作',
  },
  message: {
    type: String,
    default: '确定要执行此操作吗？',
  },
  confirmText: {
    type: String,
    default: '确定',
  },
  cancelText: {
    type: String,
    default: '取消',
  },
  confirmClass: {
    type: String,
    default: 'btn-primary',
  },
  showCancel: {
    type: Boolean,
    default: true,
  },
  maxWidth: {
    type: String,
    default: '400px',
  },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const handleConfirm = () => {
  emit('confirm')
  emit('update:modelValue', false)
}

const handleCancel = () => {
  emit('cancel')
  emit('update:modelValue', false)
}
const panel = ref(null)
const titleId = useId()
const messageId = useId()
useDialogFocus(panel, () => props.modelValue, handleCancel)
</script>

<style scoped>
.confirm-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
  background: rgba(0, 0, 0, 0.5);
}
.confirm-dialog {
  width: min(100%, 400px);
  max-height: calc(100dvh - 32px);
  overflow: auto;
  background: var(--xc-token-desktop-office-base-app-surface-strong, #ffffff);
  color: var(--xc-token-desktop-enterprise-xc-color-text, #1a1f2e);
  border-radius: var(--xc-token-desktop-office-base-app-radius-sm, 8px);
  box-shadow: var(--xc-token-desktop-office-base-app-shadow-sm, 0 4px 20px rgba(0, 0, 0, 0.15));
}
.confirm-dialog-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--xc-token-desktop-enterprise-xc-color-border, #dde1e9);
}
.confirm-dialog-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--xc-token-desktop-enterprise-xc-color-text, #1a1f2e);
}
.confirm-dialog-body {
  padding: 20px;
  overflow-wrap: anywhere;
}
.confirm-dialog-body p {
  margin: 0;
  color: var(--xc-token-desktop-enterprise-xc-color-text-secondary, #374151);
  line-height: 1.5;
}
.confirm-dialog-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--xc-token-desktop-enterprise-xc-color-border, #dde1e9);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}
.btn {
  min-width: 44px;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid transparent;
  border-radius: var(--xc-token-desktop-office-base-app-radius-sm, 8px);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color var(--xc-token-motion-feedback-ms, 160ms) ease;
}
.btn:focus-visible {
  outline: 3px solid var(--xc-token-desktop-enterprise-xc-color-primary, #0d47a1);
  outline-offset: 2px;
  box-shadow: none;
}
.btn:disabled { opacity: 0.65; cursor: not-allowed; }
.btn-primary {
  background-color: var(--xc-token-desktop-enterprise-xc-color-primary, #0d47a1);
  color: white;
}
.btn-primary:hover {
  background-color: var(--xc-token-desktop-enterprise-xc-color-primary-hover, #0a3880);
}
.btn-secondary {
  background-color: var(--xc-token-desktop-enterprise-xc-color-text-secondary, #374151);
  color: white;
}
.btn-secondary:hover {
  background-color: var(--xc-token-desktop-enterprise-xc-color-text, #1a1f2e);
}
.btn-danger {
  background-color: var(--xc-token-desktop-enterprise-xc-color-danger, #c0392b);
  color: white;
}
.btn-danger:hover { filter: brightness(0.90); }
.btn-success {
  background-color: var(--xc-token-desktop-enterprise-xc-color-success, #00875a);
  color: white;
}
.btn-success:hover { filter: brightness(0.90); }
@media (prefers-reduced-motion: reduce) {
  .btn { transition: none; }
}
</style>
