<template>
  <Teleport to="body">
    <div
      v-if="store.visible"
      class="app-dialog-host-overlay"
      role="presentation"
      @click.self="onOverlayClick"
    >
      <div
        class="app-dialog-host-panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        @keydown.esc.prevent="onEscape"
      >
        <h2 :id="titleId" class="app-dialog-host-title">{{ store.title }}</h2>
        <p class="app-dialog-host-message">{{ store.message }}</p>

        <div v-if="store.kind === 'prompt'" class="app-dialog-host-prompt-wrap">
          <input
            v-model="store.promptInput"
            type="text"
            class="app-dialog-host-input"
            :placeholder="store.promptPlaceholder || undefined"
            autocomplete="off"
            @keydown.enter.prevent="onPromptEnter"
          />
        </div>

        <div class="app-dialog-host-actions">
          <template v-if="store.kind === 'alert'">
            <button type="button" class="app-dialog-host-btn app-dialog-host-btn-primary" @click="store.ackAlert()">
              {{ store.confirmText }}
            </button>
          </template>
          <template v-else-if="store.kind === 'confirm'">
            <button type="button" class="app-dialog-host-btn app-dialog-host-btn-secondary" @click="store.ackConfirm(false)">
              {{ store.cancelText }}
            </button>
            <button
              type="button"
              :class="[
                'app-dialog-host-btn',
                store.danger ? 'app-dialog-host-btn-danger' : 'app-dialog-host-btn-primary',
              ]"
              @click="store.ackConfirm(true)"
            >
              {{ store.confirmText }}
            </button>
          </template>
          <template v-else>
            <button type="button" class="app-dialog-host-btn app-dialog-host-btn-secondary" @click="store.ackPrompt(false)">
              {{ store.cancelText }}
            </button>
            <button type="button" class="app-dialog-host-btn app-dialog-host-btn-primary" @click="store.ackPrompt(true)">
              {{ store.confirmText }}
            </button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { watch } from 'vue';
import { useAppDialogStore } from '@/stores/appDialog';

const store = useAppDialogStore();
const titleId = 'app-dialog-host-title-text';

function onOverlayClick() {
  if (store.kind === 'alert') {
    store.ackAlert();
    return;
  }
  if (store.kind === 'confirm') {
    store.ackConfirm(false);
    return;
  }
  store.ackPrompt(false);
}

function onEscape() {
  if (store.kind === 'alert') {
    store.ackAlert();
    return;
  }
  if (store.kind === 'confirm') {
    store.ackConfirm(false);
    return;
  }
  store.ackPrompt(false);
}

function onPromptEnter() {
  store.ackPrompt(true);
}

watch(
  () => store.visible,
  (v) => {
    if (v && store.kind === 'prompt') {
      requestAnimationFrame(() => {
        const el = document.querySelector('.app-dialog-host-input') as HTMLInputElement | null;
        el?.focus();
        el?.select();
      });
    }
  }
);
</script>

<style scoped>
.app-dialog-host-overlay {
  position: fixed;
  inset: 0;
  z-index: 100050;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  box-sizing: border-box;
}

.app-dialog-host-panel {
  width: 100%;
  max-width: 420px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
  padding: 20px 22px 18px;
  box-sizing: border-box;
}

.app-dialog-host-title {
  margin: 0 0 10px;
  font-size: 17px;
  font-weight: 600;
  color: #111827;
  line-height: 1.35;
}

.app-dialog-host-message {
  margin: 0 0 16px;
  font-size: 14px;
  color: #4b5563;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.app-dialog-host-prompt-wrap {
  margin-bottom: 16px;
}

.app-dialog-host-input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  font-size: 14px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  outline: none;
}

.app-dialog-host-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}

.app-dialog-host-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.app-dialog-host-btn {
  min-width: 88px;
  padding: 8px 16px;
  font-size: 14px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-weight: 500;
}

.app-dialog-host-btn-primary {
  background: #2563eb;
  color: #fff;
}

.app-dialog-host-btn-primary:hover {
  background: #1d4ed8;
}

.app-dialog-host-btn-secondary {
  background: #f3f4f6;
  color: #374151;
}

.app-dialog-host-btn-secondary:hover {
  background: #e5e7eb;
}

.app-dialog-host-btn-danger {
  background: #dc2626;
  color: #fff;
}

.app-dialog-host-btn-danger:hover {
  background: #b91c1c;
}
</style>
